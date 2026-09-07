"""
网盘解析器基类与工厂函数。

所有网盘解析器继承 :class:`BaseParser`，实现统一的 ``parse_share_url`` 接口。
工厂函数 :func:`get_parser` 根据 URL 域名自动匹配对应解析器。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, parse_qs

from ..exceptions import ParserError


@dataclass
class ShareInfo:
    """分享解析结果。

    Attributes:
        file_name: 文件名。
        file_size: 文件大小（字节）。
        file_type: 文件类型（扩展名，如 ``"mp4"``、``"zip"``；目录为 ``"dir"``）。
        direct_url: 下载直链。
        expires_at: 直链过期时间（UTC）；未知时为 ``None``。
        raw_response: 服务端原始响应（JSON 字典），供调试和扩展使用。
        share_id: 分享 ID（短码）。
        extract_code: 提取码。
        drive: 网盘标识。
    """

    file_name: str
    file_size: int
    file_type: str
    direct_url: str
    expires_at: datetime | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    share_id: str = ""
    extract_code: str | None = None
    drive: str = ""


def _extract_code_from_url(url: str) -> str | None:
    """从 URL 中自动提取提取码。

    支持格式：
    - ``url#code``（fragment）
    - ``url?pwd=code`` / ``url?password=code`` / ``url?passcode=code``
    """
    try:
        parsed = urlparse(url)
        # query 参数
        qs = parse_qs(parsed.query)
        for key in ("pwd", "password", "passcode", "code"):
            if key in qs and qs[key]:
                return qs[key][0]
        # fragment（4-8 位字母数字视为提取码）
        if parsed.fragment and re.fullmatch(r"[A-Za-z0-9]{4,8}", parsed.fragment):
            return parsed.fragment
    except Exception:
        pass
    return None


class BaseParser(ABC):
    """网盘解析器抽象基类。

    子类必须声明 :attr:`supported_domains` 并实现 :meth:`parse_share_url`。
    """

    #: 该解析器支持的域名列表（小写，不含协议）。
    supported_domains: list[str] = []

    #: 网盘标识（如 ``"quark"``、``"pan123"``）。
    drive_name: str = ""

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        """初始化解析器。

        Args:
            credential: 登录凭证字典（Cookie / Token 等），由上层从配置管理器传入。
        """
        self.credential = credential or {}

    @abstractmethod
    def parse_share_url(
        self, url: str, extract_code: str | None = None
    ) -> ShareInfo:
        """解析分享链接，返回文件信息与下载直链。

        Args:
            url: 分享链接。
            extract_code: 提取码；为 ``None`` 时尝试从 URL 自动提取。

        Returns:
            解析结果 :class:`ShareInfo`。

        Raises:
            ParserError: 解析失败（分享失效、提取码错误、API 变更等）。
        """

    def _resolve_extract_code(
        self, url: str, extract_code: str | None
    ) -> str | None:
        """解析提取码：显式传入优先，否则从 URL 自动提取。"""
        if extract_code:
            return extract_code
        return _extract_code_from_url(url)

    @classmethod
    def matches_domain(cls, url: str) -> bool:
        """判断该解析器是否支持给定 URL 的域名。"""
        try:
            host = urlparse(url).hostname or ""
            host = host.lower()
            return any(host == d or host.endswith("." + d) for d in cls.supported_domains)
        except Exception:
            return False


# ---------- 工厂函数 ----------

def _get_all_parsers() -> list[type[BaseParser]]:
    """延迟导入所有解析器，避免循环依赖。"""
    from .quark import QuarkParser
    from .pan123 import Pan123Parser
    from .xunlei import XunleiParser
    from .baidu import BaiduParser
    from .uc import UCParser
    from .caiyun import CaiyunParser

    return [QuarkParser, Pan123Parser, XunleiParser, BaiduParser, UCParser, CaiyunParser]


def get_parser(url: str, credential: dict[str, Any] | None = None) -> BaseParser:
    """根据分享链接的域名自动匹配并实例化解析器。

    Args:
        url: 分享链接。
        credential: 可选的登录凭证。

    Returns:
        匹配到的解析器实例。

    Raises:
        ParserError: 无法识别的网盘链接。
    """
    for parser_cls in _get_all_parsers():
        if parser_cls.matches_domain(url):
            return parser_cls(credential=credential)
    raise ParserError(f"无法识别的网盘分享链接: {url}")


def list_supported_drives() -> list[dict[str, Any]]:
    """列出所有支持的网盘及其状态。

    Returns:
        列表，每项包含 ``drive``、``domains``、``status``（``"stable"`` / ``"experimental"``）。
    """
    result = []
    for parser_cls in _get_all_parsers():
        status = getattr(parser_cls, "status", "stable")
        result.append(
            {
                "drive": parser_cls.drive_name,
                "domains": parser_cls.supported_domains,
                "status": status,
            }
        )
    return result
