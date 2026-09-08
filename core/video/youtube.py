"""
YouTube 视频解析器。

完整支持：
- 多种 URL 格式的视频 ID 提取（watch / youtu.be / embed / shorts）
- itag 格式映射与清晰度列表构建
- player_response 解析（从 watch 页面提取）
- 可选 yt-dlp 后端（用于签名解密和复杂场景）

核心逻辑用 Python 重写，yt-dlp 仅作为可选降级后端。

免责声明：仅供个人学习研究使用，请尊重版权。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.parse
from typing import Any

import requests

from ..exceptions import NetworkError, ParserError
from .base import BaseVideoParser, QualityOption, VideoInfo

# ---------- 常量 ----------

WATCH_URL = "https://www.youtube.com/watch"
EMBED_URL = "https://www.youtube.com/embed/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# YouTube itag -> (清晰度, 格式, 是否含音频) 映射
_ITAG_MAP: dict[int, tuple[str, str, bool]] = {
    # 渐进式（视频+音频）
    5: ("240p", "flv", True),
    6: ("270p", "flv", True),
    13: ("144p", "3gp", True),
    17: ("144p", "3gp", True),
    18: ("360p", "mp4", True),
    22: ("720p", "mp4", True),
    34: ("360p", "flv", True),
    35: ("480p", "flv", True),
    36: ("240p", "3gp", True),
    37: ("1080p", "mp4", True),
    38: ("3072p", "mp4", True),
    43: ("360p", "webm", True),
    44: ("480p", "webm", True),
    45: ("720p", "webm", True),
    46: ("1080p", "webm", True),
    59: ("480p", "mp4", True),
    78: ("480p", "mp4", True),
    # DASH 视频流（仅视频）
    133: ("240p", "mp4", False),
    134: ("360p", "mp4", False),
    135: ("480p", "mp4", False),
    136: ("720p", "mp4", False),
    137: ("1080p", "mp4", False),
    138: ("2160p", "mp4", False),
    160: ("144p", "mp4", False),
    212: ("480p", "mp4", False),
    264: ("1440p", "mp4", False),
    266: ("2160p", "mp4", False),
    298: ("720p60", "mp4", False),
    299: ("1080p60", "mp4", False),
    # DASH WebM 视频流
    167: ("360p", "webm", False),
    168: ("480p", "webm", False),
    169: ("720p", "webm", False),
    170: ("1080p", "webm", False),
    218: ("480p", "webm", False),
    219: ("144p", "webm", False),
    242: ("240p", "webm", False),
    243: ("360p", "webm", False),
    244: ("480p", "webm", False),
    245: ("480p", "webm", False),
    246: ("480p", "webm", False),
    247: ("720p", "webm", False),
    248: ("1080p", "webm", False),
    271: ("1440p", "webm", False),
    272: ("2160p", "webm", False),
    302: ("720p60", "webm", False),
    303: ("1080p60", "webm", False),
    308: ("1440p60", "webm", False),
    313: ("2160p", "webm", False),
    315: ("2160p60", "webm", False),
    # 音频流
    139: ("audio_low", "m4a", False),
    140: ("audio", "m4a", False),
    141: ("audio_high", "m4a", False),
    249: ("audio_low", "webm", False),
    250: ("audio", "webm", False),
    251: ("audio_high", "webm", False),
}

# 视频 ID 正则（11 位 base64url 字符）
_VIDEO_ID_RE = re.compile(r"[0-9A-Za-z_-]{11}")


class YoutubeParser(BaseVideoParser):
    """YouTube 视频解析器。

    基础解析无需登录。部分受版权保护或年龄限制的视频可能需要
    使用 yt-dlp 可选后端或提供 Cookie。

    凭证格式（可选）::

        {"cookie": "SAPISID=xxx; ...", "use_ytdlp": true}
    """

    supported_domains = [
        "youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
        "googlevideo.com",
    ]
    platform_name = "youtube"
    experimental = False

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._cookie: str = (credential or {}).get("cookie", "")
        self._use_ytdlp: bool = (credential or {}).get("use_ytdlp", False)

    # ---------- 公共接口 ----------

    def parse_video_url(self, url: str) -> VideoInfo:
        """解析 YouTube 视频链接。

        支持格式：
        - ``https://www.youtube.com/watch?v=xxxxxxxxxxx``
        - ``https://youtu.be/xxxxxxxxxxx``
        - ``https://www.youtube.com/embed/xxxxxxxxxxx``
        - ``https://www.youtube.com/shorts/xxxxxxxxxxx``
        - ``https://www.youtube.com/live/xxxxxxxxxxx``

        Args:
            url: YouTube 视频链接。

        Returns:
            :class:`VideoInfo`，包含标题、封面、时长、清晰度列表。

        Raises:
            ParserError: 解析失败或视频不存在。
        """
        video_id = self._extract_video_id(url)

        # 优先尝试 yt-dlp 后端（如果启用）
        if self._use_ytdlp and self._has_ytdlp():
            try:
                return self._parse_with_ytdlp(video_id)
            except ParserError:
                pass  # 降级到内置解析

        # 内置解析：从 watch 页面提取 player_response
        player_response = self._fetch_player_response(video_id)

        video_details = player_response.get("videoDetails", {})
        title = video_details.get("title", "YouTube Video")
        cover = video_details.get("thumbnail", {}).get(
            "thumbnails", [{}]
        )[-1].get("url", "")
        duration = int(video_details.get("lengthSeconds", 0))

        # 构建清晰度列表
        quality_list = self._build_quality_list(player_response)

        return VideoInfo(
            title=title,
            cover=cover,
            duration=duration,
            quality_list=quality_list,
            file_size=quality_list[0].file_size if quality_list else 0,
            platform=self.platform_name,
            video_id=video_id,
            raw_response=player_response,
            extra={
                "video_id": video_id,
                "author": video_details.get("author", ""),
                "view_count": video_details.get("viewCount", "0"),
                "is_live": video_details.get("isLiveContent", False),
            },
        )

    def get_download_url(
        self, video_info: VideoInfo, quality: str
    ) -> str:
        """获取指定清晰度的下载直链。

        对于 DASH 分离格式，返回视频流 URL；音频需单独获取后合并。
        优先返回包含音视频的渐进式格式（itag 18/22 等）。

        Args:
            video_info: :meth:`parse_video_url` 返回的视频信息。
            quality: 清晰度标识（如 ``"720p"``、``"1080p"``）。

        Returns:
            视频下载直链。

        Raises:
            ParserError: 清晰度不可用或获取失败。
        """
        option = video_info.find_quality(quality)
        if option is None:
            available = ", ".join(q.quality for q in video_info.quality_list)
            raise ParserError(
                f"不支持的清晰度: {quality}，可用: {available}"
            )

        itag = int(option.code) if option.code else 0
        streaming_data = video_info.raw_response.get("streamingData", {})

        # 先查渐进式格式
        for fmt in streaming_data.get("formats", []):
            if fmt.get("itag") == itag:
                return self._extract_url(fmt)

        # 再查 DASH 视频流
        for fmt in streaming_data.get("adaptiveFormats", []):
            if fmt.get("itag") == itag:
                return self._extract_url(fmt)

        raise ParserError(f"未找到 itag={itag} 的视频流")

    # ---------- 视频 ID 提取 ----------

    @staticmethod
    def _extract_video_id(url: str) -> str:
        """从各种 YouTube URL 格式中提取 11 位视频 ID。"""
        parsed = urllib.parse.urlparse(url)

        # youtu.be/xxxxxxxxxxx
        if "youtu.be" in parsed.netloc:
            video_id = parsed.path.lstrip("/")
            if _VIDEO_ID_RE.fullmatch(video_id):
                return video_id

        # youtube.com/watch?v=xxx
        if parsed.path == "/watch":
            qs = urllib.parse.parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                return qs["v"][0]

        # youtube.com/embed/xxx / shorts/xxx / live/xxx
        for prefix in ("/embed/", "/shorts/", "/live/", "/v/"):
            if parsed.path.startswith(prefix):
                video_id = parsed.path[len(prefix):].split("/")[0]
                if _VIDEO_ID_RE.fullmatch(video_id):
                    return video_id

        # 最后尝试在整个 URL 中搜索 11 位 ID
        m = _VIDEO_ID_RE.search(url)
        if m:
            return m.group(0)

        raise ParserError(f"无法从链接中提取 YouTube 视频 ID: {url}")

    # ---------- player_response 解析 ----------

    def _fetch_player_response(self, video_id: str) -> dict[str, Any]:
        """从 watch 页面提取 ytInitialPlayerResponse JSON。"""
        url = f"{WATCH_URL}?v={video_id}&hl=en&has_verified=1"
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        if self._cookie:
            headers["Cookie"] = self._cookie

        try:
            resp = self._session.get(url, headers=headers, timeout=20)
        except requests.RequestException as exc:
            raise NetworkError(f"YouTube 页面请求失败: {exc}") from exc

        html = resp.text

        # 尝试提取 ytInitialPlayerResponse
        m = re.search(
            r"ytInitialPlayerResponse\s*=\s*(\{.+?\});",
            html,
            re.DOTALL,
        )
        if not m:
            # 尝试另一种格式
            m = re.search(
                r'"playerResponse":\s*(\{.+?\})\s*,\s*"',
                html,
                re.DOTALL,
            )
        if not m:
            raise ParserError("无法从页面中提取 playerResponse")

        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            raise ParserError(f"playerResponse 解析失败: {exc}") from exc

    # ---------- 清晰度列表构建 ----------

    def _build_quality_list(
        self, player_response: dict[str, Any]
    ) -> list[QualityOption]:
        """从 player_response 构建清晰度列表。

        优先展示包含音视频的渐进式格式，DASH 格式作为补充。
        """
        streaming_data = player_response.get("streamingData", {})
        if not streaming_data:
            # 检查是否需要解密签名或有错误
            playability = player_response.get("playabilityStatus", {})
            status = playability.get("status", "ERROR")
            reason = playability.get("reason", "未知错误")
            raise ParserError(f"视频不可播放: {status} - {reason}")

        quality_map: dict[str, QualityOption] = {}

        # 渐进式格式（含音频）
        for fmt in streaming_data.get("formats", []):
            self._add_format(quality_map, fmt, has_audio=True)

        # DASH 视频流（不含音频）
        for fmt in streaming_data.get("adaptiveFormats", []):
            if fmt.get("mimeType", "").startswith("video"):
                self._add_format(quality_map, fmt, has_audio=False)

        # 按清晰度排序
        order = [
            "2160p", "1440p", "1080p60", "1080p", "720p60", "720p",
            "480p", "360p", "240p", "144p",
        ]
        result = []
        for q in order:
            if q in quality_map:
                result.append(quality_map[q])
        # 添加未在排序列表中的
        for q, opt in quality_map.items():
            if opt not in result:
                result.append(opt)
        return result

    @staticmethod
    def _add_format(
        quality_map: dict[str, QualityOption],
        fmt: dict[str, Any],
        has_audio: bool,
    ) -> None:
        """将单个格式添加到清晰度映射中。"""
        itag = fmt.get("itag", 0)
        if itag not in _ITAG_MAP:
            return

        quality, fmt_type, _ = _ITAG_MAP[itag]
        # 跳过纯音频格式
        if quality.startswith("audio"):
            return

        file_size = (
            fmt.get("contentLength")
            or fmt.get("byteRange", {}).get("lastByte", 0)
        )
        try:
            file_size = int(file_size)
        except (TypeError, ValueError):
            file_size = 0

        # 含音频的渐进式格式优先
        existing = quality_map.get(quality)
        if existing is None or (has_audio and not existing.code.startswith("a")):
            suffix = "（含音频）" if has_audio else "（仅视频）"
            quality_map[quality] = QualityOption(
                quality=quality,
                file_size=file_size,
                format=fmt_type,
                code=str(itag),
                description=f"{quality.upper()} {fmt_type.upper()}{suffix}",
            )

    # ---------- URL 提取 ----------

    @staticmethod
    def _extract_url(fmt: dict[str, Any]) -> str:
        """从格式信息中提取直链 URL。

        处理 ``url`` 直接链接和 ``signatureCipher`` 加密签名两种情况。
        """
        if "url" in fmt:
            return fmt["url"]

        # 签名加密情况：需要解密 signatureCipher
        cipher = fmt.get("signatureCipher", "")
        if cipher:
            params = urllib.parse.parse_qs(cipher)
            base_url = params.get("url", [""])[0]
            # TODO: 实现完整的签名解密算法（需要解析 player JS）
            # 当前版本对加密签名的支持有限，建议启用 yt-dlp 后端
            if base_url:
                return urllib.parse.unquote(base_url)

        raise ParserError("视频流 URL 被加密签名保护，请启用 yt-dlp 后端")

    # ---------- yt-dlp 可选后端 ----------

    @staticmethod
    def _has_ytdlp() -> bool:
        """检查系统中是否安装了 yt-dlp。"""
        return shutil.which("yt-dlp") is not None

    def _parse_with_ytdlp(self, video_id: str) -> VideoInfo:
        """使用 yt-dlp 作为后端解析视频信息。

        适用于签名解密、年龄限制、会员视频等复杂场景。
        """
        url = f"{WATCH_URL}?v={video_id}"
        cmd = [
            "yt-dlp",
            "--dump-single-json",
            "--no-warnings",
            "--no-playlist",
            url,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                raise ParserError(f"yt-dlp 执行失败: {result.stderr.strip()}")
            data = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            raise ParserError(f"yt-dlp 解析失败: {exc}") from exc

        title = data.get("title", "YouTube Video")
        cover = data.get("thumbnail", "")
        duration = data.get("duration", 0)

        quality_list = []
        for fmt in data.get("formats", []):
            if fmt.get("vcodec") == "none":
                continue  # 跳过纯音频
            height = fmt.get("height", 0)
            quality = f"{height}p" if height else "unknown"
            fps = fmt.get("fps", 0)
            if fps and fps > 30:
                quality += f"{int(fps)}"
            quality_list.append(
                QualityOption(
                    quality=quality,
                    file_size=fmt.get("filesize") or fmt.get("filesize_approx") or 0,
                    format=fmt.get("ext", "mp4"),
                    code=str(fmt.get("format_id", "")),
                    description=fmt.get("format_note", quality),
                )
            )

        # 去重并按高度降序
        seen = set()
        unique = []
        for q in sorted(quality_list, key=lambda x: x.file_size, reverse=True):
            if q.quality not in seen:
                seen.add(q.quality)
                unique.append(q)

        return VideoInfo(
            title=title,
            cover=cover,
            duration=duration,
            quality_list=unique,
            file_size=unique[0].file_size if unique else 0,
            platform=self.platform_name,
            video_id=video_id,
            raw_response=data,
            extra={"backend": "yt-dlp"},
        )
