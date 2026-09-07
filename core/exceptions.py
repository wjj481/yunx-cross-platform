"""
统一异常定义。

所有核心引擎抛出的异常均继承自 :class:`YunXError`，便于上层统一捕获。
"""

from __future__ import annotations


class YunXError(Exception):
    """所有 YunX 异常的基类。"""


class ParserError(YunXError):
    """网盘分享链接解析失败。

    通常由 API 变更、分享失效、提取码错误等触发。
    携带服务端原始 message 以便 UI 展示。
    """

    def __init__(self, message: str = "解析失败", code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class NetworkError(YunXError):
    """网络请求失败（连接超时、DNS 错误、HTTP 非预期状态等）。"""


class DownloadError(YunXError):
    """下载引擎失败（分片写入、合并、校验等环节出错）。"""


class BaiduRiskWarning(YunXError):
    """百度网盘风控警告。

    百度网盘对自动化解析有严格的风控策略，频繁调用可能导致账号被封。
    UI 层在调用百度解析器前必须展示此警告并获得用户确认。
    """


class AuthenticationError(YunXError):
    """认证失败（Cookie 过期、Token 无效、未登录等）。"""
