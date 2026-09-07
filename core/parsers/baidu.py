"""
百度网盘解析器（实验性）。

⚠️  风控警告 ⚠️
百度网盘对自动化解析和下载有极其严格的风控策略：
- 频繁调用分享解析 API 可能导致账号被临时封禁或永久封号。
- 下载直链有严格的防盗链和限速机制，非会员账号可能被限速到极低速度。
- 使用本模块可能违反百度网盘用户协议。

UI 层在调用本解析器前，必须展示 :class:`core.exceptions.BaiduRiskWarning`
警告并获得用户明确确认。

当前为基础框架，完整实现待后续补充。
"""

from __future__ import annotations

import re
from typing import Any

from ..exceptions import BaiduRiskWarning, ParserError
from .base import BaseParser, ShareInfo

_SHARE_ID_RE = re.compile(
    r"pan\.baidu\.com/s/(1[A-Za-z0-9_-]+)", re.IGNORECASE
)


class BaiduParser(BaseParser):
    """百度网盘解析器（实验性，带风控警告）。

    需要登录凭证（BDUSS Cookie）。

    凭证格式::

        {"cookie": "BDUSS=...; ..."}
    """

    supported_domains = ["pan.baidu.com", "yun.baidu.com"]
    drive_name = "baidu"
    status = "experimental"

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._risk_acknowledged = False

    def acknowledge_risk(self) -> None:
        """用户确认已知晓风控风险。UI 层必须在调用 parse_share_url 前调用此方法。"""
        self._risk_acknowledged = True

    def parse_share_url(
        self, url: str, extract_code: str | None = None
    ) -> ShareInfo:
        """解析百度网盘分享链接（实验性）。

        Raises:
            BaiduRiskWarning: 用户未确认风控风险。
            ParserError: 解析失败或功能未实现。
        """
        if not self._risk_acknowledged:
            raise BaiduRiskWarning(
                "百度网盘解析存在账号封禁风险，请确认已知晓风险后再使用。"
            )

        # TODO: 完整实现百度网盘解析流程
        # 1. POST /share/verify 验证提取码 → 获取 shareid / uk / sign
        # 2. GET /share/list 获取文件列表
        # 3. POST /api/sharedownload 获取下载直链（需要 BDUSS + 签名）
        # 参考：https://pan.baidu.com/share/verify?surl=xxx
        #       https://pan.baidu.com/s/share/list?shareid=xxx&uk=xxx
        #       https://pan.baidu.com/api/sharedownload

        share_id = self._extract_share_id(url)
        code = self._resolve_extract_code(url, extract_code)

        raise ParserError(
            f"百度网盘解析器为实验性功能，尚未完整实现。"
            f"（share_id={share_id}, extract_code={code}）"
        )

    @staticmethod
    def _extract_share_id(url: str) -> str:
        m = _SHARE_ID_RE.search(url)
        if not m:
            raise ParserError(f"无法从链接中提取百度分享 ID: {url}")
        # 百度 surl 去掉开头的 "1"
        sid = m.group(1)
        return sid[1:] if sid.startswith("1") else sid
