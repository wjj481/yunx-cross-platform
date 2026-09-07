"""
剪贴板识别辅助：从任意文本中检测网盘分享链接并提取提取码。

支持的分享链接格式：
- 夸克：``https://pan.quark.cn/s/xxx``
- UC：``https://drive.uc.cn/s/xxx``
- 迅雷：``https://pan.xunlei.com/s/xxx``
- 百度：``https://pan.baidu.com/s/1xxx``
- 123 云盘：``https://www.123pan.com/s/xxx`` / ``https://www.123865.com/s/xxx``
- 和彩云：``https://yun.139.com/shareweb/.../w/i/xxx``

提取码识别：
- URL 内：``?pwd=xxxx``、``?password=xxxx``、``#xxxx``
- 文本内：``提取码: xxxx``、``访问码：xxxx``、``密码 xxxx``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs, unquote


@dataclass
class ShareURL:
    """检测到的分享链接信息。"""

    url: str
    """完整分享链接。"""
    drive: str
    """网盘标识（``quark`` / ``uc`` / ``xunlei`` / ``baidu`` / ``pan123`` / ``caiyun``）。"""
    share_id: str
    """分享 ID（短码）。"""
    extract_code: str | None
    """提取码；无则为 ``None``。"""


# ---------- 各网盘分享 ID 正则 ----------

_DRIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("quark", re.compile(r"pan\.quark\.cn/s/([A-Za-z0-9]+)", re.IGNORECASE)),
    ("uc", re.compile(r"drive\.uc\.cn/s/([A-Za-z0-9]+)", re.IGNORECASE)),
    ("xunlei", re.compile(r"pan\.xunlei\.com/s/([A-Za-z0-9_-]+)", re.IGNORECASE)),
    ("baidu", re.compile(r"pan\.baidu\.com/s/(1[A-Za-z0-9_-]+)", re.IGNORECASE)),
    (
        "pan123",
        re.compile(r"123(?:865|pan)\.(?:com|cn)/s/([A-Za-z0-9]+-[A-Za-z0-9]+)", re.IGNORECASE),
    ),
    ("pan123", re.compile(r"share\.123pan\.cn/123pan/([A-Za-z0-9-]+)", re.IGNORECASE)),
    (
        "caiyun",
        re.compile(r"yun\.139\.com/shareweb/.*?/w/i/([A-Za-z0-9_-]+)", re.IGNORECASE),
    ),
]

# URL 中的提取码
_PWD_IN_URL = re.compile(r"[?&](?:pwd|password|passcode)=([A-Za-z0-9]+)", re.IGNORECASE)
# URL fragment 中的提取码（#xxxx）
_FRAGMENT_CODE = re.compile(r"#([A-Za-z0-9]{4,8})$")
# 文本中的提取码
_PWD_IN_TEXT = re.compile(r"(?:提取码|访问码|密码|提取密码)\s*[：:]\s*([A-Za-z0-9]{4,8})")
# 通用 URL 提取
_URL_FINDER = re.compile(r"https?://[^\s\u3000\u3001\u3002\uff0c\uff1b\)\]\}\"']+")


def _extract_code_from_url(url: str) -> str | None:
    """从 URL 中提取提取码（query 参数或 fragment）。"""
    # query 参数
    m = _PWD_IN_URL.search(url)
    if m:
        return m.group(1)
    # fragment
    m = _FRAGMENT_CODE.search(url)
    if m:
        return m.group(1)
    # 用 urllib 再确认一次
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for key in ("pwd", "password", "passcode"):
            if key in qs and qs[key]:
                return qs[key][0]
        if parsed.fragment and re.fullmatch(r"[A-Za-z0-9]{4,8}", parsed.fragment):
            return parsed.fragment
    except Exception:
        pass
    return None


def detect_share_url(text: str) -> list[ShareURL]:
    """从文本中检测所有网盘分享链接。

    Args:
        text: 任意文本（可能是整段分享文案）。

    Returns:
        检测到的 :class:`ShareURL` 列表，按出现顺序排列，已去重。
    """
    results: list[ShareURL] = []
    seen_urls: set[str] = set()

    for url_match in _URL_FINDER.finditer(text):
        url = url_match.group(0).rstrip("。，,；;)]}\"'")
        if url in seen_urls:
            continue

        for drive, pattern in _DRIVE_PATTERNS:
            m = pattern.search(url)
            if not m:
                continue
            share_id = m.group(1)
            # 百度 surl 去掉开头的 "1"
            if drive == "baidu":
                share_id = share_id[1:] if share_id.startswith("1") else share_id

            # 提取码：先从 URL 取，再从整段文本取
            code = _extract_code_from_url(url)
            if code is None:
                text_match = _PWD_IN_TEXT.search(text)
                if text_match:
                    code = text_match.group(1)

            results.append(
                ShareURL(
                    url=url,
                    drive=drive,
                    share_id=share_id,
                    extract_code=code,
                )
            )
            seen_urls.add(url)
            break  # 一个 URL 只匹配一个网盘

    return results
