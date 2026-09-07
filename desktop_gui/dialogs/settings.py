"""
设置对话框。

配置默认保存路径、默认并发数、默认分片大小、剪贴板自动监听开关、
下载完成提示音开关、主题选择。
设置通过 ConfigManager 的通用配置接口持久化。
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from core.config import ConfigManager
from core.exceptions import AuthenticationError

# 默认配置值
DEFAULT_SAVE_PATH = str(Path.home() / "Downloads" / "YunX")
DEFAULT_CONCURRENCY = 8
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024  # 4MB
DEFAULT_CLIPBOARD_MONITOR = False
DEFAULT_SOUND_NOTIFY = True
DEFAULT_THEME = "light"

# 分片大小选项（显示名 → 字节数）
CHUNK_SIZE_OPTIONS: dict[str, int] = {
    "1 MB": 1 * 1024 * 1024,
    "2 MB": 2 * 1024 * 1024,
    "4 MB": 4 * 1024 * 1024,
    "8 MB": 8 * 1024 * 1024,
}

# 主题选项
THEME_OPTIONS = ["浅色", "深色（实验性）"]


class SettingsDialog(tk.Toplevel):
    """设置对话框。

    所有设置项通过 ConfigManager 的 set/get 接口持久化到加密配置文件。
    """

    def __init__(self, master: tk.Misc, config: ConfigManager | None = None) -> None:
        """初始化设置对话框。

        Args:
            master: 父窗口。
            config: 已解锁的 ConfigManager 实例；为 None 时使用默认值且不持久化。
        """
        super().__init__(master)
        self.title("设置")
        self.geometry("480x420")
        self.minsize(420, 380)
        self.resizable(False, False)

        self._config = config
        self._result: dict[str, Any] | None = None

        self._build_ui()
        self._load_settings()
        self._center_on_parent(master)

        self.transient(master)
        self.grab_set()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        row = 0

        # 默认保存路径
        ttk.Label(main, text="默认保存路径：").grid(
            row=row, column=0, sticky=tk.W, pady=(0, 6)
        )
        path_frame = ttk.Frame(main)
        path_frame.grid(row=row, column=1, sticky=tk.EW, pady=(0, 6))
        self._path_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self._path_var, width=28).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(path_frame, text="浏览...", command=self._browse_path).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        row += 1

        # 默认并发数
        ttk.Label(main, text="默认并发数：").grid(
            row=row, column=0, sticky=tk.W, pady=(0, 6)
        )
        conc_frame = ttk.Frame(main)
        conc_frame.grid(row=row, column=1, sticky=tk.W, pady=(0, 6))
        self._conc_var = tk.IntVar(value=DEFAULT_CONCURRENCY)
        self._conc_scale = ttk.Scale(
            conc_frame,
            from_=1,
            to=32,
            orient=tk.HORIZONTAL,
            variable=self._conc_var,
            length=180,
            command=self._on_conc_change,
        )
        self._conc_scale.pack(side=tk.LEFT)
        self._conc_label = ttk.Label(conc_frame, text=f"{DEFAULT_CONCURRENCY}", width=4)
        self._conc_label.pack(side=tk.LEFT, padx=(8, 0))
        row += 1

        # 默认分片大小
        ttk.Label(main, text="默认分片大小：").grid(
            row=row, column=0, sticky=tk.W, pady=(0, 6)
        )
        self._chunk_var = tk.StringVar()
        self._chunk_combo = ttk.Combobox(
            main,
            textvariable=self._chunk_var,
            values=list(CHUNK_SIZE_OPTIONS.keys()),
            state="readonly",
            width=15,
        )
        self._chunk_combo.grid(row=row, column=1, sticky=tk.W, pady=(0, 6))
        row += 1

        # 分隔线
        ttk.Separator(main, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=8
        )
        row += 1

        # 剪贴板自动监听
        self._clipboard_var = tk.BooleanVar(value=DEFAULT_CLIPBOARD_MONITOR)
        ttk.Checkbutton(
            main,
            text="启用剪贴板自动监听（复制分享链接时自动填充）",
            variable=self._clipboard_var,
        ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 6))
        row += 1

        # 下载完成提示音
        self._sound_var = tk.BooleanVar(value=DEFAULT_SOUND_NOTIFY)
        ttk.Checkbutton(
            main,
            text="下载完成时播放提示音",
            variable=self._sound_var,
        ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 6))
        row += 1

        # 主题选择
        ttk.Label(main, text="界面主题：").grid(
            row=row, column=0, sticky=tk.W, pady=(0, 6)
        )
        self._theme_var = tk.StringVar()
        self._theme_combo = ttk.Combobox(
            main,
            textvariable=self._theme_var,
            values=THEME_OPTIONS,
            state="readonly",
            width=15,
        )
        self._theme_combo.grid(row=row, column=1, sticky=tk.W, pady=(0, 6))
        row += 1

        # 分隔线
        ttk.Separator(main, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=8
        )
        row += 1

        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=(4, 0))
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="保存", command=self._on_save).pack(
            side=tk.RIGHT
        )

        # 列权重
        main.columnconfigure(1, weight=1)

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

    def _on_conc_change(self, _value: str) -> None:
        """并发数滑块变化时更新标签。"""
        self._conc_label.config(text=str(self._conc_var.get()))

    def _browse_path(self) -> None:
        """浏览选择保存路径。"""
        path = filedialog.askdirectory(
            title="选择默认保存目录",
            initialdir=self._path_var.get() or str(Path.home()),
            parent=self,
        )
        if path:
            self._path_var.set(path)

    def _load_settings(self) -> None:
        """从 ConfigManager 加载设置。"""
        self._path_var.set(DEFAULT_SAVE_PATH)
        self._conc_var.set(DEFAULT_CONCURRENCY)
        self._chunk_var.set("4 MB")
        self._theme_var.set("浅色")

        if self._config is None:
            return

        try:
            self._path_var.set(
                self._config.get("save_path", DEFAULT_SAVE_PATH)
            )
            self._conc_var.set(
                int(self._config.get("concurrency", DEFAULT_CONCURRENCY))
            )
            chunk = int(self._config.get("chunk_size", DEFAULT_CHUNK_SIZE))
            # 反查显示名
            for name, size in CHUNK_SIZE_OPTIONS.items():
                if size == chunk:
                    self._chunk_var.set(name)
                    break
            self._clipboard_var.set(
                bool(self._config.get("clipboard_monitor", DEFAULT_CLIPBOARD_MONITOR))
            )
            self._sound_var.set(
                bool(self._config.get("sound_notify", DEFAULT_SOUND_NOTIFY))
            )
            self._theme_var.set(
                self._config.get("theme", "浅色")
            )
        except Exception:
            pass  # 加载失败时使用默认值

    def _on_save(self) -> None:
        """保存设置。"""
        save_path = self._path_var.get().strip()
        if not save_path:
            messagebox.showwarning("提示", "请填写保存路径", parent=self)
            return

        # 确保目录存在
        try:
            os.makedirs(save_path, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("错误", f"无法创建目录：{exc}", parent=self)
            return

        concurrency = int(self._conc_var.get())
        chunk_size = CHUNK_SIZE_OPTIONS.get(
            self._chunk_var.get(), DEFAULT_CHUNK_SIZE
        )

        self._result = {
            "save_path": save_path,
            "concurrency": concurrency,
            "chunk_size": chunk_size,
            "clipboard_monitor": self._clipboard_var.get(),
            "sound_notify": self._sound_var.get(),
            "theme": self._theme_var.get(),
        }

        # 持久化
        if self._config is not None:
            try:
                for key, value in self._result.items():
                    self._config.set(key, value)
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc), parent=self)
                return

        self.destroy()

    def get_settings(self) -> dict[str, Any] | None:
        """获取保存后的设置。

        Returns:
            设置字典；用户取消时返回 None。
        """
        return self._result
