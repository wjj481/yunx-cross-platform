"""
账号管理对话框。

管理各网盘的登录凭证（Cookie / JWT），通过 ConfigManager 进行 AES-GCM 加密存储。
支持添加、删除、测试凭证。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from core.config import ConfigManager
from core.exceptions import AuthenticationError, YunXError
from ..utils import DRIVE_NAMES, SUPPORTED_DRIVES, get_drive_color, get_drive_display


class AccountManagerDialog(tk.Toplevel):
    """网盘账号管理对话框。

    功能：
    - 列表显示已配置的网盘账号
    - 添加：选择网盘类型 → 输入 Cookie/JWT → 密码加密保存
    - 删除：移除选中的账号
    - 测试：验证凭证是否有效
    """

    def __init__(self, master: tk.Misc) -> None:
        """初始化账号管理对话框。

        Args:
            master: 父窗口。
        """
        super().__init__(master)
        self.title("账号管理")
        self.geometry("560x460")
        self.minsize(480, 380)

        self._config: ConfigManager | None = None
        self._build_ui()
        self._center_on_parent(master)

        # 模态
        self.transient(master)
        self.grab_set()

        # 启动时请求主密码
        self.after(100, self._request_master_password)

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # 顶部说明
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill=tk.X)
        ttk.Label(
            top,
            text="管理各网盘的登录凭证（Cookie / Token），所有凭证经 AES-GCM 加密存储。",
            foreground="#555",
            wraplength=520,
        ).pack(anchor=tk.W)

        # 账号列表
        list_frame = ttk.LabelFrame(self, text="已配置账号", padding=8)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        columns = ("drive", "type", "status")
        self._tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", height=8
        )
        self._tree.heading("drive", text="网盘")
        self._tree.heading("type", text="凭证类型")
        self._tree.heading("status", text="状态")
        self._tree.column("drive", width=150, anchor=tk.W)
        self._tree.column("type", width=150, anchor=tk.CENTER)
        self._tree.column("status", width=120, anchor=tk.CENTER)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self._tree.yview
        )
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 按钮区
        btn_frame = ttk.Frame(self, padding=(12, 0, 12, 10))
        btn_frame.pack(fill=tk.X)

        self._add_btn = ttk.Button(
            btn_frame, text="添加", command=self._on_add, state=tk.DISABLED
        )
        self._add_btn.pack(side=tk.LEFT)

        self._delete_btn = ttk.Button(
            btn_frame, text="删除", command=self._on_delete, state=tk.DISABLED
        )
        self._delete_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._test_btn = ttk.Button(
            btn_frame, text="测试", command=self._on_test, state=tk.DISABLED
        )
        self._test_btn.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(btn_frame, text="关闭", command=self.destroy).pack(
            side=tk.RIGHT
        )

        # 底部状态
        self._status_var = tk.StringVar(value="请先输入主密码以解锁配置")
        ttk.Label(
            self, textvariable=self._status_var, foreground="#888", padding=(12, 4)
        ).pack(fill=tk.X, side=tk.BOTTOM)

    def _center_on_parent(self, master: tk.Misc) -> None:
        """居中到父窗口。"""
        self.update_idletasks()
        try:
            px = master.winfo_rootx()
            py = master.winfo_rooty()
            pw = master.winfo_width()
            ph = master.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
        except tk.TclError:
            pass

    # ---------- 主密码 ----------

    def _request_master_password(self) -> None:
        """弹出主密码输入对话框，解锁配置。"""
        dlg = _MasterPasswordDialog(self)
        if not dlg.ok:
            self._status_var.set("未解锁，操作受限")
            return

        try:
            self._config = ConfigManager(password=dlg.password)
            self._status_var.set("配置已解锁")
            self._add_btn.config(state=tk.NORMAL)
            self._refresh_list()
        except AuthenticationError as exc:
            messagebox.showerror("密码错误", str(exc), parent=self)
            self._status_var.set("解锁失败：主密码错误")
        except Exception as exc:
            messagebox.showerror("错误", f"配置加载失败：{exc}", parent=self)
            self._status_var.set("解锁失败")

    # ---------- 列表刷新 ----------

    def _refresh_list(self) -> None:
        """刷新账号列表。"""
        for item in self._tree.get_children():
            self._tree.delete(item)

        if self._config is None:
            return

        drives = self._config.list_drives()
        for drive in drives:
            cred = self._config.get_credential(drive)
            cred_type = self._detect_credential_type(cred)
            display = get_drive_display(drive)
            self._tree.insert(
                "",
                tk.END,
                iid=drive,
                values=(display, cred_type, "已保存"),
            )

        # 选中状态变化时更新按钮
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

    @staticmethod
    def _detect_credential_type(cred: dict[str, Any] | None) -> str:
        """判断凭证类型。

        Args:
            cred: 凭证字典。

        Returns:
            凭证类型描述。
        """
        if not cred:
            return "未知"
        if "cookie" in cred:
            return "Cookie"
        if "access_token" in cred or "token" in cred:
            return "Token / JWT"
        if "authorization" in cred:
            return "Authorization"
        return "自定义"

    def _on_select(self, _event: tk.Event) -> None:
        """列表选中变化时更新按钮状态。"""
        selected = self._tree.selection()
        has_selection = len(selected) > 0
        self._delete_btn.config(state=tk.NORMAL if has_selection else tk.DISABLED)
        self._test_btn.config(state=tk.NORMAL if has_selection else tk.DISABLED)

    # ---------- 添加账号 ----------

    def _on_add(self) -> None:
        """添加新账号。"""
        if self._config is None:
            return
        dlg = _AddAccountDialog(self, SUPPORTED_DRIVES)
        if not dlg.ok:
            return

        drive = dlg.drive
        credential = dlg.credential
        if not drive or not credential:
            return

        try:
            self._config.set_credential(drive, credential)
            self._refresh_list()
            self._status_var.set(f"已保存 {get_drive_display(drive)} 凭证")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)

    # ---------- 删除账号 ----------

    def _on_delete(self) -> None:
        """删除选中的账号。"""
        selected = self._tree.selection()
        if not selected or self._config is None:
            return

        drive = selected[0]
        display = get_drive_display(drive)
        if not messagebox.askyesno(
            "确认删除",
            f"确定要删除 {display} 的登录凭证吗？\n此操作不可撤销。",
            parent=self,
        ):
            return

        try:
            self._config.remove_credential(drive)
            self._refresh_list()
            self._status_var.set(f"已删除 {display} 凭证")
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)

    # ---------- 测试凭证 ----------

    def _on_test(self) -> None:
        """测试选中的凭证是否有效。"""
        selected = self._tree.selection()
        if not selected or self._config is None:
            return

        drive = selected[0]
        cred = self._config.get_credential(drive)
        if not cred:
            messagebox.showwarning("提示", "该账号无凭证数据", parent=self)
            return

        self._status_var.set(f"正在测试 {get_drive_display(drive)} 凭证...")
        self.update_idletasks()

        # 在子线程中测试，避免阻塞 UI
        import threading

        def _test_worker():
            try:
                # 尝试用凭证初始化对应解析器并做基础连通性测试
                from core.parsers.base import get_parser

                # 使用各网盘的典型分享域名构造测试 URL
                test_urls = {
                    "quark": "https://pan.quark.cn/s/test",
                    "pan123": "https://www.123pan.com/s/test",
                    "xunlei": "https://pan.xunlei.com/s/test",
                    "baidu": "https://pan.baidu.com/s/1test",
                    "uc": "https://drive.uc.cn/s/test",
                    "caiyun": "https://yun.139.com/shareweb/test/w/i/test",
                }
                test_url = test_urls.get(drive, "https://example.com")
                parser = get_parser(test_url, credential=cred)
                # 仅验证解析器能正常初始化，不实际发起解析（避免误触发）
                self.after(
                    0,
                    lambda: self._test_result(
                        True, f"{get_drive_display(drive)} 凭证格式有效，解析器初始化成功"
                    ),
                )
            except YunXError as exc:
                self.after(0, lambda: self._test_result(False, str(exc)))
            except Exception as exc:
                self.after(0, lambda: self._test_result(False, f"测试失败: {exc}"))

        threading.Thread(target=_test_worker, daemon=True).start()

    def _test_result(self, success: bool, message: str) -> None:
        """测试结果回调（主线程）。"""
        if success:
            messagebox.showinfo("测试成功", message, parent=self)
            self._status_var.set("凭证测试通过")
        else:
            messagebox.showerror("测试失败", message, parent=self)
            self._status_var.set("凭证测试失败")


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
            frame,
            text="请输入配置主密码以解锁凭证存储：",
            wraplength=300,
        ).pack(pady=(0, 8))

        self._entry = ttk.Entry(frame, show="*", width=30)
        self._entry.pack(pady=(0, 12))
        self._entry.focus_set()
        self._entry.bind("<Return>", lambda _e: self._on_ok())

        ttk.Label(
            frame,
            text="首次使用时设置的密码将用于加密所有网盘凭证。\n忘记密码将无法恢复已保存的凭证。",
            foreground="#888",
            justify=tk.LEFT,
            wraplength=300,
        ).pack(pady=(0, 12))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="确定", command=self._on_ok).pack(
            side=tk.RIGHT
        )

        self.wait_window(self)

    def _on_ok(self) -> None:
        self.password = self._entry.get()
        if self.password:
            self.ok = True
        self.destroy()


class _AddAccountDialog(tk.Toplevel):
    """添加账号对话框：选择网盘 + 输入凭证。"""

    def __init__(self, master: tk.Misc, drives: list[str]) -> None:
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
            frame,
            textvariable=self._drive_var,
            values=drive_names,
            state="readonly",
            width=28,
        )
        self._drive_combo.grid(row=0, column=1, sticky=tk.EW, pady=(0, 6))
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
            foreground="#888",
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(0, 12))

        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, sticky=tk.EW)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="保存", command=self._on_save).pack(
            side=tk.RIGHT
        )

        self.wait_window(self)

    def _on_save(self) -> None:
        """保存凭证。"""
        selected = self._drive_combo.get()
        # 从显示名中提取 drive 标识
        for d in DRIVE_NAMES:
            if d in selected:
                self.drive = d
                break

        cred_content = self._cred_text.get("1.0", tk.END).strip()
        if not self.drive or not cred_content:
            messagebox.showwarning("提示", "请选择网盘并输入凭证内容", parent=self)
            return

        cred_type = self._cred_type_var.get()
        if cred_type == "cookie":
            self.credential = {"cookie": cred_content}
        else:
            self.credential = {"access_token": cred_content}

        self.ok = True
        self.destroy()
