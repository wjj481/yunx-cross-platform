"""
百度网盘上传器（实验性，含风控警告）。

⚠️  风控警告 ⚠️
百度网盘对自动化上传有极其严格的风控策略：
- 频繁调用上传 API 可能导致账号被临时封禁或永久封号。
- 上传接口有严格的频率限制和行为检测，非官方客户端可能被识别。
- 使用本模块可能违反百度网盘用户协议。

UI 层在调用本上传器前，必须展示 :class:`core.exceptions.BaiduRiskWarning`
警告并获得用户明确确认（调用 :meth:`acknowledge_risk`）。

上传流程：
1. precreate（预创建，获取 uploadid）
2. 分片上传（superfile 接口，需要 BDUSS Cookie）
3. create（创建文件，合并分片）

需要登录凭证（BDUSS Cookie）。

免责声明：仅供个人学习技术交流。
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import requests

from ..exceptions import (
    AuthenticationError,
    BaiduRiskWarning,
    NetworkError,
    QuotaExceededError,
    UploadError,
)
from .base import BaseUploader, DirInfo, ShareInfo, UploadResult

# ---------- 常量 ----------

PAN_API_BASE = "https://pan.baidu.com"
PCS_BASE = "https://d.pcs.baidu.com"

PRECREATE_URL = f"{PAN_API_BASE}/api/precreate"
SUPERFILE_URL = f"{PCS_BASE}/rest/2.0/pcs/superfile2"
CREATE_URL = f"{PAN_API_BASE}/api/create"
FILE_LIST_URL = f"{PAN_API_BASE}/api/list"
SHARE_SET_URL = f"{PAN_API_BASE}/share/set"

WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

# 百度网盘分片大小（固定 4MB，superfile2 接口要求）
BAIDU_CHUNK_SIZE = 4 * 1024 * 1024


class BaiduUploader(BaseUploader):
    """百度网盘上传器（实验性，带风控警告）。

    需要登录凭证（BDUSS Cookie）。

    凭证格式::

        {"cookie": "BDUSS=...; ..."}

    使用前必须调用 :meth:`acknowledge_risk` 确认已知晓风控风险。
    """

    drive_name = "baidu"
    status = "experimental"

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": WEB_UA})
        self._cookie: str = (credential or {}).get("cookie", "")
        self._risk_acknowledged = False

    def acknowledge_risk(self) -> None:
        """用户确认已知晓百度网盘风控风险。

        UI 层必须在调用任何上传方法前调用此方法。
        """
        self._risk_acknowledged = True

    def _check_risk(self) -> None:
        """检查用户是否已确认风控风险。"""
        if not self._risk_acknowledged:
            raise BaiduRiskWarning(
                "百度网盘上传存在账号封禁风险，请确认已知晓风险后再使用。"
                "（调用 acknowledge_risk() 确认）"
            )

    # ---------- 公共接口 ----------

    def init_upload(
        self, file_path: str, remote_dir: str, file_name: str, file_size: int
    ) -> dict[str, Any]:
        """预创建百度网盘文件，获取 uploadid。

        Args:
            file_path: 本地文件路径。
            remote_dir: 远程目标目录路径（如 ``"/"``、``"/我的上传"``）。
            file_name: 文件名。
            file_size: 文件大小（字节）。

        Returns:
            上传上下文字典，包含：
            - ``uploadid``: 上传会话 ID
            - ``remote_path``: 远程完整路径（目录 + 文件名）
            - ``file_size``: 文件大小
            - ``block_list``: 分片 MD5 列表（用于秒传检测）

        Raises:
            BaiduRiskWarning: 用户未确认风控风险。
            AuthenticationError: 未提供 BDUSS。
            QuotaExceededError: 空间不足。
            UploadError: 预创建失败。
        """
        self._check_risk()

        if not self._cookie or "BDUSS" not in self._cookie:
            raise AuthenticationError("百度网盘需要 BDUSS Cookie")

        # 计算所有分片的 MD5（用于秒传检测）
        block_md5s = self._calc_block_md5s(file_path, file_size)
        content_md5 = self._calc_file_md5(file_path)
        slice_md5 = self._calc_slice_md5(file_path)

        remote_path = self._join_path(remote_dir, file_name)

        body = {
            "path": remote_path,
            "size": file_size,
            "isdir": 0,
            "autoinit": 1,
            "block_list": block_md5s,
            "content-md5": content_md5,
            "slice-md5": slice_md5,
        }

        params = {"method": "precreate", "app_id": "250528"}
        resp = self._post_form(PRECREATE_URL, params, body)
        result = self._parse_json(resp)

        # 错误处理
        errno = result.get("errno", -1)
        if errno != 0:
            self._handle_baidu_error(errno, result.get("errmsg", ""))

        # 秒传命中
        if result.get("return_type") == 2:
            return {
                "uploadid": "",
                "remote_path": remote_path,
                "file_size": file_size,
                "block_list": block_md5s,
                "instant_upload": True,
                "fs_id": result.get("fs_id", ""),
            }

        uploadid = result.get("uploadid", "")
        if not uploadid:
            raise UploadError("百度网盘预创建失败：未获取到 uploadid")

        return {
            "uploadid": uploadid,
            "remote_path": remote_path,
            "file_size": file_size,
            "block_list": block_md5s,
            "instant_upload": False,
        }

    def upload_chunk(
        self,
        context: dict[str, Any],
        chunk_index: int,
        chunk_data: bytes,
        total_chunks: int,
    ) -> dict[str, Any]:
        """上传单个分片到百度网盘 superfile2 接口。

        Args:
            context: 上传上下文。
            chunk_index: 分片序号（从 0 开始）。
            chunk_data: 分片二进制数据。
            total_chunks: 总分片数。

        Returns:
            分片上传结果，包含 ``md5`` 和 ``part_index``。
        """
        self._check_risk()

        if context.get("instant_upload"):
            return {"md5": "", "part_index": chunk_index, "skipped": True}

        params = {
            "method": "upload",
            "app_id": "250528",
            "path": context["remote_path"],
            "uploadid": context["uploadid"],
            "partseq": str(chunk_index),
        }

        files = {"file": ("chunk", chunk_data, "application/octet-stream")}

        try:
            resp = self._session.post(
                SUPERFILE_URL,
                params=params,
                files=files,
                headers={"Cookie": self._cookie},
                timeout=60,
            )
        except requests.RequestException as exc:
            raise NetworkError(f"百度网盘分片上传失败: {exc}") from exc

        result = self._parse_json(resp)
        errno = result.get("errno", -1)
        if errno != 0:
            self._handle_baidu_error(errno, result.get("errmsg", ""))

        md5 = result.get("md5", "")
        return {"md5": md5, "part_index": chunk_index}

    def complete_upload(
        self, context: dict[str, Any], chunk_results: list[dict[str, Any]]
    ) -> UploadResult:
        """完成百度网盘上传，创建文件（合并分片）。

        Args:
            context: 上传上下文。
            chunk_results: 所有分片的上传结果列表。

        Returns:
            上传结果 :class:`UploadResult`。
        """
        self._check_risk()

        if context.get("instant_upload"):
            return UploadResult(
                file_id=str(context.get("fs_id", "")),
                file_name=os.path.basename(context["remote_path"]),
                file_size=context["file_size"],
                remote_path=context["remote_path"],
                drive=self.drive_name,
                raw_response={"instant_upload": True},
            )

        body = {
            "path": context["remote_path"],
            "size": context["file_size"],
            "isdir": 0,
            "uploadid": context["uploadid"],
            "block_list": context["block_list"],
        }

        params = {"method": "create", "app_id": "250528"}
        resp = self._post_form(CREATE_URL, params, body)
        result = self._parse_json(resp)

        errno = result.get("errno", -1)
        if errno != 0:
            self._handle_baidu_error(errno, result.get("errmsg", ""))

        fs_id = str(result.get("fs_id", ""))
        if not fs_id:
            raise UploadError("百度网盘创建文件失败：未返回 fs_id")

        return UploadResult(
            file_id=fs_id,
            file_name=os.path.basename(context["remote_path"]),
            file_size=context["file_size"],
            remote_path=context["remote_path"],
            drive=self.drive_name,
            raw_response=result,
        )

    # ---------- 可选方法 ----------

    def get_remote_dirs(self, parent_dir: str | None = None) -> list[DirInfo]:
        """获取百度网盘远程目录列表。"""
        self._check_risk()

        dir_path = parent_dir or "/"
        params = {
            "method": "list",
            "app_id": "250528",
            "dir": dir_path,
            "order": "name",
            "desc": 0,
            "limit": 200,
        }
        resp = self._request("GET", FILE_LIST_URL, params=params,
                             headers={"Cookie": self._cookie})
        result = self._parse_json(resp)

        errno = result.get("errno", -1)
        if errno != 0:
            self._handle_baidu_error(errno, result.get("errmsg", ""))

        dirs = []
        for item in result.get("list", []):
            if item.get("isdir") == 1:
                dirs.append(
                    DirInfo(
                        dir_id=str(item.get("fs_id", "")),
                        dir_name=item.get("server_filename", ""),
                        parent_id=dir_path,
                    )
                )
        return dirs

    def create_share_link(self, file_id: str) -> ShareInfo:
        """为百度网盘文件生成分享链接。"""
        self._check_risk()

        body = {
            "fid_list": f"[{file_id}]",
            "schannel": 0,  # 0=公开
            "channel_list": "[]",
            "period": 0,  # 0=永久
        }
        params = {"method": "set", "app_id": "250528"}
        resp = self._post_form(SHARE_SET_URL, params, body)
        result = self._parse_json(resp)

        errno = result.get("errno", -1)
        if errno != 0:
            self._handle_baidu_error(errno, result.get("errmsg", ""))

        share_id = str(result.get("shareid", ""))
        link = result.get("link", "")
        return ShareInfo(
            share_url=link,
            share_id=share_id,
            extract_code="",
            expires_at="永久有效",
            drive=self.drive_name,
        )

    # ---------- 工具方法 ----------

    @staticmethod
    def _join_path(remote_dir: str, file_name: str) -> str:
        """拼接远程路径。"""
        if not remote_dir or remote_dir == "/":
            return f"/{file_name}"
        if remote_dir.endswith("/"):
            return f"{remote_dir}{file_name}"
        return f"{remote_dir}/{file_name}"

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

    @staticmethod
    def _calc_slice_md5(file_path: str) -> str:
        """计算文件前 256KB 的 MD5（百度秒传用 slice-md5）。"""
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            data = f.read(256 * 1024)
            hasher.update(data)
        return hasher.hexdigest()

    @staticmethod
    def _calc_block_md5s(file_path: str, file_size: int) -> list[str]:
        """计算所有分片的 MD5 列表（百度 precreate 用）。"""
        md5s = []
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(BAIDU_CHUNK_SIZE)
                if not chunk:
                    break
                md5s.append(hashlib.md5(chunk).hexdigest())
        return md5s

    def _post_form(
        self,
        url: str,
        params: dict[str, Any],
        data: dict[str, Any],
    ) -> requests.Response:
        """发送 POST 表单请求。"""
        try:
            return self._session.post(
                url,
                params=params,
                data=data,
                headers={"Cookie": self._cookie},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise NetworkError(f"百度网盘 API 请求失败: {exc}") from exc

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """发送 HTTP 请求。"""
        try:
            return self._session.request(
                method, url, params=params, headers=headers or {}, timeout=30
            )
        except requests.RequestException as exc:
            raise NetworkError(f"百度网盘 API 请求失败: {exc}") from exc

    @staticmethod
    def _parse_json(resp: requests.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except ValueError as exc:
            raise UploadError(f"响应解析失败: {exc}") from exc

    @staticmethod
    def _handle_baidu_error(errno: int, errmsg: str) -> None:
        """根据百度网盘 errno 抛出对应异常。"""
        # 空间不足
        if errno in (31071, 31072, -8):
            raise QuotaExceededError(f"百度网盘空间不足: {errmsg}（errno={errno}）")
        # 认证失败
        if errno in (-1, 1, 2, 3, 4, 111, 112, 113, 114, 115):
            raise AuthenticationError(
                f"百度网盘认证失败，请重新登录: {errmsg}（errno={errno}）"
            )
        # 频率限制 / 风控
        if errno in (31031, 31032, 31033, 31034, 31035):
            raise UploadError(
                f"百度网盘触发频率限制或风控，请稍后重试: {errmsg}（errno={errno}）"
            )
        raise UploadError(f"百度网盘上传失败: {errmsg}（errno={errno}）")
