"""
网盘上传器包。

提供各网盘的文件上传能力，统一通过 :func:`core.uploader.base.get_uploader`
工厂函数获取上传器，配合 :class:`core.uploader.engine.UploadEngine` 实现
分片并发上传 + 断点续传 + 进度回调。

支持的网盘：
- 夸克网盘（quark）
- 123 云盘（pan123）
- 百度网盘（baidu，实验性，含风控警告）
- 迅雷网盘（xunlei）

免责声明：本模块仅供个人学习技术交流，请勿用于商业用途或违反各网盘用户协议。
"""

from .base import (
    BaseUploader,
    DirInfo,
    ShareInfo,
    UploadProgressCallback,
    UploadResult,
    UploadTask,
    get_uploader,
    list_supported_upload_drives,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_PENDING,
    STATUS_UPLOADING,
)
from .engine import (
    UploadChunkInfo,
    UploadEngine,
    UploadMetadata,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CONCURRENCY,
    MAX_CONCURRENCY,
    MAX_RETRIES,
)
from .quark_uploader import QuarkUploader
from .pan123_uploader import Pan123Uploader
from .baidu_uploader import BaiduUploader
from .xunlei_uploader import XunleiUploader

__all__ = [
    # 基类与工厂
    "BaseUploader",
    "get_uploader",
    "list_supported_upload_drives",
    # 数据类
    "UploadTask",
    "UploadResult",
    "DirInfo",
    "ShareInfo",
    "UploadProgressCallback",
    # 状态常量
    "STATUS_PENDING",
    "STATUS_UPLOADING",
    "STATUS_PAUSED",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_CANCELLED",
    # 上传引擎
    "UploadEngine",
    "UploadMetadata",
    "UploadChunkInfo",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CONCURRENCY",
    "MAX_CONCURRENCY",
    "MAX_RETRIES",
    # 各网盘上传器
    "QuarkUploader",
    "Pan123Uploader",
    "BaiduUploader",
    "XunleiUploader",
]
