"""
上传任务组件。

显示单个云盘上传任务的进度，包含文件名、目标网盘、进度条、
百分比、速度和状态。与 DownloadTaskWidget 风格一致。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..utils import format_size, format_speed, get_drive_display

# 上传状态常量
UPLOAD_STATUS_PENDING = "等待上传"
UPLOAD_STATUS_UPLOADING = "上传中"
UPLOAD_STATUS_COMPLETED = "已完成"
UPLOAD_STATUS_FAILED = "失败"


class UploadTaskWidget(ttk.Frame):
    """单个上传任务的 UI 组件。

    包含文件名、目标网盘、进度条、百分比、速度和状态。
    上传进度通过 :meth:`update_progress` 由外部更新。
    """

    def __init__(
        self,
        master: tk.Misc,
        file_path: str,
        drive: str,
        on_remove: Callable[["UploadTaskWidget"], None] | None = None,
    ) -> None:
        """初始化上传任务组件。

        Args:
            master: 父容器。
            file_path: 本地文件路径。
            drive: 目标网盘标识。
            on_remove: 移除回调 (widget)。
        """
        super().__init__(master, padding=4, relief=tk.GROOVE, borderwidth=1)

        self._file_path = file_path
        self._file_name = os.path.basename(file_path)
        self._drive = drive
        self._on_remove = on_remove
        self._status = UPLOAD_STATUS_PENDING
        self._total = os.path.getsize(file_path) if os.path.exists(file_path) else 0

        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # 第一行：文件名 + 网盘 + 状态 + 移除
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X)

        self._name_label = ttk.Label(
            row1, text=f"☁ {self._file_name}", font=("", 10, "bold"), anchor=tk.W
        )
        self._name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        drive_display = get_drive_display(self._drive)
        self._drive_label = ttk.Label(
            row1, text=f"→ {drive_display}", foreground="#1976D2", font=("", 9)
        )
        self._drive_label.pack(side=tk.LEFT, padx=(0, 8))

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
            row2, orient=tk.HORIZONTAL, mode="determinate", maximum=100,
            style="Download.Horizontal.TProgressbar",
        )
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self._percent_label = ttk.Label(row2, text="0.0%", width=7, anchor=tk.E)
        self._percent_label.pack(side=tk.RIGHT)

        # 第三行：速度 + 大小
        row3 = ttk.Frame(self)
        row3.pack(fill=tk.X)

        self._speed_label = ttk.Label(row3, text="0 B/s", foreground="#1565C0")
        self._speed_label.pack(side=tk.LEFT)

        self._size_label = ttk.Label(row3, text=f"0 B / {format_size(self._total)}", foreground="#666")
        self._size_label.pack(side=tk.LEFT, padx=(12, 0))

    @property
    def file_name(self) -> str:
        """文件名。"""
        return self._file_name

    @property
    def status(self) -> str:
        """当前状态。"""
        return self._status

    def update_progress(
        self, uploaded: int, total: int, speed: float, percent: float
    ) -> None:
        """更新上传进度。

        Args:
            uploaded: 已上传字节数。
            total: 总字节数。
            speed: 速度（字节/秒）。
            percent: 百分比。
        """
        self._progress["value"] = min(percent, 100.0)
        self._percent_label.config(text=f"{percent:.1f}%")
        self._speed_label.config(text=format_speed(speed))
        total_str = format_size(total) if total > 0 else format_size(self._total)
        self._size_label.config(text=f"{format_size(uploaded)} / {total_str}")

    def set_completed(self) -> None:
        """标记为上传完成。"""
        self._status = UPLOAD_STATUS_COMPLETED
        self._progress["value"] = 100
        self._percent_label.config(text="100.0%")
        self._status_label.config(text=UPLOAD_STATUS_COMPLETED, foreground="#2E7D32")
        self._speed_label.config(text="完成")
        self._progress.config(style="Completed.Horizontal.TProgressbar")

    def set_failed(self, message: str = "") -> None:
        """标记为上传失败。"""
        self._status = UPLOAD_STATUS_FAILED
        self._status_label.config(
            text=f"{UPLOAD_STATUS_FAILED}: {message[:20]}" if message else UPLOAD_STATUS_FAILED,
            foreground="#C62828",
        )
        self._progress.config(style="Error.Horizontal.TProgressbar")

    def _handle_remove(self) -> None:
        """处理移除按钮。"""
        if self._on_remove:
            self._on_remove(self)
