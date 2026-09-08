"""
音乐解析器基类与工厂函数。

所有音乐平台解析器继承 :class:`BaseMusicParser`，实现统一的
``parse_song_url`` / ``parse_playlist_url`` / ``get_download_url`` 接口。
工厂函数 :func:`get_music_parser` 根据 URL 域名自动匹配对应解析器。

音质等级定义：
- ``standard`` — 标准 MP3 128kbps
- ``higher``   — 高品质 MP3 320kbps
- ``lossless`` — FLAC 无损

免责声明：本模块仅供个人学习研究使用，请尊重版权，下载内容请于 24 小时内删除。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ..exceptions import ParserError


# ---------- 音质常量 ----------

QUALITY_STANDARD = "standard"
"""标准音质（MP3 128kbps）。"""

QUALITY_HIGHER = "higher"
"""高品质（MP3 320kbps）。"""

QUALITY_LOSSLESS = "lossless"
"""无损音质（FLAC）。"""

# 音质从低到高排序
QUALITY_ORDER = [QUALITY_STANDARD, QUALITY_HIGHER, QUALITY_LOSSLESS]

# 音质描述映射
QUALITY_LABELS = {
    QUALITY_STANDARD: "标准 128kbps",
    QUALITY_HIGHER: "高品质 320kbps",
    QUALITY_LOSSLESS: "无损 FLAC",
}

# 音质对应文件扩展名
QUALITY_EXTENSIONS = {
    QUALITY_STANDARD: "mp3",
    QUALITY_HIGHER: "mp3",
    QUALITY_LOSSLESS: "flac",
}


@dataclass
class QualityInfo:
    """单条音质信息。

    Attributes:
        quality: 音质标识（``standard`` / ``higher`` / ``lossless``）。
        label: 音质描述（如 ``"高品质 320kbps"``）。
        bitrate: 比特率（bps），未知时为 ``None``。
        extension: 文件扩展名（``"mp3"`` / ``"flac"``）。
        size: 文件大小（字节），未知时为 ``None``。
        available: 该音质是否可用（版权受限或未登录时可能不可用）。
    """

    quality: str
    label: str = ""
    bitrate: int | None = None
    extension: str = "mp3"
    size: int | None = None
    available: bool = True

    def __post_init__(self) -> None:
        if not self.label:
            self.label = QUALITY_LABELS.get(self.quality, self.quality)
        if self.extension == "mp3" and self.quality not in QUALITY_EXTENSIONS:
            pass


@dataclass
class SongInfo:
    """歌曲解析结果。

    Attributes:
        song_id: 平台内部歌曲 ID。
        title: 歌曲名称。
        artist: 歌手名称（多人用 ``/`` 分隔）。
        album: 专辑名称。
        cover: 封面图片 URL。
        duration: 歌曲时长（秒）。
        quality_list: 可用音质列表。
        source: 来源平台标识（如 ``"netease"``、``"qqmusic"``）。
        raw_response: 服务端原始响应，供调试和扩展使用。
        copyright_restricted: 是否因版权限制无法下载。
    """

    song_id: str
    title: str
    artist: str = ""
    album: str = ""
    cover: str = ""
    duration: int = 0
    quality_list: list[QualityInfo] = field(default_factory=list)
    source: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)
    copyright_restricted: bool = False

    def get_quality(self, quality: str) -> QualityInfo | None:
        """获取指定音质的信息。

        Args:
            quality: 音质标识。

        Returns:
            对应的 :class:`QualityInfo`；不存在或不可用时返回 ``None``。
        """
        for q in self.quality_list:
            if q.quality == quality:
                return q if q.available else None
        return None

    def best_available_quality(self) -> QualityInfo | None:
        """获取当前可用的最高音质。

        Returns:
            最高可用音质的 :class:`QualityInfo`；无可用音质时返回 ``None``。
        """
        for q in reversed(QUALITY_ORDER):
            info = self.get_quality(q)
            if info is not None:
                return info
        return None


@dataclass
class PlaylistInfo:
    """歌单/专辑解析结果。

    Attributes:
        playlist_id: 平台内部歌单 ID。
        title: 歌单名称。
        creator: 创建者名称。
        cover: 歌单封面 URL。
        description: 歌单描述。
        song_count: 歌曲总数。
        songs: 歌曲列表（每项为 :class:`SongInfo`）。
        source: 来源平台标识。
        playlist_type: 歌单类型（``"playlist"`` / ``"album"``）。
        raw_response: 服务端原始响应。
    """

    playlist_id: str
    title: str
    creator: str = ""
    cover: str = ""
    description: str = ""
    song_count: int = 0
    songs: list[SongInfo] = field(default_factory=list)
    source: str = ""
    playlist_type: str = "playlist"
    raw_response: dict[str, Any] = field(default_factory=dict)


class BaseMusicParser(ABC):
    """音乐解析器抽象基类。

    子类必须声明 :attr:`supported_domains` 并实现
    :meth:`parse_song_url`、:meth:`parse_playlist_url`、:meth:`get_download_url`。
    """

    #: 该解析器支持的域名列表（小写，不含协议）。
    supported_domains: list[str] = []

    #: 平台标识（如 ``"netease"``、``"qqmusic"``）。
    source_name: str = ""

    #: 解析器状态（``"stable"`` / ``"experimental"``）。
    status: str = "stable"

    #: 是否为实验性平台（等价于 status == "experimental"）。
    experimental: bool = False

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        """初始化解析器。

        Args:
            credential: 登录凭证字典（Cookie / Token 等），高音质下载通常需要。
        """
        self.credential = credential or {}

    # ---------- 抽象接口 ----------

    @abstractmethod
    def parse_song_url(self, url: str) -> SongInfo:
        """解析单曲链接，返回歌曲信息与可用音质列表。

        Args:
            url: 单曲分享链接。

        Returns:
            :class:`SongInfo`，包含歌曲元数据和可用音质列表。

        Raises:
            ParserError: 解析失败（链接无效、API 变更等）。
        """

    @abstractmethod
    def parse_playlist_url(self, url: str) -> PlaylistInfo:
        """解析歌单/专辑链接，返回歌单信息与歌曲列表。

        Args:
            url: 歌单或专辑分享链接。

        Returns:
            :class:`PlaylistInfo`，包含歌单元数据和歌曲列表。

        Raises:
            ParserError: 解析失败。
        """

    @abstractmethod
    def get_download_url(self, song_info: SongInfo, quality: str) -> str:
        """获取指定音质的下载直链。

        Args:
            song_info: 已解析的歌曲信息。
            quality: 音质标识（``standard`` / ``higher`` / ``lossless``）。

        Returns:
            下载直链 URL。

        Raises:
            ParserError: 获取直链失败（版权受限、音质不可用等）。
        """

    # ---------- 通用工具 ----------

    @classmethod
    def matches_domain(cls, url: str) -> bool:
        """判断该解析器是否支持给定 URL 的域名。

        Args:
            url: 待检测的 URL。

        Returns:
            支持时返回 ``True``。
        """
        try:
            host = urlparse(url).hostname or ""
            host = host.lower()
            return any(
                host == d or host.endswith("." + d) for d in cls.supported_domains
            )
        except Exception:
            return False

    @staticmethod
    def _extract_id_from_url(url: str, pattern: str) -> str:
        """从 URL 中提取 ID。

        Args:
            url: 原始 URL。
            pattern: 正则表达式（需包含一个捕获组）。

        Returns:
            提取到的 ID。

        Raises:
            ParserError: 无法从 URL 中提取 ID。
        """
        m = re.search(pattern, url)
        if not m:
            raise ParserError(f"无法从链接中提取 ID: {url}")
        return m.group(1)

    @staticmethod
    def _safe_filename(name: str) -> str:
        """生成安全的文件名（移除非法字符）。

        Args:
            name: 原始文件名。

        Returns:
            清理后的文件名。
        """
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


# ---------- 工厂函数 ----------

def _get_all_music_parsers() -> list[type[BaseMusicParser]]:
    """延迟导入所有音乐解析器，避免循环依赖。"""
    from .netease import NetEaseParser
    from .qqmusic import QQMusicParser
    from .kugou import KuGouParser
    from .kuwo import KuWoParser

    return [NetEaseParser, QQMusicParser, KuGouParser, KuWoParser]


def get_music_parser(
    url: str, credential: dict[str, Any] | None = None
) -> BaseMusicParser:
    """根据音乐链接的域名自动匹配并实例化解析器。

    Args:
        url: 音乐分享链接（单曲/歌单/专辑）。
        credential: 可选的登录凭证（高音质下载通常需要）。

    Returns:
        匹配到的解析器实例。

    Raises:
        ParserError: 无法识别的音乐平台链接。
    """
    for parser_cls in _get_all_music_parsers():
        if parser_cls.matches_domain(url):
            return parser_cls(credential=credential)
    raise ParserError(f"无法识别的音乐平台链接: {url}")


def list_supported_music_sources() -> list[dict[str, Any]]:
    """列出所有支持的音乐平台及其状态。

    Returns:
        列表，每项包含 ``source``、``domains``、``status``、``experimental``。
    """
    result = []
    for parser_cls in _get_all_music_parsers():
        result.append(
            {
                "source": parser_cls.source_name,
                "domains": parser_cls.supported_domains,
                "status": parser_cls.status,
                "experimental": parser_cls.experimental,
            }
        )
    return result
