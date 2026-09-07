"""
YunX 桌面端主应用类。

整合所有 UI 组件，管理解析/下载线程，处理菜单事件和设置。
所有耗时操作（解析、下载）在子线程中运行，通过 root.after() 更新 UI。
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from core import (
    AuthenticationError,
    BaiduRiskWarning,
    DownloadError,
    NetworkError,
    ParserError,
    YunXError,
)
from core.config import ConfigManager
from core.parsers.base import ShareInfo, get_parser
from core.clipboard import detect_share_url

from . import __app_name__, __version__
from .dialogs.account_manager import AccountManagerDialog
from .dialogs.baidu_warning import BaiduWarningDialog
from .dialogs.settings import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CONCURRENCY,
    DEFAULT_SAVE_PATH,
    CHUNK_SIZE_OPTIONS,
    SettingsDialog,
)
from .utils import (
    format_size,
    get_drive_color,
    get_drive_display,
    needs_risk_warning,
)
from .widgets.download_task import (
    STATUS_COMPLETED,
    DownloadTaskWidget,
)
from .widgets.file_list import FileListWidget
from .widgets.status_bar import StatusBarWidget
from .widgets.url_input import URLInputWidget


class YunXApp(tk.Tk):
    """YunX 桌面端主应用。

    整合 URL 输入、文件列表、下载控制、下载任务管理、状态栏和菜单栏。
    解析和下载均在子线程中执行，不阻塞 UI。
    """

    def __init__(self) -> None:
        """初始化主应用。"""
        super().__init__()

        # 窗口基本设置
        self.title(f"{__app_name__} - 全平台网盘解析下载器 v{__version__}")
        self.geometry("960x720")
        self.minsize(900, 650)

        # 配置管理器（延迟初始化，需要主密码解锁）
        self._config: ConfigManager | None = None

        # 当前设置
        self._save_path = DEFAULT_SAVE_PATH
        self._concurrency = DEFAULT_CONCURRENCY
        self._chunk_size = DEFAULT_CHUNK_SIZE
        self._clipboard_monitor = False
        self._sound_notify = True
        self._theme = "浅色"

        # 解析结果缓存
        self._current_share_infos: list[ShareInfo] = []
        self._current_drive = ""

        # 下载任务列表
        self._download_tasks: list[DownloadTaskWidget] = []

        # 剪贴板监听
        self._last_clipboard = ""
        self._clipboard_polling = False

        # 构建 UI
        # 菜单栏在某些虚拟帧缓冲（Xvfb）环境下可能因 XCB 问题崩溃，
        # 真实桌面环境不受影响；此处容错降级，无菜单时应用仍可运行。
        try:
            self._build_menu()
        except Exception:
            pass
        self._build_ui()
        self._configure_styles()

        # 尝试自动加载设置（如果配置文件存在且无需密码）
        self._try_load_settings()

        # 确保默认下载目录存在
        os.makedirs(self._save_path, exist_ok=True)

    # ==================================================================
    # UI 构建
    # ==================================================================

    def _configure_styles(self) -> None:
        """配置 ttk 样式。"""
        style = ttk.Style(self)
        # 使用系统默认主题
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # 进度条颜色样式（通过 ttk 样式近似实现）
        style.configure(
            "Download.Horizontal.TProgressbar",
            troughcolor="#E0E0E0",
            background="#1E88E5",
        )
        style.configure(
            "Paused.Horizontal.TProgressbar",
            troughcolor="#E0E0E0",
            background="#F9A825",
        )
        style.configure(
            "Completed.Horizontal.TProgressbar",
            troughcolor="#E0E0E0",
            background="#43A047",
        )
        style.configure(
            "Error.Horizontal.TProgressbar",
            troughcolor="#E0E0E0",
            background="#E53935",
        )

    def _build_menu(self) -> None:
        """构建菜单栏。"""
        menubar = tk.Menu(self)

        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="设置保存路径...", command=self._menu_set_save_path)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        # 工具菜单
        tools_menu = tk.Menu(menubar, tearoff=0)
        self._clipboard_monitor_var = tk.BooleanVar(value=False)
        tools_menu.add_checkbutton(
            label="剪贴板监听",
            variable=self._clipboard_monitor_var,
            command=self._toggle_clipboard_monitor,
        )
        tools_menu.add_command(label="清理临时转存文件", command=self._menu_clean_temp)
        tools_menu.add_command(label="打开下载目录", command=self._menu_open_download_dir)
        menubar.add_cascade(label="工具", menu=tools_menu)

        # 账号菜单
        account_menu = tk.Menu(menubar, tearoff=0)
        account_menu.add_command(label="管理网盘账号...", command=self._menu_account_manager)
        menubar.add_cascade(label="账号", menu=account_menu)

        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._menu_help)
        help_menu.add_command(label="关于", command=self._menu_about)
        help_menu.add_command(label="免责声明", command=self._menu_disclaimer)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.config(menu=menubar)

    def _build_ui(self) -> None:
        """构建主界面布局。"""
        # 主容器
        main = ttk.Frame(self, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ---- 顶部标题栏 ----
        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            header,
            text=f"{__app_name__}",
            font=("", 16, "bold"),
            foreground="#1565C0",
        ).pack(side=tk.LEFT)
        ttk.Label(
            header,
            text=f"  v{__version__}  |  全平台网盘解析下载器",
            font=("", 10),
            foreground="#666",
        ).pack(side=tk.LEFT, pady=(6, 0))

        # ---- URL 输入区 ----
        self._url_input = URLInputWidget(main, on_parse=self._on_parse)
        self._url_input.pack(fill=tk.X, pady=(0, 8))

        # ---- 文件列表区 ----
        self._file_list = FileListWidget(main)
        self._file_list.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # ---- 下载控制区 ----
        control_frame = ttk.LabelFrame(main, text="下载控制", padding=8)
        control_frame.pack(fill=tk.X, pady=(0, 8))

        # 第一行：下载按钮
        btn_row = ttk.Frame(control_frame)
        btn_row.pack(fill=tk.X, pady=(0, 6))

        self._download_selected_btn = ttk.Button(
            btn_row, text="下载选中", command=self._on_download_selected
        )
        self._download_selected_btn.pack(side=tk.LEFT)

        self._download_all_btn = ttk.Button(
            btn_row, text="全部下载", command=self._on_download_all
        )
        self._download_all_btn.pack(side=tk.LEFT, padx=(6, 0))

        # 保存路径
        path_row = ttk.Frame(btn_row)
        path_row.pack(side=tk.LEFT, padx=(16, 0), fill=tk.X, expand=True)
        ttk.Label(path_row, text="保存到：").pack(side=tk.LEFT)
        self._save_path_var = tk.StringVar(value=self._save_path)
        ttk.Entry(path_row, textvariable=self._save_path_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4)
        )
        ttk.Button(path_row, text="...", width=3, command=self._browse_save_path).pack(
            side=tk.LEFT
        )

        # 第二行：并发数 + 分片大小
        opt_row = ttk.Frame(control_frame)
        opt_row.pack(fill=tk.X)

        ttk.Label(opt_row, text="并发数：").pack(side=tk.LEFT)
        self._concurrency_var = tk.IntVar(value=self._concurrency)
        self._concurrency_scale = ttk.Scale(
            opt_row,
            from_=1,
            to=32,
            orient=tk.HORIZONTAL,
            variable=self._concurrency_var,
            length=120,
            command=self._on_concurrency_change,
        )
        self._concurrency_scale.pack(side=tk.LEFT)
        self._concurrency_label = ttk.Label(
            opt_row, text=f"{self._concurrency}", width=4
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
        # 设置默认值
        for name, size in CHUNK_SIZE_OPTIONS.items():
            if size == self._chunk_size:
                self._chunk_var.set(name)
                break
        self._chunk_combo.pack(side=tk.LEFT, padx=(4, 0))

        # ---- 下载任务区 ----
        tasks_frame = ttk.LabelFrame(main, text="下载任务", padding=6)
        tasks_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # 可滚动的任务容器
        self._tasks_canvas = tk.Canvas(tasks_frame, height=160, highlightthickness=0)
        tasks_scrollbar = ttk.Scrollbar(
            tasks_frame, orient=tk.VERTICAL, command=self._tasks_canvas.yview
        )
        self._tasks_scroll_frame = ttk.Frame(self._tasks_canvas)

        self._tasks_scroll_frame.bind(
            "<Configure>",
            lambda e: self._tasks_canvas.configure(
                scrollregion=self._tasks_canvas.bbox("all")
            ),
        )
        self._tasks_canvas.create_window(
            (0, 0), window=self._tasks_scroll_frame, anchor="nw"
        )
        self._tasks_canvas.configure(yscrollcommand=tasks_scrollbar.set)

        self._tasks_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tasks_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 空任务提示
        self._empty_tasks_label = ttk.Label(
            self._tasks_scroll_frame,
            text="暂无下载任务",
            foreground="#999",
        )
        self._empty_tasks_label.pack(pady=20)

        # ---- 状态栏 ----
        self._status_bar = StatusBarWidget(self)
        self._status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # 启动总速度轮询
        self._schedule_speed_update()

    # ==================================================================
    # 解析流程
    # ==================================================================

    def _on_parse(self, url: str, extract_code: str | None) -> None:
        """处理解析按钮点击。

        Args:
            url: 分享链接。
            extract_code: 提取码。
        """
        if not url:
            messagebox.showwarning("提示", "请输入分享链接", parent=self)
            return

        # 识别网盘类型
        try:
            detected = detect_share_url(url)
            drive = detected[0].drive if detected else ""
        except Exception:
            drive = ""

        # 百度网盘风控警告
        if drive == "baidu" or needs_risk_warning(drive):
            dlg = BaiduWarningDialog(self)
            if not dlg.confirmed:
                self._status_bar.set_status("用户取消百度网盘解析")
                return

        # 禁用解析按钮
        self._url_input.set_parsing(True)
        self._status_bar.set_status("正在解析...")

        # 在子线程中执行解析
        thread = threading.Thread(
            target=self._parse_worker,
            args=(url, extract_code),
            daemon=True,
        )
        thread.start()

    def _parse_worker(self, url: str, extract_code: str | None) -> None:
        """解析工作线程。

        Args:
            url: 分享链接。
            extract_code: 提取码。
        """
        try:
            # 获取对应网盘的凭证（如果已配置）
            credential = None
            if self._config is not None:
                detected = detect_share_url(url)
                if detected:
                    drive = detected[0].drive
                    credential = self._config.get_credential(drive)

            # 获取解析器
            parser = get_parser(url, credential=credential)
            share_info = parser.parse_share_url(url, extract_code=extract_code)

            # 成功，回到主线程更新 UI
            self.after(0, lambda: self._parse_success(share_info, parser.drive_name))

        except ParserError as exc:
            self.after(0, lambda: self._parse_error(f"解析失败：{exc}"))
        except NetworkError as exc:
            self.after(0, lambda: self._parse_error(f"网络错误：{exc}"))
        except AuthenticationError as exc:
            self.after(
                0,
                lambda: self._parse_error(
                    f"认证失败：{exc}\n请在「账号」菜单中配置正确的登录凭证。"
                ),
            )
        except BaiduRiskWarning as exc:
            self.after(0, lambda: self._parse_error(f"百度风控：{exc}"))
        except YunXError as exc:
            self.after(0, lambda: self._parse_error(f"错误：{exc}"))
        except Exception as exc:
            self.after(0, lambda: self._parse_error(f"未知错误：{exc}"))

    def _parse_success(self, share_info: ShareInfo, drive: str) -> None:
        """解析成功回调（主线程）。

        Args:
            share_info: 解析结果。
            drive: 网盘标识。
        """
        self._current_share_infos = [share_info]
        self._current_drive = drive
        self._file_list.set_files([share_info], drive)

        display = get_drive_display(drive)
        self._status_bar.set_status(
            f"解析成功：{share_info.file_name}（{format_size(share_info.file_size)}）"
        )
        self._url_input.set_parsing(False)

    def _parse_error(self, message: str) -> None:
        """解析失败回调（主线程）。

        Args:
            message: 错误信息。
        """
        self._url_input.set_parsing(False)
        self._status_bar.set_status("解析失败")
        messagebox.showerror("解析失败", message, parent=self)

    # ==================================================================
    # 下载流程
    # ==================================================================

    def _on_download_selected(self) -> None:
        """下载选中的文件。"""
        selected = self._file_list.get_selected_files()
        if not selected:
            messagebox.showinfo("提示", "请先在文件列表中选择要下载的文件", parent=self)
            return
        self._start_downloads(selected)

    def _on_download_all(self) -> None:
        """下载所有文件。"""
        all_files = self._file_list.get_all_files()
        if not all_files:
            messagebox.showinfo("提示", "文件列表为空，请先解析分享链接", parent=self)
            return
        self._start_downloads(all_files)

    def _start_downloads(self, share_infos: list[ShareInfo]) -> None:
        """启动一批下载任务。

        Args:
            share_infos: 要下载的文件列表。
        """
        save_path = self._save_path_var.get().strip() or DEFAULT_SAVE_PATH
        concurrency = int(self._concurrency_var.get())
        chunk_size = CHUNK_SIZE_OPTIONS.get(self._chunk_var.get(), DEFAULT_CHUNK_SIZE)

        # 确保保存目录存在
        try:
            os.makedirs(save_path, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("错误", f"无法创建下载目录：{exc}", parent=self)
            return

        for info in share_infos:
            if not info.direct_url:
                messagebox.showwarning(
                    "提示", f"文件 {info.file_name} 没有可用的下载链接", parent=self
                )
                continue

            task = DownloadTaskWidget(
                master=self._tasks_scroll_frame,
                file_name=info.file_name,
                url=info.direct_url,
                output_dir=save_path,
                chunk_size=chunk_size,
                concurrency=concurrency,
                on_status_change=self._on_task_status_change,
                on_remove=self._on_task_remove,
            )
            task.pack(fill=tk.X, padx=2, pady=2)
            self._download_tasks.append(task)
            task.start()

        # 隐藏空任务提示
        self._empty_tasks_label.pack_forget()
        self._status_bar.set_status(f"已启动 {len(share_infos)} 个下载任务")

    def _on_task_status_change(
        self, task: DownloadTaskWidget, status: str
    ) -> None:
        """下载任务状态变化回调。

        Args:
            task: 任务组件。
            status: 新状态。
        """
        if status == STATUS_COMPLETED:
            self._status_bar.set_status(f"下载完成：{task.file_name}")
            if self._sound_notify:
                self._play_notify_sound()

    def _on_task_remove(self, task: DownloadTaskWidget) -> None:
        """移除下载任务。

        Args:
            task: 要移除的任务组件。
        """
        if task in self._download_tasks:
            self._download_tasks.remove(task)
        task.destroy()

        # 如果没有任务了，显示空提示
        if not self._download_tasks:
            self._empty_tasks_label.pack(pady=20)

    def _schedule_speed_update(self) -> None:
        """调度总速度更新（每 500ms）。"""
        self._update_total_speed()
        self.after(500, self._schedule_speed_update)

    def _update_total_speed(self) -> None:
        """更新状态栏的总下载速度。"""
        total_speed = sum(t.speed for t in self._download_tasks)
        self._status_bar.set_total_speed(total_speed)

    # ==================================================================
    # 控制区事件
    # ==================================================================

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

    # ==================================================================
    # 菜单事件
    # ==================================================================

    def _menu_set_save_path(self) -> None:
        """文件 → 设置保存路径。"""
        self._browse_save_path()

    def _menu_clean_temp(self) -> None:
        """工具 → 清理临时转存文件。"""
        save_path = self._save_path_var.get().strip()
        if not save_path:
            return

        count = 0
        try:
            for fname in os.listdir(save_path):
                if fname.endswith(".yunx_download.json") or fname.endswith(".part"):
                    fpath = os.path.join(save_path, fname)
                    try:
                        os.remove(fpath)
                        count += 1
                    except OSError:
                        pass
            messagebox.showinfo("清理完成", f"已清理 {count} 个临时文件", parent=self)
            self._status_bar.set_status(f"已清理 {count} 个临时文件")
        except OSError as exc:
            messagebox.showerror("错误", f"清理失败：{exc}", parent=self)

    def _menu_open_download_dir(self) -> None:
        """工具 → 打开下载目录。"""
        path = self._save_path_var.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showwarning("提示", "下载目录不存在", parent=self)
            return

        # 跨平台打开目录
        import subprocess
        import sys

        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("错误", f"无法打开目录：{exc}", parent=self)

    def _menu_account_manager(self) -> None:
        """账号 → 管理网盘账号。"""
        dlg = AccountManagerDialog(self)
        # 如果用户在账号管理中解锁了配置，保存引用
        if dlg._config is not None:
            self._config = dlg._config
            self._load_settings_from_config()

    def _menu_help(self) -> None:
        """帮助 → 使用说明。"""
        help_text = (
            "YunX 云析 使用说明\n\n"
            "1. 复制网盘分享链接（夸克、123云盘、迅雷、百度、UC、和彩云）\n"
            "2. 粘贴到链接输入框，如有提取码请一并填写\n"
            "3. 点击「解析」按钮获取文件信息和下载直链\n"
            "4. 在文件列表中选择要下载的文件（支持多选）\n"
            "5. 设置保存路径、并发数和分片大小\n"
            "6. 点击「下载选中」或「全部下载」开始下载\n"
            "7. 下载过程中可暂停、恢复或取消任务\n\n"
            "提示：\n"
            "  • 百度网盘使用前请仔细阅读风控警告\n"
            "  • 部分网盘需要登录凭证（Cookie），可在「账号」菜单中配置\n"
            "  • 凭证通过 AES-GCM 加密存储在 ~/.yunx/config.enc\n"
            "  • 并发数建议 4-16，分片大小建议 4MB"
        )
        messagebox.showinfo("使用说明", help_text, parent=self)

    def _menu_about(self) -> None:
        """帮助 → 关于。"""
        about_text = (
            f"{__app_name__} v{__version__}\n\n"
            "全平台网盘解析 + 高速下载工具\n"
            "支持夸克、123云盘、迅雷、百度、UC、和彩云\n\n"
            "桌面端：tkinter + ttk\n"
            "核心引擎：Python 3.10+\n"
            "下载引擎：Range 分片并发 + 断点续传\n"
            "凭证加密：AES-256-GCM"
        )
        messagebox.showinfo("关于", about_text, parent=self)

    def _menu_disclaimer(self) -> None:
        """帮助 → 免责声明。"""
        disclaimer = (
            "免责声明\n\n"
            "本工具仅供学习和研究使用，用户应遵守相关法律法规和\n"
            "各网盘平台的用户协议。\n\n"
            "  • 不得用于下载侵权、违法或未经授权的内容\n"
            "  • 不得用于商业用途或大规模批量下载\n"
            "  • 使用本工具导致的账号封禁等后果由用户自行承担\n"
            "  • 开发者不对因使用本工具造成的任何损失负责\n\n"
            "请合理、合法地使用本工具。"
        )
        messagebox.showwarning("免责声明", disclaimer, parent=self)

    def _on_quit(self) -> None:
        """退出应用。"""
        # 取消所有下载任务
        for task in self._download_tasks:
            task.cancel()
        self.destroy()

    # ==================================================================
    # 剪贴板监听
    # ==================================================================

    def _toggle_clipboard_monitor(self) -> None:
        """切换剪贴板监听开关。"""
        enabled = self._clipboard_monitor_var.get()
        self._clipboard_monitor = enabled
        if enabled:
            self._clipboard_polling = True
            self._last_clipboard = ""
            self._poll_clipboard()
            self._status_bar.set_status("剪贴板监听已开启")
        else:
            self._clipboard_polling = False
            self._status_bar.set_status("剪贴板监听已关闭")

    def _poll_clipboard(self) -> None:
        """轮询剪贴板内容变化。"""
        if not self._clipboard_polling:
            return

        try:
            text = self.clipboard_get()
            if text and text != self._last_clipboard:
                self._last_clipboard = text
                urls = detect_share_url(text)
                if urls:
                    share = urls[0]
                    self._url_input.set_url(share.url)
                    if share.extract_code:
                        self._url_input.set_extract_code(share.extract_code)
                    self._status_bar.set_status(
                        f"已从剪贴板识别：{get_drive_display(share.drive)} 链接"
                    )
        except tk.TclError:
            pass

        self.after(1000, self._poll_clipboard)

    # ==================================================================
    # 设置管理
    # ==================================================================

    def _try_load_settings(self) -> None:
        """尝试加载设置（配置文件存在时提示输入密码）。

        如果配置文件不存在，使用默认设置。
        """
        config_path = Path.home() / ".yunx" / "config.enc"
        if not config_path.exists():
            return

        # 配置文件存在，延迟到用户主动打开账号管理时再解锁
        # 这里不自动弹窗，避免打扰用户

    def _load_settings_from_config(self) -> None:
        """从已解锁的 ConfigManager 加载设置到 UI。"""
        if self._config is None:
            return

        try:
            self._save_path = self._config.get("save_path", DEFAULT_SAVE_PATH)
            self._save_path_var.set(self._save_path)

            self._concurrency = int(self._config.get("concurrency", DEFAULT_CONCURRENCY))
            self._concurrency_var.set(self._concurrency)
            self._concurrency_label.config(text=str(self._concurrency))

            self._chunk_size = int(self._config.get("chunk_size", DEFAULT_CHUNK_SIZE))
            for name, size in CHUNK_SIZE_OPTIONS.items():
                if size == self._chunk_size:
                    self._chunk_var.set(name)
                    break

            self._clipboard_monitor = bool(
                self._config.get("clipboard_monitor", False)
            )
            self._clipboard_monitor_var.set(self._clipboard_monitor)

            self._sound_notify = bool(self._config.get("sound_notify", True))
            self._theme = self._config.get("theme", "浅色")
        except Exception:
            pass

    # ==================================================================
    # 工具方法
    # ==================================================================

    @staticmethod
    def _play_notify_sound() -> None:
        """播放下载完成提示音（跨平台，失败静默）。"""
        try:
            import sys

            if sys.platform == "win32":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            elif sys.platform == "darwin":
                # macOS: 用 afplay 播放系统提示音
                import subprocess

                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # Linux: 尝试用 paplay 或 beep
                import subprocess

                subprocess.Popen(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass  # 静默失败
