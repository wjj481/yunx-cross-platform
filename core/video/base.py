"""
视频解析器基类与工厂函数。

所有视频平台解析器继承 :class:`BaseVideoParser`，实现统一的
``parse_video_url`` / ``get_download_url`` 接口。
工厂函数 :func:`get_video_parser` 根据 URL 域名自动匹配对应解析器。

免责声明：本模块仅供个人学习研究使用，请尊重版权，下载内容请于 24 小时内删除。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ..exceptions import ParserError


@dataclass
class QualityOption:
    """单个清晰度选项。

    Attributes:
        quality: 清晰度标识（如 ``"1080p"``、``"720p"``、``"480p"``）。
        file_size: 文件大小（字节）；未知时为 ``0``。
        format: 容器格式（如 ``"mp4"``、``"flv"``、``"webm"``）。
        code: 平台内部清晰度代码（如 B 站 qn 值、YouTube itag）。
        description: 人类可读描述（如 ``"1080P 高清"``）。
    """

    quality: str
    file_size: int = 0
    format: str = "mp4"
    code: str = ""
    description: str = ""


@dataclass
class VideoInfo:
    """视频解析结果。

    Attributes:
        title: 视频标题。
        cover: 封面图 URL。
        duration: 时长（秒）。
        quality_list: 可用清晰度列表，按清晰度从高到低排序。
        file_size: 默认清晰度文件大小（字节）；未知时为 ``0``。
        platform: 平台标识（如 ``"bilibili"``、``"douyin"``）。
        video_id: 平台内部视频 ID。
        raw_response: 服务端原始响应，供调试和扩展使用。
        extra: 额外平台相关信息（如分P列表、作者等）。
    """

    title: str
    cover: str = ""
    duration: int = 0
    quality_list: list[QualityOption] = field(default_factory=list)
    file_size: int = 0
    platform: str = ""
    video_id: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def best_quality(self) -> QualityOption | None:
        """获取最高清晰度选项。

        Returns:
            清晰度列表第一项（已按从高到低排序）；列表为空时返回 ``None``。
        """
        return self.quality_list[0] if self.quality_list else None

    def find_quality(self, quality: str) -> QualityOption | None:
        """按清晰度标识查找选项。

        Args:
            quality: 清晰度标识（如 ``"1080p"``），不区分大小写。

        Returns:
            匹配的 :class:`QualityOption`；未找到时返回 ``None``。
        """
        target = quality.lower()
        for q in self.quality_list:
            if q.quality.lower() == target:
                return q
        return None


class BaseVideoParser(ABC):
    """视频解析器抽象基类。

    子类必须声明 :attr:`supported_domains` 并实现
    :meth:`parse_video_url` 和 :meth:`get_download_url`。
    """

    #: 该解析器支持的域名列表（小写，不含协议）。
    supported_domains: list[str] = []

    #: 平台标识（如 ``"bilibili"``、``"douyin"``）。
    platform_name: str = ""

    #: 是否为实验性实现。
    experimental: bool = False

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        """初始化解析器。

        Args:
            credential: 登录凭证字典（Cookie / Token 等），由上层从配置管理器传入。
        """
        self.credential = credential or {}

    @abstractmethod
    def parse_video_url(self, url: str) -> VideoInfo:
        """解析视频链接，返回视频元信息与可用清晰度列表。

        Args:
            url: 视频页面链接。

        Returns:
            解析结果 :class:`VideoInfo`。

        Raises:
            ParserError: 解析失败（链接无效、视频不存在、API 变更等）。
        """

    @abstractmethod
    def get_download_url(
        self, video_info: VideoInfo, quality: str
    ) -> str:
        """获取指定清晰度的下载直链。

        Args:
            video_info: :meth:`parse_video_url` 返回的视频信息。
            quality: 清晰度标识（如 ``"1080p"``）。

        Returns:
            下载直链 URL。

        Raises:
            ParserError: 获取直链失败或清晰度不可用。
        """

    @classmethod
    def matches_domain(cls, url: str) -> bool:
        """判断该解析器是否支持给定 URL 的域名。

        Args:
            url: 待判断的 URL。

        Returns:
            支持则返回 ``True``。
        """
        try:
            host = urlparse(url).hostname or ""
            host = host.lower()
            return any(
                host == d or host.endswith("." + d) for d in cls.supported_domains
            )
        except Exception:
            return False

    # ---------- 通用工具 ----------

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符。"""
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


# ---------- 工厂函数 ----------

def _get_all_parsers() -> list[type[BaseVideoParser]]:
    """延迟导入所有视频解析器，避免循环依赖。"""
    from .bilibili import BilibiliParser
    from .douyin import DouyinParser
    from .youtube import YoutubeParser
    from .kuaishou import KuaishouParser
    from .weibo import WeiboParser
    from .xiaohongshu import XiaohongshuParser
    from .xigua import XiguaParser
    from .zhihu import ZhihuParser
    from .twitter import TwitterParser
    from .tiktok import TiktokParser
    from .instagram import InstagramParser
    from .facebook import FacebookParser

    return [
        BilibiliParser,
        DouyinParser,
        YoutubeParser,
        KuaishouParser,
        WeiboParser,
        XiaohongshuParser,
        XiguaParser,
        ZhihuParser,
        TwitterParser,
        TiktokParser,
        InstagramParser,
        FacebookParser,
    ]


def get_video_parser(
    url: str, credential: dict[str, Any] | None = None
) -> BaseVideoParser:
    """根据视频链接的域名自动匹配并实例化解析器。

    Args:
        url: 视频链接。
        credential: 可选的登录凭证。

    Returns:
        匹配到的视频解析器实例。

    Raises:
        ParserError: 无法识别的视频链接。
    """
    for parser_cls in _get_all_parsers():
        if parser_cls.matches_domain(url):
            return parser_cls(credential=credential)
    raise ParserError(f"无法识别的视频链接: {url}")


def list_supported_platforms() -> list[dict[str, Any]]:
    """列出所有支持的视频平台及其状态。

    Returns:
        列表，每项包含 ``platform``、``domains``、``experimental``。
    """
    result = []
    for parser_cls in _get_all_parsers():
        result.append(
            {
                "platform": parser_cls.platform_name,
                "domains": parser_cls.supported_domains,
                "experimental": parser_cls.experimental,
            }
        )
    return result
