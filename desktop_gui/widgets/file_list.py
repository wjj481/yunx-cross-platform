"""
文件列表组件。

使用 ttk.Treeview 展示解析后的文件列表，支持多选下载。
列：文件名、大小、类型、状态。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from core.parsers.base import ShareInfo
from ..utils import format_size, get_drive_display, get_drive_color


class FileListWidget(ttk.LabelFrame):
    """文件列表区域组件。

    使用 Treeview 展示解析得到的文件信息，支持多选。
    每个 item 的 iid 对应文件索引，values 存储 ShareInfo。
    """

    def __init__(self, master: tk.Misc) -> None:
        """初始化文件列表组件。

        Args:
            master: 父容器。
        """
        super().__init__(master, text="文件列表", padding=6)
        self._share_infos: list[ShareInfo] = []
        self._drive: str = ""
        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # 网盘标识标签
        self._drive_frame = ttk.Frame(self)
        self._drive_frame.pack(fill=tk.X, pady=(0, 4))
        self._drive_label = ttk.Label(
            self._drive_frame, text="网盘：未识别", font=("", 10, "bold")
        )
        self._drive_label.pack(side=tk.LEFT)

        # Treeview + 滚动条
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("name", "size", "type", "status")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=8,
        )
        # 列定义
        self._tree.heading("name", text="文件名")
        self._tree.heading("size", text="大小")
        self._tree.heading("type", text="类型")
        self._tree.heading("status", text="状态")

        self._tree.column("name", width=380, anchor=tk.W)
        self._tree.column("size", width=100, anchor=tk.E)
        self._tree.column("type", width=80, anchor=tk.CENTER)
        self._tree.column("status", width=100, anchor=tk.CENTER)

        # 滚动条
        vsb = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self._tree.yview
        )
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 空状态提示
        self._empty_label = ttk.Label(
            self,
            text="暂无文件，请先解析分享链接",
            foreground="#999",
            justify=tk.CENTER,
        )
        # 初始显示空提示
        self._show_empty(True)

    def _show_empty(self, show: bool) -> None:
        """显示或隐藏空状态提示。"""
        if show:
            self._tree.pack_forget()
            self._empty_label.pack(fill=tk.BOTH, expand=True, pady=20)
        else:
            self._empty_label.pack_forget()
            # 重新 pack tree（已在 tree_frame 中 pack）
            pass

    # ---------- 公共方法 ----------

    def set_files(self, share_infos: list[ShareInfo], drive: str = "") -> None:
        """设置文件列表数据。

        Args:
            share_infos: 解析得到的 ShareInfo 列表。
            drive: 网盘标识，用于显示网盘名称。
        """
        self._share_infos = list(share_infos)
        self._drive = drive

        # 清空现有项
        for item in self._tree.get_children():
            self._tree.delete(item)

        if not self._share_infos:
            self._show_empty(True)
            self._drive_label.config(text="网盘：未识别")
            return

        self._show_empty(False)

        # 更新网盘标签
        if drive:
            color = get_drive_color(drive)
            name = get_drive_display(drive)
            self._drive_label.config(text=f"网盘：{name}", foreground=color)
        else:
            self._drive_label.config(text="网盘：未识别", foreground="#333")

        # 插入文件项
        for idx, info in enumerate(self._share_infos):
            size_str = format_size(info.file_size) if info.file_size > 0 else "未知"
            type_str = info.file_type or "未知"
            self._tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(info.file_name, size_str, type_str, "待下载"),
            )

    def get_selected_files(self) -> list[ShareInfo]:
        """获取用户选中的文件列表。

        Returns:
            选中的 ShareInfo 列表。
        """
        selected = self._tree.selection()
        result = []
        for iid in selected:
            idx = int(iid)
            if 0 <= idx < len(self._share_infos):
                result.append(self._share_infos[idx])
        return result

    def get_all_files(self) -> list[ShareInfo]:
        """获取所有文件列表。

        Returns:
            全部 ShareInfo 列表。
        """
        return list(self._share_infos)

    def set_item_status(self, index: int, status: str) -> None:
        """更新指定文件项的状态列。

        Args:
            index: 文件索引。
            status: 状态文本。
        """
        iid = str(index)
        if self._tree.exists(iid):
            values = list(self._tree.item(iid, "values"))
            if len(values) >= 4:
                values[3] = status
                self._tree.item(iid, values=values)

    def clear(self) -> None:
        """清空文件列表。"""
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._share_infos = []
        self._drive = ""
        self._drive_label.config(text="网盘：未识别", foreground="#333")
        self._show_empty(True)

    @property
    def drive(self) -> str:
        """当前网盘标识。"""
        return self._drive
