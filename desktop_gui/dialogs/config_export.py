"""
配置导出 / 导入对话框。

提供明文导出、加密导出（AES-256-GCM）、自动检测加密、密码输入、
合并/替换导入模式等完整交互流程。
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from core import (
    AuthenticationError,
    apply_imported_config,
    export_config,
    import_config,
    is_encrypted,
)
from core.config import ConfigManager

from ..utils import format_size


# ==================================================================
# 导出配置对话框
# ==================================================================

class ExportConfigDialog(tk.Toplevel):
    """配置导出对话框。

    流程：
    1. 用户选择导出文件路径（默认 yunx_config.yunxcfg）
    2. 选择明文导出或加密导出
    3. 加密导出时输入密码（两次确认）
    4. 执行导出并显示结果
    """

    def __init__(
        self,
        master: tk.Misc,
        config_manager: ConfigManager,
    ) -> None:
        """初始化导出对话框。

        Args:
            master: 父窗口。
            config_manager: 已解锁的 ConfigManager 实例。
        """
        super().__init__(master)
        self.title("导出配置")
        self.geometry("480x360")
        self.minsize(440, 320)
        self.resizable(False, False)

        self._config = config_manager
        self._output_path: str = ""

        self.transient(master)
        self.grab_set()

        self._build_ui()
        self._center_on_parent(master)

    def _build_ui(self) -> None:
        """构建 UI。"""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # 说明
        ttk.Label(
            main,
            text="将网盘凭证、下载设置和任务导出为配置文件，\n可用于备份或迁移到其他设备。",
            justify=tk.LEFT,
            wraplength=440,
        ).pack(anchor=tk.W, pady=(0, 12))

        # 导出路径
        ttk.Label(main, text="导出路径：").pack(anchor=tk.W, pady=(0, 4))
        path_frame = ttk.Frame(main)
        path_frame.pack(fill=tk.X, pady=(0, 12))
        self._path_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self._path_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(path_frame, text="浏览...", command=self._browse_path, width=8).pack(
            side=tk.LEFT
        )

        # 导出模式
        ttk.Label(main, text="导出模式：", font=("", 10, "bold")).pack(
            anchor=tk.W, pady=(0, 4)
        )
        self._mode_var = tk.StringVar(value="plaintext")
        mode_frame = ttk.Frame(main)
        mode_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Radiobutton(
            mode_frame,
            text="明文导出（JSON，不加密）",
            variable=self._mode_var,
            value="plaintext",
            command=self._on_mode_change,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            mode_frame,
            text="加密导出（AES-256-GCM，需密码）",
            variable=self._mode_var,
            value="encrypted",
            command=self._on_mode_change,
        ).pack(anchor=tk.W, pady=(4, 0))

        # 密码区域（加密模式时显示）
        self._password_frame = ttk.Frame(main)
        self._password_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(self._password_frame, text="密码：").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 4)
        )
        self._pwd_var = tk.StringVar()
        self._pwd_entry = ttk.Entry(
            self._password_frame, textvariable=self._pwd_var, show="*", width=30
        )
        self._pwd_entry.grid(row=0, column=1, sticky=tk.W, pady=(0, 4))

        ttk.Label(self._password_frame, text="确认密码：").grid(
            row=1, column=0, sticky=tk.W, pady=(0, 4)
        )
        self._pwd2_var = tk.StringVar()
        self._pwd2_entry = ttk.Entry(
            self._password_frame, textvariable=self._pwd2_var, show="*", width=30
        )
        self._pwd2_entry.grid(row=1, column=1, sticky=tk.W, pady=(0, 4))

        ttk.Label(
            self._password_frame,
            text="密码至少 4 位，忘记密码将无法恢复配置。",
            foreground="#888",
            font=("", 8),
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W)

        # 包含任务选项
        self._include_tasks_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            main,
            text="包含已保存的下载任务",
            variable=self._include_tasks_var,
        ).pack(anchor=tk.W, pady=(0, 12))

        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        self._export_btn = ttk.Button(
            btn_frame, text="导出", style="Primary.TButton", command=self._on_export
        )
        self._export_btn.pack(side=tk.RIGHT)

        # 初始状态：明文模式隐藏密码区
        self._on_mode_change()

    def _on_mode_change(self) -> None:
        """导出模式变化时显示/隐藏密码区域。"""
        if self._mode_var.get() == "encrypted":
            self._password_frame.pack(fill=tk.X, pady=(0, 12))
        else:
            self._password_frame.pack_forget()

    def _browse_path(self) -> None:
        """浏览选择导出路径。"""
        path = filedialog.asksaveasfilename(
            title="选择导出文件位置",
            defaultextension=".yunxcfg",
            initialfile="yunx_config.yunxcfg",
            filetypes=[("YunX 配置文件", "*.yunxcfg"), ("所有文件", "*.*")],
            parent=self,
        )
        if path:
            self._path_var.set(path)

    def _on_export(self) -> None:
        """执行导出。"""
        output_path = self._path_var.get().strip()
        if not output_path:
            messagebox.showwarning("提示", "请选择导出文件路径", parent=self)
            return

        password = None
        if self._mode_var.get() == "encrypted":
            pwd = self._pwd_var.get()
            pwd2 = self._pwd2_var.get()
            if len(pwd) < 4:
                messagebox.showwarning("提示", "密码至少 4 位", parent=self)
                return
            if pwd != pwd2:
                messagebox.showwarning("提示", "两次输入的密码不一致", parent=self)
                return
            password = pwd

        try:
            result_path = export_config(
                self._config,
                output_path,
                password=password,
                include_tasks=self._include_tasks_var.get(),
            )
            file_size = os.path.getsize(result_path)
            mode_text = "加密" if password else "明文"
            messagebox.showinfo(
                "导出成功",
                f"配置已{mode_text}导出到：\n{result_path}\n\n文件大小：{format_size(file_size)}",
                parent=self,
            )
            self.destroy()
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)

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


# ==================================================================
# 导入配置对话框
# ==================================================================

class ImportConfigDialog(tk.Toplevel):
    """配置导入对话框。

    流程：
    1. 用户选择 .yunxcfg 文件
    2. 自动检测是否加密
    3. 加密文件弹出密码输入（最多 3 次重试）
    4. 显示导入内容摘要
    5. 选择合并/替换模式
    6. 执行导入
    """

    def __init__(
        self,
        master: tk.Misc,
        config_manager: ConfigManager,
        on_imported: Any | None = None,
    ) -> None:
        """初始化导入对话框。

        Args:
            master: 父窗口。
            config_manager: 已解锁的 ConfigManager 实例。
            on_imported: 导入成功回调，无参数。
        """
        super().__init__(master)
        self.title("导入配置")
        self.geometry("520x440")
        self.minsize(480, 400)

        self._config = config_manager
        self._on_imported = on_imported
        self._imported_data: dict[str, Any] | None = None
        self._file_path: str = ""
        self._password_attempts = 0

        self.transient(master)
        self.grab_set()

        self._build_ui()
        self._center_on_parent(master)

        # 启动时先选择文件
        self.after(100, self._select_file)

    def _build_ui(self) -> None:
        """构建 UI。"""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # 文件路径
        ttk.Label(main, text="配置文件：").pack(anchor=tk.W, pady=(0, 4))
        path_frame = ttk.Frame(main)
        path_frame.pack(fill=tk.X, pady=(0, 8))
        self._path_var = tk.StringVar(value="（未选择文件）")
        ttk.Label(path_frame, textvariable=self._path_var, foreground="#666").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(path_frame, text="选择文件...", command=self._select_file, width=10).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        # 加密状态
        self._encrypt_var = tk.StringVar(value="")
        self._encrypt_label = ttk.Label(main, textvariable=self._encrypt_var)
        self._encrypt_label.pack(anchor=tk.W, pady=(0, 8))

        # 内容摘要
        summary_frame = ttk.LabelFrame(main, text="导入内容摘要", padding=8)
        summary_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self._summary_text = tk.Text(
            summary_frame, height=6, wrap=tk.WORD, state=tk.DISABLED,
            bg="#FAFAFA", relief=tk.FLAT, font=("", 9),
        )
        self._summary_text.pack(fill=tk.BOTH, expand=True)

        # 导入模式
        ttk.Label(main, text="导入模式：", font=("", 10, "bold")).pack(
            anchor=tk.W, pady=(0, 4)
        )
        self._mode_var = tk.StringVar(value="merge")
        mode_frame = ttk.Frame(main)
        mode_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Radiobutton(
            mode_frame,
            text="合并导入（保留现有配置，新凭证覆盖同名网盘）",
            variable=self._mode_var,
            value="merge",
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            mode_frame,
            text="替换导入（清空现有配置，仅保留导入内容）",
            variable=self._mode_var,
            value="replace",
        ).pack(anchor=tk.W, pady=(4, 0))

        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        self._import_btn = ttk.Button(
            btn_frame, text="导入", style="Primary.TButton",
            command=self._on_import, state=tk.DISABLED,
        )
        self._import_btn.pack(side=tk.RIGHT)

    def _select_file(self) -> None:
        """选择配置文件。"""
        path = filedialog.askopenfilename(
            title="选择配置文件",
            filetypes=[("YunX 配置文件", "*.yunxcfg"), ("所有文件", "*.*")],
            parent=self,
        )
        if not path:
            return

        self._file_path = path
        self._path_var.set(path)
        self._imported_data = None
        self._set_summary("")
        self._import_btn.config(state=tk.DISABLED)

        # 检测加密
        try:
            encrypted = is_encrypted(path)
            if encrypted:
                self._encrypt_var.set("🔒 该文件已加密，需要密码才能导入")
                self._encrypt_label.config(foreground="#FB8C00")
                self._request_password()
            else:
                self._encrypt_var.set("📄 明文配置文件")
                self._encrypt_label.config(foreground="#43A047")
                self._load_import_data(None)
        except Exception as exc:
            messagebox.showerror("错误", f"文件检测失败：{exc}", parent=self)

    def _request_password(self) -> None:
        """请求加密文件密码。"""
        dlg = _PasswordDialog(self, attempts=self._password_attempts)
        if not dlg.ok:
            self._encrypt_var.set("已取消密码输入")
            return

        self._load_import_data(dlg.password)

    def _load_import_data(self, password: str | None) -> None:
        """加载导入数据并显示摘要。

        Args:
            password: 解密密码（明文文件为 None）。
        """
        try:
            data = import_config(self._file_path, password=password)
            self._imported_data = data
            self._password_attempts = 0
            self._show_summary(data)
            self._import_btn.config(state=tk.NORMAL)
        except AuthenticationError:
            self._password_attempts += 1
            remaining = 3 - self._password_attempts
            if remaining > 0:
                messagebox.showerror(
                    "密码错误",
                    f"密码错误，还剩 {remaining} 次尝试机会。",
                    parent=self,
                )
                self._request_password()
            else:
                messagebox.showerror(
                    "密码错误",
                    "密码错误次数过多，导入已取消。",
                    parent=self,
                )
                self._encrypt_var.set("❌ 密码验证失败")
                self._encrypt_label.config(foreground="#E53935")
        except ValueError as exc:
            messagebox.showerror("文件格式错误", str(exc), parent=self)
            self._encrypt_var.set("❌ 文件格式无效")
            self._encrypt_label.config(foreground="#E53935")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)

    def _show_summary(self, data: dict[str, Any]) -> None:
        """显示导入内容摘要。

        Args:
            data: 导入的配置字典。
        """
        from ..utils import get_drive_display

        credentials = data.get("credentials", {})
        settings = data.get("settings", {})
        tasks = data.get("tasks", [])
        meta = data.get("meta", {})

        lines = []
        lines.append(f"网盘凭证：{len(credentials)} 个")
        for drive in credentials:
            lines.append(f"  - {get_drive_display(drive)} ({drive})")

        lines.append(f"\n设置项：{len(settings)} 项")
        for key in list(settings.keys())[:8]:
            lines.append(f"  - {key}")
        if len(settings) > 8:
            lines.append(f"  ... 还有 {len(settings) - 8} 项")

        lines.append(f"\n下载任务：{len(tasks)} 个")

        if meta:
            export_time = meta.get("export_time", "未知")
            lines.append(f"\n导出时间：{export_time}")
            lines.append(f"格式版本：{meta.get('format_version', '未知')}")

        self._set_summary("\n".join(lines))

    def _set_summary(self, text: str) -> None:
        """设置摘要文本。"""
        self._summary_text.config(state=tk.NORMAL)
        self._summary_text.delete("1.0", tk.END)
        self._summary_text.insert("1.0", text)
        self._summary_text.config(state=tk.DISABLED)

    def _on_import(self) -> None:
        """执行导入。"""
        if self._imported_data is None:
            return

        merge = self._mode_var.get() == "merge"

        if not merge:
            if not messagebox.askyesno(
                "确认替换",
                "替换导入将清空当前所有配置（凭证、设置、任务），\n"
                "此操作不可撤销，确定继续吗？",
                parent=self,
            ):
                return

        try:
            apply_imported_config(self._config, self._imported_data, merge=merge)
            messagebox.showinfo(
                "导入成功",
                "配置已成功导入！\n\n账号列表和设置将自动刷新。",
                parent=self,
            )
            if self._on_imported:
                self._on_imported()
            self.destroy()
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)

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


class _PasswordDialog(tk.Toplevel):
    """密码输入对话框（用于加密配置文件导入）。"""

    def __init__(self, master: tk.Misc, attempts: int = 0) -> None:
        super().__init__(master)
        self.title("输入密码")
        self.resizable(False, False)
        self.ok = False
        self.password = ""

        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="该配置文件已加密，请输入密码：",
            wraplength=280,
        ).pack(pady=(0, 8))

        if attempts > 0:
            ttk.Label(
                frame,
                text=f"已错误 {attempts} 次，最多 3 次。",
                foreground="#E53935",
                font=("", 9),
            ).pack(pady=(0, 8))

        self._entry = ttk.Entry(frame, show="*", width=30)
        self._entry.pack(pady=(0, 12))
        self._entry.focus_set()
        self._entry.bind("<Return>", lambda _e: self._on_ok())

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
