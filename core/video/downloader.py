"""
视频下载器：封装解析 -> 选择清晰度 -> 调用下载引擎的完整流程。

复用 :class:`core.downloader.engine.DownloadEngine` 的 Range 分片并发
+ 断点续传能力，进度回调复用 :class:`DownloadProgress`。

免责声明：仅供个人学习研究使用，请尊重版权，下载内容请于 24 小时内删除。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..downloader.engine import DownloadEngine
from ..downloader.progress import DownloadProgress, ProgressCallback
from ..exceptions import ParserError
from .base import (
    BaseVideoParser,
    QualityOption,
    VideoInfo,
    get_video_parser,
)


class VideoDownloader:
    """视频下载封装类。

    整合视频解析器和下载引擎，提供一站式视频下载能力。

    Example::

        downloader = VideoDownloader(concurrency=8)
        video_info = downloader.parse("https://www.bilibili.com/video/BV1xx411c7mD")
        print(f"标题: {video_info.title}")
        print(f"可用清晰度: {[q.quality for q in video_info.quality_list]}")
        downloader.download(
            video_info,
            quality="1080p",
            output_dir="/tmp/videos",
            progress_callback=lambda p: print(f"{p.percent:.1f}%"),
        )
    """

    def __init__(
        self,
        concurrency: int = 8,
        chunk_size: int = 4 * 1024 * 1024,
        timeout: int = 30,
        credential: dict[str, Any] | None = None,
    ) -> None:
        """初始化视频下载器。

        Args:
            concurrency: 下载并发数（1-32）。
            chunk_size: 分片大小（字节）。
            timeout: HTTP 请求超时（秒）。
            credential: 全局登录凭证（各平台共用，可在 parse 时覆盖）。
        """
        self._engine = DownloadEngine(
            concurrency=concurrency,
            chunk_size=chunk_size,
            timeout=timeout,
        )
        self._credential = credential or {}
        self._parser: BaseVideoParser | None = None
        self._current_video: VideoInfo | None = None

    # ---------- 公共接口 ----------

    def parse(
        self,
        url: str,
        credential: dict[str, Any] | None = None,
    ) -> VideoInfo:
        """解析视频链接，返回视频信息。

        Args:
            url: 视频页面链接。
            credential: 本次解析使用的凭证（覆盖全局凭证）。

        Returns:
            :class:`VideoInfo`，包含标题、封面、时长、清晰度列表。

        Raises:
            ParserError: 无法识别的链接或解析失败。
        """
        cred = credential or self._credential
        self._parser = get_video_parser(url, credential=cred)
        self._current_video = self._parser.parse_video_url(url)
        return self._current_video

    def download(
        self,
        video_info: VideoInfo,
        quality: str = "",
        output_dir: str | Path = ".",
        filename: str | None = None,
        progress_callback: ProgressCallback | None = None,
        headers: dict[str, str] | None = None,
    ) -> Path:
        """下载指定清晰度的视频。

        Args:
            video_info: :meth:`parse` 返回的视频信息。
            quality: 清晰度标识（如 ``"1080p"``）；为空时自动选择最高清晰度。
            output_dir: 输出目录。
            filename: 自定义文件名（不含扩展名）；为 ``None`` 时使用视频标题。
            progress_callback: 进度回调函数。
            headers: 下载时额外请求头（如 Referer、Cookie）。

        Returns:
            下载完成的文件路径。

        Raises:
            ParserError: 清晰度不可用或获取直链失败。
            DownloadError: 下载失败。
        """
        if self._parser is None:
            # 如果没有通过 parse 获取的 parser，尝试从 video_info 重建
            self._parser = get_video_parser(
                f"https://{video_info.platform}.com",
                credential=self._credential,
            )

        # 选择清晰度
        if not quality:
            best = video_info.best_quality()
            if best is None:
                raise ParserError("视频没有可用的清晰度")
            quality = best.quality

        option = video_info.find_quality(quality)
        if option is None:
            available = ", ".join(q.quality for q in video_info.quality_list)
            raise ParserError(
                f"不支持的清晰度: {quality}，可用: {available}"
            )

        # 获取下载直链
        download_url = self._parser.get_download_url(video_info, quality)

        # 构建输出路径
        output_path = self._build_output_path(
            video_info, option, output_dir, filename
        )

        # 构建下载请求头（部分平台需要 Referer）
        download_headers = self._build_headers(video_info, headers)

        # 调用下载引擎
        return self._engine.download(
            url=download_url,
            output_path=output_path,
            progress_callback=progress_callback,
            headers=download_headers,
        )

    def parse_and_download(
        self,
        url: str,
        quality: str = "",
        output_dir: str | Path = ".",
        progress_callback: ProgressCallback | None = None,
        credential: dict[str, Any] | None = None,
    ) -> Path:
        """一站式：解析并下载视频。

        Args:
            url: 视频链接。
            quality: 清晰度标识；为空时选择最高清晰度。
            output_dir: 输出目录。
            progress_callback: 进度回调。
            credential: 登录凭证。

        Returns:
            下载完成的文件路径。
        """
        video_info = self.parse(url, credential=credential)
        return self.download(
            video_info,
            quality=quality,
            output_dir=output_dir,
            progress_callback=progress_callback,
        )

    def pause(self) -> None:
        """暂停当前下载。"""
        self._engine.pause()

    def resume(self) -> None:
        """恢复下载。"""
        self._engine.resume()

    def cancel(self) -> None:
        """取消当前下载。"""
        self._engine.cancel()

    # ---------- 内部方法 ----------

    @staticmethod
    def _build_output_path(
        video_info: VideoInfo,
        option: QualityOption,
        output_dir: str | Path,
        filename: str | None,
    ) -> Path:
        """构建输出文件路径。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if filename:
            base_name = filename
        else:
            # 使用视频标题，清理非法字符
            base_name = BaseVideoParser._sanitize_filename(video_info.title)
            # 附加清晰度标识
            base_name = f"{base_name}_{option.quality}"

        ext = option.format or "mp4"
        return output_dir / f"{base_name}.{ext}"

    @staticmethod
    def _build_headers(
        video_info: VideoInfo,
        extra_headers: dict[str, str] | None,
    ) -> dict[str, str]:
        """根据平台构建下载请求头。"""
        headers = {"User-Agent": "YunX-Downloader/1.0"}

        # 各平台需要的 Referer
        referer_map = {
            "bilibili": "https://www.bilibili.com",
            "douyin": "https://www.douyin.com/",
            "youtube": "https://www.youtube.com/",
            "kuaishou": "https://www.kuaishou.com/",
            "weibo": "https://weibo.com/",
            "xiaohongshu": "https://www.xiaohongshu.com/",
            "xigua": "https://www.ixigua.com/",
            "zhihu": "https://www.zhihu.com/",
        }
        if video_info.platform in referer_map:
            headers["Referer"] = referer_map[video_info.platform]

        if extra_headers:
            headers.update(extra_headers)
        return headers
