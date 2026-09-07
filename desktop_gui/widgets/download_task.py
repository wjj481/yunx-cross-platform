"""
单个下载任务组件。

每个下载任务对应一个 DownloadEngine 实例，在子线程中运行阻塞下载。
通过 root.after() 将进度更新调度到主线程。
支持暂停、恢复、取消操作。
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from core.downloader.engine import DownloadEngine
from core.downloader.progress import DownloadProgress
from core.exceptions import DownloadError, NetworkError, YunXError
from ..utils import format_size, format_speed

# 任务状态常量
STATUS_PENDING = "等待中"
STATUS_DOWNLOADING = "下载中"
STATUS_PAUSED = "已暂停"
STATUS_COMPLETED = "已完成"
STATUS_ERROR = "错误"
STATUS_CANCELLED = "已取消"

# 进度条样式映射（状态 → 样式名）
_PROGRESS_STYLES = {
    STATUS_DOWNLOADING: "Download.Horizontal.TProgressbar",
    STATUS_PAUSED: "Paused.Horizontal.TProgressbar",
    STATUS_COMPLETED: "Completed.Horizontal.TProgressbar",
    STATUS_ERROR: "Error.Horizontal.TProgressbar",
}


class DownloadTaskWidget(ttk.Frame):
    """单个下载任务的 UI 组件。

    包含文件名、进度条、百分比、速度、已下载/总大小、状态和控制按钮。
    下载在子线程中执行，进度通过队列 + root.after 回主线程更新。
    """

    def __init__(
        self,
        master: tk.Misc,
        file_name: str,
        url: str,
        output_dir: str,
        chunk_size: int,
        concurrency: int,
        on_status_change: Callable[["DownloadTaskWidget", str], None] | None = None,
        on_remove: Callable[["DownloadTaskWidget"], None] | None = None,
    ) -> None:
        """初始化下载任务组件。

        Args:
            master: 父容器。
            file_name: 文件名。
            url: 下载直链。
            output_dir: 保存目录。
            chunk_size: 分片大小（字节）。
            concurrency: 并发数（1-32）。
            on_status_change: 状态变化回调 (widget, new_status)。
            on_remove: 任务移除回调 (widget)。
        """
        super().__init__(master, padding=4, relief=tk.GROOVE, borderwidth=1)

        self._file_name = file_name
        self._url = url
        self._output_dir = output_dir
        self._chunk_size = chunk_size
        self._concurrency = concurrency
        self._on_status_change = on_status_change
        self._on_remove = on_remove

        # 状态
        self._status = STATUS_PENDING
        self._downloaded = 0
        self._total = 0
        self._speed = 0.0
        self._percent = 0.0

        # 下载引擎与线程
        self._engine: DownloadEngine | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # 进度更新节流：子线程写入，主线程读取
        self._pending_progress: DownloadProgress | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # 第一行：文件名 + 状态 + 移除按钮
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X)

        self._name_label = ttk.Label(
            row1, text=self._file_name, font=("", 10, "bold"), anchor=tk.W
        )
        self._name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._status_label = ttk.Label(row1, text=self._status, foreground="#666")
        self._status_label.pack(side=tk.LEFT, padx=(0, 8))

        self._remove_btn = ttk.Button(
            row1, text="×", width=3, command=self._handle_remove
        )
        self._remove_btn.pack(side=tk.RIGHT)

        # 第二行：进度条 + 百分比
        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X, pady=(4, 2))

        self._progress = ttk.Progressbar(
            row2, orient=tk.HORIZONTAL, mode="determinate", maximum=100
        )
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self._percent_label = ttk.Label(row2, text="0.0%", width=7, anchor=tk.E)
        self._percent_label.pack(side=tk.RIGHT)

        # 第三行：速度 + 已下载/总大小 + 控制按钮
        row3 = ttk.Frame(self)
        row3.pack(fill=tk.X)

        self._speed_label = ttk.Label(row3, text="0 B/s", foreground="#1565C0")
        self._speed_label.pack(side=tk.LEFT)

        self._size_label = ttk.Label(row3, text="0 B / 0 B", foreground="#666")
        self._size_label.pack(side=tk.LEFT, padx=(12, 0))

        # 控制按钮
        btn_frame = ttk.Frame(row3)
        btn_frame.pack(side=tk.RIGHT)

        self._pause_btn = ttk.Button(
            btn_frame, text="暂停", command=self._handle_pause, state=tk.DISABLED
        )
        self._pause_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._resume_btn = ttk.Button(
            btn_frame, text="恢复", command=self._handle_resume, state=tk.DISABLED
        )
        self._resume_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._cancel_btn = ttk.Button(
            btn_frame, text="取消", command=self._handle_cancel, state=tk.DISABLED
        )
        self._cancel_btn.pack(side=tk.LEFT)

    # ---------- 公共方法 ----------

    def start(self) -> None:
        """启动下载任务（在子线程中运行）。"""
        if self._status in (STATUS_DOWNLOADING, STATUS_COMPLETED):
            return

        self._engine = DownloadEngine(
            concurrency=self._concurrency,
            chunk_size=self._chunk_size,
        )

        output_path = os.path.join(self._output_dir, self._file_name)

        self._thread = threading.Thread(
            target=self._download_worker,
            args=(self._engine, self._url, output_path),
            daemon=True,
        )
        self._set_status(STATUS_DOWNLOADING)
        self._thread.start()

        # 启动 UI 轮询
        self._schedule_ui_update()

    def pause(self) -> None:
        """暂停下载。"""
        if self._engine and self._status == STATUS_DOWNLOADING:
            self._engine.pause()
            self._set_status(STATUS_PAUSED)

    def resume(self) -> None:
        """恢复下载。"""
        if self._engine and self._status == STATUS_PAUSED:
            self._engine.resume()
            self._set_status(STATUS_DOWNLOADING)

    def cancel(self) -> None:
        """取消下载。"""
        if self._engine and self._status in (STATUS_DOWNLOADING, STATUS_PAUSED):
            self._engine.cancel()

    @property
    def status(self) -> str:
        """当前任务状态。"""
        return self._status

    @property
    def speed(self) -> float:
        """当前下载速度（字节/秒）。"""
        return self._speed if self._status == STATUS_DOWNLOADING else 0.0

    @property
    def file_name(self) -> str:
        """文件名。"""
        return self._file_name

    # ---------- 内部方法 ----------

    def _download_worker(
        self, engine: DownloadEngine, url: str, output_path: str
    ) -> None:
        """下载工作线程函数。

        Args:
            engine: 下载引擎实例。
            url: 下载 URL。
            output_path: 输出文件路径。
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            engine.download(
                url=url,
                output_path=output_path,
                progress_callback=self._progress_callback,
            )
            # 下载完成
            self._set_status_async(STATUS_COMPLETED)
        except DownloadError as exc:
            if "已取消" in str(exc):
                self._set_status_async(STATUS_CANCELLED)
            else:
                self._set_status_async(STATUS_ERROR, str(exc))
        except NetworkError as exc:
            self._set_status_async(STATUS_ERROR, f"网络错误: {exc}")
        except YunXError as exc:
            self._set_status_async(STATUS_ERROR, str(exc))
        except Exception as exc:
            self._set_status_async(STATUS_ERROR, f"未知错误: {exc}")

    def _progress_callback(self, progress: DownloadProgress) -> None:
        """下载引擎的进度回调（在下载线程中调用）。

        将进度快照保存，由主线程轮询读取并更新 UI。

        Args:
            progress: 下载进度快照。
        """
        with self._lock:
            self._pending_progress = progress

    def _schedule_ui_update(self) -> None:
        """调度下一次 UI 更新（100ms 间隔）。"""
        if self._status in (STATUS_COMPLETED, STATUS_ERROR, STATUS_CANCELLED):
            # 最终状态，做一次最终更新后停止轮询
            self._update_ui()
            return
        self.after(100, self._update_ui)

    def _update_ui(self) -> None:
        """从 pending_progress 读取并更新 UI（主线程）。"""
        with self._lock:
            progress = self._pending_progress
            self._pending_progress = None

        if progress is not None:
            self._downloaded = progress.downloaded_bytes
            self._total = progress.total_bytes
            self._speed = progress.speed
            self._percent = progress.percent

            self._progress["value"] = self._percent
            self._percent_label.config(text=f"{self._percent:.1f}%")
            self._speed_label.config(text=format_speed(self._speed))
            total_str = format_size(self._total) if self._total > 0 else "未知"
            self._size_label.config(
                text=f"{format_size(self._downloaded)} / {total_str}"
            )

        # 根据状态更新按钮和进度条样式
        self._update_controls()

        # 继续轮询
        if self._status in (STATUS_DOWNLOADING, STATUS_PAUSED, STATUS_PENDING):
            self._schedule_ui_update()

    def _update_controls(self) -> None:
        """根据当前状态更新控制按钮的可用状态。"""
        if self._status == STATUS_DOWNLOADING:
            self._pause_btn.config(state=tk.NORMAL)
            self._resume_btn.config(state=tk.DISABLED)
            self._cancel_btn.config(state=tk.NORMAL)
            self._status_label.config(text=STATUS_DOWNLOADING, foreground="#1565C0")
        elif self._status == STATUS_PAUSED:
            self._pause_btn.config(state=tk.DISABLED)
            self._resume_btn.config(state=tk.NORMAL)
            self._cancel_btn.config(state=tk.NORMAL)
            self._status_label.config(text=STATUS_PAUSED, foreground="#F9A825")
            self._speed_label.config(text="已暂停")
        elif self._status == STATUS_COMPLETED:
            self._pause_btn.config(state=tk.DISABLED)
            self._resume_btn.config(state=tk.DISABLED)
            self._cancel_btn.config(state=tk.DISABLED)
            self._status_label.config(text=STATUS_COMPLETED, foreground="#2E7D32")
            self._speed_label.config(text="完成")
            self._progress["value"] = 100
            self._percent_label.config(text="100.0%")
        elif self._status in (STATUS_ERROR, STATUS_CANCELLED):
            self._pause_btn.config(state=tk.DISABLED)
            self._resume_btn.config(state=tk.DISABLED)
            self._cancel_btn.config(state=tk.DISABLED)
            color = "#C62828" if self._status == STATUS_ERROR else "#666"
            self._status_label.config(text=self._status, foreground=color)
            self._speed_label.config(text="—")

    def _set_status(self, status: str, message: str = "") -> None:
        """设置任务状态（主线程调用）。"""
        self._status = status
        if message:
            self._status_label.config(text=f"{status}: {message[:30]}")
        self._update_controls()
        if self._on_status_change:
            self._on_status_change(self, status)

    def _set_status_async(self, status: str, message: str = "") -> None:
        """从子线程安全地设置状态（通过 after 调度到主线程）。"""
        self.after(0, lambda: self._set_status(status, message))

    # ---------- 按钮事件 ----------

    def _handle_pause(self) -> None:
        """处理暂停按钮。"""
        self.pause()

    def _handle_resume(self) -> None:
        """处理恢复按钮。"""
        self.resume()

    def _handle_cancel(self) -> None:
        """处理取消按钮。"""
        self.cancel()

    def _handle_remove(self) -> None:
        """处理移除按钮：先取消下载，再通知父容器移除。"""
        self.cancel()
        if self._on_remove:
            # 延迟移除，给取消操作一点时间
            self.after(200, lambda: self._on_remove(self))
