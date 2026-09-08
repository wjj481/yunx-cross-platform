"""
123 云盘上传器。

上传流程：
1. 获取上传 URL（mupload 接口，需要 auth-key / auth-value CRC32 签名）
2. 分片上传到返回的预签名 URL
3. 合并确认（commit 接口）

签名算法复用 :mod:`core.parsers.pan123` 中的 ``_make_sign`` 逻辑：
- auth-key (timeSign) = CRC32(替换表映射后的 UTC "YYYYMMDDHHmm"，基准 ts + 57600s)
- auth-value = "<ts>-<random>-<CRC32(ts|random|path|web|3|auth_key)>"

需要登录凭证（JWT Token，从网页 localStorage 的 authorToken 获取）。

免责声明：仅供个人学习技术交流。
"""

from __future__ import annotations

import hashlib
import random
import time
import zlib
from datetime import datetime, timezone
from typing import Any

import requests

from ..exceptions import AuthenticationError, NetworkError, QuotaExceededError, UploadError
from .base import BaseUploader, DirInfo, ShareInfo, UploadResult

# ---------- 常量（对齐 123 云盘解析器） ----------

API_BASE = "https://yun.123pan.cn"
UPLOAD_INIT_URL = f"{API_BASE}/b/api/file/upload/create"
UPLOAD_COMMIT_URL = f"{API_BASE}/b/api/file/upload/commit"
FILE_LIST_URL = f"{API_BASE}/b/api/file/list"
SHARE_CREATE_URL = f"{API_BASE}/b/api/share/create"

WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

PLATFORM_WEB = "web"
APP_VERSION_WEB = "3"

# 数字 0-9 的替换表（索引 = 数字值）
SIGN_TABLE = "adefghlmyijnopkqrstubcvwsz"
SIGN_OS = "web"
SIGN_VER = "3"
# timeSign 时间基准偏移：ts + 57600 秒（+16h）
SIGN_OFFSET_SECONDS = 57600


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

    # 1) auth-key (timeSign)
    offset_ts = ts + SIGN_OFFSET_SECONDS
    dt = datetime.fromtimestamp(offset_ts, tz=timezone.utc)
    minute = dt.strftime("%Y%m%d%H%M")
    substituted = "".join(SIGN_TABLE[int(c)] for c in minute)
    auth_key = _crc32_hex(substituted)

    # 2) auth-value
    rand = random.randint(0, 10_000_000)
    data = f"{ts}|{rand}|{path}|{SIGN_OS}|{SIGN_VER}|{auth_key}"
    auth_value = f"{ts}-{rand}-{_crc32_hex(data)}"

    return auth_key, auth_value


class Pan123Uploader(BaseUploader):
    """123 云盘上传器。

    需要登录凭证（JWT Token，从网页 localStorage 的 authorToken 获取）。

    凭证格式::

        {"access_token": "Bearer JWT 或纯 JWT"}
    """

    drive_name = "pan123"
    status = "stable"

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._token: str = (credential or {}).get("access_token", "")
        if self._token.lower().startswith("bearer "):
            self._token = self._token[7:]
        self._loginuuid = "%032x" % random.getrandbits(128)

    # ---------- 公共接口 ----------

    def init_upload(
        self, file_path: str, remote_dir: str, file_name: str, file_size: int
    ) -> dict[str, Any]:
        """初始化 123 云盘上传，获取预签名上传 URL。

        Args:
            file_path: 本地文件路径。
            remote_dir: 远程目标目录 ID（根目录为 ``"0"``）。
            file_name: 文件名。
            file_size: 文件大小（字节）。

        Returns:
            上传上下文字典，包含：
            - ``upload_url``: 预签名上传地址
            - ``file_id``: 预创建文件 ID
            - ``parent_file_id``: 父目录 ID
            - ``file_name``: 文件名
            - ``file_size``: 文件大小
            - ``etag``: 文件 MD5（用于秒传）

        Raises:
            AuthenticationError: 未提供登录 Token。
            QuotaExceededError: 空间不足。
            UploadError: 初始化失败。
        """
        if not self._token:
            raise AuthenticationError("123 云盘需要登录 Token（authorToken）")

        file_etag = self._calc_file_md5(file_path)

        body = {
            "ParentFileId": remote_dir or "0",
            "FileName": file_name,
            "Size": file_size,
            "Etag": file_etag,
            "S3KeyFlag": "0",
        }

        auth_key, auth_value = _make_sign("/b/api/file/upload/create")
        headers = self._build_headers(auth_key, auth_value)

        resp = self._request("POST", UPLOAD_INIT_URL, headers, body)
        result = self._parse_json(resp)
        self._check_ok(result, "初始化上传失败")

        data = result.get("data", {})
        # 秒传命中
        if data.get("FileId") and not data.get("UploadURL"):
            return {
                "upload_url": "",
                "file_id": str(data["FileId"]),
                "parent_file_id": remote_dir or "0",
                "file_name": file_name,
                "file_size": file_size,
                "etag": file_etag,
                "instant_upload": True,
            }

        upload_url = data.get("UploadURL", "")
        file_id = str(data.get("FileId", ""))
        if not upload_url:
            raise UploadError("123 云盘上传初始化失败：未获取到 UploadURL")

        return {
            "upload_url": upload_url,
            "file_id": file_id,
            "parent_file_id": remote_dir or "0",
            "file_name": file_name,
            "file_size": file_size,
            "etag": file_etag,
            "instant_upload": False,
        }

    def upload_chunk(
        self,
        context: dict[str, Any],
        chunk_index: int,
        chunk_data: bytes,
        total_chunks: int,
    ) -> dict[str, Any]:
        """上传单个分片到 123 云盘 OSS。

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

        # 123 云盘使用 S3 兼容的分片上传
        params = {
            "partNumber": str(chunk_index + 1),
            "uploadId": context.get("upload_id", ""),
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
            raise NetworkError(f"123 云盘分片上传失败: {exc}") from exc

        if resp.status_code not in (200, 201):
            raise UploadError(
                f"123 云盘分片上传失败: HTTP {resp.status_code}, body={resp.text[:200]}"
            )

        etag = resp.headers.get("ETag", "").strip('"')
        return {"etag": etag, "part_number": chunk_index + 1}

    def complete_upload(
        self, context: dict[str, Any], chunk_results: list[dict[str, Any]]
    ) -> UploadResult:
        """完成 123 云盘上传，合并确认。

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
                remote_path=context["parent_file_id"],
                drive=self.drive_name,
                raw_response={"instant_upload": True},
            )

        body = {
            "FileId": int(context["file_id"]) if context["file_id"].isdigit() else 0,
            "FileName": context["file_name"],
            "Size": context["file_size"],
            "Etag": context["etag"],
            "ParentFileId": context["parent_file_id"],
        }

        auth_key, auth_value = _make_sign("/b/api/file/upload/commit")
        headers = self._build_headers(auth_key, auth_value)

        resp = self._request("POST", UPLOAD_COMMIT_URL, headers, body)
        result = self._parse_json(resp)
        self._check_ok(result, "上传合并失败")

        data = result.get("data", {})
        file_id = str(data.get("FileId", context["file_id"]))

        return UploadResult(
            file_id=file_id,
            file_name=context["file_name"],
            file_size=context["file_size"],
            remote_path=context["parent_file_id"],
            drive=self.drive_name,
            raw_response=data,
        )

    # ---------- 可选方法 ----------

    def get_remote_dirs(self, parent_dir: str | None = None) -> list[DirInfo]:
        """获取 123 云盘远程目录列表。"""
        parent_id = parent_dir or "0"
        url = (
            f"{FILE_LIST_URL}?limit=200&next=0"
            f"&orderBy=file_name&orderDirection=asc"
            f"&ParentFileId={parent_id}&Page=1"
        )
        auth_key, auth_value = _make_sign("/b/api/file/list")
        headers = self._build_headers(auth_key, auth_value)

        resp = self._request("GET", url, headers)
        result = self._parse_json(resp)
        self._check_ok(result, "获取目录列表失败")

        data = result.get("data", {})
        info_list = data.get("InfoList", [])
        dirs = []
        for item in info_list:
            if item.get("Type", 0) == 1:  # 1=目录
                dirs.append(
                    DirInfo(
                        dir_id=str(item.get("FileId", "")),
                        dir_name=item.get("FileName", ""),
                        parent_id=parent_id,
                    )
                )
        return dirs

    def create_share_link(self, file_id: str) -> ShareInfo:
        """为 123 云盘文件生成分享链接。"""
        body = {
            "FileIds": [int(file_id)] if file_id.isdigit() else [],
            "SharePwd": "",
            "ShareDay": 0,  # 0=永久
        }
        auth_key, auth_value = _make_sign("/b/api/share/create")
        headers = self._build_headers(auth_key, auth_value)

        resp = self._request("POST", SHARE_CREATE_URL, headers, body)
        result = self._parse_json(resp)
        self._check_ok(result, "生成分享链接失败")

        data = result.get("data", {})
        share_key = data.get("ShareKey", "")
        share_pwd = data.get("SharePwd", "")
        share_url = f"https://www.123pan.com/s/{share_key}" if share_key else ""
        return ShareInfo(
            share_url=share_url,
            share_id=share_key,
            extract_code=share_pwd,
            expires_at="永久有效",
            drive=self.drive_name,
        )

    # ---------- 工具方法 ----------

    @staticmethod
    def _calc_file_md5(file_path: str) -> str:
        """计算文件 MD5。"""
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                buf = f.read(1024 * 1024)
                if not buf:
                    break
                hasher.update(buf)
        return hasher.hexdigest()

    def _build_headers(
        self, auth_key: str, auth_value: str
    ) -> dict[str, str]:
        """构建带签名的请求头。"""
        return {
            "platform": PLATFORM_WEB,
            "app-version": APP_VERSION_WEB,
            "authorization": f"Bearer {self._token}",
            "loginuuid": self._loginuuid,
            "auth-key": auth_key,
            "auth-value": auth_value,
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": WEB_UA,
        }

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        """发送 HTTP 请求，统一处理网络异常。"""
        try:
            return self._session.request(
                method, url, headers=headers or {}, json=json_body, timeout=30
            )
        except requests.RequestException as exc:
            raise NetworkError(f"123 云盘 API 请求失败: {exc}") from exc

    @staticmethod
    def _parse_json(resp: requests.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except ValueError as exc:
            raise UploadError(f"响应解析失败: {exc}") from exc

    @staticmethod
    def _check_ok(result: dict[str, Any], fallback: str) -> None:
        """校验 123 API 响应 code == 0。"""
        code = result.get("code", -1)
        if code != 0:
            msg = result.get("message", fallback)
            # 空间不足
            if code in (4101, 4102) or "空间" in msg:
                raise QuotaExceededError(msg)
            # 凭证失效
            if code in (401, 403) or "登录" in msg or "token" in msg.lower():
                raise AuthenticationError(f"123 云盘凭证失效: {msg}")
            raise UploadError(f"{msg}（code={code}）")
