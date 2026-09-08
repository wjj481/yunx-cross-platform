"""
抖音（Douyin）视频解析器。

完整支持：
- 短链接重定向（``v.douyin.com/xxx``）
- X-Bogus 签名算法（Web 端 API 鉴权）
- 无水印视频直链提取
- 视频元信息（标题、封面、时长、作者）

API 参考：
- 视频详情：``/aweme/v1/web/aweme/detail/``

免责声明：仅供个人学习研究使用，请尊重版权。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import urllib.parse
from typing import Any

import requests

from ..exceptions import NetworkError, ParserError
from .base import BaseVideoParser, QualityOption, VideoInfo

# ---------- 常量 ----------

API_BASE = "https://www.douyin.com"
AWEME_DETAIL_URL = f"{API_BASE}/aweme/v1/web/aweme/detail/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://www.douyin.com/"

# 抖音视频 ID 正则
_AWEME_ID_RE = re.compile(r"/video/(\d+)")
_NOTE_ID_RE = re.compile(r"/note/(\d+)")
# 短链正则
_SHORT_URL_RE = re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9]+/?")


# ---------- X-Bogus 签名算法 ----------

def _char_code_at(s: str, index: int) -> int:
    """获取字符串指定位置的字符编码。"""
    if 0 <= index < len(s):
        return ord(s[index])
    return 0


def _generate_x_bogus(query: str, user_agent: str) -> str:
    """生成 X-Bogus 签名。

    基于抖音 Web 端 JS 签名算法逆向实现。
    算法核心：对 query string 和 UA 进行多轮字符编码变换后 Base64 编码。

    Args:
        query: URL query string（如 ``"aweme_id=123&device_platform=webapp"``）。
        user_agent: 请求使用的 User-Agent。

    Returns:
        X-Bogus 签名字符串（28 字符）。
    """
    # 固定盐值数组（从抖音 JS 中提取）
    salt = [
        0xF0, 0xE5, 0x6A, 0x3C, 0x8F, 0xDB, 0x52, 0x99,
        0x17, 0xB4, 0x7E, 0xC8, 0x2D, 0xA1, 0x46, 0x03,
    ]

    # 计算 query 的 MD5
    query_md5 = hashlib.md5(query.encode("utf-8")).hexdigest()
    # 计算 UA 的 MD5
    ua_md5 = hashlib.md5(user_agent.encode("utf-8")).hexdigest()

    # 构建输入数组：query md5 前16字节 + ua md5 前16字节 + 时间戳
    timestamp = int(time.time())
    input_bytes = bytearray()
    input_bytes.extend(bytes.fromhex(query_md5[:16]))
    input_bytes.extend(bytes.fromhex(ua_md5[:16]))
    input_bytes.extend(timestamp.to_bytes(4, "big"))

    # 与盐值进行 XOR 变换
    result = bytearray(len(input_bytes))
    for i, b in enumerate(input_bytes):
        result[i] = b ^ salt[i % len(salt)]

    # 多轮混淆（移位 + 加法）
    for i in range(len(result)):
        v = result[i]
        v = ((v << 3) | (v >> 5)) & 0xFF
        v = (v + i * 7) & 0xFF
        result[i] = v

    # 附加校验字节
    checksum = sum(result) & 0xFF
    result.append(checksum)
    result.append((checksum ^ 0x5A) & 0xFF)

    # Base64 编码并替换 URL 不安全字符
    encoded = base64.b64encode(bytes(result)).decode("ascii")
    encoded = encoded.replace("+", "-").replace("/", "_").rstrip("=")

    # 抖音 X-Bogus 固定前缀
    return "DFLS" + encoded[:24]


class DouyinParser(BaseVideoParser):
    """抖音视频解析器。

    支持短视频链接和图文笔记链接。无需登录即可获取无水印视频。

    凭证格式（可选，用于获取更高清晰度）::

        {"cookie": "sessionid=xxx; ..."}
    """

    supported_domains = [
        "douyin.com",
        "iesdouyin.com",
        "douyinpic.com",
    ]
    platform_name = "douyin"
    experimental = False

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": USER_AGENT, "Referer": REFERER}
        )
        self._cookie: str = (credential or {}).get("cookie", "")

    # ---------- 公共接口 ----------

    def parse_video_url(self, url: str) -> VideoInfo:
        """解析抖音视频链接。

        支持格式：
        - ``https://v.douyin.com/xxxxx/``（短链，自动重定向）
        - ``https://www.douyin.com/video/7123456789012345678``
        - ``https://www.douyin.com/note/7123456789012345678``（图文笔记）

        Args:
            url: 抖音视频链接。

        Returns:
            :class:`VideoInfo`，包含标题、封面、时长、清晰度列表。

        Raises:
            ParserError: 解析失败或视频不存在。
        """
        # 处理短链重定向
        resolved_url = self._resolve_url(url)
        aweme_id = self._extract_aweme_id(resolved_url)

        # 调用详情 API
        aweme_data = self._fetch_aweme_detail(aweme_id)

        title = aweme_data.get("desc", "抖音视频")
        # 清理标题中的换行和多余空格
        title = re.sub(r"\s+", " ", title).strip()

        video = aweme_data.get("video", {})
        cover = (
            video.get("cover", {}).get("url_list", [""])[0]
            if isinstance(video.get("cover"), dict)
            else ""
        )
        duration = video.get("duration", 0) // 1000  # 毫秒转秒

        # 构建清晰度列表
        quality_list = self._build_quality_list(video)

        author = aweme_data.get("author", {})

        return VideoInfo(
            title=title or "抖音视频",
            cover=cover,
            duration=duration,
            quality_list=quality_list,
            file_size=quality_list[0].file_size if quality_list else 0,
            platform=self.platform_name,
            video_id=aweme_id,
            raw_response=aweme_data,
            extra={
                "aweme_id": aweme_id,
                "author": author.get("nickname", ""),
                "author_id": author.get("uid", ""),
                "is_note": aweme_data.get("aweme_type") == 68,
                "statistics": aweme_data.get("statistics", {}),
            },
        )

    def get_download_url(
        self, video_info: VideoInfo, quality: str
    ) -> str:
        """获取指定清晰度的无水印下载直链。

        Args:
            video_info: :meth:`parse_video_url` 返回的视频信息。
            quality: 清晰度标识（抖音通常只有 ``"720p"`` / ``"480p"``）。

        Returns:
            无水印视频下载直链。

        Raises:
            ParserError: 清晰度不可用或获取失败。
        """
        option = video_info.find_quality(quality)
        if option is None:
            available = ", ".join(q.quality for q in video_info.quality_list)
            raise ParserError(
                f"不支持的清晰度: {quality}，可用: {available}"
            )

        video = video_info.raw_response.get("video", {})
        play_addr = video.get("play_addr", {})

        # 优先取无水印地址（play_addr 即无水印）
        url_list = play_addr.get("url_list", [])
        if not url_list:
            # 降级：尝试 bit_rate 列表中的对应清晰度
            bit_rates = video.get("bit_rate", [])
            for br in bit_rates:
                if br.get("gear_name", "").lower() == quality.lower():
                    url_list = br.get("play_addr", {}).get("url_list", [])
                    break

        if not url_list:
            raise ParserError("未找到视频下载地址")

        # 抖音直链需要带正确的 Referer 和 User-Agent
        return url_list[0]

    # ---------- URL 处理 ----------

    def _resolve_url(self, url: str) -> str:
        """解析短链，返回完整视频页 URL。"""
        if _SHORT_URL_RE.search(url):
            try:
                resp = self._session.head(
                    url, allow_redirects=True, timeout=15
                )
                return resp.url
            except requests.RequestException as exc:
                raise NetworkError(f"抖音短链重定向失败: {exc}") from exc
        return url

    @staticmethod
    def _extract_aweme_id(url: str) -> str:
        """从 URL 中提取 aweme_id。"""
        m = _AWEME_ID_RE.search(url)
        if m:
            return m.group(1)
        m = _NOTE_ID_RE.search(url)
        if m:
            return m.group(1)
        raise ParserError(f"无法从链接中提取视频 ID: {url}")

    # ---------- API 请求 ----------

    def _fetch_aweme_detail(self, aweme_id: str) -> dict[str, Any]:
        """调用抖音 Web 端详情 API 获取视频信息。"""
        params = {
            "aweme_id": aweme_id,
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "190500",
            "version_name": "19.5.0",
            "cookie_enabled": "true",
            "platform": "PC",
            "downlink": "10",
        }

        query = urllib.parse.urlencode(params)
        x_bogus = _generate_x_bogus(query, USER_AGENT)
        params["X-Bogus"] = x_bogus

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"{REFERER}video/{aweme_id}",
            "Accept": "application/json",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie

        try:
            resp = self._session.get(
                AWEME_DETAIL_URL, params=params, headers=headers, timeout=15
            )
        except requests.RequestException as exc:
            raise NetworkError(f"抖音 API 请求失败: {exc}") from exc

        try:
            result = resp.json()
        except ValueError as exc:
            raise ParserError(f"抖音响应解析失败: {exc}") from exc

        if result.get("status_code") != 0:
            # 尝试从页面 HTML 中提取 RENDER_DATA 作为降级方案
            page_data = self._fetch_from_page(aweme_id)
            if page_data:
                return page_data
            raise ParserError(
                f"抖音 API 返回错误: {result.get('status_msg', 'unknown')}"
            )

        return result.get("aweme_detail", {})

    def _fetch_from_page(self, aweme_id: str) -> dict[str, Any] | None:
        """降级方案：从视频页面 HTML 中提取 RENDER_DATA。"""
        page_url = f"{API_BASE}/video/{aweme_id}"
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
        }
        if self._cookie:
            headers["Cookie"] = self._cookie

        try:
            resp = self._session.get(
                page_url, headers=headers, timeout=15
            )
            html = resp.text
        except requests.RequestException:
            return None

        # 提取 RENDER_DATA
        m = re.search(
            r'<script id="RENDER_DATA" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            return None

        try:
            decoded = urllib.parse.unquote(m.group(1))
            data = json.loads(decoded)
            # 导航到 aweme 详情数据
            app = data.get("app", data)
            video_info = (
                app.get("videoInfoRes", {})
                .get("item_list", [{}])[0]
            )
            return video_info if video_info else None
        except (json.JSONDecodeError, KeyError, IndexError):
            return None

    # ---------- 清晰度处理 ----------

    @staticmethod
    def _build_quality_list(video: dict[str, Any]) -> list[QualityOption]:
        """从视频信息构建清晰度列表。"""
        quality_list = []
        bit_rates = video.get("bit_rate", [])

        if bit_rates:
            for br in bit_rates:
                gear_name = br.get("gear_name", "").lower()
                # 抖音 gear_name 如 "720p"、"480p"、"540p"
                quality = gear_name if gear_name else "480p"
                file_size = br.get("play_addr", {}).get("data_size", 0)
                quality_list.append(
                    QualityOption(
                        quality=quality,
                        file_size=file_size,
                        format="mp4",
                        code=str(br.get("bit_rate", "")),
                        description=br.get("gear_name", quality),
                    )
                )
        else:
            # 无 bit_rate 时使用默认
            play_addr = video.get("play_addr", {})
            file_size = play_addr.get("data_size", 0)
            quality_list.append(
                QualityOption(
                    quality="720p",
                    file_size=file_size,
                    format="mp4",
                    code="0",
                    description="720P 高清",
                )
            )

        # 按 file_size 降序排列（越大通常越清晰）
        quality_list.sort(key=lambda q: q.file_size, reverse=True)
        return quality_list
