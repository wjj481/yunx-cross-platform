"""
解析页标签页。

包含大 URL 输入框（支持拖拽）、提取码输入、解析按钮、剪贴板识别提示条、
文件列表（Treeview 多选）和下载操作栏。
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Callable

from core.clipboard import detect_share_url
from core.parsers.base import ShareInfo

from ..dialogs.settings import (
    CHUNK_SIZE_OPTIONS,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CONCURRENCY,
    DEFAULT_SAVE_PATH,
)
from ..utils import format_size, get_drive_display, get_drive_color, needs_risk_warning
from ..widgets.file_list import FileListWidget


class ParsePage(ttk.Frame):
    """解析页标签页。

    Signals:
        on_parse(url, extract_code): 用户点击解析按钮时触发。
        on_download(share_infos, save_path, concurrency, chunk_size): 启动下载时触发。
    """

    def __init__(
        self,
        master: tk.Misc,
        on_parse: Callable[[str, str | None], None],
        on_download: Callable[[list[ShareInfo], str, int, int], None],
    ) -> None:
        """初始化解析页。

        Args:
            master: 父容器。
            on_parse: 解析回调。
            on_download: 下载回调。
        """
        super().__init__(master, padding=12)
        self._on_parse = on_parse
        self._on_download = on_download

        # 当前设置
        self._save_path = DEFAULT_SAVE_PATH
        self._concurrency = DEFAULT_CONCURRENCY
        self._chunk_size = DEFAULT_CHUNK_SIZE

        # 剪贴板提示
        self._clipboard_hint_url = ""

        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # ---- URL 输入区 ----
        url_frame = ttk.LabelFrame(self, text="分享链接", padding=10)
        url_frame.pack(fill=tk.X, pady=(0, 10))

        # 大输入框（3行 Text 组件）
        self._url_text = tk.Text(
            url_frame,
            height=3,
            wrap=tk.WORD,
            font=("", 11),
            relief=tk.SOLID,
            borderwidth=1,
            padx=8,
            pady=6,
        )
        self._url_text.pack(fill=tk.X, pady=(0, 6))
        self._url_text.bind("<Return>", lambda _e: self._handle_parse())
        # 支持拖拽（在支持的平台上）
        self._setup_drag_drop()

        # 剪贴板提示条（默认隐藏）
        self._clipboard_hint_frame = ttk.Frame(url_frame)
        self._clipboard_hint_label = ttk.Label(
            self._clipboard_hint_frame,
            text="",
            foreground="#1976D2",
            cursor="hand2",
            font=("", 9),
        )
        self._clipboard_hint_label.pack(side=tk.LEFT)
        self._clipboard_hint_label.bind(
            "<Button-1>", lambda _e: self._apply_clipboard_url()
        )

        # 第二行：提取码 + 按钮
        row2 = ttk.Frame(url_frame)
        row2.pack(fill=tk.X)

        ttk.Label(row2, text="提取码：").pack(side=tk.LEFT)
        self._code_var = tk.StringVar()
        self._code_entry = ttk.Entry(row2, textvariable=self._code_var, width=14)
        self._code_entry.pack(side=tk.LEFT, padx=(4, 12))
        self._code_entry.bind("<Return>", lambda _e: self._handle_parse())

        ttk.Label(
            row2, text="（可选，自动识别时预填）", foreground="#888", font=("", 9)
        ).pack(side=tk.LEFT)

        self._clipboard_btn = ttk.Button(
            row2, text="从剪贴板粘贴", command=self._handle_clipboard
        )
        self._clipboard_btn.pack(side=tk.LEFT, padx=(12, 0))

        self._parse_btn = ttk.Button(
            row2, text="🔍 解析", style="Primary.TButton", command=self._handle_parse
        )
        self._parse_btn.pack(side=tk.RIGHT)

        # ---- 文件列表区 ----
        self._file_list = FileListWidget(self)
        self._file_list.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # ---- 下载操作栏 ----
        dl_frame = ttk.LabelFrame(self, text="下载操作", padding=10)
        dl_frame.pack(fill=tk.X)

        # 第一行：下载按钮
        btn_row = ttk.Frame(dl_frame)
        btn_row.pack(fill=tk.X, pady=(0, 8))

        self._download_selected_btn = ttk.Button(
            btn_row, text="下载选中", style="Primary.TButton",
            command=self._on_download_selected,
        )
        self._download_selected_btn.pack(side=tk.LEFT)

        self._download_all_btn = ttk.Button(
            btn_row, text="全部下载", command=self._on_download_all
        )
        self._download_all_btn.pack(side=tk.LEFT, padx=(8, 0))

        # 全选/反选
        self._select_all_btn = ttk.Button(
            btn_row, text="全选", command=self._select_all
        )
        self._select_all_btn.pack(side=tk.LEFT, padx=(8, 0))

        self._invert_btn = ttk.Button(
            btn_row, text="反选", command=self._invert_selection
        )
        self._invert_btn.pack(side=tk.LEFT, padx=(4, 0))

        # 第二行：保存路径
        path_row = ttk.Frame(dl_frame)
        path_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(path_row, text="保存到：").pack(side=tk.LEFT)
        self._save_path_var = tk.StringVar(value=self._save_path)
        ttk.Entry(path_row, textvariable=self._save_path_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6)
        )
        ttk.Button(path_row, text="浏览...", width=8, command=self._browse_save_path).pack(
            side=tk.LEFT
        )

        # 第三行：并发数 + 分片大小
        opt_row = ttk.Frame(dl_frame)
        opt_row.pack(fill=tk.X)

        ttk.Label(opt_row, text="并发数：").pack(side=tk.LEFT)
        self._concurrency_var = tk.IntVar(value=self._concurrency)
        self._concurrency_scale = ttk.Scale(
            opt_row,
            from_=1,
            to=32,
            orient=tk.HORIZONTAL,
            variable=self._concurrency_var,
            length=140,
            command=self._on_concurrency_change,
        )
        self._concurrency_scale.pack(side=tk.LEFT)
        self._concurrency_label = ttk.Label(
            opt_row, text=f"{self._concurrency}", width=4, font=("", 10, "bold")
        )
        self._concurrency_label.pack(side=tk.LEFT, padx=(4, 16))

        ttk.Label(opt_row, text="分片大小：").pack(side=tk.LEFT)
        self._chunk_var = tk.StringVar()
        self._chunk_combo = ttk.Combobox(
            opt_row,
            textvariable=self._chunk_var,
            values=list(CHUNK_SIZE_OPTIONS.keys()),
            state="readonly",
            width=8,
        )
        for name, size in CHUNK_SIZE_OPTIONS.items():
            if size == self._chunk_size:
                self._chunk_var.set(name)
                break
        self._chunk_combo.pack(side=tk.LEFT, padx=(4, 0))

    def _setup_drag_drop(self) -> None:
        """设置拖拽支持（tkinter 原生不支持，通过 Tk DND 扩展尝试）。"""
        try:
            # 尝试使用 tkinterdnd2（如果已安装）
            self._url_text.drop_target_register("DND_Text")  # type: ignore[attr-defined]
            self._url_text.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
        except Exception:
            # 不支持拖拽时静默降级
            pass

    def _on_drop(self, event: Any) -> None:
        """拖拽放下事件处理。"""
        text = getattr(event, "data", "")
        if text:
            self._url_text.delete("1.0", tk.END)
            self._url_text.insert("1.0", text.strip())

    # ==================================================================
    # 公共方法
    # ==================================================================

    def get_url(self) -> str:
        """获取 URL 输入框内容。"""
        return self._url_text.get("1.0", tk.END).strip()

    def get_extract_code(self) -> str | None:
        """获取提取码。"""
        code = self._code_var.get().strip()
        return code if code else None

    def set_url(self, url: str) -> None:
        """设置 URL。"""
        self._url_text.delete("1.0", tk.END)
        self._url_text.insert("1.0", url)

    def set_extract_code(self, code: str | None) -> None:
        """设置提取码。"""
        self._code_var.set(code or "")

    def set_parsing(self, parsing: bool) -> None:
        """设置解析中状态。"""
        state = tk.DISABLED if parsing else tk.NORMAL
        self._parse_btn.config(state=state)
        self._clipboard_btn.config(state=state)
        if parsing:
            self._parse_btn.config(text="解析中...")
        else:
            self._parse_btn.config(text="🔍 解析")

    def set_files(self, share_infos: list[ShareInfo], drive: str = "") -> None:
        """设置文件列表。"""
        self._file_list.set_files(share_infos, drive)

    def show_clipboard_hint(self, url: str, drive: str = "") -> None:
        """显示剪贴板识别提示条。

        Args:
            url: 识别到的分享链接。
            drive: 网盘标识。
        """
        self._clipboard_hint_url = url
        display = get_drive_display(drive) if drive else "网盘"
        self._clipboard_hint_label.config(
            text=f"📋 检测到剪贴板中的{display}分享链接，点击填入"
        )
        self._clipboard_hint_frame.pack(fill=tk.X, pady=(0, 6))

    def hide_clipboard_hint(self) -> None:
        """隐藏剪贴板提示条。"""
        self._clipboard_hint_frame.pack_forget()
        self._clipboard_hint_url = ""

    def update_settings(
        self,
        save_path: str | None = None,
        concurrency: int | None = None,
        chunk_size: int | None = None,
    ) -> None:
        """更新下载设置。

        Args:
            save_path: 保存路径。
            concurrency: 并发数。
            chunk_size: 分片大小。
        """
        if save_path is not None:
            self._save_path = save_path
            self._save_path_var.set(save_path)
        if concurrency is not None:
            self._concurrency = concurrency
            self._concurrency_var.set(concurrency)
            self._concurrency_label.config(text=str(concurrency))
        if chunk_size is not None:
            self._chunk_size = chunk_size
            for name, size in CHUNK_SIZE_OPTIONS.items():
                if size == chunk_size:
                    self._chunk_var.set(name)
                    break

    def clear(self) -> None:
        """清空输入和文件列表。"""
        self._url_text.delete("1.0", tk.END)
        self._code_var.set("")
        self._file_list.clear()

    # ==================================================================
    # 事件处理
    # ==================================================================

    def _handle_parse(self) -> None:
        """处理解析按钮点击。"""
        url = self.get_url()
        if not url:
            return
        code = self.get_extract_code()
        self._on_parse(url, code)

    def _handle_clipboard(self) -> None:
        """从剪贴板读取并识别分享链接。"""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return

        if not text:
            return

        urls = detect_share_url(text)
        if urls:
            share = urls[0]
            self.set_url(share.url)
            if share.extract_code:
                self.set_extract_code(share.extract_code)
        else:
            self.set_url(text.strip())

    def _apply_clipboard_url(self) -> None:
        """应用剪贴板提示中的 URL。"""
        if self._clipboard_hint_url:
            self.set_url(self._clipboard_hint_url)
            self.hide_clipboard_hint()

    def _on_download_selected(self) -> None:
        """下载选中的文件。"""
        selected = self._file_list.get_selected_files()
        if not selected:
            tk.messagebox.showinfo("提示", "请先在文件列表中选择要下载的文件", parent=self)
            return
        self._start_downloads(selected)

    def _on_download_all(self) -> None:
        """下载所有文件。"""
        all_files = self._file_list.get_all_files()
        if not all_files:
            tk.messagebox.showinfo("提示", "文件列表为空，请先解析分享链接", parent=self)
            return
        self._start_downloads(all_files)

    def _start_downloads(self, share_infos: list[ShareInfo]) -> None:
        """启动下载。

        Args:
            share_infos: 要下载的文件列表。
        """
        save_path = self._save_path_var.get().strip() or DEFAULT_SAVE_PATH
        concurrency = int(self._concurrency_var.get())
        chunk_size = CHUNK_SIZE_OPTIONS.get(self._chunk_var.get(), DEFAULT_CHUNK_SIZE)
        self._on_download(share_infos, save_path, concurrency, chunk_size)

    def _select_all(self) -> None:
        """全选文件列表。"""
        tree = self._file_list._tree
        for item in tree.get_children():
            tree.selection_add(item)

    def _invert_selection(self) -> None:
        """反选文件列表。"""
        tree = self._file_list._tree
        all_items = set(tree.get_children())
        selected = set(tree.selection())
        tree.selection_remove(*selected)
        tree.selection_add(*(all_items - selected))

    def _on_concurrency_change(self, _value: str) -> None:
        """并发数滑块变化。"""
        self._concurrency_label.config(text=str(int(self._concurrency_var.get())))

    def _browse_save_path(self) -> None:
        """浏览选择保存路径。"""
        path = filedialog.askdirectory(
            title="选择下载保存目录",
            initialdir=self._save_path_var.get() or str(Path.home()),
            parent=self,
        )
        if path:
            self._save_path_var.set(path)
            self._save_path = path
