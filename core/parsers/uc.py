"""
UC 网盘解析器（实验性）。

UC 网盘（drive.uc.cn）与夸克网盘同属阿里体系，API 结构类似，
但使用独立的账号体系和 Cookie 字段。

当前为基础框架，完整实现待后续补充。
"""

from __future__ import annotations

import re
from typing import Any

from ..exceptions import ParserError
from .base import BaseParser, ShareInfo

_SHARE_ID_RE = re.compile(
    r"drive\.uc\.cn/s/([A-Za-z0-9]+)", re.IGNORECASE
)


class UCParser(BaseParser):
    """UC 网盘解析器（实验性）。

    需要登录凭证（UC 网盘 Cookie）。

    凭证格式::

        {"cookie": "..."}
    """

    supported_domains = ["drive.uc.cn"]
    drive_name = "uc"
    status = "experimental"

    def parse_share_url(
        self, url: str, extract_code: str | None = None
    ) -> ShareInfo:
        """解析 UC 网盘分享链接（实验性）。

        TODO: 完整实现 UC 网盘解析流程
        - API 基础域名：https://drive-pc.uc.cn
        - 分享 Token：/1/clouddrive/share/sharepage/token
        - 文件列表：/1/clouddrive/share/sharepage/detail
        - 下载直链：/1/clouddrive/file/download
        - Cookie 关键字段：__pus / __puus（UC 体系独立）
        - 流程与夸克类似：token → 列表 → 转存 → 直链
        """
        share_id = self._extract_share_id(url)
        code = self._resolve_extract_code(url, extract_code)

        raise ParserError(
            f"UC 网盘解析器为实验性功能，尚未完整实现。"
            f"（share_id={share_id}, extract_code={code}）"
        )

    @staticmethod
    def _extract_share_id(url: str) -> str:
        m = _SHARE_ID_RE.search(url)
        if not m:
            raise ParserError(f"无法从链接中提取 UC 网盘分享 ID: {url}")
        return m.group(1)
