"""
状态栏组件。

显示当前状态、总下载速度、版本信息。
位于主窗口底部。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import __version__
from ..utils import format_speed


class StatusBarWidget(ttk.Frame):
    """底部状态栏组件。

    左侧显示当前状态文本，中间显示总下载速度，右侧显示版本信息。
    """

    def __init__(self, master: tk.Misc) -> None:
        """初始化状态栏。

        Args:
            master: 父容器。
        """
        super().__init__(master, relief=tk.SUNKEN, borderwidth=1)
        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # 左侧：状态
        self._status_var = tk.StringVar(value="就绪")
        self._status_label = ttk.Label(
            self, textvariable=self._status_var, anchor=tk.W, padding=(8, 2)
        )
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 中间：总下载速度
        self._speed_var = tk.StringVar(value="总速度：0 B/s")
        self._speed_label = ttk.Label(
            self, textvariable=self._speed_var, anchor=tk.CENTER, padding=(8, 2)
        )
        self._speed_label.pack(side=tk.LEFT)

        # 分隔线
        ttk.Separator(self, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=4
        )

        # 右侧：版本
        self._version_label = ttk.Label(
            self, text=f"YunX v{__version__}", anchor=tk.E, padding=(8, 2)
        )
        self._version_label.pack(side=tk.RIGHT)

    def set_status(self, text: str) -> None:
        """设置状态栏文本。

        Args:
            text: 状态文本。
        """
        self._status_var.set(text)

    def set_total_speed(self, speed_bytes_per_sec: float) -> None:
        """设置总下载速度显示。

        Args:
            speed_bytes_per_sec: 总速度（字节/秒）。
        """
        self._speed_var.set(f"总速度：{format_speed(speed_bytes_per_sec)}")
