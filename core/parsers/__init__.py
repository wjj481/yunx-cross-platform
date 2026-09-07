"""
网盘解析器包。

提供各网盘分享链接的解析能力，统一通过 :func:`core.parsers.base.get_parser` 工厂函数获取。
"""

from .base import BaseParser, ShareInfo, get_parser, list_supported_drives

__all__ = ["BaseParser", "ShareInfo", "get_parser", "list_supported_drives"]
