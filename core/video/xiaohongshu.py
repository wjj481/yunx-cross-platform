"""
小红书（Xiaohongshu）视频解析器（实验性框架）。

TODO: 完整实现
- 笔记链接解析（``xiaohongshu.com/explore/``）
- 短链重定向（``xhslink.com``）
- 视频笔记与图文笔记区分
- 无水印视频直链提取
- 签名算法（x-s / x-t）

免责声明：仅供个人学习研究使用，请尊重版权。
"""

from __future__ import annotations

from typing import Any

import requests

from ..exceptions import ParserError
from .base import BaseVideoParser, QualityOption, VideoInfo


class XiaohongshuParser(BaseVideoParser):
    """小红书视频解析器（实验性）。

    当前为框架代码，核心解析逻辑待实现。
    """

    supported_domains = [
        "xiaohongshu.com",
        "xhslink.com",
        "xhscdn.com",
    ]
    platform_name = "xiaohongshu"
    experimental = True

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._cookie: str = (credential or {}).get("cookie", "")

    def parse_video_url(self, url: str) -> VideoInfo:
        """解析小红书笔记链接（实验性，尚未完整实现）。

        Args:
            url: 小红书笔记链接。

        Returns:
            :class:`VideoInfo`。

        Raises:
            ParserError: 解析失败。
        """
        # TODO: 实现小红书视频解析
        # 1. 处理 xhslink.com 短链重定向
        # 2. 从 URL 提取 note_id
        # 3. 调用 /api/sns/web/v1/feed 获取笔记详情（需 x-s 签名）
        # 4. 区分视频笔记（video）和图文笔记（normal）
        # 5. 提取视频无水印直链
        raise ParserError(
            "小红书解析器为实验性功能，尚未完整实现。"
            "当前支持的平台：Bilibili / Douyin / YouTube。"
        )

    def get_download_url(
        self, video_info: VideoInfo, quality: str
    ) -> str:
        """获取下载直链（实验性，尚未完整实现）。"""
        raise ParserError("小红书解析器尚未完整实现")
