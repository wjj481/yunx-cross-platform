"""
URL 输入组件。

提供分享链接输入框、提取码输入框、解析按钮和剪贴板粘贴按钮。
支持从剪贴板自动识别分享链接并预填提取码。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from core.clipboard import detect_share_url


class URLInputWidget(ttk.LabelFrame):
    """URL 输入区域组件。

    包含：
    - 分享链接单行输入框
    - 提取码输入框（可选）
    - 「解析」按钮
    - 「从剪贴板粘贴」按钮

    Signals:
        on_parse(url, extract_code): 用户点击解析按钮时触发。
    """

    def __init__(
        self,
        master: tk.Misc,
        on_parse: Callable[[str, str | None], None],
    ) -> None:
        """初始化 URL 输入组件。

        Args:
            master: 父容器。
            on_parse: 解析回调函数，接收 (url, extract_code)。
        """
        super().__init__(master, text="分享链接", padding=10)
        self._on_parse = on_parse

        # 变量
        self._url_var = tk.StringVar()
        self._code_var = tk.StringVar()

        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # 第一行：URL 输入 + 剪贴板按钮
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(row1, text="链接：", width=6).pack(side=tk.LEFT)
        self._url_entry = ttk.Entry(row1, textvariable=self._url_var)
        self._url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self._url_entry.bind("<Return>", lambda _e: self._handle_parse())

        self._clipboard_btn = ttk.Button(
            row1, text="从剪贴板粘贴", command=self._handle_clipboard
        )
        self._clipboard_btn.pack(side=tk.LEFT)

        # 第二行：提取码 + 解析按钮
        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X)

        ttk.Label(row2, text="提取码：", width=6).pack(side=tk.LEFT)
        self._code_entry = ttk.Entry(row2, textvariable=self._code_var, width=12)
        self._code_entry.pack(side=tk.LEFT, padx=(0, 6))
        self._code_entry.bind("<Return>", lambda _e: self._handle_parse())

        ttk.Label(row2, text="（可选，自动识别时预填）", foreground="#888").pack(
            side=tk.LEFT
        )

        self._parse_btn = ttk.Button(
            row2, text="解析", command=self._handle_parse
        )
        self._parse_btn.pack(side=tk.RIGHT)

    # ---------- 公共方法 ----------

    def get_url(self) -> str:
        """获取当前输入的 URL。"""
        return self._url_var.get().strip()

    def get_extract_code(self) -> str | None:
        """获取提取码，为空时返回 None。"""
        code = self._code_var.get().strip()
        return code if code else None

    def set_url(self, url: str) -> None:
        """设置 URL 输入框内容。"""
        self._url_var.set(url)

    def set_extract_code(self, code: str | None) -> None:
        """设置提取码输入框内容。"""
        self._code_var.set(code or "")

    def set_parsing(self, parsing: bool) -> None:
        """设置解析中状态，禁用/启用按钮。

        Args:
            parsing: 是否正在解析。
        """
        state = tk.DISABLED if parsing else tk.NORMAL
        self._parse_btn.config(state=state)
        self._clipboard_btn.config(state=state)

    def clear(self) -> None:
        """清空输入框。"""
        self._url_var.set("")
        self._code_var.set("")

    def focus(self) -> None:
        """聚焦到 URL 输入框。"""
        self._url_entry.focus_set()

    # ---------- 事件处理 ----------

    def _handle_clipboard(self) -> None:
        """从剪贴板读取文本，自动识别分享链接并填充。"""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            # 剪贴板为空或不可用
            return

        if not text:
            return

        urls = detect_share_url(text)
        if urls:
            # 取第一个识别到的链接
            share = urls[0]
            self._url_var.set(share.url)
            if share.extract_code:
                self._code_var.set(share.extract_code)
        else:
            # 未识别到网盘链接，直接粘贴原始文本
            self._url_var.set(text.strip())

    def _handle_parse(self) -> None:
        """处理解析按钮点击。"""
        url = self.get_url()
        if not url:
            return
        code = self.get_extract_code()
        self._on_parse(url, code)
