"""
视频解析下载模块。

提供各平台视频链接的解析和下载能力，统一通过
:func:`core.video.base.get_video_parser` 工厂函数获取解析器，
或使用 :class:`core.video.downloader.VideoDownloader` 一站式下载。

支持平台：
- 稳定版：Bilibili、Douyin、YouTube
- 实验性：Kuaishou、Weibo、Xiaohongshu、Xigua、Zhihu、Twitter、TikTok、Instagram、Facebook

免责声明：本模块仅供个人学习研究使用，请尊重版权，下载内容请于 24 小时内删除。
"""

from .base import (
    BaseVideoParser,
    QualityOption,
    VideoInfo,
    get_video_parser,
    list_supported_platforms,
)
from .downloader import VideoDownloader

__all__ = [
    "BaseVideoParser",
    "QualityOption",
    "VideoInfo",
    "get_video_parser",
    "list_supported_platforms",
    "VideoDownloader",
]
