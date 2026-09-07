"""
下载引擎：Range 分片并发下载 + 断点续传。

特性：
- 自动检测服务器是否支持 Range 请求
- 分片大小可配置（默认 4MB）
- 并发数可配置（上限 32，默认 8）
- 下载状态持久化到 ``.yunx_download.json`` 元数据文件
- 中断后重新开始时自动检测已下载分片，跳过已完成部分
- 支持暂停/恢复
- 进度回调：downloaded_bytes / total_bytes / speed / percent
- 所有分片下载完成后按顺序合并为最终文件
- 可选 MD5/SHA256 校验
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from ..exceptions import DownloadError, NetworkError
from .progress import DownloadProgress, ProgressTracker, ProgressCallback

# 默认分片大小（4MB）
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
# 默认并发数
DEFAULT_CONCURRENCY = 8
# 最大并发数
MAX_CONCURRENCY = 32
# 元数据文件后缀
META_SUFFIX = ".yunx_download.json"
# 分片临时文件后缀
PART_SUFFIX = ".part"
# 单分片最大重试次数
MAX_RETRIES = 5
# 重试初始等待（秒）
RETRY_BASE_DELAY = 1.0


@dataclass
class ChunkInfo:
    """单个下载分片的元数据。"""

    index: int
    """分片序号（从 0 开始）。"""
    start: int
    """起始字节偏移（含）。"""
    end: int
    """结束字节偏移（含）。"""
    downloaded: bool = False
    """是否已下载完成。"""


@dataclass
class DownloadMetadata:
    """下载任务元数据（持久化到 .yunx_download.json）。"""

    url: str
    """下载 URL。"""
    output_path: str
    """最终输出文件路径。"""
    total_size: int
    """文件总大小（字节）。"""
    chunk_size: int
    """分片大小（字节）。"""
    supports_range: bool
    """服务器是否支持 Range 请求。"""
    chunks: list[ChunkInfo] = field(default_factory=list)
    """所有分片的状态。"""
    md5: str | None = None
    """期望的 MD5 校验值。"""
    sha256: str | None = None
    """期望的 SHA256 校验值。"""
    headers: dict[str, str] = field(default_factory=dict)
    """下载时使用的额外请求头。"""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "url": self.url,
            "output_path": self.output_path,
            "total_size": self.total_size,
            "chunk_size": self.chunk_size,
            "supports_range": self.supports_range,
            "chunks": [
                {
                    "index": c.index,
                    "start": c.start,
                    "end": c.end,
                    "downloaded": c.downloaded,
                }
                for c in self.chunks
            ],
            "md5": self.md5,
            "sha256": self.sha256,
            "headers": self.headers,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadMetadata":
        """从字典反序列化。"""
        return cls(
            url=data["url"],
            output_path=data["output_path"],
            total_size=data["total_size"],
            chunk_size=data["chunk_size"],
            supports_range=data["supports_range"],
            chunks=[
                ChunkInfo(
                    index=c["index"],
                    start=c["start"],
                    end=c["end"],
                    downloaded=c.get("downloaded", False),
                )
                for c in data.get("chunks", [])
            ],
            md5=data.get("md5"),
            sha256=data.get("sha256"),
            headers=data.get("headers", {}),
        )


class DownloadEngine:
    """Range 分片并发下载引擎。

    Example::

        engine = DownloadEngine(concurrency=8, chunk_size=4*1024*1024)
        engine.download(
            url="https://example.com/file.zip",
            output_path="/tmp/file.zip",
            progress_callback=lambda p: print(f"{p.percent:.1f}%"),
        )
    """

    def __init__(
        self,
        concurrency: int = DEFAULT_CONCURRENCY,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        timeout: int = 30,
    ) -> None:
        """初始化下载引擎。

        Args:
            concurrency: 并发下载数（1-32，超出自动截断）。
            chunk_size: 分片大小（字节）。
            timeout: HTTP 请求超时（秒）。
        """
        self.concurrency = max(1, min(concurrency, MAX_CONCURRENCY))
        self.chunk_size = max(64 * 1024, chunk_size)  # 最小 64KB
        self.timeout = timeout
        self._session = requests.Session()
        self._pause_event = threading.Event()
        self._pause_event.set()  # set = 运行中
        self._cancel_event = threading.Event()
        self._meta: DownloadMetadata | None = None

    # ---------- 公共接口 ----------

    def download(
        self,
        url: str,
        output_path: str | Path,
        progress_callback: ProgressCallback | None = None,
        headers: dict[str, str] | None = None,
        md5: str | None = None,
        sha256: str | None = None,
    ) -> Path:
        """下载文件。

        如果存在未完成的元数据文件，自动恢复断点续传。

        Args:
            url: 下载 URL。
            output_path: 输出文件路径。
            progress_callback: 进度回调函数。
            headers: 额外请求头（如 Referer、Cookie）。
            md5: 期望的 MD5 校验值（提供则下载后校验）。
            sha256: 期望的 SHA256 校验值（提供则下载后校验）。

        Returns:
            最终文件路径。

        Raises:
            DownloadError: 下载失败。
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        extra_headers = headers or {}

        # 尝试恢复已有任务
        meta_path = self._meta_path(output_path)
        if meta_path.exists():
            self._meta = self._load_metadata(meta_path)
            # 验证 URL 一致
            if self._meta.url != url:
                self._meta = None  # URL 不一致，重新开始
            else:
                # 恢复已下载字节数
                pass

        if self._meta is None:
            # 新任务：探测服务器能力
            total_size, supports_range = self._probe_server(url, extra_headers)
            chunks = self._build_chunks(total_size)
            self._meta = DownloadMetadata(
                url=url,
                output_path=str(output_path),
                total_size=total_size,
                chunk_size=self.chunk_size,
                supports_range=supports_range,
                chunks=chunks,
                md5=md5,
                sha256=sha256,
                headers=extra_headers,
            )
            self._save_metadata()

        # 初始化进度追踪器
        tracker = ProgressTracker(
            total_bytes=self._meta.total_size,
            callback=progress_callback,
        )
        # 恢复已下载进度
        already = sum(
            (c.end - c.start + 1) for c in self._meta.chunks if c.downloaded
        )
        tracker.set_downloaded(already)

        # 执行下载
        if self._meta.supports_range and len(self._meta.chunks) > 1:
            self._download_concurrent(tracker)
        else:
            self._download_single(tracker)

        # 合并分片
        self._merge_chunks(output_path)

        # 校验
        if md5 or sha256 or self._meta.md5 or self._meta.sha256:
            self._verify_checksum(
                output_path,
                md5 or self._meta.md5,
                sha256 or self._meta.sha256,
            )

        # 清理临时文件
        self._cleanup(output_path)

        return output_path

    def pause(self) -> None:
        """暂停下载。"""
        self._pause_event.clear()

    def resume(self) -> None:
        """恢复下载。"""
        self._pause_event.set()

    def cancel(self) -> None:
        """取消下载。"""
        self._cancel_event.set()
        self._pause_event.set()  # 解除暂停阻塞

    # ---------- 服务器探测 ----------

    def _probe_server(
        self, url: str, headers: dict[str, str]
    ) -> tuple[int, bool]:
        """探测服务器：获取文件大小和 Range 支持情况。

        Returns:
            (total_size, supports_range) 元组。
        """
        probe_headers = {"User-Agent": "YunX-Downloader/1.0"}
        probe_headers.update(headers)

        try:
            resp = self._session.head(
                url, headers=probe_headers, timeout=self.timeout, allow_redirects=True
            )
        except requests.RequestException as exc:
            raise NetworkError(f"服务器探测失败: {exc}") from exc

        total_size = 0
        supports_range = False

        if resp.status_code in (200, 206):
            content_length = resp.headers.get("Content-Length")
            if content_length:
                try:
                    total_size = int(content_length)
                except ValueError:
                    total_size = 0
            supports_range = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
        elif resp.status_code == 405:
            # HEAD 不被允许，用 GET Range 探测
            pass

        # 如果 HEAD 没拿到信息，用 GET Range: bytes=0-0 探测
        if total_size == 0 or not supports_range:
            try:
                range_headers = dict(probe_headers)
                range_headers["Range"] = "bytes=0-0"
                resp = self._session.get(
                    url,
                    headers=range_headers,
                    timeout=self.timeout,
                    stream=True,
                    allow_redirects=True,
                )
                if resp.status_code == 206:
                    supports_range = True
                    content_range = resp.headers.get("Content-Range", "")
                    # Content-Range: bytes 0-0/12345
                    if "/" in content_range:
                        try:
                            total_size = int(content_range.rsplit("/", 1)[-1])
                        except ValueError:
                            pass
                elif resp.status_code == 200:
                    supports_range = False
                    content_length = resp.headers.get("Content-Length")
                    if content_length:
                        try:
                            total_size = int(content_length)
                        except ValueError:
                            pass
                resp.close()
            except requests.RequestException:
                pass

        return total_size, supports_range

    # ---------- 分片管理 ----------

    def _build_chunks(self, total_size: int) -> list[ChunkInfo]:
        """根据文件大小和分片大小构建分片列表。"""
        if total_size <= 0:
            return [ChunkInfo(index=0, start=0, end=0)]
        chunks = []
        index = 0
        start = 0
        while start < total_size:
            end = min(start + self.chunk_size - 1, total_size - 1)
            chunks.append(ChunkInfo(index=index, start=start, end=end))
            start = end + 1
            index += 1
        return chunks

    def _part_path(self, output_path: Path, index: int) -> Path:
        """获取分片临时文件路径。"""
        return output_path.parent / f"{output_path.name}.part{index:04d}"

    @staticmethod
    def _meta_path(output_path: Path) -> Path:
        """获取元数据文件路径。"""
        return output_path.parent / f"{output_path.name}{META_SUFFIX}"

    # ---------- 并发下载 ----------

    def _download_concurrent(self, tracker: ProgressTracker) -> None:
        """并发下载所有分片。"""
        assert self._meta is not None
        pending = [c for c in self._meta.chunks if not c.downloaded]

        if not pending:
            return  # 所有分片已完成

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures: dict[Future, ChunkInfo] = {}
            for chunk in pending:
                self._check_pause_and_cancel()
                future = executor.submit(self._download_chunk, chunk, tracker)
                futures[future] = chunk

            for future in futures:
                self._check_pause_and_cancel()
                try:
                    future.result()
                except Exception as exc:
                    chunk = futures[future]
                    raise DownloadError(
                        f"分片 {chunk.index} 下载失败: {exc}"
                    ) from exc

    def _download_chunk(
        self, chunk: ChunkInfo, tracker: ProgressTracker
    ) -> None:
        """下载单个分片（带重试）。"""
        assert self._meta is not None
        part_path = self._part_path(Path(self._meta.output_path), chunk.index)

        # 如果分片文件已存在且大小正确，直接标记完成
        expected_size = chunk.end - chunk.start + 1
        if part_path.exists() and part_path.stat().st_size == expected_size:
            chunk.downloaded = True
            tracker.update(expected_size)
            self._save_metadata()
            return

        headers = {"User-Agent": "YunX-Downloader/1.0"}
        headers.update(self._meta.headers)
        headers["Range"] = f"bytes={chunk.start}-{chunk.end}"

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self._check_pause_and_cancel()
            try:
                resp = self._session.get(
                    self._meta.url,
                    headers=headers,
                    timeout=self.timeout,
                    stream=True,
                )
                if resp.status_code not in (200, 206):
                    raise DownloadError(
                        f"HTTP {resp.status_code}"
                    )

                # 写入分片文件（临时文件，完成后原子替换）
                tmp_path = part_path.with_suffix(part_path.suffix + ".tmp")
                downloaded = 0
                with open(tmp_path, "wb") as f:
                    for data in resp.iter_content(chunk_size=64 * 1024):
                        self._check_pause_and_cancel()
                        if data:
                            f.write(data)
                            downloaded += len(data)
                            tracker.update(len(data))
                resp.close()

                # 验证分片大小
                if downloaded != expected_size:
                    raise DownloadError(
                        f"分片大小不匹配: 期望 {expected_size}, 实际 {downloaded}"
                    )

                # 原子替换
                tmp_path.replace(part_path)
                chunk.downloaded = True
                self._save_metadata()
                return

            except (requests.RequestException, DownloadError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    time.sleep(delay)
                    # 清理不完整的临时文件
                    if "tmp_path" in locals() and Path(tmp_path).exists():
                        Path(tmp_path).unlink(missing_ok=True)

        raise DownloadError(
            f"分片 {chunk.index} 下载失败（重试 {MAX_RETRIES} 次）: {last_error}"
        )

    def _download_single(self, tracker: ProgressTracker) -> None:
        """单线程下载（服务器不支持 Range 时）。"""
        assert self._meta is not None
        output_path = Path(self._meta.output_path)
        part_path = self._part_path(output_path, 0)

        headers = {"User-Agent": "YunX-Downloader/1.0"}
        headers.update(self._meta.headers)

        # 断点续传：如果已有部分文件，尝试 Range 续传
        resume_from = 0
        if part_path.exists():
            resume_from = part_path.stat().st_size
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"

        try:
            resp = self._session.get(
                self._meta.url,
                headers=headers,
                timeout=self.timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise NetworkError(f"下载请求失败: {exc}") from exc

        if resp.status_code not in (200, 206):
            resp.close()
            raise DownloadError(f"HTTP {resp.status_code}")

        # 如果服务器忽略了 Range 返回 200，从头开始
        if resp.status_code == 200 and resume_from > 0:
            resume_from = 0
            if part_path.exists():
                part_path.unlink()

        mode = "ab" if resume_from > 0 else "wb"
        with open(part_path, mode) as f:
            for data in resp.iter_content(chunk_size=64 * 1024):
                self._check_pause_and_cancel()
                if data:
                    f.write(data)
                    tracker.update(len(data))
        resp.close()

        # 标记完成
        if self._meta.chunks:
            self._meta.chunks[0].downloaded = True
        self._save_metadata()

    # ---------- 合并与校验 ----------

    def _merge_chunks(self, output_path: Path) -> None:
        """按顺序合并所有分片为最终文件。"""
        assert self._meta is not None

        # 单分片情况：直接重命名
        if len(self._meta.chunks) == 1:
            part_path = self._part_path(output_path, 0)
            if part_path.exists():
                part_path.replace(output_path)
            return

        # 多分片：按顺序拼接
        with open(output_path, "wb") as out:
            for chunk in self._meta.chunks:
                part_path = self._part_path(output_path, chunk.index)
                if not part_path.exists():
                    raise DownloadError(f"缺少分片文件: {part_path.name}")
                with open(part_path, "rb") as f:
                    while True:
                        buf = f.read(1024 * 1024)
                        if not buf:
                            break
                        out.write(buf)

    def _verify_checksum(
        self,
        file_path: Path,
        expected_md5: str | None,
        expected_sha256: str | None,
    ) -> None:
        """校验文件 MD5/SHA256。"""
        if expected_md5:
            actual = self._calc_hash(file_path, hashlib.md5())
            if actual.lower() != expected_md5.lower():
                raise DownloadError(
                    f"MD5 校验失败: 期望 {expected_md5}, 实际 {actual}"
                )
        if expected_sha256:
            actual = self._calc_hash(file_path, hashlib.sha256())
            if actual.lower() != expected_sha256.lower():
                raise DownloadError(
                    f"SHA256 校验失败: 期望 {expected_sha256}, 实际 {actual}"
                )

    @staticmethod
    def _calc_hash(file_path: Path, hasher: Any) -> str:
        """计算文件哈希。"""
        with open(file_path, "rb") as f:
            while True:
                buf = f.read(1024 * 1024)
                if not buf:
                    break
                hasher.update(buf)
        return hasher.hexdigest()

    # ---------- 元数据持久化 ----------

    def _save_metadata(self) -> None:
        """保存下载元数据到磁盘。"""
        if self._meta is None:
            return
        meta_path = self._meta_path(Path(self._meta.output_path))
        tmp_path = meta_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(meta_path)

    @staticmethod
    def _load_metadata(meta_path: Path) -> DownloadMetadata:
        """从磁盘加载下载元数据。"""
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return DownloadMetadata.from_dict(data)

    def _cleanup(self, output_path: Path) -> None:
        """清理临时分片文件和元数据。"""
        # 删除分片文件
        for chunk in self._meta.chunks if self._meta else []:
            part_path = self._part_path(output_path, chunk.index)
            part_path.unlink(missing_ok=True)
        # 删除元数据
        meta_path = self._meta_path(output_path)
        meta_path.unlink(missing_ok=True)
        self._meta = None

    # ---------- 暂停/取消控制 ----------

    def _check_pause_and_cancel(self) -> None:
        """检查暂停和取消状态。"""
        if self._cancel_event.is_set():
            raise DownloadError("下载已取消")
        # 暂停时阻塞等待
        self._pause_event.wait()
        if self._cancel_event.is_set():
            raise DownloadError("下载已取消")
