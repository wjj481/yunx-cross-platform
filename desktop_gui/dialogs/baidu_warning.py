"""
百度网盘风控警告对话框。

在解析百度网盘分享链接前弹出，醒目提示用户百度网盘的风控风险，
用户确认后才继续解析。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class BaiduWarningDialog(tk.Toplevel):
    """百度网盘风控警告对话框。

    使用红色醒目标题和详细风险说明，用户必须点击「我已知晓，继续解析」
    或「取消」来关闭对话框。

    Attributes:
        confirmed: 用户是否确认继续。
    """

    def __init__(self, master: tk.Misc) -> None:
        """初始化百度风控警告对话框。

        Args:
            master: 父窗口。
        """
        super().__init__(master)
        self.title("百度网盘风控警告")
        self.confirmed = False

        # 模态对话框
        self.transient(master)
        self.grab_set()

        # 窗口设置
        self.resizable(False, False)
        self._build_ui()
        self._center_on_parent(master)

        # 等待对话框关闭
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window(self)

    def _build_ui(self) -> None:
        """构建 UI。"""
        # 主容器
        main = ttk.Frame(self, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        # 警告图标（用大号文字代替）
        icon_frame = ttk.Frame(main)
        icon_frame.pack(pady=(0, 12))
        ttk.Label(
            icon_frame,
            text="⚠ 风控警告",
            font=("", 18, "bold"),
            foreground="#C62828",
        ).pack()

        # 警告标题
        ttk.Label(
            main,
            text="百度网盘解析风险提示",
            font=("", 12, "bold"),
            foreground="#B71C1C",
        ).pack(pady=(0, 10))

        # 详细说明
        warning_text = (
            "百度网盘对自动化解析和下载有严格的风控策略。\n\n"
            "频繁使用本工具解析百度网盘链接可能导致：\n"
            "  • 您的百度账号被临时封禁或永久封禁\n"
            "  • IP 地址被百度服务器列入黑名单\n"
            "  • 分享链接被举报失效\n\n"
            "建议：\n"
            "  • 不要频繁、连续地解析百度链接\n"
            "  • 单次解析后间隔一段时间再使用\n"
            "  • 优先使用夸克、123云盘等风控较宽松的网盘\n\n"
            "继续使用即表示您已知晓并愿意承担上述风险。"
        )
        text_frame = ttk.Frame(main)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 16))
        ttk.Label(
            text_frame,
            text=warning_text,
            justify=tk.LEFT,
            foreground="#333",
        ).pack(anchor=tk.W)

        # 按钮区
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(
            btn_frame,
            text="取消",
            command=self._on_cancel,
            width=15,
        ).pack(side=tk.RIGHT, padx=(8, 0))

        ttk.Button(
            btn_frame,
            text="我已知晓，继续解析",
            command=self._on_confirm,
            width=20,
        ).pack(side=tk.RIGHT)

    def _center_on_parent(self, master: tk.Misc) -> None:
        """将对话框居中到父窗口。

        Args:
            master: 父窗口。
        """
        self.update_idletasks()
        try:
            parent_x = master.winfo_rootx()
            parent_y = master.winfo_rooty()
            parent_w = master.winfo_width()
            parent_h = master.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = parent_x + (parent_w - w) // 2
            y = parent_y + (parent_h - h) // 2
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except tk.TclError:
            pass

    def _on_confirm(self) -> None:
        """用户确认继续。"""
        self.confirmed = True
        self.destroy()

    def _on_cancel(self) -> None:
        """用户取消。"""
        self.confirmed = False
        self.destroy()
