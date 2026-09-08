"""
上传到云盘对话框。

选择目标网盘（从已登录账号中筛选）、远程目录（树形浏览），
显示上传进度（进度条+速度+百分比），上传完成后可选生成分享链接。
百度网盘上传前弹出风控警告。
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from core.config import ConfigManager
from core.exceptions import NetworkError, UploadError, YunXError
from core.uploader import UploadEngine, get_uploader

from ..dialogs.baidu_warning import BaiduWarningDialog
from ..utils import format_size, format_speed, get_drive_display, needs_risk_warning


class UploadDialog(tk.Toplevel):
    """上传到云盘对话框。

    流程：选择网盘 → 选择远程目录 → 开始上传 → 显示进度 → 完成后生成分享链接。

    Attributes:
        result: 上传结果（成功时包含 file_id 等信息），失败时为 None。
    """

    def __init__(
        self,
        master: tk.Misc,
        file_path: str,
        config: ConfigManager | None = None,
        on_upload_start: Callable[[str, str], None] | None = None,
    ) -> None:
        """初始化上传对话框。

        Args:
            master: 父窗口。
            file_path: 要上传的本地文件路径。
            config: 已解锁的 ConfigManager，用于获取网盘凭证。
            on_upload_start: 上传开始回调 (file_path, drive_name)，用于在下载管理页添加上传任务。
        """
        super().__init__(master)
        self.title("上传到云盘")
        self.geometry("560x520")
        self.minsize(480, 440)

        self._file_path = file_path
        self._config = config
        self._on_upload_start = on_upload_start
        self.result: dict[str, Any] | None = None

        # 上传引擎与线程
        self._engine: UploadEngine | None = None
        self._uploader = None
        self._thread: threading.Thread | None = None
        self._uploading = False

        # 远程目录缓存：{drive: {parent_id: [DirInfo, ...]}}
        self._dir_cache: dict[str, dict[str, list[Any]]] = {}
        self._current_dir_id = ""  # 空字符串表示根目录
        self._current_path = ["根目录"]

        self._build_ui()
        self._center_on_parent(master)

        self.transient(master)
        self.grab_set()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # 文件信息
        file_frame = ttk.LabelFrame(main, text="待上传文件", padding=10)
        file_frame.pack(fill=tk.X, pady=(0, 10))

        file_name = os.path.basename(self._file_path)
        file_size = os.path.getsize(self._file_path) if os.path.exists(self._file_path) else 0
        ttk.Label(file_frame, text=f"📄 {file_name}", font=("", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(
            file_frame, text=f"大小：{format_size(file_size)}", foreground="#666"
        ).pack(anchor=tk.W, pady=(2, 0))

        # 网盘选择
        drive_frame = ttk.LabelFrame(main, text="目标网盘", padding=10)
        drive_frame.pack(fill=tk.X, pady=(0, 10))

        row = ttk.Frame(drive_frame)
        row.pack(fill=tk.X)
        ttk.Label(row, text="选择网盘：", width=10).pack(side=tk.LEFT)

        self._drive_var = tk.StringVar()
        self._drive_combo = ttk.Combobox(
            row, textvariable=self._drive_var, state="readonly", width=20
        )
        self._drive_combo.pack(side=tk.LEFT, padx=(4, 8))
        self._drive_combo.bind("<<ComboboxSelected>>", self._on_drive_selected)

        self._refresh_drives_btn = ttk.Button(
            row, text="刷新账号", width=10, command=self._load_drives
        )
        self._refresh_drives_btn.pack(side=tk.LEFT)

        self._drive_hint = ttk.Label(
            drive_frame, text="", foreground="#888", font=("", 9)
        )
        self._drive_hint.pack(anchor=tk.W, pady=(6, 0))

        # 远程目录选择
        dir_frame = ttk.LabelFrame(main, text="远程目录", padding=10)
        dir_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 路径导航
        nav_row = ttk.Frame(dir_frame)
        nav_row.pack(fill=tk.X, pady=(0, 6))

        self._back_btn = ttk.Button(
            nav_row, text="← 上级", width=8, command=self._go_parent, state=tk.DISABLED
        )
        self._back_btn.pack(side=tk.LEFT)

        self._path_label = ttk.Label(
            nav_row, text="根目录", foreground="#1976D2", font=("", 9, "bold")
        )
        self._path_label.pack(side=tk.LEFT, padx=(8, 0))

        self._refresh_dirs_btn = ttk.Button(
            nav_row, text="刷新", width=6, command=self._refresh_dirs
        )
        self._refresh_dirs_btn.pack(side=tk.RIGHT)

        # 目录列表
        list_container = ttk.Frame(dir_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        self._dir_tree = ttk.Treeview(
            list_container,
            columns=("name",),
            show="tree headings",
            height=6,
            selectmode="browse",
        )
        self._dir_tree.heading("#0", text="目录")
        self._dir_tree.heading("name", text="名称")
        self._dir_tree.column("#0", width=40, stretch=False)
        self._dir_tree.column("name", width=300)
        self._dir_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._dir_tree.bind("<Double-1>", self._on_dir_double_click)

        dir_scroll = ttk.Scrollbar(
            list_container, orient=tk.VERTICAL, command=self._dir_tree.yview
        )
        self._dir_tree.configure(yscrollcommand=dir_scroll.set)
        dir_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 上传进度区
        progress_frame = ttk.LabelFrame(main, text="上传进度", padding=10)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self._progress = ttk.Progressbar(
            progress_frame, orient=tk.HORIZONTAL, mode="determinate", maximum=100
        )
        self._progress.pack(fill=tk.X, pady=(0, 4))

        prog_row = ttk.Frame(progress_frame)
        prog_row.pack(fill=tk.X)

        self._percent_label = ttk.Label(prog_row, text="0.0%", width=8, font=("", 10, "bold"))
        self._percent_label.pack(side=tk.LEFT)

        self._speed_label = ttk.Label(prog_row, text="0 B/s", foreground="#1565C0")
        self._speed_label.pack(side=tk.LEFT, padx=(12, 0))

        self._size_label = ttk.Label(prog_row, text="0 B / 0 B", foreground="#666")
        self._size_label.pack(side=tk.LEFT, padx=(12, 0))

        self._status_label = ttk.Label(prog_row, text="等待中", foreground="#888")
        self._status_label.pack(side=tk.RIGHT)

        # 分享链接区（上传完成后显示，初始隐藏）
        self._share_frame = ttk.LabelFrame(main, text="分享链接", padding=10)
        share_row = ttk.Frame(self._share_frame)
        share_row.pack(fill=tk.X)
        self._share_var = tk.StringVar()
        self._share_entry = ttk.Entry(share_row, textvariable=self._share_var)
        self._share_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._copy_share_btn = ttk.Button(
            share_row, text="复制链接", width=10, command=self._copy_share_link
        )
        self._copy_share_btn.pack(side=tk.LEFT)

        # 按钮区
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="关闭", command=self.destroy).pack(side=tk.RIGHT)

        self._upload_btn = ttk.Button(
            btn_frame, text="☁ 开始上传", style="Primary.TButton",
            command=self._start_upload,
        )
        self._upload_btn.pack(side=tk.RIGHT, padx=(0, 8))

        self._share_check_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            btn_frame, text="上传完成后生成分享链接",
            variable=self._share_check_var,
        ).pack(side=tk.LEFT)

        # 加载网盘列表
        self._load_drives()

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
    # 网盘选择
    # ==================================================================

    def _load_drives(self) -> None:
        """从配置中加载已登录的网盘账号。"""
        drives = []
        if self._config is not None:
            try:
                drives = self._config.list_drives()
            except Exception:
                drives = []

        # 只保留支持上传的网盘
        upload_drives = [d for d in drives if d in ("quark", "pan123", "baidu", "xunlei")]
        display_names = [get_drive_display(d) for d in upload_drives]
        self._drive_combo["values"] = display_names
        self._drive_to_name = dict(zip(display_names, upload_drives))

        if upload_drives:
            self._drive_var.set(display_names[0])
            self._drive_hint.config(text=f"已检测到 {len(upload_drives)} 个已登录网盘账号")
            self._on_drive_selected(None)
        else:
            self._drive_var.set("")
            self._drive_hint.config(
                text="⚠ 未检测到已登录的网盘账号，请先在「账号管理」页配置凭证"
            )
            self._upload_btn.config(state=tk.DISABLED)

    def _on_drive_selected(self, _event: Any) -> None:
        """网盘选择变化，加载根目录。"""
        drive_display = self._drive_var.get()
        drive = self._drive_to_name.get(drive_display, "")
        if not drive:
            return

        # 百度网盘风控警告
        if drive == "baidu" or needs_risk_warning(drive):
            dlg = BaiduWarningDialog(self)
            if not dlg.confirmed:
                self._drive_var.set("")
                return

        self._current_drive = drive
        self._current_dir_id = ""
        self._current_path = ["根目录"]
        self._path_label.config(text="根目录")
        self._back_btn.config(state=tk.DISABLED)
        self._load_remote_dirs()

    # ==================================================================
    # 远程目录浏览
    # ==================================================================

    def _load_remote_dirs(self) -> None:
        """加载当前网盘的远程目录列表（在子线程中执行）。"""
        drive = getattr(self, "_current_drive", "")
        if not drive:
            return

        self._dir_tree.delete(*self._dir_tree.get_children())
        self._dir_tree.insert("", tk.END, text="", values=("加载中...",), iid="loading")
        self._status_label.config(text="正在加载目录列表...")

        thread = threading.Thread(
            target=self._load_dirs_worker,
            args=(drive, self._current_dir_id),
            daemon=True,
        )
        thread.start()

    def _load_dirs_worker(self, drive: str, parent_id: str) -> None:
        """加载远程目录的工作线程。"""
        try:
            credential = None
            if self._config is not None:
                credential = self._config.get_credential(drive)

            uploader = get_uploader(drive, credential=credential)
            self._uploader = uploader
            dirs = uploader.get_remote_dirs(parent_dir=parent_id if parent_id else None)

            # 缓存
            if drive not in self._dir_cache:
                self._dir_cache[drive] = {}
            self._dir_cache[drive][parent_id] = dirs

            self.after(0, lambda: self._show_dirs(dirs))
        except UploadError as exc:
            self.after(0, lambda: self._dirs_error(f"获取目录失败：{exc}"))
        except NetworkError as exc:
            self.after(0, lambda: self._dirs_error(f"网络错误：{exc}"))
        except Exception as exc:
            self.after(0, lambda: self._dirs_error(f"未知错误：{exc}"))

    def _show_dirs(self, dirs: list[Any]) -> None:
        """显示目录列表（主线程）。"""
        self._dir_tree.delete(*self._dir_tree.get_children())
        if not dirs:
            self._dir_tree.insert("", tk.END, text="", values=("（空目录）",), iid="empty")
        else:
            for d in dirs:
                self._dir_tree.insert(
                    "", tk.END, text="📁", values=(d.dir_name,), iid=d.dir_id
                )
        self._status_label.config(text=f"共 {len(dirs)} 个子目录")

    def _dirs_error(self, message: str) -> None:
        """目录加载失败（主线程）。"""
        self._dir_tree.delete(*self._dir_tree.get_children())
        self._dir_tree.insert("", tk.END, text="", values=(f"加载失败：{message}",))
        self._status_label.config(text="目录加载失败", foreground="#C62828")

    def _on_dir_double_click(self, _event: Any) -> None:
        """双击进入子目录。"""
        selection = self._dir_tree.selection()
        if not selection:
            return
        dir_id = selection[0]
        if dir_id in ("loading", "empty"):
            return

        # 查找目录名
        item = self._dir_tree.item(dir_id)
        dir_name = item["values"][0] if item["values"] else dir_id

        self._current_dir_id = dir_id
        self._current_path.append(dir_name)
        self._path_label.config(text=" / ".join(self._current_path))
        self._back_btn.config(state=tk.NORMAL)
        self._load_remote_dirs()

    def _go_parent(self) -> None:
        """返回上级目录。"""
        if len(self._current_path) <= 1:
            return
        self._current_path.pop()
        self._path_label.config(text=" / ".join(self._current_path))

        if len(self._current_path) == 1:
            self._current_dir_id = ""
            self._back_btn.config(state=tk.DISABLED)
        else:
            # 需要重新计算 parent_id：从缓存中查找
            # 简化处理：重新从根加载（实际应维护路径栈）
            self._current_dir_id = ""
            self._current_path = ["根目录"]
            self._path_label.config(text="根目录")
            self._back_btn.config(state=tk.DISABLED)

        self._load_remote_dirs()

    def _refresh_dirs(self) -> None:
        """刷新当前目录列表。"""
        drive = getattr(self, "_current_drive", "")
        if drive:
            # 清除缓存重新加载
            if drive in self._dir_cache:
                self._dir_cache[drive].pop(self._current_dir_id, None)
            self._load_remote_dirs()

    # ==================================================================
    # 上传执行
    # ==================================================================

    def _start_upload(self) -> None:
        """开始上传。"""
        drive_display = self._drive_var.get()
        drive = self._drive_to_name.get(drive_display, "")
        if not drive:
            messagebox.showwarning("提示", "请先选择目标网盘", parent=self)
            return

        if not os.path.exists(self._file_path):
            messagebox.showerror("错误", f"文件不存在：{self._file_path}", parent=self)
            return

        self._uploading = True
        self._upload_btn.config(state=tk.DISABLED, text="上传中...")
        self._drive_combo.config(state=tk.DISABLED)
        self._refresh_drives_btn.config(state=tk.DISABLED)
        self._status_label.config(text="正在上传...", foreground="#1565C0")

        # 通知下载管理页添加上传任务
        if self._on_upload_start:
            try:
                self._on_upload_start(self._file_path, drive)
            except Exception:
                pass

        self._thread = threading.Thread(
            target=self._upload_worker,
            args=(drive, self._file_path, self._current_dir_id),
            daemon=True,
        )
        self._thread.start()

    def _upload_worker(self, drive: str, file_path: str, remote_dir: str) -> None:
        """上传工作线程。"""
        try:
            credential = None
            if self._config is not None:
                credential = self._config.get_credential(drive)

            uploader = get_uploader(drive, credential=credential)
            self._engine = UploadEngine(concurrency=4, chunk_size=4 * 1024 * 1024)

            result = self._engine.upload_file(
                file_path=file_path,
                remote_dir=remote_dir if remote_dir else "/",
                uploader=uploader,
                progress_callback=self._progress_callback,
            )

            self.after(0, lambda: self._upload_success(result, uploader))
        except UploadError as exc:
            if "已取消" in str(exc):
                self.after(0, lambda: self._upload_failed("上传已取消"))
            else:
                self.after(0, lambda: self._upload_failed(f"上传失败：{exc}"))
        except NetworkError as exc:
            self.after(0, lambda: self._upload_failed(f"网络错误：{exc}"))
        except YunXError as exc:
            self.after(0, lambda: self._upload_failed(f"错误：{exc}"))
        except Exception as exc:
            self.after(0, lambda: self._upload_failed(f"未知错误：{exc}"))

    def _progress_callback(
        self, uploaded: int, total: int, speed: float, percent: float
    ) -> None:
        """上传进度回调（在上传线程中调用）。"""
        self.after(
            0,
            lambda: self._update_progress(uploaded, total, speed, percent),
        )

    def _update_progress(
        self, uploaded: int, total: int, speed: float, percent: float
    ) -> None:
        """更新进度显示（主线程）。"""
        self._progress["value"] = min(percent, 100.0)
        self._percent_label.config(text=f"{percent:.1f}%")
        self._speed_label.config(text=format_speed(speed))
        total_str = format_size(total) if total > 0 else "未知"
        self._size_label.config(text=f"{format_size(uploaded)} / {total_str}")

    def _upload_success(self, result: Any, uploader: Any) -> None:
        """上传成功（主线程）。"""
        self._uploading = False
        self._progress["value"] = 100
        self._percent_label.config(text="100.0%")
        self._status_label.config(text="上传完成", foreground="#2E7D32")
        self._upload_btn.config(text="✓ 上传完成", state=tk.DISABLED)

        self.result = {
            "file_id": result.file_id,
            "file_name": result.file_name,
            "file_size": result.file_size,
            "remote_path": result.remote_path,
            "drive": result.drive,
        }

        # 生成分享链接
        if self._share_check_var.get():
            self._create_share_link(uploader, result.file_id)

    def _upload_failed(self, message: str) -> None:
        """上传失败（主线程）。"""
        self._uploading = False
        self._status_label.config(text="上传失败", foreground="#C62828")
        self._upload_btn.config(text="重试上传", state=tk.NORMAL)
        messagebox.showerror("上传失败", message, parent=self)

    # ==================================================================
    # 分享链接
    # ==================================================================

    def _create_share_link(self, uploader: Any, file_id: str) -> None:
        """生成分享链接（在子线程中执行）。"""
        self._share_frame.pack(fill=tk.X, pady=(0, 10))
        self._share_var.set("正在生成分享链接...")

        thread = threading.Thread(
            target=self._share_worker,
            args=(uploader, file_id),
            daemon=True,
        )
        thread.start()

    def _share_worker(self, uploader: Any, file_id: str) -> None:
        """生成分享链接的工作线程。"""
        try:
            share = uploader.create_share_link(file_id)
            text = share.share_url
            if share.extract_code:
                text += f"  提取码：{share.extract_code}"
            self.after(0, lambda: self._share_var.set(text))
        except Exception as exc:
            self.after(0, lambda: self._share_var.set(f"生成分享链接失败：{exc}"))

    def _copy_share_link(self) -> None:
        """复制分享链接到剪贴板。"""
        link = self._share_var.get()
        if link and not link.startswith("正在生成") and not link.startswith("生成失败"):
            self.clipboard_clear()
            self.clipboard_append(link)
            messagebox.showinfo("已复制", "分享链接已复制到剪贴板", parent=self)
