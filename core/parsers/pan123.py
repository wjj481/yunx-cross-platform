"""
123 云盘解析器。

参考云析 (YunX) Kotlin 实现重写，完整流程：
1. 匿名获取分享文件列表（无需登录）
2. 使用登录 Token + 签名获取下载直链

签名算法（文档 §6）：
- auth-key (timeSign) = CRC32(替换表映射后的 UTC "YYYYMMDDHHmm"，基准 ts + 57600s)
- auth-value = "<ts>-<random>-<CRC32(ts|random|path|web|3|auth_key)>"
"""

from __future__ import annotations

import base64
import json
import random
import time
import zlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import requests

from ..exceptions import AuthenticationError, NetworkError, ParserError
from .base import BaseParser, ShareInfo

# ---------- 常量（对齐云析 Pan123Constants） ----------

API_BASE = "https://yun.123pan.cn"
DOWNLOAD_BASE = "https://www.123865.com"

SHARE_GET_URL = f"{API_BASE}/b/api/share/get"
SHARE_DOWNLOAD_INFO_URL = f"{DOWNLOAD_BASE}/b/api/share/download/info"

WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
DART_UA = "Dart/3.12 (dart:io)"

PLATFORM_WEB = "web"
PLATFORM_ANDROID = "android"
APP_VERSION_WEB = "3"
APP_VERSION_ANDROID = "39"

DOWNLOAD_REFERER = "https://yun.123pan.cn/"

# 数字 0-9 的替换表（索引 = 数字值）
SIGN_TABLE = "adefghlmyijnopkqrstubcvwsz"
SIGN_OS = "web"
SIGN_VER = "3"
# timeSign 时间基准偏移：ts + 57600 秒（+16h）
SIGN_OFFSET_SECONDS = 57600

# 分享 ID 正则
import re

_SHARE_ID_RE = re.compile(
    r"123(?:865|pan)\.(?:com|cn)/s/([A-Za-z0-9]+-[A-Za-z0-9]+)", re.IGNORECASE
)
_SHARE_SUB_RE = re.compile(
    r"share\.123pan\.cn/123pan/([A-Za-z0-9-]+)", re.IGNORECASE
)


def _crc32_hex(s: str) -> str:
    """标准 CRC-32 → 8 位小写十六进制。"""
    crc = zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF
    return f"{crc:08x}"


def _make_sign(path: str, ts: int | None = None) -> tuple[str, str]:
    """生成 123 云盘签名头 (auth-key, auth-value)。

    Args:
        path: URL 路径（含 /b 前缀，不含 host 和 query）。
        ts: Unix 时间戳（秒），默认当前时间。

    Returns:
        (auth_key, auth_value) 元组。
    """
    if ts is None:
        ts = int(time.time())

    # 1) auth-key (timeSign)：ts + 16h 以 UTC 格式化为 YYYYMMDDHHmm，逐数字替换
    offset_ts = ts + SIGN_OFFSET_SECONDS
    dt = datetime.fromtimestamp(offset_ts, tz=timezone.utc)
    minute = dt.strftime("%Y%m%d%H%M")
    substituted = "".join(SIGN_TABLE[int(c)] for c in minute)
    auth_key = _crc32_hex(substituted)

    # 2) auth-value：ts|random|path|web|3|auth_key 的 CRC32
    rand = random.randint(0, 10_000_000)
    data = f"{ts}|{rand}|{path}|{SIGN_OS}|{SIGN_VER}|{auth_key}"
    auth_value = f"{ts}-{rand}-{_crc32_hex(data)}"

    return auth_key, auth_value


class Pan123Parser(BaseParser):
    """123 云盘解析器。

    需要登录凭证（JWT Token，从网页 localStorage 的 authorToken 获取）。

    凭证格式::

        {"access_token": "Bearer JWT 或纯 JWT"}
    """

    supported_domains = [
        "www.123pan.com",
        "www.123865.com",
        "123pan.com",
        "123865.com",
        "yun.123pan.cn",
    ]
    drive_name = "pan123"
    status = "stable"

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._token: str = (credential or {}).get("access_token", "")
        # 去除可能的 "Bearer " 前缀
        if self._token.lower().startswith("bearer "):
            self._token = self._token[7:]
        # 设备标识（同一会话内不变）
        self._loginuuid = "%032x" % random.getrandbits(128)

    # ---------- 公共接口 ----------

    def parse_share_url(
        self, url: str, extract_code: str | None = None
    ) -> ShareInfo:
        """解析 123 云盘分享链接。

        Args:
            url: 123 云盘分享链接。
            extract_code: 提取码；为 ``None`` 时从 URL 自动提取。

        Returns:
            :class:`ShareInfo`。

        Raises:
            AuthenticationError: 未提供登录 Token。
            ParserError: 解析失败。
        """
        if not self._token:
            raise AuthenticationError("123 云盘需要登录 Token（authorToken）")

        code = self._resolve_extract_code(url, extract_code) or ""
        share_key = self._extract_share_key(url)

        # 1. 匿名获取分享文件列表（校验提取码）
        files = self._get_share_files(share_key, code)
        if not files:
            raise ParserError("分享内容为空或已失效")

        first_file = files[0]
        if first_file.get("isdir"):
            raise ParserError("暂不支持目录分享，请选择具体文件")

        # 2. 获取下载直链（需登录 + 签名）
        direct_url = self._get_download_link(share_key, first_file)

        file_name = first_file.get("fname", share_key)
        file_size = first_file.get("fsize", 0)
        file_type = self._guess_file_type(file_name)

        return ShareInfo(
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            direct_url=direct_url,
            expires_at=None,
            raw_response={"file": first_file},
            share_id=share_key,
            extract_code=code or None,
            drive=self.drive_name,
        )

    # ---------- 内部流程 ----------

    def _extract_share_key(self, url: str) -> str:
        """从 URL 提取分享 Key。"""
        m = _SHARE_ID_RE.search(url)
        if m:
            return m.group(1)
        m = _SHARE_SUB_RE.search(url)
        if m:
            return m.group(1)
        raise ParserError(f"无法从链接中提取 123 云盘分享 Key: {url}")

    def _get_share_files(
        self, share_key: str, share_pwd: str
    ) -> list[dict[str, Any]]:
        """匿名获取分享文件列表（接口 §5.2）。"""
        url = (
            f"{SHARE_GET_URL}?limit=100&next=0"
            f"&orderBy=file_name&orderDirection=asc"
            f"&shareKey={quote(share_key)}"
            f"&ParentFileId=0&Page=1"
        )
        if share_pwd:
            url += f"&SharePwd={quote(share_pwd)}"

        resp = self._request(
            "GET", url, headers={"User-Agent": DART_UA}
        )
        result = self._parse_json(resp)
        self._check_ok(result, "获取文件列表失败")
        data = result.get("data", {})
        if data.get("Expired"):
            raise ParserError("分享已失效")

        info_list = data.get("InfoList", [])
        files = []
        for item in info_list:
            files.append(
                {
                    "fid": str(item.get("FileId", "")),
                    "fname": item.get("FileName", ""),
                    "fsize": item.get("Size", 0),
                    "isdir": item.get("Type", 0) == 1,
                    "pdirFid": str(item.get("ParentFileId", "")),
                    # 编码 S3KeyFlag|Etag|StorageNode 供下载使用
                    "fidToken": (
                        f"{item.get('S3KeyFlag', '')}|"
                        f"{item.get('Etag', '')}|"
                        f"{item.get('StorageNode', '')}"
                    ),
                }
            )
        return files

    def _get_download_link(
        self, share_key: str, file_info: dict[str, Any]
    ) -> str:
        """获取分享文件下载直链（接口 §5.3，需登录+签名）。"""
        fid_token = file_info.get("fidToken", "")
        parts = fid_token.split("|")
        s3_key_flag = parts[0] if len(parts) > 0 else ""
        etag = parts[1] if len(parts) > 1 else ""

        body = {
            "ShareKey": share_key,
            "FileID": file_info["fid"],
            "S3KeyFlag": s3_key_flag,
            "Size": file_info["fsize"],
            "Etag": etag,
        }

        auth_key, auth_value = _make_sign("/b/api/share/download/info")
        headers = {
            "platform": PLATFORM_ANDROID,
            "app-version": APP_VERSION_ANDROID,
            "authorization": f"Bearer {self._token}",
            "loginuuid": self._loginuuid,
            "auth-key": auth_key,
            "auth-value": auth_value,
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": WEB_UA,
        }

        resp = self._request(
            "POST", SHARE_DOWNLOAD_INFO_URL, headers=headers, json_body=body
        )
        result = self._parse_json(resp)
        self._check_ok(result, "获取下载链接失败")

        data = result.get("data", {})
        download_url = data.get("DownloadURL", "")
        if not download_url:
            raise ParserError("未返回下载链接")

        # 解码 download-v2 包装 URL
        real_url = self._decode_download_url(download_url) or download_url
        # 跟随可能的 redirect_url
        real_url = self._follow_redirect_url(real_url)
        return real_url

    def _decode_download_url(self, download_url: str) -> str | None:
        """解码 123 下载 URL（兼容 base64 整段和 download-v2?params= 两种形态）。"""
        trimmed = download_url.strip()
        # 形态 1：整段 base64（不含协议头）
        if "://" not in trimmed:
            try:
                decoded = base64.b64decode(trimmed).decode("utf-8")
                if decoded.lower().startswith("http"):
                    return decoded
            except Exception:
                pass
            return None
        # 形态 2：download-v2?params=<base64>
        idx = trimmed.find("params=")
        if idx < 0:
            return None
        params = trimmed[idx + len("params="):].split("&")[0]
        try:
            normalized = params.replace("-", "+").replace("_", "/")
            # 补充 padding
            padding = 4 - len(normalized) % 4
            if padding != 4:
                normalized += "=" * padding
            return base64.b64decode(normalized).decode("utf-8")
        except Exception:
            return None

    def _follow_redirect_url(self, initial_url: str, max_hops: int = 5) -> str:
        """跟随 123 CDN 的 redirect_url（最多 5 跳）。

        带 ``auto_redirect=0`` 时，GET 直链返回 JSON ``{"data":{"redirect_url":"..."}}``
        而非直接文件。循环跟随直到获得真实文件流地址。
        """
        url = initial_url
        for _ in range(max_hops):
            try:
                resp = self._session.get(
                    url,
                    headers={
                        "Referer": DOWNLOAD_REFERER,
                        "User-Agent": DART_UA,
                    },
                    stream=True,
                    timeout=15,
                )
                content_length = resp.headers.get("Content-Length")
                # 小响应（≤8KB）可能是 JSON 跳转页
                if content_length and int(content_length) <= 8192:
                    body = resp.text
                    if body.strip().startswith("{"):
                        try:
                            data = json.loads(body)
                            redirect = (
                                data.get("data", {}).get("redirect_url", "")
                            )
                            if redirect:
                                url = redirect
                                continue
                        except json.JSONDecodeError:
                            pass
                # 大响应或非 JSON → 当前 URL 即最终地址
                resp.close()
                return url
            except requests.RequestException:
                return url
        return url

    # ---------- HTTP 工具 ----------

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        merged_headers = dict(headers or {})
        try:
            return self._session.request(
                method, url, headers=merged_headers, json=json_body, timeout=30
            )
        except requests.RequestException as exc:
            raise NetworkError(f"123 云盘 API 请求失败: {exc}") from exc

    @staticmethod
    def _parse_json(resp: requests.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except ValueError as exc:
            raise ParserError(f"响应解析失败: {exc}") from exc

    @staticmethod
    def _check_ok(result: dict[str, Any], fallback: str) -> None:
        """校验 123 API 响应 code == 0。"""
        code = result.get("code", -1)
        if code != 0:
            msg = result.get("message", fallback)
            raise ParserError(f"{msg}（code={code}）")

    @staticmethod
    def _guess_file_type(file_name: str) -> str:
        if "." in file_name:
            return file_name.rsplit(".", 1)[-1].lower()
        return "unknown"
