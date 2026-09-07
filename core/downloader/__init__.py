"""
下载引擎包。

提供 Range 分片并发下载 + 断点续传能力。
"""

from .engine import DownloadEngine, DownloadMetadata, ChunkInfo
from .progress import DownloadProgress, ProgressTracker, ProgressCallback

__all__ = [
    "DownloadEngine",
    "DownloadMetadata",
    "ChunkInfo",
    "DownloadProgress",
    "ProgressTracker",
    "ProgressCallback",
]
