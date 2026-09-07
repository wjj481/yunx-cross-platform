"""
夸克网盘解析器。

参考云析 (YunX) Kotlin 实现重写，完整流程：
1. 获取分享 Token（携带提取码）
2. 获取分享文件列表
3. 转存文件到个人网盘临时目录（夸克直链必须转存后才能获取）
4. 轮询异步转存任务
5. 获取下载直链

API 端点与请求头严格对齐云析源码中的 QuarkConstants / QuarkApi。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import requests

from ..exceptions import AuthenticationError, NetworkError, ParserError
from .base import BaseParser, ShareInfo

# ---------- 常量（对齐云析 QuarkConstants） ----------

API_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "quark-cloud-drive/2.5.20 Chrome/100.0.4896.160 Electron/18.3.5.12-a038f7b798 "
    "Safari/537.36 Channel/pckk_other_ch"
)

API_BASE = "https://drive-pc.quark.cn"
SHARE_TOKEN_URL = f"{API_BASE}/1/clouddrive/share/sharepage/token?pr=ucpro&fr=pc"
SHARE_PASSWORD_URL = f"{API_BASE}/1/clouddrive/share/password?pr=ucpro&fr=pc"
SHARE_DETAIL_URL = f"{API_BASE}/1/clouddrive/share/sharepage/detail?pr=ucpro&fr=pc"
DOWNLOAD_URL = (
    f"{API_BASE}/1/clouddrive/file/download?pr=ucpro&fr=pc&sys=win32&ve=3.23.2"
)
FILE_URL = f"{API_BASE}/1/clouddrive/file?pr=ucpro&fr=pc"
SAVE_URL = f"{API_BASE}/1/clouddrive/share/sharepage/save?pr=ucpro&fr=pc"
TASK_URL = f"{API_BASE}/1/clouddrive/task?pr=ucpro&fr=pc"
DELETE_URL = f"{API_BASE}/1/clouddrive/file/delete?pr=ucpro&fr=pc&uc_param_str="
CONFIG_URL = f"{API_BASE}/1/clouddrive/config?pr=ucpro&fr=pc"

DEFAULT_PDIR_FID = "0"
TEMP_DIR_NAME = "YunX临时转存"
DOWNLOAD_REFERER = "https://pan.quark.cn/"

# 分享 ID 正则
_SHARE_ID_RE = __import__("re").compile(r"pan\.quark\.cn/s/([A-Za-z0-9]+)", __import__("re").IGNORECASE)


class QuarkParser(BaseParser):
    """夸克网盘解析器。

    需要登录凭证（Cookie，必须包含 ``__pus`` 和 ``__puus`` 字段）。

    凭证格式::

        {"cookie": "__pus=xxx; __puus=xxx; ..."}
    """

    supported_domains = ["pan.quark.cn", "drive.quark.cn"]
    drive_name = "quark"
    status = "stable"

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": API_USER_AGENT})
        self._cookie: str = (credential or {}).get("cookie", "")

    # ---------- 公共接口 ----------

    def parse_share_url(
        self, url: str, extract_code: str | None = None
    ) -> ShareInfo:
        """解析夸克分享链接。

        Args:
            url: 夸克分享链接（``https://pan.quark.cn/s/xxx``）。
            extract_code: 提取码；为 ``None`` 时从 URL 自动提取。

        Returns:
            :class:`ShareInfo`，包含文件信息和下载直链。

        Raises:
            AuthenticationError: 未提供有效 Cookie。
            ParserError: 解析失败。
        """
        if not self._cookie or "__pus" not in self._cookie:
            raise AuthenticationError("夸克网盘需要登录 Cookie（包含 __pus / __puus）")

        code = self._resolve_extract_code(url, extract_code)
        share_id = self._extract_share_id(url)

        # 1. 获取分享 Token
        token_data = self._get_share_token(share_id, code)
        stoken = token_data.get("stoken", "")
        title = token_data.get("title", share_id)

        # 2. 获取分享文件列表（取第一个文件）
        files = self._get_share_files(share_id, stoken, DEFAULT_PDIR_FID)
        if not files:
            raise ParserError("分享内容为空或已失效")
        # 优先取第一个文件；如果是目录则提示（当前版本仅支持单文件直链）
        first_file = files[0]
        if first_file.get("dir") or first_file.get("isdir"):
            raise ParserError("暂不支持目录分享，请选择具体文件")

        # 3. 转存到临时目录并获取直链
        direct_url, file_size = self._get_direct_link(
            share_id, stoken, first_file
        )

        file_name = first_file.get("file_name") or first_file.get("fname") or title
        file_type = self._guess_file_type(file_name)

        return ShareInfo(
            file_name=file_name,
            file_size=file_size or first_file.get("size", 0),
            file_type=file_type,
            direct_url=direct_url,
            expires_at=None,
            raw_response={"token": token_data, "file": first_file},
            share_id=share_id,
            extract_code=code,
            drive=self.drive_name,
        )

    # ---------- 内部流程 ----------

    def _extract_share_id(self, url: str) -> str:
        """从 URL 提取分享 ID。"""
        m = _SHARE_ID_RE.search(url)
        if not m:
            raise ParserError(f"无法从链接中提取夸克分享 ID: {url}")
        return m.group(1)

    def _get_share_token(
        self, share_id: str, passcode: str | None
    ) -> dict[str, Any]:
        """获取分享 Token（接口 4.1）。"""
        body = {
            "pwd_id": share_id,
            "passcode": passcode or "",
            "support_visit_limit_private_share": True,
        }
        data = self._post_json(SHARE_TOKEN_URL, body)
        return data

    def _get_share_files(
        self, share_id: str, stoken: str, pdir_fid: str
    ) -> list[dict[str, Any]]:
        """获取分享文件列表（接口 4.2）。"""
        url = (
            f"{SHARE_DETAIL_URL}"
            f"&pwd_id={share_id}"
            f"&stoken={quote(stoken)}"
            f"&pdir_fid={pdir_fid}"
            f"&ver=2&force=0&_page=1&_size=100"
            f"&_fetch_banner=0&_fetch_share=0"
            f"&fetch_relate_conversation=0&_fetch_total=1"
            f"&_sort=file_type:asc,file_name:asc"
        )
        headers = {
            "Cookie": self._cookie,
            "Origin": "https://pan.quark.cn",
            "Referer": "https://pan.quark.cn/",
        }
        resp = self._request("GET", url, headers=headers)
        data = self._parse_response(resp)
        return data.get("list", [])

    def _get_direct_link(
        self,
        share_id: str,
        stoken: str,
        file_info: dict[str, Any],
    ) -> tuple[str, int]:
        """转存文件到临时目录并获取下载直链。

        夸克网盘的下载直链必须将分享文件转存到个人网盘后才能获取。
        采用唯一子目录策略避免夸克去重机制导致的二次取链失败。
        """
        # 确保临时目录存在
        base_dir_fid = self._ensure_temp_dir()

        # 创建唯一子目录（绕开夸克去重）
        sub_dir_name = f"tr_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        sub_dir_fid = self._create_folder(sub_dir_name, base_dir_fid)

        try:
            # 转存
            fid = file_info.get("fid", "")
            fid_token = file_info.get("share_fid_token") or file_info.get(
                "fid_token", ""
            )
            pdir_fid = file_info.get("pdir_fid", DEFAULT_PDIR_FID)

            task_id = self._save_share_file(
                share_id, stoken, pdir_fid, fid, fid_token, sub_dir_fid
            )
            saved_fid = self._poll_task(task_id)

            # 获取下载直链
            link_data = self._get_download_link(saved_fid)
            direct_url = link_data.get("download_url", "")
            file_size = link_data.get("size", 0)

            if not direct_url:
                raise ParserError("未获取到下载直链")

            return direct_url, file_size
        finally:
            # 下载完成后由调用方清理；此处不删除（直链有效期内需要文件存在）
            # 记录待清理的目录 fid 到 raw_response
            pass

    def _ensure_temp_dir(self) -> str:
        """确保「YunX临时转存」目录存在，返回其 fid。"""
        files = self._get_file_list(DEFAULT_PDIR_FID)
        for f in files:
            if f.get("dir") and f.get("file_name") == TEMP_DIR_NAME:
                return f["fid"]
        return self._create_folder(TEMP_DIR_NAME, DEFAULT_PDIR_FID)

    def _get_file_list(self, pdir_fid: str) -> list[dict[str, Any]]:
        """获取个人网盘文件列表。"""
        url = f"{FILE_URL}&pdir_fid={pdir_fid}&page=1&size=100"
        resp = self._request("GET", url, headers={"Cookie": self._cookie})
        data = self._parse_response(resp)
        return data.get("list", [])

    def _create_folder(self, name: str, parent_fid: str) -> str:
        """创建目录，返回新目录 fid。"""
        body = {
            "pdir_fid": parent_fid,
            "file_name": name,
            "dir_path": "",
            "dir_init_lock": False,
        }
        data = self._post_json(FILE_URL, body)
        fid = data.get("fid", "")
        if not fid:
            raise ParserError(f"创建目录失败: {name}")
        return fid

    def _save_share_file(
        self,
        share_id: str,
        stoken: str,
        pdir_fid: str,
        fid: str,
        fid_token: str,
        to_pdir_fid: str,
    ) -> str:
        """转存分享文件，返回异步任务 ID。"""
        body = {
            "pwd_id": share_id,
            "stoken": stoken,
            "pdir_fid": pdir_fid,
            "to_pdir_fid": to_pdir_fid,
            "fid_list": [fid],
            "fid_token_list": [fid_token],
            "scene": "link",
        }
        data = self._post_json(SAVE_URL, body)
        task_id = data.get("task_id", "")
        if not task_id:
            raise ParserError("转存失败：未返回任务 ID")
        return task_id

    def _poll_task(self, task_id: str, max_retries: int = 15) -> str:
        """轮询异步转存任务，返回转存后的新 fid。"""
        url = f"{TASK_URL}&task_id={quote(task_id)}&retry_index=0"
        for _ in range(max_retries):
            resp = self._request("GET", url, headers={"Cookie": self._cookie})
            try:
                result = resp.json()
            except ValueError:
                raise ParserError("任务轮询响应解析失败")
            if result.get("status") != 200:
                raise ParserError(
                    result.get("message", "转存任务查询失败")
                )
            data = result.get("data", {})
            finished = (
                data.get("finished_at", 0) > 0
                or data.get("status") == 2
                or data.get("task_status") == 2
            )
            if finished:
                save_as = data.get("save_as", {})
                fids = save_as.get("save_as_top_fids", [])
                if fids:
                    return fids[0]
            time.sleep(1)
        raise ParserError("转存超时，请稍后重试")

    def _get_download_link(self, fid: str) -> dict[str, Any]:
        """获取下载直链（接口 6.1）。"""
        body = {"fids": [fid]}
        resp = self._request(
            "POST",
            DOWNLOAD_URL,
            headers={"Cookie": self._cookie, "Content-Type": "application/json"},
            json_body=body,
        )
        try:
            result = resp.json()
        except ValueError:
            raise ParserError("下载链接响应解析失败")
        if result.get("status") != 200 and result.get("code") != 0:
            raise ParserError(
                result.get("message", "获取下载链接失败"),
                code=result.get("code"),
            )
        data_list = result.get("data", [])
        if not data_list:
            raise ParserError("未返回下载链接")
        return data_list[0]

    # ---------- HTTP 工具 ----------

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
            resp = self._session.request(
                method, url, headers=merged_headers, json=json_body, timeout=30
            )
            return resp
        except requests.RequestException as exc:
            raise NetworkError(f"夸克 API 请求失败: {exc}") from exc

    def _parse_response(self, resp: requests.Response) -> dict[str, Any]:
        """解析夸克 API 响应，校验 status 字段。"""
        try:
            result = resp.json()
        except ValueError as exc:
            raise ParserError(f"响应解析失败: {exc}") from exc
        if result.get("status") != 200:
            raise ParserError(
                result.get("message", "请求失败"), code=result.get("code")
            )
        data = result.get("data")
        if data is None:
            raise ParserError("响应缺少 data 字段")
        return data

    @staticmethod
    def _guess_file_type(file_name: str) -> str:
        """从文件名推断扩展名。"""
        if "." in file_name:
            return file_name.rsplit(".", 1)[-1].lower()
        return "unknown"
