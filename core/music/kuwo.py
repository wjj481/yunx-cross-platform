"""
酷我音乐解析器（实验性框架）。

当前仅提供框架代码，完整解析逻辑待实现。
酷我音乐 API 涉及签名算法（secret + md5），
且高音质需要登录 Cookie。

实验性标记：``experimental = True``
"""

from __future__ import annotations

import re
from typing import Any

import requests

from ..exceptions import ParserError
from .base import (
    BaseMusicParser,
    PlaylistInfo,
    QUALITY_EXTENSIONS,
    QUALITY_HIGHER,
    QUALITY_LOSSLESS,
    QUALITY_STANDARD,
    SongInfo,
    QualityInfo,
)

# ---------- 常量 ----------

API_BASE = "http://www.kuwo.cn"
MOBI_API_BASE = "http://m.kuwo.cn"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# URL 正则
_SONG_ID_RE = re.compile(r"(?:songid=|/song/|play/)(\d+)", re.IGNORECASE)
_PLAYLIST_ID_RE = re.compile(r"(?:playlistid=|/playlist/|purl/)(\d+)", re.IGNORECASE)


class KuWoParser(BaseMusicParser):
    """酷我音乐解析器（实验性）。

    框架已搭建，完整 API 签名与解析逻辑待实现。
    调用公共接口将抛出 :class:`ParserError` 提示实验性状态。
    """

    supported_domains = ["kuwo.cn", "kuwo.com"]
    source_name = "kuwo"
    status = "experimental"
    experimental = True

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "http://www.kuwo.cn/",
            }
        )
        self._cookie: str = (credential or {}).get("cookie", "")
        if self._cookie:
            self._session.headers["Cookie"] = self._cookie
        # 酷我需要 CSRF token
        self._csrf: str = ""

    # ---------- 公共接口（实验性，未实现） ----------

    def parse_song_url(self, url: str) -> SongInfo:
        """解析酷我单曲链接（实验性，尚未实现）。

        Args:
            url: 单曲链接。

        Raises:
            ParserError: 实验性平台，功能尚未实现。
        """
        raise ParserError(
            "酷我音乐解析为实验性功能，暂未实现完整解析逻辑"
        )

    def parse_playlist_url(self, url: str) -> PlaylistInfo:
        """解析酷我歌单/专辑链接（实验性，尚未实现）。

        Args:
            url: 歌单或专辑链接。

        Raises:
            ParserError: 实验性平台，功能尚未实现。
        """
        raise ParserError(
            "酷我音乐解析为实验性功能，暂未实现完整解析逻辑"
        )

    def get_download_url(self, song_info: SongInfo, quality: str) -> str:
        """获取酷我歌曲下载直链（实验性，尚未实现）。

        Args:
            song_info: 歌曲信息。
            quality: 音质标识。

        Raises:
            ParserError: 实验性平台，功能尚未实现。
        """
        raise ParserError(
            "酷我音乐下载为实验性功能，暂未实现完整下载逻辑"
        )

    # ---------- 预留工具方法 ----------

    @staticmethod
    def _extract_song_id(url: str) -> str:
        """从 URL 提取歌曲 ID（预留）。"""
        m = _SONG_ID_RE.search(url)
        if not m:
            raise ParserError(f"无法从链接中提取歌曲 ID: {url}")
        return m.group(1)

    @staticmethod
    def _build_quality_list(copyright_restricted: bool) -> list[QualityInfo]:
        """构建默认音质列表（预留）。"""
        return [
            QualityInfo(
                quality=QUALITY_STANDARD,
                bitrate=128000,
                extension=QUALITY_EXTENSIONS[QUALITY_STANDARD],
                available=not copyright_restricted,
            ),
            QualityInfo(
                quality=QUALITY_HIGHER,
                bitrate=320000,
                extension=QUALITY_EXTENSIONS[QUALITY_HIGHER],
                available=not copyright_restricted,
            ),
            QualityInfo(
                quality=QUALITY_LOSSLESS,
                bitrate=999000,
                extension=QUALITY_EXTENSIONS[QUALITY_LOSSLESS],
                available=False,  # 无损需要登录
            ),
        ]
