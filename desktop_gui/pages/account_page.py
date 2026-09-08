"""
账号管理页标签页。

网盘账号卡片列表，每卡片显示网盘图标/名称、登录状态、凭证预览（脱敏）。
支持添加账号（6种网盘选择 + Cookie/JWT 输入）、删除账号、测试连接。
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from core.config import ConfigManager
from core.exceptions import AuthenticationError, YunXError

from ..dialogs.baidu_warning import BaiduWarningDialog
from ..theme import get_drive_brand_color
from ..utils import (
    DRIVE_NAMES,
    SUPPORTED_DRIVES,
    get_drive_color,
    get_drive_display,
    needs_risk_warning,
)


class AccountPage(ttk.Frame):
    """账号管理页标签页。

    以卡片形式展示各网盘账号状态，支持添加、删除、测试凭证。
    """

    def __init__(
        self,
        master: tk.Misc,
        get_config: Any,
        on_config_unlocked: Any | None = None,
    ) -> None:
        """初始化账号管理页。

        Args:
            master: 父容器。
            get_config: 回调函数，返回当前 ConfigManager 或 None。
            on_config_unlocked: 配置解锁后的回调。
        """
        super().__init__(master, padding=12)
        self._get_config = get_config
        self._on_config_unlocked = on_config_unlocked
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # 顶部标题 + 添加按钮
        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(header, text="网盘账号", font=("", 14, "bold")).pack(side=tk.LEFT)
        ttk.Label(
            header, text="  管理各网盘的登录凭证（Cookie / Token）",
            foreground="#888", font=("", 9),
        ).pack(side=tk.LEFT, pady=(4, 0))

        self._add_btn = ttk.Button(
            header, text="+ 添加账号", style="Primary.TButton",
            command=self._on_add_account,
        )
        self._add_btn.pack(side=tk.RIGHT)

        # 解锁提示（配置未解锁时显示）
        self._lock_frame = ttk.Frame(self)
        self._lock_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            self._lock_frame,
            text="🔒 配置未解锁，点击下方按钮输入主密码以管理账号",
            foreground="#FB8C00",
        ).pack(side=tk.LEFT)
        ttk.Button(
            self._lock_frame, text="解锁配置", command=self._unlock_config,
        ).pack(side=tk.LEFT, padx=(10, 0))

        # 账号卡片容器（可滚动）
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            container, orient=tk.VERTICAL, command=self._canvas.yview
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

        # 卡片字典：drive -> card frame
        self._cards: dict[str, ttk.Frame] = {}

    # ==================================================================
    # 公共方法
    # ==================================================================

    def refresh(self) -> None:
        """刷新账号卡片列表。"""
        config = self._get_config()

        # 显示/隐藏解锁提示
        if config is None:
            self._lock_frame.pack(fill=tk.X, pady=(0, 10))
        else:
            self._lock_frame.pack_forget()

        # 清空现有卡片
        for card in self._cards.values():
            card.destroy()
        self._cards.clear()

        # 为每个支持的网盘创建卡片
        for drive in SUPPORTED_DRIVES:
            self._create_account_card(drive, config)

    # ==================================================================
    # 内部方法
    # ==================================================================

    def _create_account_card(self, drive: str, config: ConfigManager | None) -> None:
        """创建单个网盘账号卡片。

        Args:
            drive: 网盘标识。
            config: 配置管理器（可能为 None）。
        """
        color = get_drive_brand_color(drive)
        display = get_drive_display(drive)

        # 检查是否已配置
        has_credential = False
        cred_preview = ""
        cred_type = ""
        if config is not None:
            try:
                cred = config.get_credential(drive)
                if cred:
                    has_credential = True
                    cred_type = self._detect_cred_type(cred)
                    cred_preview = self._mask_credential(cred)
            except Exception:
                pass

        # 卡片容器
        card = ttk.Frame(self._scroll_frame, style="Card.TFrame", padding=12)
        card.pack(fill=tk.X, padx=2, pady=4)
        self._cards[drive] = card

        # 第一行：网盘徽章 + 名称 + 状态
        row1 = ttk.Frame(card, style="Card.TFrame")
        row1.pack(fill=tk.X)

        # 彩色徽章
        badge = tk.Label(
            row1, text=f"  {display}  ", bg=color, fg="#FFFFFF",
            font=("", 9, "bold"), padx=2, pady=2,
        )
        badge.pack(side=tk.LEFT)

        # 状态标签
        if has_credential:
            status_text = "✓ 已登录"
            status_color = "#43A047"
        else:
            status_text = "未登录"
            status_color = "#999"
        ttk.Label(
            row1, text=status_text, foreground=status_color,
            font=("", 9, "bold"), style="Card.TLabel",
        ).pack(side=tk.LEFT, padx=(10, 0))

        # 凭证类型
        if cred_type:
            ttk.Label(
                row1, text=f"[{cred_type}]", foreground="#888",
                font=("", 8), style="CardMuted.TLabel",
            ).pack(side=tk.LEFT, padx=(8, 0))

        # 第二行：凭证预览或登录引导
        row2 = ttk.Frame(card, style="Card.TFrame")
        row2.pack(fill=tk.X, pady=(8, 0))

        if has_credential:
            ttk.Label(
                row2, text=f"凭证：{cred_preview}", foreground="#666",
                font=("", 9), style="CardMuted.TLabel",
            ).pack(side=tk.LEFT)
        else:
            ttk.Label(
                row2, text="点击「添加」配置登录凭证", foreground="#AAA",
                font=("", 9), style="CardMuted.TLabel",
            ).pack(side=tk.LEFT)

        # 第三行：操作按钮
        row3 = ttk.Frame(card, style="Card.TFrame")
        row3.pack(fill=tk.X, pady=(8, 0))

        if has_credential:
            ttk.Button(
                row3, text="测试", width=8,
                command=lambda d=drive: self._on_test(d),
            ).pack(side=tk.LEFT, padx=(0, 6))
            ttk.Button(
                row3, text="删除", width=8, style="Danger.TButton",
                command=lambda d=drive: self._on_delete(d),
            ).pack(side=tk.LEFT)
        else:
            ttk.Button(
                row3, text="点击登录", width=10, style="Secondary.TButton",
                command=lambda d=drive: self._on_add_account(d),
            ).pack(side=tk.LEFT)

    @staticmethod
    def _detect_cred_type(cred: dict[str, Any]) -> str:
        """判断凭证类型。"""
        if "cookie" in cred:
            return "Cookie"
        if "access_token" in cred or "token" in cred:
            return "Token"
        if "authorization" in cred:
            return "Auth"
        return "自定义"

    @staticmethod
    def _mask_credential(cred: dict[str, Any]) -> str:
        """脱敏显示凭证内容。"""
        for key in ("cookie", "access_token", "token", "authorization"):
            if key in cred:
                value = str(cred[key])
                if len(value) > 20:
                    return f"{value[:10]}...{value[-6:]}"
                return value[:20] + "..." if len(value) > 20 else value
        return "已配置"

    def _unlock_config(self) -> None:
        """解锁配置（请求主密码）。"""
        dlg = _MasterPasswordDialog(self)
        if not dlg.ok:
            return

        try:
            config = ConfigManager(password=dlg.password)
            if self._on_config_unlocked:
                self._on_config_unlocked(config)
            self.refresh()
        except AuthenticationError as exc:
            messagebox.showerror("密码错误", str(exc), parent=self)
        except Exception as exc:
            messagebox.showerror("错误", f"配置加载失败：{exc}", parent=self)

    def _on_add_account(self, drive: str = "") -> None:
        """添加账号。

        Args:
            drive: 预选的网盘标识，为空时让用户选择。
        """
        config = self._get_config()
        if config is None:
            messagebox.showinfo("提示", "请先解锁配置", parent=self)
            self._unlock_config()
            return

        dlg = _AddAccountDialog(self, SUPPORTED_DRIVES, preselect_drive=drive)
        if not dlg.ok:
            return

        selected_drive = dlg.drive
        credential = dlg.credential
        if not selected_drive or not credential:
            return

        # 百度网盘风控警告
        if needs_risk_warning(selected_drive):
            warn = BaiduWarningDialog(self)
            if not warn.confirmed:
                return

        try:
            config.set_credential(selected_drive, credential)
            config.save()
            messagebox.showinfo(
                "保存成功",
                f"{get_drive_display(selected_drive)} 凭证已保存",
                parent=self,
            )
            self.refresh()
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)

    def _on_delete(self, drive: str) -> None:
        """删除账号。

        Args:
            drive: 网盘标识。
        """
        config = self._get_config()
        if config is None:
            return

        display = get_drive_display(drive)
        if not messagebox.askyesno(
            "确认删除",
            f"确定要删除 {display} 的登录凭证吗？\n此操作不可撤销。",
            parent=self,
        ):
            return

        try:
            config.remove_credential(drive)
            config.save()
            self.refresh()
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)

    def _on_test(self, drive: str) -> None:
        """测试凭证连接。

        Args:
            drive: 网盘标识。
        """
        config = self._get_config()
        if config is None:
            return

        cred = config.get_credential(drive)
        if not cred:
            messagebox.showwarning("提示", "该账号无凭证数据", parent=self)
            return

        display = get_drive_display(drive)

        def _test_worker():
            try:
                from core.parsers.base import get_parser

                test_urls = {
                    "quark": "https://pan.quark.cn/s/test",
                    "pan123": "https://www.123pan.com/s/test",
                    "xunlei": "https://pan.xunlei.com/s/test",
                    "baidu": "https://pan.baidu.com/s/1test",
                    "uc": "https://drive.uc.cn/s/test",
                    "caiyun": "https://yun.139.com/shareweb/test/w/i/test",
                }
                test_url = test_urls.get(drive, "https://example.com")
                get_parser(test_url, credential=cred)
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "测试成功",
                        f"{display} 凭证格式有效，解析器初始化成功",
                        parent=self,
                    ),
                )
            except YunXError as exc:
                self.after(
                    0, lambda: messagebox.showerror("测试失败", str(exc), parent=self)
                )
            except Exception as exc:
                self.after(
                    0,
                    lambda: messagebox.showerror("测试失败", f"测试失败: {exc}", parent=self),
                )

        threading.Thread(target=_test_worker, daemon=True).start()
        messagebox.showinfo("测试中", f"正在测试 {display} 凭证...", parent=self)


# ==================================================================
# 内部对话框
# ==================================================================

class _MasterPasswordDialog(tk.Toplevel):
    """主密码输入对话框。"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.title("输入主密码")
        self.resizable(False, False)
        self.ok = False
        self.password = ""

        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame, text="请输入配置主密码以解锁凭证存储：", wraplength=300,
        ).pack(pady=(0, 8))

        self._entry = ttk.Entry(frame, show="*", width=30)
        self._entry.pack(pady=(0, 12))
        self._entry.focus_set()
        self._entry.bind("<Return>", lambda _e: self._on_ok())

        ttk.Label(
            frame,
            text="首次使用时设置的密码将用于加密所有网盘凭证。\n忘记密码将无法恢复已保存的凭证。",
            foreground="#888", justify=tk.LEFT, wraplength=300,
        ).pack(pady=(0, 12))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="确定", style="Primary.TButton", command=self._on_ok).pack(
            side=tk.RIGHT
        )

        self.wait_window(self)

    def _on_ok(self) -> None:
        pwd = self._entry.get()
        if pwd:
            self.password = pwd
            self.ok = True
        self.destroy()


class _AddAccountDialog(tk.Toplevel):
    """添加账号对话框：选择网盘 + 输入凭证。"""

    def __init__(
        self,
        master: tk.Misc,
        drives: list[str],
        preselect_drive: str = "",
    ) -> None:
        super().__init__(master)
        self.title("添加账号")
        self.resizable(False, False)
        self.ok = False
        self.drive = ""
        self.credential: dict[str, Any] = {}

        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        # 网盘选择
        ttk.Label(frame, text="网盘类型：").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 6)
        )
        self._drive_var = tk.StringVar()
        drive_names = [f"{get_drive_display(d)} ({d})" for d in drives]
        self._drive_combo = ttk.Combobox(
            frame, textvariable=self._drive_var, values=drive_names,
            state="readonly", width=28,
        )
        self._drive_combo.grid(row=0, column=1, sticky=tk.EW, pady=(0, 6))

        # 预选
        if preselect_drive:
            for i, d in enumerate(drives):
                if d == preselect_drive:
                    self._drive_combo.current(i)
                    break
        else:
            self._drive_combo.current(0)

        # 凭证类型
        ttk.Label(frame, text="凭证类型：").grid(
            row=1, column=0, sticky=tk.W, pady=(0, 6)
        )
        self._cred_type_var = tk.StringVar(value="cookie")
        type_frame = ttk.Frame(frame)
        type_frame.grid(row=1, column=1, sticky=tk.W, pady=(0, 6))
        ttk.Radiobutton(
            type_frame, text="Cookie", variable=self._cred_type_var, value="cookie"
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            type_frame, text="Token/JWT", variable=self._cred_type_var, value="token"
        ).pack(side=tk.LEFT, padx=(8, 0))

        # 凭证内容
        ttk.Label(frame, text="凭证内容：").grid(
            row=2, column=0, sticky=tk.NW, pady=(0, 6)
        )
        self._cred_text = tk.Text(frame, width=36, height=6, wrap=tk.WORD)
        self._cred_text.grid(row=2, column=1, sticky=tk.EW, pady=(0, 6))

        # 提示
        ttk.Label(
            frame,
            text="提示：从浏览器开发者工具复制完整 Cookie 字符串，\n或粘贴 API 返回的 access_token。",
            foreground="#888", justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(0, 12))

        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, sticky=tk.EW)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="保存", style="Primary.TButton", command=self._on_save).pack(
            side=tk.RIGHT
        )

        self.wait_window(self)

    def _on_save(self) -> None:
        selected = self._drive_combo.get()
        for d in DRIVE_NAMES:
            if d in selected:
                self.drive = d
                break

        cred_content = self._cred_text.get("1.0", tk.END).strip()
        if not self.drive or not cred_content:
            messagebox.showwarning("提示", "请选择网盘并输入凭证内容", parent=self)
            return

        if self._cred_type_var.get() == "cookie":
            self.credential = {"cookie": cred_content}
        else:
            self.credential = {"access_token": cred_content}

        self.ok = True
        self.destroy()
