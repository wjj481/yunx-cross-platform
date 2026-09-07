"""
YunX 跨平台网盘解析 + 高速下载工具 —— 核心引擎包。

本包为纯 Python 模块，与任何 GUI 框架（tkinter / Kivy）完全解耦，
可供桌面端与移动端共同调用。
"""

from .exceptions import (
    YunXError,
    ParserError,
    NetworkError,
    DownloadError,
    BaiduRiskWarning,
    AuthenticationError,
)

__all__ = [
    "YunXError",
    "ParserError",
    "NetworkError",
    "DownloadError",
    "BaiduRiskWarning",
    "AuthenticationError",
]

__version__ = "0.1.0"
