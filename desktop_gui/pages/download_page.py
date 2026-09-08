"""
下载管理页标签页。

任务卡片式布局，每任务独立卡片，包含文件名、进度条、百分比、速度、
已下载/总大小、状态和操作按钮。顶部工具栏支持全部暂停/恢复/清除已完成。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from ..utils import format_size, format_speed
from ..widgets.download_task import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_DOWNLOADING,
    STATUS_ERROR,
    STATUS_PAUSED,
    STATUS_PENDING,
    DownloadTaskWidget,
)


class DownloadPage(ttk.Frame):
    """下载管理页标签页。

    管理所有下载任务，以卡片形式展示，支持批量操作。
    """

    def __init__(self, master: tk.Misc) -> None:
        """初始化下载管理页。

        Args:
            master: 父容器。
        """
        super().__init__(master, padding=12)
        self._tasks: list[DownloadTaskWidget] = []
        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # ---- 顶部工具栏 ----
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(toolbar, text="下载管理", font=("", 14, "bold")).pack(side=tk.LEFT)

        # 总速度
        self._total_speed_var = tk.StringVar(value="总速度：0 B/s")
        ttk.Label(
            toolbar, textvariable=self._total_speed_var,
            foreground="#1976D2", font=("", 10, "bold"),
        ).pack(side=tk.LEFT, padx=(20, 0))

        # 操作按钮
        btn_frame = ttk.Frame(toolbar)
        btn_frame.pack(side=tk.RIGHT)

        self._pause_all_btn = ttk.Button(
            btn_frame, text="全部暂停", command=self._pause_all
        )
        self._pause_all_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._resume_all_btn = ttk.Button(
            btn_frame, text="全部恢复", command=self._resume_all
        )
        self._resume_all_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._clear_completed_btn = ttk.Button(
            btn_frame, text="清除已完成", command=self._clear_completed
        )
        self._clear_completed_btn.pack(side=tk.LEFT)

        # ---- 任务列表（可滚动） ----
        list_container = ttk.Frame(self)
        list_container.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(list_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            list_container, orient=tk.VERTICAL, command=self._canvas.yview
        )
        self._scroll_frame = ttk.Frame(self._canvas)

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮支持
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind_all("<Button-4>", lambda e: self._canvas.yview_scroll(-1, "units"))
        self._canvas.bind_all("<Button-5>", lambda e: self._canvas.yview_scroll(1, "units"))

        # ---- 空状态 ----
        self._empty_frame = ttk.Frame(self._scroll_frame)
        self._empty_frame.pack(fill=tk.BOTH, expand=True, pady=60)

        ttk.Label(
            self._empty_frame,
            text="📥",
            font=("", 48),
        ).pack(pady=(0, 12))
        ttk.Label(
            self._empty_frame,
            text="暂无下载任务",
            font=("", 12),
            foreground="#888",
        ).pack()
        ttk.Label(
            self._empty_frame,
            text="在「解析」页解析分享链接后开始下载",
            font=("", 9),
            foreground="#AAA",
        ).pack(pady=(4, 0))

    def _on_mousewheel(self, event: tk.Event) -> None:
        """鼠标滚轮滚动。"""
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ==================================================================
    # 公共方法
    # ==================================================================

    def create_task(
        self,
        file_name: str,
        url: str,
        output_dir: str,
        chunk_size: int,
        concurrency: int,
        on_status_change: Any | None = None,
        on_remove: Any | None = None,
    ) -> DownloadTaskWidget:
        """创建并添加一个下载任务卡片。

        在卡片容器内创建任务组件，避免 tkinter reparent 问题。

        Args:
            file_name: 文件名。
            url: 下载直链。
            output_dir: 保存目录。
            chunk_size: 分片大小。
            concurrency: 并发数。
            on_status_change: 状态变化回调。
            on_remove: 任务移除回调。

        Returns:
            创建的 DownloadTaskWidget 实例。
        """
        # 隐藏空状态
        self._empty_frame.pack_forget()

        # 创建卡片容器
        card = ttk.Frame(self._scroll_frame, style="Card.TFrame", padding=8)
        card.pack(fill=tk.X, padx=2, pady=4)

        # 在卡片内创建任务组件
        task = DownloadTaskWidget(
            master=card,
            file_name=file_name,
            url=url,
            output_dir=output_dir,
            chunk_size=chunk_size,
            concurrency=concurrency,
            on_status_change=on_status_change,
            on_remove=on_remove,
        )
        task.pack(fill=tk.X)
        task._card_frame = card  # type: ignore[attr-defined]

        self._tasks.append(task)
        self._update_toolbar_state()
        return task

    def add_task(self, task: DownloadTaskWidget) -> None:
        """添加已创建的下载任务（兼容接口）。

        注意：task 应已创建在 _scroll_frame 中。此方法仅注册引用。
        推荐使用 create_task() 在卡片内创建任务。

        Args:
            task: DownloadTaskWidget 实例。
        """
        self._empty_frame.pack_forget()
        self._tasks.append(task)
        self._update_toolbar_state()

    def remove_task(self, task: DownloadTaskWidget) -> None:
        """移除下载任务。

        Args:
            task: 要移除的任务。
        """
        if task in self._tasks:
            self._tasks.remove(task)

        card = getattr(task, "_card_frame", None)
        if card is not None:
            card.destroy()
        else:
            task.destroy()

        if not self._tasks:
            self._empty_frame.pack(fill=tk.BOTH, expand=True, pady=60)

        self._update_toolbar_state()

    def get_tasks(self) -> list[DownloadTaskWidget]:
        """获取所有任务。"""
        return list(self._tasks)

    def update_total_speed(self, speed: float) -> None:
        """更新总速度显示。"""
        self._total_speed_var.set(f"总速度：{format_speed(speed)}")

    def pause_all(self) -> None:
        """暂停所有下载中的任务。"""
        for task in self._tasks:
            if task.status == STATUS_DOWNLOADING:
                task.pause()

    def resume_all(self) -> None:
        """恢复所有暂停的任务。"""
        for task in self._tasks:
            if task.status == STATUS_PAUSED:
                task.resume()

    def clear_completed(self) -> None:
        """清除所有已完成的任务。"""
        completed = [t for t in self._tasks if t.status == STATUS_COMPLETED]
        for task in completed:
            self.remove_task(task)

    # ==================================================================
    # 内部方法
    # ==================================================================

    def _pause_all(self) -> None:
        """全部暂停按钮。"""
        self.pause_all()

    def _resume_all(self) -> None:
        """全部恢复按钮。"""
        self.resume_all()

    def _clear_completed(self) -> None:
        """清除已完成按钮。"""
        self.clear_completed()

    def _update_toolbar_state(self) -> None:
        """根据任务状态更新工具栏按钮可用状态。"""
        has_downloading = any(t.status == STATUS_DOWNLOADING for t in self._tasks)
        has_paused = any(t.status == STATUS_PAUSED for t in self._tasks)
        has_completed = any(t.status == STATUS_COMPLETED for t in self._tasks)

        self._pause_all_btn.config(state=tk.NORMAL if has_downloading else tk.DISABLED)
        self._resume_all_btn.config(state=tk.NORMAL if has_paused else tk.DISABLED)
        self._clear_completed_btn.config(state=tk.NORMAL if has_completed else tk.DISABLED)
