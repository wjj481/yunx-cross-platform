"""
迅雷云盘解析器。

参考云析 (YunX) Kotlin 实现重写，完整流程：
1. 解析分享（share_id + pass_code），获取 pass_code_token
2. 转存文件到个人网盘临时目录
3. 获取文件详情中的下载直链

认证方式：Bearer access_token + X-Device-Id + X-Captcha-Token。
captcha_sign 算法：client_id+client_version+package_name+device_id+timestamp_ms
→ 10 层 MD5(raw+salt)，前缀 "1."。
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

from ..exceptions import AuthenticationError, NetworkError, ParserError
from .base import BaseParser, ShareInfo

# ---------- 常量（对齐云析 XunleiConstants） ----------

AUTH_BASE = "https://xluser-ssl.xunlei.com"
PAN_BASE = "https://api-pan.xunlei.com"

APP_CLIENT_ID = "Xp6vsxz_7IYVw2BB"
APP_CLIENT_SECRET = "Xp6vsy4tN9toTVdMSpomVdXpRmES"
APP_CLIENT_VERSION = "8.31.0.9726"
APP_PACKAGE_NAME = "com.xunlei.downloadprovider"

# captcha 盐（10 个，alist 源码确认）
CAPTCHA_SALTS = [
    "9uJNVj/wLmdwKrJaVj/omlQ",
    "Oz64Lp0GigmChHMf/6TNfxx7O9PyopcczMsnf",
    "Eb+L7Ce+Ej48u",
    "jKY0",
    "ASr0zCl6v8W4aidjPK5KHd1Lq3t+vBFf41dqv5+fnOd",
    "wQlozdg6r1qxh0eRmt3QgNXOvSZO6q/GXK",
    "gmirk+ciAvIgA/cxUUCema47jr/YToixTT+Q6O",
    "5IiCoM9B1/788ntB",
    "P07JH0h6qoM6TSUAK2aL9T5s2QBVeY9JWvalf",
    "+oK0AN",
]

APP_UA = (
    "ANDROID-com.xunlei.downloadprovider/8.31.0.9726 netWorkType/5G appid/40 "
    "deviceName/Xiaomi_M2004j7ac deviceModel/M2004J7AC OSVersion/12 "
    "protocolVersion/301 platformVersion/10 sdkVersion/512000 "
    "Oauth2Client/0.9 (Linux 4_14_186-perf-gddfs8vbb238b) (JAVA 0)"
)
WEB_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

CAPTCHA_INIT_URL = f"{AUTH_BASE}/v1/shield/captcha/init"
FILES_URL = f"{PAN_BASE}/drive/v1/files"
SHARE_URL = f"{PAN_BASE}/drive/v1/share"
SHARE_DETAIL_URL = f"{PAN_BASE}/drive/v1/share/detail"
RESTORE_URL = f"{PAN_BASE}/drive/v1/share/restore"
TRASH_URL = f"{PAN_BASE}/drive/v1/files:batchTrash"

TEMP_DIR_NAME = "YunX临时转存"

import re

_SHARE_ID_RE = re.compile(
    r"pan\.xunlei\.com/s/([A-Za-z0-9_-]+)", re.IGNORECASE
)


def _md5_hex(s: str) -> str:
    """计算 MD5 并返回 32 位小写十六进制。"""
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _build_captcha_sign(device_id: str, ts_ms: str) -> str:
    """构建 captcha_sign。

    算法：raw = client_id + client_version + package_name + device_id + timestamp_ms
    对 10 个盐依次做 MD5(raw + salt)，最终前缀 "1."。
    """
    h = (
        APP_CLIENT_ID
        + APP_CLIENT_VERSION
        + APP_PACKAGE_NAME
        + device_id
        + ts_ms
    )
    for salt in CAPTCHA_SALTS:
        h = _md5_hex(h + salt)
    return f"1.{h}"


class XunleiParser(BaseParser):
    """迅雷云盘解析器。

    需要登录凭证（access_token、device_id、可选 captcha_token）。

    凭证格式::

        {
            "access_token": "...",
            "device_id": "...",
            "captcha_token": "..."  # 可选，为空时自动初始化
        }
    """

    supported_domains = ["pan.xunlei.com", "api-pan.xunlei.com"]
    drive_name = "xunlei"
    status = "stable"

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        cred = credential or {}
        self._access_token: str = cred.get("access_token", "")
        self._device_id: str = cred.get("device_id", "")
        self._captcha_token: str = cred.get("captcha_token", "")
        self._session = requests.Session()

        # 未提供 device_id 时生成一个
        if not self._device_id:
            self._device_id = "%032x" % random.getrandbits(128)

    # ---------- 公共接口 ----------

    def parse_share_url(
        self, url: str, extract_code: str | None = None
    ) -> ShareInfo:
        """解析迅雷云盘分享链接。

        Args:
            url: 迅雷分享链接（``https://pan.xunlei.com/s/xxx``）。
            extract_code: 提取码；为 ``None`` 时从 URL 自动提取。

        Returns:
            :class:`ShareInfo`。

        Raises:
            AuthenticationError: 未提供 access_token。
            ParserError: 解析失败。
        """
        if not self._access_token:
            raise AuthenticationError("迅雷网盘需要 access_token")

        code = self._resolve_extract_code(url, extract_code) or ""
        share_id = self._extract_share_id(url)

        # 确保 captcha_token 有效
        if not self._captcha_token:
            self._captcha_token = self._init_captcha(share_id)

        # 1. 解析分享
        share_result = self._get_share(share_id, code)
        files = share_result.get("files", [])
        if not files:
            raise ParserError("分享内容为空或已失效")

        first_file = files[0]
        if first_file.get("isdir"):
            raise ParserError("暂不支持目录分享，请选择具体文件")

        # 2. 转存到临时目录
        temp_dir_id = self._ensure_temp_dir()
        saved_fid = self._restore_file(
            share_id, share_result.get("pass_code_token", ""), temp_dir_id, first_file
        )

        # 3. 获取文件详情（含下载直链）
        detail = self._get_file_detail(saved_fid)
        direct_url = detail.get("download_url", "")
        file_size = detail.get("size", first_file.get("fsize", 0))

        if not direct_url:
            raise ParserError("未获取到下载直链")

        # 转存后删除临时文件（直链自带签名，删除不影响下载）
        try:
            self._batch_delete([saved_fid])
        except Exception:
            pass

        file_name = first_file.get("fname", detail.get("filename", share_id))
        file_type = self._guess_file_type(file_name)

        return ShareInfo(
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            direct_url=direct_url,
            expires_at=None,
            raw_response={"share": share_result, "detail": detail},
            share_id=share_id,
            extract_code=code or None,
            drive=self.drive_name,
        )

    # ---------- 内部流程 ----------

    def _extract_share_id(self, url: str) -> str:
        m = _SHARE_ID_RE.search(url)
        if not m:
            raise ParserError(f"无法从链接中提取迅雷分享 ID: {url}")
        return m.group(1)

    def _init_captcha(self, share_id: str) -> str:
        """初始化验证码盾，获取 captcha_token。"""
        ts_ms = str(int(time.time() * 1000))
        sign = _build_captcha_sign(self._device_id, ts_ms)
        body = {
            "action": "GET:/drive/v1/share",
            "captcha_token": "",
            "client_id": APP_CLIENT_ID,
            "device_id": self._device_id,
            "meta": {
                "client_version": APP_CLIENT_VERSION,
                "package_name": APP_PACKAGE_NAME,
                "timestamp": ts_ms,
                "captcha_sign": sign,
                "user_id": "",
            },
            "redirect_uri": "xlaccsdk01://xunlei.com/callback?state=harbor",
        }
        headers = {
            "User-Agent": APP_UA,
            "Accept": "application/json;charset=UTF-8",
            "Content-Type": "application/json",
            "X-Client-Id": APP_CLIENT_ID,
            "X-Device-Id": self._device_id,
            "X-Client-Version": APP_CLIENT_VERSION,
        }
        resp = self._request("POST", CAPTCHA_INIT_URL, headers, body)
        result = self._parse_json(resp)
        token = result.get("captcha_token", "")
        if not token:
            raise ParserError("获取 captcha_token 失败")
        return token

    def _get_share(
        self, share_id: str, pass_code: str
    ) -> dict[str, Any]:
        """解析分享（GET /drive/v1/share）。"""
        url = (
            f"{SHARE_URL}?share_id={share_id}"
            f"&pass_code={quote(pass_code)}"
            f"&limit=100&page_token=&thumbnail_size=SIZE_SMALL"
        )
        resp = self._pan_request("GET", url)
        result = self._parse_json(resp)
        data = result.get("data", result)

        # 提取码状态检查
        status = data.get("share_status", "")
        if status == "PASS_CODE_EMPTY":
            raise ParserError("请输入提取码")
        if status == "PASS_CODE_ERROR":
            raise ParserError("提取码错误")
        if status == "PASS_CODE_NEED":
            raise ParserError("该分享需要提取码")

        files = []
        for item in data.get("files", []):
            files.append(
                {
                    "fid": item.get("id", ""),
                    "fname": item.get("name", ""),
                    "fsize": item.get("size", 0),
                    "isdir": item.get("kind") == "drive#folder",
                    "pdirFid": item.get("parent_id", ""),
                }
            )
        return {
            "title": data.get("title", ""),
            "files": files,
            "pass_code_token": data.get("pass_code_token", ""),
            "next_page_token": data.get("next_page_token", ""),
        }

    def _ensure_temp_dir(self) -> str:
        """确保「YunX临时转存」目录存在，返回其 id。"""
        files = self._get_files("")
        for f in files:
            if f.get("isdir") and f.get("fname") == TEMP_DIR_NAME:
                return f["fid"]
        return self._create_folder(TEMP_DIR_NAME, "")

    def _get_files(self, parent_id: str) -> list[dict[str, Any]]:
        """获取个人网盘文件列表。"""
        filters = quote('{"trashed":{"eq":false}}')
        url = (
            f"{FILES_URL}?parent_id={parent_id}"
            f"&page_token=&limit=100&with_audit=true&filters={filters}"
        )
        resp = self._pan_request("GET", url)
        result = self._parse_json(resp)
        data = result.get("data", result)
        files = []
        for item in data.get("files", []):
            files.append(
                {
                    "fid": item.get("id", ""),
                    "fname": item.get("name", ""),
                    "fsize": item.get("size", 0),
                    "isdir": item.get("kind") == "drive#folder",
                }
            )
        return files

    def _create_folder(self, name: str, parent_id: str) -> str:
        """创建文件夹，返回新文件夹 id。"""
        body = {
            "kind": "drive#folder",
            "name": name,
            "parent_id": parent_id,
            "space": "",
        }
        resp = self._pan_request("POST", FILES_URL, body)
        result = self._parse_json(resp)
        data = result.get("data", result)
        folder_id = data.get("id", "")
        if not folder_id:
            raise ParserError(f"创建目录失败: {name}")
        return folder_id

    def _restore_file(
        self,
        share_id: str,
        pass_code_token: str,
        parent_folder_id: str,
        file_info: dict[str, Any],
    ) -> str:
        """转存分享文件到指定目录，返回转存后的新文件 id。"""
        body = {
            "share_id": share_id,
            "pass_code_token": pass_code_token,
            "parent_id": parent_folder_id,
            "ancestor_ids": [],
            "file_ids": [file_info["fid"]],
            "specify_parent_id": True,
        }
        resp = self._pan_request("POST", RESTORE_URL, body)
        result = self._parse_json(resp)
        data = result.get("data", result)

        # trace_file_ids 是 JSON 字符串：{"分享文件id":"转存后新id"}
        trace = data.get("params", {}).get("trace_file_ids", "")
        if trace:
            try:
                trace_map = json.loads(trace)
                if file_info["fid"] in trace_map:
                    return trace_map[file_info["fid"]]
            except json.JSONDecodeError:
                pass
        new_id = data.get("file_id", "")
        if not new_id:
            raise ParserError("转存失败：未返回新文件 ID")
        return new_id

    def _get_file_detail(self, file_id: str) -> dict[str, Any]:
        """获取文件详情，返回下载直链。"""
        url = (
            f"{FILES_URL}/{file_id}?_magic=2021&usage=PLAY"
            f"&thumbnail_size=SIZE_LARGE&with=hdr10"
            f"&with=subtitle_files&with=task&with=public_share_tag"
        )
        resp = self._pan_request("GET", url)
        result = self._parse_json(resp)
        data = result.get("data", result)

        links = data.get("links", {})
        download_url = (
            links.get("application/octet-stream", {}).get("url", "")
            or data.get("web_content_link", "")
        )
        return {
            "fid": data.get("id", ""),
            "filename": data.get("name", ""),
            "download_url": download_url,
            "size": data.get("size", 0),
        }

    def _batch_delete(self, file_ids: list[str]) -> None:
        """批量删除文件（移入回收站）。"""
        body = {"ids": file_ids, "space": ""}
        self._pan_request("POST", TRASH_URL, body)

    # ---------- HTTP 工具 ----------

    def _pan_request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
    ) -> requests.Response:
        """发送 pan API 请求（Bearer + 设备 + captcha 头）。"""
        headers = {
            "User-Agent": WEB_UA,
            "Authorization": f"Bearer {self._access_token}",
            "X-Device-Id": self._device_id,
            "X-Client-Version": APP_CLIENT_VERSION,
            "Content-Type": "application/json",
            "Origin": "https://pan.xunlei.com",
            "Referer": "https://pan.xunlei.com/",
        }
        if self._captcha_token:
            headers["X-Captcha-Token"] = self._captcha_token
        return self._request(method, url, headers, body)

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        try:
            return self._session.request(
                method,
                url,
                headers=headers or {},
                json=json_body,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise NetworkError(f"迅雷 API 请求失败: {exc}") from exc

    @staticmethod
    def _parse_json(resp: requests.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except ValueError as exc:
            raise ParserError(f"响应解析失败: {exc}") from exc

    @staticmethod
    def _guess_file_type(file_name: str) -> str:
        if "." in file_name:
            return file_name.rsplit(".", 1)[-1].lower()
        return "unknown"
