"""
下载进度追踪。

提供线程安全的进度统计，供下载引擎和 UI 层共同使用。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class DownloadProgress:
    """下载进度快照。"""

    downloaded_bytes: int
    """已下载字节数。"""
    total_bytes: int
    """总字节数（未知时为 0）。"""
    speed: float
    """当前下载速度（字节/秒）。"""
    percent: float
    """完成百分比（0.0 - 100.0）。"""


ProgressCallback = Callable[[DownloadProgress], None]
"""进度回调函数类型。"""


class ProgressTracker:
    """线程安全的下载进度追踪器。

    使用滑动窗口计算实时速度（默认 3 秒窗口）。
    """

    def __init__(
        self,
        total_bytes: int = 0,
        callback: ProgressCallback | None = None,
        speed_window: float = 3.0,
    ) -> None:
        """初始化进度追踪器。

        Args:
            total_bytes: 文件总大小（字节）。
            callback: 进度更新回调函数。
            speed_window: 速度计算滑动窗口（秒）。
        """
        self._total = total_bytes
        self._downloaded = 0
        self._callback = callback
        self._speed_window = speed_window
        self._lock = threading.Lock()
        # 速度采样：(timestamp, bytes_delta) 列表
        self._samples: list[tuple[float, int]] = []
        self._start_time = time.monotonic()
        self._paused = False
        self._pause_start: float | None = None
        self._paused_duration = 0.0

    def update(self, bytes_delta: int) -> None:
        """记录新下载的字节数。

        Args:
            bytes_delta: 本次新增的字节数。
        """
        with self._lock:
            self._downloaded += bytes_delta
            now = time.monotonic()
            self._samples.append((now, bytes_delta))
            self._prune_samples(now)
            self._notify()

    def set_total(self, total_bytes: int) -> None:
        """设置文件总大小。"""
        with self._lock:
            self._total = total_bytes
            self._notify()

    def set_downloaded(self, downloaded: int) -> None:
        """设置已下载字节数（用于断点续传恢复）。"""
        with self._lock:
            self._downloaded = downloaded
            self._notify()

    def pause(self) -> None:
        """暂停计时（速度计算会排除暂停时长）。"""
        with self._lock:
            if not self._paused:
                self._paused = True
                self._pause_start = time.monotonic()

    def resume(self) -> None:
        """恢复计时。"""
        with self._lock:
            if self._paused and self._pause_start is not None:
                self._paused_duration += time.monotonic() - self._pause_start
                self._paused = False
                self._pause_start = None

    def snapshot(self) -> DownloadProgress:
        """获取当前进度快照。"""
        with self._lock:
            speed = self._calc_speed()
            percent = (
                (self._downloaded / self._total * 100.0) if self._total > 0 else 0.0
            )
            return DownloadProgress(
                downloaded_bytes=self._downloaded,
                total_bytes=self._total,
                speed=speed,
                percent=min(percent, 100.0),
            )

    # ---------- 内部方法 ----------

    def _prune_samples(self, now: float) -> None:
        """清理窗口外的采样点。"""
        cutoff = now - self._speed_window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.pop(0)

    def _calc_speed(self) -> float:
        """计算滑动窗口内的平均速度。"""
        if not self._samples:
            return 0.0
        now = time.monotonic()
        cutoff = now - self._speed_window
        recent = [(t, b) for t, b in self._samples if t >= cutoff]
        if not recent:
            return 0.0
        total_bytes = sum(b for _, b in recent)
        time_span = recent[-1][0] - recent[0][0]
        if time_span <= 0:
            return float(total_bytes)
        return total_bytes / time_span

    def _notify(self) -> None:
        """触发进度回调（调用方已持有锁）。"""
        if self._callback is None:
            return
        speed = self._calc_speed()
        percent = (
            (self._downloaded / self._total * 100.0) if self._total > 0 else 0.0
        )
        self._callback(
            DownloadProgress(
                downloaded_bytes=self._downloaded,
                total_bytes=self._total,
                speed=speed,
                percent=min(percent, 100.0),
            )
        )
