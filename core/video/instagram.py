"""
Instagram 视频解析器（实验性框架）。

TODO: 完整实现
- Reels / Post / IGTV 链接解析
- 短链重定向（``instagram.com/reel/`` / ``/p/``）
- GraphQL API（需登录 Cookie）
- 视频直链提取
- 轮播图（carousel）中的视频处理

免责声明：仅供个人学习研究使用，请尊重版权。
"""

from __future__ import annotations

from typing import Any

import requests

from ..exceptions import ParserError
from .base import BaseVideoParser, QualityOption, VideoInfo


class InstagramParser(BaseVideoParser):
    """Instagram 视频解析器（实验性）。

    当前为框架代码，核心解析逻辑待实现。
    """

    supported_domains = [
        "instagram.com",
        "cdninstagram.com",
        "fbcdn.net",
    ]
    platform_name = "instagram"
    experimental = True

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._cookie: str = (credential or {}).get("cookie", "")

    def parse_video_url(self, url: str) -> VideoInfo:
        """解析 Instagram 视频链接（实验性，尚未完整实现）。

        Args:
            url: Instagram Reels / Post 链接。

        Returns:
            :class:`VideoInfo`。

        Raises:
            ParserError: 解析失败。
        """
        # TODO: 实现 Instagram 视频解析
        # 1. 从 /reel/xxx 或 /p/xxx 提取 shortcode
        # 2. 调用 GraphQL: /api/graphql?query_hash=...&variables={"shortcode":"xxx"}
        #    需要登录 Cookie（sessionid）和 x-csrftoken
        # 3. 解析 shortcode_media.video_url
        # 4. 处理 edge_sidecar_to_children（轮播图）
        # 5. 视频通常只有单一清晰度
        raise ParserError(
            "Instagram 解析器为实验性功能，尚未完整实现。"
            "当前支持的平台：Bilibili / Douyin / YouTube。"
        )

    def get_download_url(
        self, video_info: VideoInfo, quality: str
    ) -> str:
        """获取下载直链（实验性，尚未完整实现）。"""
        raise ParserError("Instagram 解析器尚未完整实现")
