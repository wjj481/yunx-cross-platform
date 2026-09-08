"""
哔哩哔哩（Bilibili）视频解析器。

完整支持：
- BV 号 / AV 号识别与互转
- 分P视频（多 cid）
- wbi 签名（用于新版 API 鉴权）
- DASH 格式音视频流分离
- 登录 Cookie 获取高清晰度（4K / 1080P60 等）

API 参考：
- 视频信息：``/x/web-interface/view``
- 播放地址：``/x/player/playurl``
- wbi 密钥：``/x/web-interface/nav``

免责声明：仅供个人学习研究使用，请尊重版权。
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse
from functools import reduce
from typing import Any

import requests

from ..exceptions import AuthenticationError, NetworkError, ParserError
from .base import BaseVideoParser, QualityOption, VideoInfo

# ---------- 常量 ----------

API_BASE = "https://api.bilibili.com"
VIDEO_VIEW_URL = f"{API_BASE}/x/web-interface/view"
PLAY_URL = f"{API_BASE}/x/player/playurl"
NAV_URL = f"{API_BASE}/x/web-interface/nav"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://www.bilibili.com"

# B 站清晰度 qn -> 标识映射
_QN_MAP: dict[int, tuple[str, str]] = {
    127: ("8k", "8K 超高清"),
    126: ("dolby", "杜比视界"),
    125: ("hdr", "HDR 真彩"),
    120: ("4k", "4K 超清"),
    116: ("1080p60", "1080P 60帧"),
    112: ("1080p+", "1080P 高码率"),
    80: ("1080p", "1080P 高清"),
    74: ("720p60", "720P 60帧"),
    64: ("720p", "720P 高清"),
    32: ("480p", "480P 清晰"),
    16: ("360p", "360P 流畅"),
}

# wbi 签名混淆表（固定）
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# BV <-> AV 转换表
_BV_TABLE = "fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTKNPAwcF"
_BV_TR = {c: i for i, c in enumerate(_BV_TABLE)}
_BV_S = [11, 10, 3, 8, 4, 6]
_BV_XOR = 177451812
_BV_ADD = 8728348608


def bv_to_av(bvid: str) -> int:
    """BV 号转 AV 号（aid）。

    Args:
        bvid: BV 号（如 ``"BV1xx411c7mD"``）。

    Returns:
        对应的 AV 号（纯数字）。
    """
    r = 0
    for i, pos in enumerate(_BV_S):
        r += _BV_TR[bvid[pos]] * (58**i)
    return (r - _BV_ADD) ^ _BV_XOR


def av_to_bv(aid: int) -> str:
    """AV 号转 BV 号。

    Args:
        aid: AV 号（纯数字）。

    Returns:
        对应的 BV 号。
    """
    aid = (aid ^ _BV_XOR) + _BV_ADD
    r = list("BV1  4 1 7  ")
    for i, pos in enumerate(_BV_S):
        r[pos] = _BV_TABLE[(aid // (58**i)) % 58]
    return "".join(r)


class BilibiliParser(BaseVideoParser):
    """哔哩哔哩视频解析器。

    高清晰度（4K / 1080P60 / 杜比视界）需要登录 Cookie。
    未登录时默认最高可获取 720P。

    凭证格式::

        {"cookie": "SESSDATA=xxx; bili_jct=xxx; ..."}
    """

    supported_domains = [
        "bilibili.com",
        "b23.tv",
        "bilibili.cn",
    ]
    platform_name = "bilibili"
    experimental = False

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": USER_AGENT, "Referer": REFERER}
        )
        self._cookie: str = (credential or {}).get("cookie", "")
        self._wbi_keys: tuple[str, str] | None = None
        self._wbi_expire: float = 0.0

    # ---------- 公共接口 ----------

    def parse_video_url(self, url: str) -> VideoInfo:
        """解析 B 站视频链接。

        支持格式：
        - ``https://www.bilibili.com/video/BV1xx411c7mD``
        - ``https://www.bilibili.com/video/av170001``
        - ``https://b23.tv/xxxxx``（短链，自动重定向）
        - 带 ``?p=2`` 参数指定分P

        Args:
            url: B 站视频链接。

        Returns:
            :class:`VideoInfo`，包含标题、封面、时长、清晰度列表。

        Raises:
            ParserError: 解析失败或视频不存在。
        """
        bvid, aid, page = self._extract_ids(url)

        # 获取视频信息
        params: dict[str, Any] = {}
        if bvid:
            params["bvid"] = bvid
        else:
            params["aid"] = aid
        data = self._api_get(VIDEO_VIEW_URL, params)

        title = data.get("title", "未知视频")
        cover = data.get("pic", "")
        duration = data.get("duration", 0)
        aid = data.get("aid", aid or 0)
        bvid = data.get("bvid", bvid or "")

        # 分P处理
        pages = data.get("pages", [])
        page_index = max(1, min(page, len(pages))) if pages else 1
        current_page = pages[page_index - 1] if pages else {}
        cid = current_page.get("cid", data.get("cid", 0))
        part_title = current_page.get("part", "")

        # 如果是多P且标题不同，拼接分P标题
        if len(pages) > 1 and part_title:
            full_title = f"{title} - P{page_index} {part_title}"
        else:
            full_title = title

        # 获取可用清晰度列表（通过 playurl 接口的 accept_quality）
        quality_list = self._fetch_quality_list(bvid or av_to_bv(aid), cid)

        return VideoInfo(
            title=full_title,
            cover=cover,
            duration=duration,
            quality_list=quality_list,
            file_size=quality_list[0].file_size if quality_list else 0,
            platform=self.platform_name,
            video_id=bvid or str(aid),
            raw_response=data,
            extra={
                "aid": aid,
                "bvid": bvid,
                "cid": cid,
                "page": page_index,
                "pages": [
                    {"cid": p.get("cid"), "part": p.get("part", "")}
                    for p in pages
                ],
                "owner": data.get("owner", {}).get("name", ""),
            },
        )

    def get_download_url(
        self, video_info: VideoInfo, quality: str
    ) -> str:
        """获取指定清晰度的下载直链。

        B 站 DASH 格式下视频和音频分离，此处返回视频流 URL。
        如需完整文件，需自行合并音视频（TODO: 提供 ffmpeg 合并工具）。

        Args:
            video_info: :meth:`parse_video_url` 返回的视频信息。
            quality: 清晰度标识（如 ``"1080p"``、``"720p"``）。

        Returns:
            视频流下载直链。

        Raises:
            ParserError: 清晰度不可用或获取失败。
        """
        option = video_info.find_quality(quality)
        if option is None:
            available = ", ".join(q.quality for q in video_info.quality_list)
            raise ParserError(
                f"不支持的清晰度: {quality}，可用: {available}"
            )

        bvid = video_info.extra.get("bvid", "")
        cid = video_info.extra.get("cid", 0)
        qn = self._quality_to_qn(quality)

        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": qn,
            "fnval": 16,  # DASH 格式
            "fnver": 0,
            "fourk": 1,
        }
        data = self._api_get(PLAY_URL, params)

        # DASH 格式：从 video 流中选匹配的清晰度
        dash = data.get("dash")
        if dash:
            video_streams = dash.get("video", [])
            target = self._select_dash_video(video_streams, qn)
            if target:
                return target.get("baseUrl", "") or target.get("base_url", "")
            raise ParserError("DASH 流中未找到对应清晰度的视频轨")

        # 非 DASH（旧版 durl 格式）
        durl = data.get("durl", [])
        if durl:
            return durl[0].get("url", "")
        raise ParserError("响应中未包含播放地址")

    # ---------- URL 解析 ----------

    def _extract_ids(self, url: str) -> tuple[str, int, int]:
        """从 URL 中提取 bvid / aid / 分P号。

        Returns:
            (bvid, aid, page) 元组；未提取到的字段为空字符串或 0。
        """
        # 处理 b23.tv 短链重定向
        if "b23.tv" in url:
            url = self._resolve_short_url(url)

        bvid = ""
        aid = 0
        page = 1

        # BV 号
        m = __import__("re").search(r"BV[0-9A-Za-z]{10}", url)
        if m:
            bvid = m.group(0)
        # AV 号
        m = __import__("re").search(r"[Aa][Vv](\d+)", url)
        if m and not bvid:
            aid = int(m.group(1))
        # 分P
        m = __import__("re").search(r"[?&]p=(\d+)", url)
        if m:
            page = int(m.group(1))

        if not bvid and not aid:
            raise ParserError(f"无法从链接中提取 BV/AV 号: {url}")

        return bvid, aid, page

    def _resolve_short_url(self, url: str) -> str:
        """解析 b23.tv 短链，返回重定向后的完整 URL。"""
        try:
            resp = self._session.head(
                url, allow_redirects=True, timeout=15
            )
            return resp.url
        except requests.RequestException as exc:
            raise NetworkError(f"短链重定向失败: {exc}") from exc

    # ---------- 清晰度处理 ----------

    def _fetch_quality_list(
        self, bvid: str, cid: int
    ) -> list[QualityOption]:
        """通过 playurl 接口获取可用清晰度列表。"""
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": 127,  # 请求最高清晰度，返回 accept_quality
            "fnval": 16,
            "fnver": 0,
            "fourk": 1,
        }
        try:
            data = self._api_get(PLAY_URL, params)
        except ParserError:
            # 未登录时可能返回 -403，降级到基础清晰度
            return [
                QualityOption(quality="720p", format="flv", code="64",
                              description="720P 高清"),
                QualityOption(quality="480p", format="flv", code="32",
                              description="480P 清晰"),
                QualityOption(quality="360p", format="flv", code="16",
                              description="360P 流畅"),
            ]

        accept_quality = data.get("accept_quality", [])
        quality_list = []
        for qn in accept_quality:
            if qn in _QN_MAP:
                quality_id, desc = _QN_MAP[qn]
                # 尝试从 DASH 流获取文件大小
                file_size = self._estimate_file_size(data, qn)
                quality_list.append(
                    QualityOption(
                        quality=quality_id,
                        file_size=file_size,
                        format="mp4",
                        code=str(qn),
                        description=desc,
                    )
                )
        return quality_list

    @staticmethod
    def _estimate_file_size(data: dict[str, Any], qn: int) -> int:
        """从 DASH 响应中估算指定清晰度的文件大小。"""
        dash = data.get("dash", {})
        for stream in dash.get("video", []):
            if stream.get("id") == qn:
                return stream.get("bandwidth", 0) * data.get("timelength", 0) // 8
        return 0

    @staticmethod
    def _select_dash_video(
        streams: list[dict[str, Any]], qn: int
    ) -> dict[str, Any] | None:
        """从 DASH 视频流列表中选择指定 id 的流。"""
        for s in streams:
            if s.get("id") == qn:
                return s
        return None

    @staticmethod
    def _quality_to_qn(quality: str) -> int:
        """清晰度标识转 qn 值。"""
        reverse = {v[0]: k for k, v in _QN_MAP.items()}
        return reverse.get(quality.lower(), 80)

    # ---------- wbi 签名 ----------

    def _get_wbi_keys(self) -> tuple[str, str]:
        """获取 wbi 签名的 img_key 和 sub_key。

        结果缓存 1 小时。
        """
        now = time.time()
        if self._wbi_keys and now < self._wbi_expire:
            return self._wbi_keys

        headers = {}
        if self._cookie:
            headers["Cookie"] = self._cookie
        try:
            resp = self._session.get(NAV_URL, headers=headers, timeout=15)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise NetworkError(f"获取 wbi 密钥失败: {exc}") from exc

        if data.get("code") != 0:
            raise ParserError(
                f"获取 wbi 密钥失败: {data.get('message', 'unknown')}"
            )

        wbi_img = data.get("data", {}).get("wbi_img", {})
        img_url = wbi_img.get("img_url", "")
        sub_url = wbi_img.get("sub_url", "")
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]

        self._wbi_keys = (img_key, sub_key)
        self._wbi_expire = now + 3600
        return self._wbi_keys

    @staticmethod
    def _get_mixin_key(orig: str) -> str:
        """通过混淆表生成 mixin_key。"""
        return reduce(
            lambda s, i: s + orig[i] if i < len(orig) else s,
            _MIXIN_KEY_ENC_TAB,
            "",
        )[:32]

    def _sign_wbi(self, params: dict[str, Any]) -> dict[str, Any]:
        """对请求参数添加 wbi 签名。

        Args:
            params: 原始请求参数字典。

        Returns:
            添加了 ``wts`` 和 ``w_rid`` 的新参数字典。
        """
        img_key, sub_key = self._get_wbi_keys()
        mixin_key = self._get_mixin_key(img_key + sub_key)

        params = dict(params)
        params["wts"] = int(time.time())
        # 按 key 排序并编码
        sorted_params = dict(sorted(params.items()))
        query = urllib.parse.urlencode(sorted_params)
        w_rid = hashlib.md5(
            (query + mixin_key).encode("utf-8")
        ).hexdigest()
        params["w_rid"] = w_rid
        return params

    # ---------- HTTP 工具 ----------

    def _api_get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """发送 GET 请求到 B 站 API 并解析 data 字段。

        自动附加 Cookie 和 wbi 签名。
        """
        headers = {"User-Agent": USER_AGENT, "Referer": REFERER}
        if self._cookie:
            headers["Cookie"] = self._cookie

        # 对需要 wbi 签名的接口签名
        signed_params = params or {}
        if "web-interface" in url or "player" in url:
            try:
                signed_params = self._sign_wbi(signed_params)
            except (ParserError, NetworkError):
                # wbi 签名失败时降级为无签名请求
                pass

        try:
            resp = self._session.get(
                url, params=signed_params, headers=headers, timeout=15
            )
        except requests.RequestException as exc:
            raise NetworkError(f"B 站 API 请求失败: {exc}") from exc

        try:
            result = resp.json()
        except ValueError as exc:
            raise ParserError(f"响应解析失败: {exc}") from exc

        code = result.get("code", -1)
        if code != 0:
            message = result.get("message", "请求失败")
            if code in (-101, -403):
                raise AuthenticationError(
                    f"需要登录 Cookie 才能获取此内容: {message}"
                )
            raise ParserError(f"B 站 API 错误: {message}", code=code)

        return result.get("data", {})
