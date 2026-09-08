"""
夸克网盘上传器。

上传流程：
1. 获取上传凭证（upload_token）— 调用 ``/1/clouddrive/file/upload`` 接口
2. 分片上传到 OSS — 使用返回的 upload_url 直传，携带签名头
3. 合并分片（commit）— 调用 ``/1/clouddrive/file/upload/commit`` 接口

需要登录 Cookie（包含 ``__pus`` 和 ``__puus`` 字段），与夸克解析器共用凭证。

免责声明：仅供个人学习技术交流。
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import requests

from ..exceptions import AuthenticationError, NetworkError, QuotaExceededError, UploadError
from .base import BaseUploader, DirInfo, ShareInfo, UploadResult

# ---------- 常量（对齐夸克解析器） ----------

API_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "quark-cloud-drive/2.5.20 Chrome/100.0.4896.160 Electron/18.3.5.12-a038f7b798 "
    "Safari/537.36 Channel/pckk_other_ch"
)

API_BASE = "https://drive-pc.quark.cn"
UPLOAD_INIT_URL = f"{API_BASE}/1/clouddrive/file/upload?pr=ucpro&fr=pc"
UPLOAD_COMMIT_URL = f"{API_BASE}/1/clouddrive/file/upload/commit?pr=ucpro&fr=pc"
FILE_URL = f"{API_BASE}/1/clouddrive/file?pr=ucpro&fr=pc"
SHARE_CREATE_URL = f"{API_BASE}/1/clouddrive/share?pr=ucpro&fr=pc"

DEFAULT_PDIR_FID = "0"


class QuarkUploader(BaseUploader):
    """夸克网盘上传器。

    需要登录凭证（Cookie，必须包含 ``__pus`` 和 ``__puus`` 字段）。

    凭证格式::

        {"cookie": "__pus=xxx; __puus=xxx; ..."}
    """

    drive_name = "quark"
    status = "stable"

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": API_USER_AGENT})
        self._cookie: str = (credential or {}).get("cookie", "")

    # ---------- 公共接口 ----------

    def init_upload(
        self, file_path: str, remote_dir: str, file_name: str, file_size: int
    ) -> dict[str, Any]:
        """初始化夸克上传，获取 upload_token 和 OSS 上传地址。

        Args:
            file_path: 本地文件路径。
            remote_dir: 远程目标目录 fid（根目录为 ``"0"``）。
            file_name: 文件名。
            file_size: 文件大小（字节）。

        Returns:
            上传上下文字典，包含：
            - ``upload_token``: 上传凭证
            - ``upload_url``: OSS 上传地址
            - ``pdir_fid``: 目标目录 fid
            - ``file_name``: 文件名
            - ``file_size``: 文件大小
            - ``md5``: 文件 MD5（用于秒传检测）

        Raises:
            AuthenticationError: 未提供有效 Cookie。
            QuotaExceededError: 空间不足。
            UploadError: 初始化失败。
        """
        if not self._cookie or "__pus" not in self._cookie:
            raise AuthenticationError("夸克网盘需要登录 Cookie（包含 __pus / __puus）")

        # 计算文件 MD5（用于秒传检测和去重）
        file_md5 = self._calc_file_md5(file_path)

        body = {
            "pdir_fid": remote_dir or DEFAULT_PDIR_FID,
            "file_name": file_name,
            "size": file_size,
            "md5": file_md5,
            "dir_path": "",
            "dir_init_lock": False,
        }
        data = self._post_json(UPLOAD_INIT_URL, body)

        upload_token = data.get("upload_token", "")
        upload_url = data.get("upload_url", "")
        # 秒传命中时直接返回文件信息
        if data.get("fid"):
            return {
                "upload_token": upload_token,
                "upload_url": upload_url,
                "pdir_fid": remote_dir or DEFAULT_PDIR_FID,
                "file_name": file_name,
                "file_size": file_size,
                "md5": file_md5,
                "fid": data["fid"],
                "instant_upload": True,
            }

        if not upload_token or not upload_url:
            raise UploadError("夸克上传初始化失败：未获取到 upload_token 或 upload_url")

        return {
            "upload_token": upload_token,
            "upload_url": upload_url,
            "pdir_fid": remote_dir or DEFAULT_PDIR_FID,
            "file_name": file_name,
            "file_size": file_size,
            "md5": file_md5,
            "instant_upload": False,
        }

    def upload_chunk(
        self,
        context: dict[str, Any],
        chunk_index: int,
        chunk_data: bytes,
        total_chunks: int,
    ) -> dict[str, Any]:
        """上传单个分片到夸克 OSS。

        Args:
            context: 上传上下文。
            chunk_index: 分片序号（从 0 开始）。
            chunk_data: 分片二进制数据。
            total_chunks: 总分片数。

        Returns:
            分片上传结果，包含 ``etag`` 和 ``part_number``。

        Raises:
            UploadError: 分片上传失败。
        """
        # 秒传命中时无需实际上传
        if context.get("instant_upload"):
            return {"etag": "", "part_number": chunk_index + 1, "skipped": True}

        upload_url = context["upload_url"]
        upload_token = context["upload_token"]

        # OSS 分片上传参数
        params = {
            "upload_token": upload_token,
            "part_number": str(chunk_index + 1),
            "size": str(len(chunk_data)),
        }

        headers = {
            "Content-Type": "application/octet-stream",
            "Cookie": self._cookie,
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
            raise NetworkError(f"夸克分片上传失败: {exc}") from exc

        if resp.status_code not in (200, 201):
            raise UploadError(
                f"夸克分片上传失败: HTTP {resp.status_code}, body={resp.text[:200]}"
            )

        # OSS 返回 ETag 在响应头中
        etag = resp.headers.get("ETag", "").strip('"')
        return {"etag": etag, "part_number": chunk_index + 1}

    def complete_upload(
        self, context: dict[str, Any], chunk_results: list[dict[str, Any]]
    ) -> UploadResult:
        """完成夸克上传，合并分片。

        Args:
            context: 上传上下文。
            chunk_results: 所有分片的上传结果列表。

        Returns:
            上传结果 :class:`UploadResult`。

        Raises:
            UploadError: 合并失败。
        """
        # 秒传命中
        if context.get("instant_upload"):
            return UploadResult(
                file_id=context.get("fid", ""),
                file_name=context["file_name"],
                file_size=context["file_size"],
                remote_path=context["pdir_fid"],
                drive=self.drive_name,
                raw_response={"instant_upload": True},
            )

        body = {
            "upload_token": context["upload_token"],
            "pdir_fid": context["pdir_fid"],
            "file_name": context["file_name"],
            "size": context["file_size"],
            "md5": context["md5"],
            "parts": [
                {"part_number": r["part_number"], "etag": r.get("etag", "")}
                for r in chunk_results
            ],
        }
        data = self._post_json(UPLOAD_COMMIT_URL, body)

        fid = data.get("fid", "")
        if not fid:
            raise UploadError("夸克上传合并失败：未返回文件 fid")

        return UploadResult(
            file_id=fid,
            file_name=context["file_name"],
            file_size=context["file_size"],
            remote_path=context["pdir_fid"],
            drive=self.drive_name,
            raw_response=data,
        )

    # ---------- 可选方法 ----------

    def get_remote_dirs(self, parent_dir: str | None = None) -> list[DirInfo]:
        """获取夸克远程目录列表。

        Args:
            parent_dir: 父目录 fid；为 None 时获取根目录。

        Returns:
            目录信息列表。
        """
        pdir_fid = parent_dir or DEFAULT_PDIR_FID
        url = f"{FILE_URL}&pdir_fid={pdir_fid}&page=1&size=200"
        resp = self._request("GET", url, headers={"Cookie": self._cookie})
        data = self._parse_response(resp)
        dirs = []
        for item in data.get("list", []):
            if item.get("dir") or item.get("isdir"):
                dirs.append(
                    DirInfo(
                        dir_id=item.get("fid", ""),
                        dir_name=item.get("file_name", ""),
                        parent_id=pdir_fid,
                    )
                )
        return dirs

    def create_share_link(self, file_id: str) -> ShareInfo:
        """为夸克文件生成分享链接。

        Args:
            file_id: 文件 fid。

        Returns:
            分享链接信息。
        """
        body = {
            "fid_list": [file_id],
            "passcode": "",
            "expired_type": 1,  # 1=永久
        }
        data = self._post_json(SHARE_CREATE_URL, body)
        share_id = data.get("share_id", "")
        passcode = data.get("passcode", "")
        share_url = f"https://pan.quark.cn/s/{share_id}" if share_id else ""
        return ShareInfo(
            share_url=share_url,
            share_id=share_id,
            extract_code=passcode,
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

    def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """发送 POST JSON 请求并解析 data 字段。"""
        resp = self._request(
            "POST",
            url,
            headers={
                "Cookie": self._cookie,
                "Content-Type": "application/json",
            },
            json_body=body,
        )
        return self._parse_response(resp)

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        """发送 HTTP 请求，统一处理网络异常。"""
        merged_headers = {"User-Agent": API_USER_AGENT}
        if headers:
            merged_headers.update(headers)
        try:
            return self._session.request(
                method, url, headers=merged_headers, json=json_body, timeout=30
            )
        except requests.RequestException as exc:
            raise NetworkError(f"夸克 API 请求失败: {exc}") from exc

    def _parse_response(self, resp: requests.Response) -> dict[str, Any]:
        """解析夸克 API 响应，校验 status 字段。"""
        try:
            result = resp.json()
        except ValueError as exc:
            raise UploadError(f"响应解析失败: {exc}") from exc

        status = result.get("status", -1)
        code = result.get("code", 0)

        # 空间不足
        if code in (4101, 4102) or "空间不足" in str(result.get("message", "")):
            raise QuotaExceededError(
                result.get("message", "夸克网盘空间不足")
            )

        if status != 200:
            msg = result.get("message", "请求失败")
            # 凭证失效
            if code in (401, 403) or "登录" in msg or "cookie" in msg.lower():
                raise AuthenticationError(f"夸克凭证失效: {msg}")
            raise UploadError(f"{msg}（code={code}）")

        data = result.get("data")
        if data is None:
            raise UploadError("响应缺少 data 字段")
        return data
