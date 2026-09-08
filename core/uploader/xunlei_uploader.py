"""
迅雷网盘上传器。

上传流程：
1. 获取上传地址（需要 captcha_sign 10 层 MD5 签名）
2. 分片上传到返回的预签名 URL
3. 确认完成（commit 接口）

认证方式：Bearer access_token + X-Device-Id + X-Captcha-Token。
captcha_sign 算法复用 :mod:`core.parsers.xunlei` 中的 ``_build_captcha_sign``：
raw = client_id + client_version + package_name + device_id + timestamp_ms
→ 10 层 MD5(raw+salt)，前缀 "1."。

需要登录凭证（access_token、device_id、可选 captcha_token）。

免责声明：仅供个人学习技术交流。
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from typing import Any

import requests

from ..exceptions import AuthenticationError, NetworkError, QuotaExceededError, UploadError
from .base import BaseUploader, DirInfo, ShareInfo, UploadResult

# ---------- 常量（对齐迅雷解析器） ----------

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
UPLOAD_INIT_URL = f"{PAN_BASE}/drive/v1/files:uploadInit"
UPLOAD_COMMIT_URL = f"{PAN_BASE}/drive/v1/files:uploadCommit"
SHARE_URL = f"{PAN_BASE}/drive/v1/share"


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


class XunleiUploader(BaseUploader):
    """迅雷网盘上传器。

    需要登录凭证（access_token、device_id、可选 captcha_token）。

    凭证格式::

        {
            "access_token": "...",
            "device_id": "...",
            "captcha_token": "..."  # 可选，为空时自动初始化
        }
    """

    drive_name = "xunlei"
    status = "stable"

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        cred = credential or {}
        self._access_token: str = cred.get("access_token", "")
        self._device_id: str = cred.get("device_id", "")
        self._captcha_token: str = cred.get("captcha_token", "")
        self._session = requests.Session()

        if not self._device_id:
            self._device_id = "%032x" % random.getrandbits(128)

    # ---------- 公共接口 ----------

    def init_upload(
        self, file_path: str, remote_dir: str, file_name: str, file_size: int
    ) -> dict[str, Any]:
        """初始化迅雷网盘上传，获取预签名上传 URL。

        Args:
            file_path: 本地文件路径。
            remote_dir: 远程目标目录 ID（根目录为空字符串）。
            file_name: 文件名。
            file_size: 文件大小（字节）。

        Returns:
            上传上下文字典，包含：
            - ``upload_url``: 预签名上传地址
            - ``file_id``: 预创建文件 ID
            - ``parent_id``: 父目录 ID
            - ``file_name``: 文件名
            - ``file_size``: 文件大小
            - ``upload_token``: 上传会话 token

        Raises:
            AuthenticationError: 未提供 access_token。
            QuotaExceededError: 空间不足。
            UploadError: 初始化失败。
        """
        if not self._access_token:
            raise AuthenticationError("迅雷网盘需要 access_token")

        # 确保 captcha_token 有效
        if not self._captcha_token:
            self._captcha_token = self._init_captcha()

        file_hash = self._calc_file_sha1(file_path)

        body = {
            "parent_id": remote_dir or "",
            "name": file_name,
            "size": file_size,
            "kind": "drive#file",
            "sha1": file_hash,
            "space": "",
        }

        resp = self._pan_request("POST", UPLOAD_INIT_URL, body)
        result = self._parse_json(resp)
        data = result.get("data", result)

        # 错误处理
        if "error" in result or "error_code" in result:
            self._handle_xunlei_error(result)

        # 秒传命中
        if data.get("id") and not data.get("upload_url"):
            return {
                "upload_url": "",
                "file_id": data.get("id", ""),
                "parent_id": remote_dir or "",
                "file_name": file_name,
                "file_size": file_size,
                "upload_token": data.get("upload_token", ""),
                "instant_upload": True,
            }

        upload_url = data.get("upload_url", "")
        file_id = data.get("id", "")
        upload_token = data.get("upload_token", "")

        if not upload_url:
            raise UploadError("迅雷网盘上传初始化失败：未获取到 upload_url")

        return {
            "upload_url": upload_url,
            "file_id": file_id,
            "parent_id": remote_dir or "",
            "file_name": file_name,
            "file_size": file_size,
            "upload_token": upload_token,
            "instant_upload": False,
        }

    def upload_chunk(
        self,
        context: dict[str, Any],
        chunk_index: int,
        chunk_data: bytes,
        total_chunks: int,
    ) -> dict[str, Any]:
        """上传单个分片到迅雷网盘 OSS。

        Args:
            context: 上传上下文。
            chunk_index: 分片序号（从 0 开始）。
            chunk_data: 分片二进制数据。
            total_chunks: 总分片数。

        Returns:
            分片上传结果，包含 ``etag`` 和 ``part_number``。
        """
        if context.get("instant_upload"):
            return {"etag": "", "part_number": chunk_index + 1, "skipped": True}

        upload_url = context["upload_url"]

        params = {
            "partNumber": str(chunk_index + 1),
            "uploadId": context.get("upload_token", ""),
        }

        headers = {
            "Content-Type": "application/octet-stream",
        }

        try:
            resp = self._session.put(
                upload_url,
                params=params,
                headers=headers,
                data=chunk_data,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise NetworkError(f"迅雷网盘分片上传失败: {exc}") from exc

        if resp.status_code not in (200, 201):
            raise UploadError(
                f"迅雷网盘分片上传失败: HTTP {resp.status_code}, body={resp.text[:200]}"
            )

        etag = resp.headers.get("ETag", "").strip('"')
        return {"etag": etag, "part_number": chunk_index + 1}

    def complete_upload(
        self, context: dict[str, Any], chunk_results: list[dict[str, Any]]
    ) -> UploadResult:
        """完成迅雷网盘上传，确认合并。

        Args:
            context: 上传上下文。
            chunk_results: 所有分片的上传结果列表。

        Returns:
            上传结果 :class:`UploadResult`。
        """
        if context.get("instant_upload"):
            return UploadResult(
                file_id=context["file_id"],
                file_name=context["file_name"],
                file_size=context["file_size"],
                remote_path=context["parent_id"],
                drive=self.drive_name,
                raw_response={"instant_upload": True},
            )

        body = {
            "id": context["file_id"],
            "upload_token": context.get("upload_token", ""),
            "parts": [
                {"part_number": r["part_number"], "etag": r.get("etag", "")}
                for r in chunk_results
            ],
            "space": "",
        }

        resp = self._pan_request("POST", UPLOAD_COMMIT_URL, body)
        result = self._parse_json(resp)
        data = result.get("data", result)

        if "error" in result or "error_code" in result:
            self._handle_xunlei_error(result)

        file_id = data.get("id", context["file_id"])

        return UploadResult(
            file_id=file_id,
            file_name=context["file_name"],
            file_size=context["file_size"],
            remote_path=context["parent_id"],
            drive=self.drive_name,
            raw_response=data,
        )

    # ---------- 可选方法 ----------

    def get_remote_dirs(self, parent_dir: str | None = None) -> list[DirInfo]:
        """获取迅雷网盘远程目录列表。"""
        if not self._captcha_token:
            self._captcha_token = self._init_captcha()

        parent_id = parent_dir or ""
        from urllib.parse import quote
        filters = quote('{"trashed":{"eq":false}}')
        url = (
            f"{FILES_URL}?parent_id={parent_id}"
            f"&page_token=&limit=200&with_audit=true&filters={filters}"
        )
        resp = self._pan_request("GET", url)
        result = self._parse_json(resp)
        data = result.get("data", result)

        dirs = []
        for item in data.get("files", []):
            if item.get("kind") == "drive#folder":
                dirs.append(
                    DirInfo(
                        dir_id=item.get("id", ""),
                        dir_name=item.get("name", ""),
                        parent_id=parent_id,
                    )
                )
        return dirs

    def create_share_link(self, file_id: str) -> ShareInfo:
        """为迅雷网盘文件生成分享链接。"""
        if not self._captcha_token:
            self._captcha_token = self._init_captcha()

        body = {
            "files": [{"id": file_id}],
            "pass_code": "",
            "expiration": "never",
            "space": "",
        }
        resp = self._pan_request("POST", SHARE_URL, body)
        result = self._parse_json(resp)
        data = result.get("data", result)

        share_id = data.get("share_id", "")
        pass_code = data.get("pass_code", "")
        share_url = f"https://pan.xunlei.com/s/{share_id}" if share_id else ""
        return ShareInfo(
            share_url=share_url,
            share_id=share_id,
            extract_code=pass_code,
            expires_at="永久有效",
            drive=self.drive_name,
        )

    # ---------- 工具方法 ----------

    def _init_captcha(self) -> str:
        """初始化验证码盾，获取 captcha_token。"""
        ts_ms = str(int(time.time() * 1000))
        sign = _build_captcha_sign(self._device_id, ts_ms)
        body = {
            "action": "POST:/drive/v1/files:uploadInit",
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
            raise UploadError("获取 captcha_token 失败")
        return token

    @staticmethod
    def _calc_file_sha1(file_path: str) -> str:
        """计算文件 SHA1。"""
        hasher = hashlib.sha1()
        with open(file_path, "rb") as f:
            while True:
                buf = f.read(1024 * 1024)
                if not buf:
                    break
                hasher.update(buf)
        return hasher.hexdigest()

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
            raise UploadError(f"响应解析失败: {exc}") from exc

    @staticmethod
    def _handle_xunlei_error(result: dict[str, Any]) -> None:
        """根据迅雷 API 错误抛出对应异常。"""
        error = result.get("error", "")
        error_code = result.get("error_code", 0)
        error_msg = result.get("error_description", result.get("message", str(error)))

        # 空间不足
        if "quota" in error.lower() or "space" in error.lower() or error_code in (4101, 4102):
            raise QuotaExceededError(f"迅雷网盘空间不足: {error_msg}")
        # 认证失败
        if "auth" in error.lower() or "token" in error.lower() or error_code in (401, 403):
            raise AuthenticationError(f"迅雷网盘认证失败，请重新登录: {error_msg}")
        raise UploadError(f"迅雷网盘上传失败: {error_msg}")
