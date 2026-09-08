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
from .config_export import (
    export_config,
    import_config,
    is_encrypted,
    apply_imported_config,
)

__all__ = [
    "YunXError",
    "ParserError",
    "NetworkError",
    "DownloadError",
    "BaiduRiskWarning",
    "AuthenticationError",
    "export_config",
    "import_config",
    "is_encrypted",
    "apply_imported_config",
]

__version__ = "0.1.0"
