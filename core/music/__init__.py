"""
音乐解析下载模块。

提供多平台音乐解析、多音质直链获取、分片下载、ID3 标签嵌入能力。

支持平台：
- 网易云音乐（``netease``）— 完整支持
- QQ音乐（``qqmusic``）— 完整支持
- 酷狗音乐（``kugou``）— 实验性框架
- 酷我音乐（``kuwo``）— 实验性框架

快速开始::

    from core.music import get_music_parser, MusicDownloader

    # 解析单曲
    parser = get_music_parser("https://music.163.com/#/song?id=123456")
    song = parser.parse_song_url(url)
    url = parser.get_download_url(song, "higher")

    # 一键下载
    downloader = MusicDownloader(output_dir="./music")
    path = downloader.download_song(url, quality="higher")

免责声明：本模块仅供个人学习研究使用，请尊重版权，下载内容请于 24 小时内删除。
"""

from ..exceptions import MusicParseError
from .base import (
    BaseMusicParser,
    PlaylistInfo,
    QUALITY_EXTENSIONS,
    QUALITY_HIGHER,
    QUALITY_LABELS,
    QUALITY_LOSSLESS,
    QUALITY_ORDER,
    QUALITY_STANDARD,
    QualityInfo,
    SongInfo,
    get_music_parser,
    list_supported_music_sources,
)
from .id3tagger import embed_id3_tags, is_mutagen_available
from .downloader import MusicDownloader

__all__ = [
    # 异常
    "MusicParseError",
    # 基类与工厂
    "BaseMusicParser",
    "get_music_parser",
    "list_supported_music_sources",
    # 数据类
    "SongInfo",
    "PlaylistInfo",
    "QualityInfo",
    # 音质常量
    "QUALITY_STANDARD",
    "QUALITY_HIGHER",
    "QUALITY_LOSSLESS",
    "QUALITY_ORDER",
    "QUALITY_LABELS",
    "QUALITY_EXTENSIONS",
    # ID3 标签
    "embed_id3_tags",
    "is_mutagen_available",
    # 下载器
    "MusicDownloader",
]
