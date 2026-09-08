"""
网盘上传器基类与工厂函数。

所有网盘上传器继承 :class:`BaseUploader`，实现统一的上传接口。
工厂函数 :func:`get_uploader` 根据网盘标识自动匹配对应上传器。

免责声明：本模块仅供个人学习技术交流，请勿用于商业用途或违反各网盘用户协议。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from ..exceptions import UploadError

# 上传状态常量
STATUS_PENDING = "pending"
"""等待上传。"""
STATUS_UPLOADING = "uploading"
"""上传中。"""
STATUS_PAUSED = "paused"
"""已暂停。"""
STATUS_COMPLETED = "completed"
"""上传完成。"""
STATUS_FAILED = "failed"
"""上传失败。"""
STATUS_CANCELLED = "cancelled"
"""已取消。"""


@dataclass
class UploadTask:
    """上传任务数据类。

    Attributes:
        file_path: 本地文件路径。
        remote_path: 远程目标路径（目录 + 文件名）。
        total_bytes: 文件总大小（字节）。
        uploaded_bytes: 已上传字节数。
        speed: 当前上传速度（字节/秒）。
        status: 上传状态（pending / uploading / paused / completed / failed / cancelled）。
    """

    file_path: str
    remote_path: str
    total_bytes: int = 0
    uploaded_bytes: int = 0
    speed: float = 0.0
    status: str = STATUS_PENDING


@dataclass
class UploadResult:
    """上传结果。

    Attributes:
        file_id: 服务端返回的文件 ID。
        file_name: 文件名。
        file_size: 文件大小（字节）。
        remote_path: 远程路径。
        drive: 网盘标识。
        raw_response: 服务端原始响应（供调试和扩展使用）。
    """

    file_id: str
    file_name: str
    file_size: int
    remote_path: str
    drive: str
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class DirInfo:
    """远程目录信息。

    Attributes:
        dir_id: 目录 ID。
        dir_name: 目录名称。
        parent_id: 父目录 ID（根目录为空字符串）。
        is_dir: 是否为目录（始终为 True）。
    """

    dir_id: str
    dir_name: str
    parent_id: str = ""
    is_dir: bool = True


@dataclass
class ShareInfo:
    """分享链接信息。

    Attributes:
        share_url: 分享链接。
        share_id: 分享 ID。
        extract_code: 提取码（无提取码时为空字符串）。
        expires_at: 过期时间描述（如 "永久有效"、"7天"）；未知时为 None。
        drive: 网盘标识。
    """

    share_url: str
    share_id: str = ""
    extract_code: str = ""
    expires_at: str | None = None
    drive: str = ""


# 进度回调类型：接收 (uploaded_bytes, total_bytes, speed, percent)
UploadProgressCallback = Callable[[int, int, float, float], None]


class BaseUploader(ABC):
    """网盘上传器抽象基类。

    子类必须声明 :attr:`drive_name` 并实现上传相关的抽象方法。

    上传流程通用步骤：
    1. :meth:`init_upload` — 获取上传凭证 / 预创建文件
    2. :meth:`upload_chunk` — 上传单个分片（由引擎并发调用）
    3. :meth:`complete_upload` — 合并分片 / 确认完成
    """

    #: 网盘标识（如 ``"quark"``、``"pan123"``）。
    drive_name: str = ""

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        """初始化上传器。

        Args:
            credential: 登录凭证字典（Cookie / Token 等），由上层从配置管理器传入。
        """
        self.credential = credential or {}

    # ---------- 抽象方法 ----------

    @abstractmethod
    def init_upload(
        self, file_path: str, remote_dir: str, file_name: str, file_size: int
    ) -> dict[str, Any]:
        """初始化上传，获取上传凭证。

        Args:
            file_path: 本地文件路径。
            remote_dir: 远程目标目录 ID 或路径。
            file_name: 文件名。
            file_size: 文件大小（字节）。

        Returns:
            上传上下文字典，包含后续上传所需的凭证信息（如 upload_id、upload_url 等）。
            具体字段由各网盘实现定义。

        Raises:
            AuthenticationError: 凭证失效。
            QuotaExceededError: 空间不足。
            UploadError: 初始化失败。
        """

    @abstractmethod
    def upload_chunk(
        self,
        context: dict[str, Any],
        chunk_index: int,
        chunk_data: bytes,
        total_chunks: int,
    ) -> dict[str, Any]:
        """上传单个分片。

        Args:
            context: :meth:`init_upload` 返回的上传上下文。
            chunk_index: 分片序号（从 0 开始）。
            chunk_data: 分片二进制数据。
            total_chunks: 总分片数。

        Returns:
            分片上传结果（如 etag、part_number 等），用于最终合并。

        Raises:
            UploadError: 分片上传失败。
        """

    @abstractmethod
    def complete_upload(
        self, context: dict[str, Any], chunk_results: list[dict[str, Any]]
    ) -> UploadResult:
        """完成上传，合并分片。

        Args:
            context: :meth:`init_upload` 返回的上传上下文。
            chunk_results: 所有分片的上传结果列表（按分片序号排序）。

        Returns:
            上传结果 :class:`UploadResult`。

        Raises:
            UploadError: 合并失败。
        """

    # ---------- 可选方法 ----------

    def get_remote_dirs(self, parent_dir: str | None = None) -> list[DirInfo]:
        """获取远程目录列表（用于选择上传目录）。

        Args:
            parent_dir: 父目录 ID；为 None 时获取根目录下的目录列表。

        Returns:
            目录信息列表。

        Raises:
            UploadError: 获取目录列表失败。
        """
        raise UploadError(f"{self.drive_name} 暂不支持获取远程目录列表")

    def create_share_link(self, file_id: str) -> ShareInfo:
        """为已上传的文件生成分享链接。

        Args:
            file_id: 文件 ID（来自 :class:`UploadResult.file_id`）。

        Returns:
            分享链接信息 :class:`ShareInfo`。

        Raises:
            UploadError: 生成分享链接失败。
        """
        raise UploadError(f"{self.drive_name} 暂不支持生成分享链接")

    def supports_chunked_upload(self) -> bool:
        """是否支持分片上传。默认支持，子类可覆盖。"""
        return True


# ---------- 工厂函数 ----------

def _get_all_uploaders() -> list[type[BaseUploader]]:
    """延迟导入所有上传器，避免循环依赖。"""
    from .quark_uploader import QuarkUploader
    from .pan123_uploader import Pan123Uploader
    from .baidu_uploader import BaiduUploader
    from .xunlei_uploader import XunleiUploader

    return [QuarkUploader, Pan123Uploader, BaiduUploader, XunleiUploader]


def get_uploader(
    drive_name: str, credential: dict[str, Any] | None = None
) -> BaseUploader:
    """根据网盘标识获取并实例化上传器。

    Args:
        drive_name: 网盘标识（如 ``"quark"``、``"pan123"``、``"baidu"``、``"xunlei"``）。
        credential: 可选的登录凭证。

    Returns:
        匹配到的上传器实例。

    Raises:
        UploadError: 不支持的网盘标识。
    """
    normalized = drive_name.lower().strip()
    for uploader_cls in _get_all_uploaders():
        if uploader_cls.drive_name == normalized:
            return uploader_cls(credential=credential)
    supported = ", ".join(cls.drive_name for cls in _get_all_uploaders())
    raise UploadError(f"不支持的网盘标识: {drive_name}（支持: {supported}）")


def list_supported_upload_drives() -> list[dict[str, Any]]:
    """列出所有支持上传的网盘及其状态。

    Returns:
        列表，每项包含 ``drive``、``status``。
    """
    result = []
    for uploader_cls in _get_all_uploaders():
        status = getattr(uploader_cls, "status", "stable")
        result.append({"drive": uploader_cls.drive_name, "status": status})
    return result
