"""
音乐下载器：封装解析→音质选择→下载→ID3标签嵌入全流程。

复用 :class:`core.downloader.engine.DownloadEngine` 进行 Range 分片并发下载，
下载完成后自动调用 :func:`core.music.id3tagger.embed_id3_tags` 嵌入元数据。

支持单曲下载和歌单批量下载。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import requests

from ..downloader.engine import DownloadEngine
from ..downloader.progress import DownloadProgress, ProgressCallback
from ..exceptions import DownloadError, ParserError
from .base import (
    BaseMusicParser,
    PlaylistInfo,
    QUALITY_HIGHER,
    QUALITY_LOSSLESS,
    QUALITY_STANDARD,
    SongInfo,
    get_music_parser,
)
from .id3tagger import embed_id3_tags


class MusicDownloader:
    """音乐下载器。

    封装音乐解析、音质选择、分片下载、ID3 标签嵌入的完整流程。

    Example::

        downloader = MusicDownloader(output_dir="/path/to/music")
        # 单曲下载
        path = downloader.download_song(
            "https://music.163.com/#/song?id=123456",
            quality="higher",
        )
        # 歌单批量下载
        paths = downloader.download_playlist(
            "https://music.163.com/#/playlist?id=123456",
            quality="standard",
        )
    """

    def __init__(
        self,
        output_dir: str | Path = "./music_downloads",
        concurrency: int = 4,
        chunk_size: int = 1024 * 1024,
        credential: dict[str, Any] | None = None,
        embed_tags: bool = True,
        download_cover: bool = True,
    ) -> None:
        """初始化音乐下载器。

        Args:
            output_dir: 音乐文件输出目录。
            concurrency: 下载并发数（传递给 DownloadEngine）。
            chunk_size: 下载分片大小（字节）。
            credential: 音乐平台登录凭证（高音质需要）。
            embed_tags: 下载完成后是否自动嵌入 ID3 标签。
            download_cover: 是否下载封面图片用于标签嵌入。
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.credential = credential or {}
        self.embed_tags = embed_tags
        self.download_cover = download_cover

        # 复用核心下载引擎
        self._engine = DownloadEngine(
            concurrency=concurrency,
            chunk_size=chunk_size,
        )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )

    # ---------- 公共接口 ----------

    def download_song(
        self,
        url: str,
        quality: str = QUALITY_HIGHER,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        """下载单曲。

        流程：解析 URL → 获取歌曲信息 → 获取指定音质直链 → 分片下载 → 嵌入 ID3 标签。

        Args:
            url: 单曲分享链接。
            quality: 期望音质（``standard`` / ``higher`` / ``lossless``）。
                若该音质不可用，自动降级到最高可用音质。
            progress_callback: 下载进度回调。

        Returns:
            下载完成的文件路径。

        Raises:
            ParserError: 解析失败或版权受限。
            DownloadError: 下载失败。
        """
        parser = get_music_parser(url, credential=self.credential)
        song_info = parser.parse_song_url(url)

        if song_info.copyright_restricted:
            raise ParserError("该歌曲因版权限制无法下载")

        # 获取下载直链（自动处理音质降级）
        download_url = parser.get_download_url(song_info, quality)

        # 确定实际音质和扩展名
        actual_quality = self._resolve_quality(song_info, quality)
        ext = self._get_extension(actual_quality)

        # 构建输出文件名
        filename = self._build_filename(song_info, ext)
        output_path = self.output_dir / filename

        # 下载
        self._engine.download(
            url=download_url,
            output_path=output_path,
            progress_callback=progress_callback,
        )

        # 嵌入 ID3 标签
        if self.embed_tags:
            cover_bytes = None
            if self.download_cover and song_info.cover:
                cover_bytes = self._download_cover(song_info.cover)
            embed_id3_tags(output_path, song_info, cover_bytes)

        return output_path

    def download_playlist(
        self,
        url: str,
        quality: str = QUALITY_HIGHER,
        progress_callback: ProgressCallback | None = None,
        song_callback: Callable[[int, int, SongInfo], None] | None = None,
    ) -> list[Path]:
        """批量下载歌单/专辑中的所有歌曲。

        Args:
            url: 歌单或专辑分享链接。
            quality: 期望音质。
            progress_callback: 单首歌曲下载进度回调。
            song_callback: 歌曲级回调 ``(index, total, song_info)``，
                用于在每首歌开始/结束时通知。

        Returns:
            成功下载的文件路径列表。

        Raises:
            ParserError: 歌单解析失败。
        """
        parser = get_music_parser(url, credential=self.credential)
        playlist = parser.parse_playlist_url(url)

        output_paths: list[Path] = []
        total = len(playlist.songs)

        for index, song_info in enumerate(playlist.songs, 1):
            if song_callback:
                song_callback(index, total, song_info)

            if song_info.copyright_restricted:
                # 跳过版权受限歌曲，继续下载其余
                continue

            try:
                path = self._download_song_info(
                    parser, song_info, quality, progress_callback
                )
                output_paths.append(path)
            except (ParserError, DownloadError):
                # 单首失败不影响整体
                continue

        return output_paths

    def parse_song(self, url: str) -> SongInfo:
        """解析单曲链接（仅解析，不下载）。

        Args:
            url: 单曲链接。

        Returns:
            :class:`SongInfo`。
        """
        parser = get_music_parser(url, credential=self.credential)
        return parser.parse_song_url(url)

    def parse_playlist(self, url: str) -> PlaylistInfo:
        """解析歌单/专辑链接（仅解析，不下载）。

        Args:
            url: 歌单或专辑链接。

        Returns:
            :class:`PlaylistInfo`。
        """
        parser = get_music_parser(url, credential=self.credential)
        return parser.parse_playlist_url(url)

    # ---------- 内部方法 ----------

    def _download_song_info(
        self,
        parser: BaseMusicParser,
        song_info: SongInfo,
        quality: str,
        progress_callback: ProgressCallback | None,
    ) -> Path:
        """根据已解析的 SongInfo 下载歌曲。"""
        download_url = parser.get_download_url(song_info, quality)
        actual_quality = self._resolve_quality(song_info, quality)
        ext = self._get_extension(actual_quality)
        filename = self._build_filename(song_info, ext)
        output_path = self.output_dir / filename

        self._engine.download(
            url=download_url,
            output_path=output_path,
            progress_callback=progress_callback,
        )

        if self.embed_tags:
            cover_bytes = None
            if self.download_cover and song_info.cover:
                cover_bytes = self._download_cover(song_info.cover)
            embed_id3_tags(output_path, song_info, cover_bytes)

        return output_path

    @staticmethod
    def _resolve_quality(song_info: SongInfo, requested: str) -> str:
        """解析实际可用音质（请求不可用时降级）。"""
        if song_info.get_quality(requested) is not None:
            return requested
        best = song_info.best_available_quality()
        if best is not None:
            return best.quality
        return QUALITY_STANDARD

    @staticmethod
    def _get_extension(quality: str) -> str:
        """根据音质获取文件扩展名。"""
        from .base import QUALITY_EXTENSIONS

        return QUALITY_EXTENSIONS.get(quality, "mp3")

    @staticmethod
    def _build_filename(song_info: SongInfo, ext: str) -> str:
        """构建安全的输出文件名。

        格式：``歌手 - 歌名.ext``（去除文件系统非法字符）。
        """
        import re

        artist = song_info.artist or "Unknown Artist"
        title = song_info.title or "Unknown Title"
        name = f"{artist} - {title}"
        # 移除文件系统非法字符
        name = re.sub(r'[\\/:*?"<>|]', "_", name)
        # 限制长度
        if len(name) > 200:
            name = name[:200]
        return f"{name}.{ext}"

    def _download_cover(self, cover_url: str) -> bytes | None:
        """下载封面图片。

        Args:
            cover_url: 封面图片 URL。

        Returns:
            图片二进制数据；失败时返回 ``None``。
        """
        try:
            resp = self._session.get(cover_url, timeout=15)
            if resp.status_code == 200 and resp.content:
                return resp.content
        except requests.RequestException:
            pass
        return None
