"""
上传引擎：分片并发上传 + 断点续传 + 进度回调。

特性：
- 大文件自动分片（默认 4MB）
- 并发上传（默认 4 线程，上限 16）
- 上传状态持久化到 ``.yunx_upload.json`` 元数据文件
- 中断后恢复时跳过已完成分片
- 支持暂停 / 恢复 / 取消（线程安全的事件控制）
- 进度回调：uploaded_bytes / total_bytes / speed / percent
- 自动重试（单分片最多 5 次，指数退避）
- 单线程降级（上传器不支持分片时自动切换）
- 与各网盘上传器解耦，通过 :class:`BaseUploader` 接口协作

免责声明：仅供个人学习技术交流。
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..exceptions import NetworkError, UploadError
from .base import (
    BaseUploader,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_PENDING,
    STATUS_UPLOADING,
    UploadProgressCallback,
    UploadResult,
    UploadTask,
)

# 默认分片大小（4MB）
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
# 默认并发数
DEFAULT_CONCURRENCY = 4
# 最大并发数
MAX_CONCURRENCY = 16
# 元数据文件后缀
META_SUFFIX = ".yunx_upload.json"
# 单分片最大重试次数
MAX_RETRIES = 5
# 重试初始等待（秒）
RETRY_BASE_DELAY = 1.0
# 最小分片大小（64KB）
MIN_CHUNK_SIZE = 64 * 1024


@dataclass
class UploadChunkInfo:
    """单个上传分片的元数据。"""

    index: int
    """分片序号（从 0 开始）。"""
    start: int
    """起始字节偏移（含）。"""
    end: int
    """结束字节偏移（含）。"""
    uploaded: bool = False
    """是否已上传完成。"""
    result: dict[str, Any] = field(default_factory=dict)
    """分片上传结果（如 etag、part_number）。"""


@dataclass
class UploadMetadata:
    """上传任务元数据（持久化到 .yunx_upload.json）。"""

    file_path: str
    """本地文件路径。"""
    remote_path: str
    """远程目标路径。"""
    total_size: int
    """文件总大小（字节）。"""
    chunk_size: int
    """分片大小（字节）。"""
    drive_name: str
    """网盘标识。"""
    chunks: list[UploadChunkInfo] = field(default_factory=list)
    """所有分片的状态。"""
    upload_context: dict[str, Any] = field(default_factory=dict)
    """上传器返回的上传上下文（init_upload 结果）。"""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "file_path": self.file_path,
            "remote_path": self.remote_path,
            "total_size": self.total_size,
            "chunk_size": self.chunk_size,
            "drive_name": self.drive_name,
            "chunks": [
                {
                    "index": c.index,
                    "start": c.start,
                    "end": c.end,
                    "uploaded": c.uploaded,
                    "result": c.result,
                }
                for c in self.chunks
            ],
            "upload_context": self.upload_context,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UploadMetadata":
        """从字典反序列化。"""
        return cls(
            file_path=data["file_path"],
            remote_path=data["remote_path"],
            total_size=data["total_size"],
            chunk_size=data["chunk_size"],
            drive_name=data["drive_name"],
            chunks=[
                UploadChunkInfo(
                    index=c["index"],
                    start=c["start"],
                    end=c["end"],
                    uploaded=c.get("uploaded", False),
                    result=c.get("result", {}),
                )
                for c in data.get("chunks", [])
            ],
            upload_context=data.get("upload_context", {}),
        )


class UploadEngine:
    """分片并发上传引擎。

    管理上传任务队列，支持多任务并发。每个任务独立线程，
    进度通过回调通知。元数据持久化到 ``.yunx_upload.json``，支持断点续传。

    Example::

        engine = UploadEngine(concurrency=4, chunk_size=4*1024*1024)
        result = engine.upload_file(
            file_path="/tmp/file.zip",
            remote_dir="/",
            uploader=quark_uploader,
            progress_callback=lambda uploaded, total, speed, pct: print(f"{pct:.1f}%"),
        )
    """

    def __init__(
        self,
        concurrency: int = DEFAULT_CONCURRENCY,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        timeout: int = 60,
    ) -> None:
        """初始化上传引擎。

        Args:
            concurrency: 并发上传数（1-16，超出自动截断）。
            chunk_size: 分片大小（字节，最小 64KB）。
            timeout: HTTP 请求超时（秒）。
        """
        self.concurrency = max(1, min(concurrency, MAX_CONCURRENCY))
        self.chunk_size = max(MIN_CHUNK_SIZE, chunk_size)
        self.timeout = timeout
        self._pause_event = threading.Event()
        self._pause_event.set()  # set = 运行中
        self._cancel_event = threading.Event()
        self._meta: UploadMetadata | None = None
        self._tasks: dict[str, UploadTask] = {}
        self._tasks_lock = threading.Lock()

    # ---------- 公共接口 ----------

    def upload_file(
        self,
        file_path: str | Path,
        remote_dir: str,
        uploader: BaseUploader,
        progress_callback: UploadProgressCallback | None = None,
    ) -> UploadResult:
        """上传单个文件到指定网盘目录。

        如果存在未完成的元数据文件，自动恢复断点续传。

        Args:
            file_path: 本地文件路径。
            remote_dir: 远程目标目录（网盘特定的目录 ID 或路径）。
            uploader: 网盘上传器实例。
            progress_callback: 进度回调函数 ``(uploaded_bytes, total_bytes, speed, percent)``。

        Returns:
            上传结果 :class:`UploadResult`。

        Raises:
            UploadError: 上传失败。
            NetworkError: 网络错误。
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise UploadError(f"文件不存在: {file_path}")
        if not file_path.is_file():
            raise UploadError(f"不是文件: {file_path}")

        file_name = file_path.name
        file_size = file_path.stat().st_size
        remote_path = f"{remote_dir.rstrip('/')}/{file_name}" if remote_dir else f"/{file_name}"

        # 注册任务
        task = UploadTask(
            file_path=str(file_path),
            remote_path=remote_path,
            total_bytes=file_size,
            status=STATUS_PENDING,
        )
        self._register_task(task)

        # 尝试恢复已有任务
        meta_path = self._meta_path(file_path)
        resumed = False
        if meta_path.exists():
            try:
                self._meta = self._load_metadata(meta_path)
                # 验证文件一致性
                if (
                    self._meta.file_path == str(file_path)
                    and self._meta.total_size == file_size
                    and self._meta.drive_name == uploader.drive_name
                    and self._meta.upload_context
                ):
                    resumed = True
                else:
                    self._meta = None
            except Exception:
                self._meta = None

        # 初始化上传
        task.status = STATUS_UPLOADING
        self._update_task(task)

        if not resumed:
            # 新任务：初始化上传
            context = uploader.init_upload(
                file_path=str(file_path),
                remote_dir=remote_dir,
                file_name=file_name,
                file_size=file_size,
            )
            chunks = self._build_chunks(file_size)
            self._meta = UploadMetadata(
                file_path=str(file_path),
                remote_path=remote_path,
                total_size=file_size,
                chunk_size=self.chunk_size,
                drive_name=uploader.drive_name,
                chunks=chunks,
                upload_context=context,
            )
            self._save_metadata()

        assert self._meta is not None
        context = self._meta.upload_context

        # 秒传命中：直接完成
        if context.get("instant_upload"):
            task.uploaded_bytes = file_size
            task.status = STATUS_COMPLETED
            self._update_task(task)
            self._cleanup(file_path)
            result = uploader.complete_upload(context, [])
            return result

        # 计算已上传字节数（恢复进度）
        already_uploaded = sum(
            (c.end - c.start + 1) for c in self._meta.chunks if c.uploaded
        )
        task.uploaded_bytes = already_uploaded
        self._update_task(task)

        # 执行分片上传
        total_chunks = len(self._meta.chunks)
        if uploader.supports_chunked_upload() and total_chunks > 1:
            chunk_results = self._upload_chunks_concurrent(
                uploader, context, file_path, total_chunks, task, progress_callback
            )
        else:
            chunk_results = self._upload_single_thread(
                uploader, context, file_path, total_chunks, task, progress_callback
            )

        # 检查取消
        self._check_pause_and_cancel()

        # 完成上传（合并分片）
        result = uploader.complete_upload(context, chunk_results)

        task.status = STATUS_COMPLETED
        task.uploaded_bytes = file_size
        self._update_task(task)

        # 清理元数据
        self._cleanup(file_path)

        return result

    def get_task(self, file_path: str) -> UploadTask | None:
        """获取指定文件的上传任务状态。"""
        with self._tasks_lock:
            return self._tasks.get(file_path)

    def list_tasks(self) -> list[UploadTask]:
        """列出所有上传任务。"""
        with self._tasks_lock:
            return list(self._tasks.values())

    def pause(self) -> None:
        """暂停所有上传。"""
        self._pause_event.clear()
        with self._tasks_lock:
            for task in self._tasks.values():
                if task.status == STATUS_UPLOADING:
                    task.status = STATUS_PAUSED

    def resume(self) -> None:
        """恢复所有上传。"""
        self._pause_event.set()
        with self._tasks_lock:
            for task in self._tasks.values():
                if task.status == STATUS_PAUSED:
                    task.status = STATUS_UPLOADING

    def cancel(self) -> None:
        """取消所有上传。"""
        self._cancel_event.set()
        self._pause_event.set()  # 解除暂停阻塞
        with self._tasks_lock:
            for task in self._tasks.values():
                if task.status in (STATUS_UPLOADING, STATUS_PAUSED, STATUS_PENDING):
                    task.status = STATUS_CANCELLED

    # ---------- 分片管理 ----------

    def _build_chunks(self, total_size: int) -> list[UploadChunkInfo]:
        """根据文件大小和分片大小构建分片列表。"""
        if total_size <= 0:
            return [UploadChunkInfo(index=0, start=0, end=0)]
        chunks = []
        index = 0
        start = 0
        while start < total_size:
            end = min(start + self.chunk_size - 1, total_size - 1)
            chunks.append(UploadChunkInfo(index=index, start=start, end=end))
            start = end + 1
            index += 1
        return chunks

    @staticmethod
    def _meta_path(file_path: Path) -> Path:
        """获取元数据文件路径。"""
        return file_path.parent / f"{file_path.name}{META_SUFFIX}"

    # ---------- 并发上传 ----------

    def _upload_chunks_concurrent(
        self,
        uploader: BaseUploader,
        context: dict[str, Any],
        file_path: Path,
        total_chunks: int,
        task: UploadTask,
        progress_callback: UploadProgressCallback | None,
    ) -> list[dict[str, Any]]:
        """并发上传所有分片。"""
        assert self._meta is not None
        pending = [c for c in self._meta.chunks if not c.uploaded]

        if not pending:
            # 所有分片已完成，收集结果
            return [c.result for c in self._meta.chunks]

        speed_start = time.monotonic()
        speed_bytes = 0

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures: dict[Future, UploadChunkInfo] = {}
            for chunk in pending:
                self._check_pause_and_cancel()
                future = executor.submit(
                    self._upload_one_chunk,
                    uploader,
                    context,
                    file_path,
                    chunk,
                    total_chunks,
                )
                futures[future] = chunk

            for future in futures:
                self._check_pause_and_cancel()
                try:
                    chunk, result = future.result()
                    chunk.uploaded = True
                    chunk.result = result
                    chunk_size = chunk.end - chunk.start + 1
                    task.uploaded_bytes += chunk_size
                    speed_bytes += chunk_size

                    # 计算速度
                    elapsed = time.monotonic() - speed_start
                    speed = speed_bytes / elapsed if elapsed > 0 else 0.0
                    task.speed = speed

                    percent = (
                        task.uploaded_bytes / task.total_bytes * 100.0
                        if task.total_bytes > 0
                        else 0.0
                    )
                    self._update_task(task)

                    if progress_callback:
                        progress_callback(
                            task.uploaded_bytes,
                            task.total_bytes,
                            speed,
                            min(percent, 100.0),
                        )

                    self._save_metadata()
                except Exception as exc:
                    chunk = futures[future]
                    task.status = STATUS_FAILED
                    self._update_task(task)
                    raise UploadError(
                        f"分片 {chunk.index} 上传失败: {exc}"
                    ) from exc

        # 收集所有分片结果（按序号排序）
        return [c.result for c in sorted(self._meta.chunks, key=lambda c: c.index)]

    def _upload_single_thread(
        self,
        uploader: BaseUploader,
        context: dict[str, Any],
        file_path: Path,
        total_chunks: int,
        task: UploadTask,
        progress_callback: UploadProgressCallback | None,
    ) -> list[dict[str, Any]]:
        """单线程上传（服务器不支持分片时的降级方案）。"""
        assert self._meta is not None
        results = []
        speed_start = time.monotonic()
        speed_bytes = 0

        for chunk in self._meta.chunks:
            if chunk.uploaded:
                results.append(chunk.result)
                continue

            self._check_pause_and_cancel()
            chunk, result = self._upload_one_chunk(
                uploader, context, file_path, chunk, total_chunks
            )
            chunk.uploaded = True
            chunk.result = result
            chunk_size = chunk.end - chunk.start + 1
            task.uploaded_bytes += chunk_size
            speed_bytes += chunk_size

            elapsed = time.monotonic() - speed_start
            speed = speed_bytes / elapsed if elapsed > 0 else 0.0
            task.speed = speed

            percent = (
                task.uploaded_bytes / task.total_bytes * 100.0
                if task.total_bytes > 0
                else 0.0
            )
            self._update_task(task)

            if progress_callback:
                progress_callback(
                    task.uploaded_bytes,
                    task.total_bytes,
                    speed,
                    min(percent, 100.0),
                )

            self._save_metadata()
            results.append(result)

        return results

    def _upload_one_chunk(
        self,
        uploader: BaseUploader,
        context: dict[str, Any],
        file_path: Path,
        chunk: UploadChunkInfo,
        total_chunks: int,
    ) -> tuple[UploadChunkInfo, dict[str, Any]]:
        """上传单个分片（带重试和指数退避）。"""
        chunk_data = self._read_chunk(file_path, chunk)

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self._check_pause_and_cancel()
            try:
                result = uploader.upload_chunk(
                    context=context,
                    chunk_index=chunk.index,
                    chunk_data=chunk_data,
                    total_chunks=total_chunks,
                )
                return chunk, result
            except (NetworkError, UploadError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    time.sleep(delay)

        raise UploadError(
            f"分片 {chunk.index} 上传失败（重试 {MAX_RETRIES} 次）: {last_error}"
        )

    @staticmethod
    def _read_chunk(file_path: Path, chunk: UploadChunkInfo) -> bytes:
        """读取文件的指定分片数据。"""
        with open(file_path, "rb") as f:
            f.seek(chunk.start)
            return f.read(chunk.end - chunk.start + 1)

    # ---------- 任务管理 ----------

    def _register_task(self, task: UploadTask) -> None:
        """注册上传任务。"""
        with self._tasks_lock:
            self._tasks[task.file_path] = task

    def _update_task(self, task: UploadTask) -> None:
        """更新任务状态（线程安全）。"""
        with self._tasks_lock:
            self._tasks[task.file_path] = task

    # ---------- 元数据持久化 ----------

    def _save_metadata(self) -> None:
        """保存上传元数据到磁盘。"""
        if self._meta is None:
            return
        meta_path = self._meta_path(Path(self._meta.file_path))
        tmp_path = meta_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(meta_path)

    @staticmethod
    def _load_metadata(meta_path: Path) -> UploadMetadata:
        """从磁盘加载上传元数据。"""
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return UploadMetadata.from_dict(data)

    def _cleanup(self, file_path: Path) -> None:
        """清理元数据文件。"""
        meta_path = self._meta_path(file_path)
        meta_path.unlink(missing_ok=True)
        self._meta = None

    # ---------- 暂停/取消控制 ----------

    def _check_pause_and_cancel(self) -> None:
        """检查暂停和取消状态。"""
        if self._cancel_event.is_set():
            raise UploadError("上传已取消")
        # 暂停时阻塞等待
        self._pause_event.wait()
        if self._cancel_event.is_set():
            raise UploadError("上传已取消")
