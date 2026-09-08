"""
YunX 桌面端主应用类（Material 3 标签页布局）。

整合解析页、下载管理页、账号管理页、设置页四个标签页，
管理解析/下载线程、菜单事件、剪贴板监听和主题切换。
所有耗时操作在子线程中运行，通过 root.after() 更新 UI。
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from core import (
    AuthenticationError,
    BaiduRiskWarning,
    DownloadError,
    NetworkError,
    ParserError,
    YunXError,
    export_config,
    import_config,
    is_encrypted,
    apply_imported_config,
)
from core.config import ConfigManager
from core.parsers.base import ShareInfo, get_parser
from core.clipboard import detect_share_url

from . import __app_name__, __version__
from .dialogs.baidu_warning import BaiduWarningDialog
from .dialogs.config_export import ExportConfigDialog, ImportConfigDialog
from .dialogs.settings import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CLIPBOARD_MONITOR,
    DEFAULT_CONCURRENCY,
    DEFAULT_SAVE_PATH,
    DEFAULT_SOUND_NOTIFY,
)
from .pages.account_page import AccountPage
from .pages.download_page import DownloadPage
from .pages.parse_page import ParsePage
from .pages.settings_page import SettingsPage
from .theme import ThemeManager
from .utils import format_size, get_drive_display, needs_risk_warning
from .widgets.download_task import (
    STATUS_COMPLETED,
    DownloadTaskWidget,
)
from .widgets.status_bar import StatusBarWidget


class YunXApp(tk.Tk):
    """YunX 桌面端主应用（Notebook 标签页布局）。

    四个标签页：
    - 解析页：URL 输入 + 文件列表 + 下载操作
    - 下载管理页：任务卡片列表 + 批量操作
    - 账号管理页：网盘账号卡片 + 添加/删除/测试
    - 设置页：下载设置 + 外观 + 配置管理 + 关于
    """

    def __init__(self) -> None:
        """初始化主应用。"""
        super().__init__()

        # 窗口基本设置
        self.title(f"{__app_name__} - 全平台网盘解析下载器 v{__version__}")
        self.geometry("1000x760")
        self.minsize(900, 680)

        # 主题管理器
        self._theme_manager = ThemeManager(self)

        # 配置管理器（延迟初始化，需要主密码解锁）
        self._config: ConfigManager | None = None

        # 当前设置
        self._save_path = DEFAULT_SAVE_PATH
        self._concurrency = DEFAULT_CONCURRENCY
        self._chunk_size = DEFAULT_CHUNK_SIZE
        self._clipboard_monitor = DEFAULT_CLIPBOARD_MONITOR
        self._sound_notify = DEFAULT_SOUND_NOTIFY
        self._theme = "light"

        # 解析结果缓存
        self._current_share_infos: list[ShareInfo] = []
        self._current_drive = ""

        # 下载任务列表
        self._download_tasks: list[DownloadTaskWidget] = []

        # 剪贴板监听
        self._last_clipboard = ""
        self._clipboard_polling = False

        # 构建 UI
        try:
            self._build_menu()
        except Exception:
            pass
        self._build_ui()

        # 尝试自动加载设置
        self._try_load_settings()

        # 确保默认下载目录存在
        os.makedirs(self._save_path, exist_ok=True)

        # 启动总速度轮询
        self._schedule_speed_update()

    # ==================================================================
    # UI 构建
    # ==================================================================

    def _build_menu(self) -> None:
        """构建菜单栏。"""
        menubar = tk.Menu(self)

        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="导出配置...", command=self._menu_export_config)
        file_menu.add_command(label="导入配置...", command=self._menu_import_config)
        file_menu.add_separator()
        file_menu.add_command(label="设置保存路径...", command=self._menu_set_save_path)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        # 工具菜单
        tools_menu = tk.Menu(menubar, tearoff=0)
        self._clipboard_monitor_var = tk.BooleanVar(value=self._clipboard_monitor)
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
        account_menu.add_command(
            label="管理网盘账号", command=lambda: self._notebook.select(2)
        )
        menubar.add_cascade(label="账号", menu=account_menu)

        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._menu_help)
        help_menu.add_command(label="关于", command=self._menu_about)
        help_menu.add_command(label="免责声明", command=self._menu_disclaimer)
        help_menu.add_command(label="GitHub", command=self._menu_github)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.config(menu=menubar)

    def _build_ui(self) -> None:
        """构建主界面布局（Notebook 标签页）。"""
        # 主容器
        main = ttk.Frame(self, padding=4)
        main.pack(fill=tk.BOTH, expand=True)

        # Notebook 标签页
        self._notebook = ttk.Notebook(main)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        # ---- 解析页 ----
        self._parse_page = ParsePage(
            self._notebook,
            on_parse=self._on_parse,
            on_download=self._on_start_downloads,
        )
        self._notebook.add(self._parse_page, text="  🔍 解析  ")

        # ---- 下载管理页 ----
        self._download_page = DownloadPage(self._notebook)
        self._notebook.add(self._download_page, text="  📥 下载管理  ")

        # ---- 账号管理页 ----
        self._account_page = AccountPage(
            self._notebook,
            get_config=lambda: self._config,
            on_config_unlocked=self._on_config_unlocked,
        )
        self._notebook.add(self._account_page, text="  👤 账号管理  ")

        # ---- 设置页 ----
        self._settings_page = SettingsPage(
            self._notebook,
            get_config=lambda: self._config,
            on_settings_change=self._on_settings_change,
            on_theme_change=self._on_theme_change,
            on_config_imported=self._on_config_imported,
        )
        self._notebook.add(self._settings_page, text="  ⚙ 设置  ")

        # ---- 状态栏 ----
        self._status_bar = StatusBarWidget(self)
        self._status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ==================================================================
    # 配置管理
    # ==================================================================

    def _get_config(self) -> ConfigManager | None:
        """获取当前配置管理器。"""
        return self._config

    def _on_config_unlocked(self, config: ConfigManager) -> None:
        """配置解锁回调。

        Args:
            config: 已解锁的 ConfigManager。
        """
        self._config = config
        self._load_settings_from_config()
        self._status_bar.set_status("配置已解锁")

    def _on_config_imported(self) -> None:
        """配置导入成功回调。"""
        self._load_settings_from_config()
        self._account_page.refresh()
        self._status_bar.set_status("配置已导入并刷新")

    def _try_load_settings(self) -> None:
        """尝试加载设置（配置文件存在时延迟到用户解锁）。"""
        config_path = Path.home() / ".yunx" / "config.enc"
        if not config_path.exists():
            return
        # 配置文件存在，延迟到用户主动解锁

    def _load_settings_from_config(self) -> None:
        """从已解锁的 ConfigManager 加载设置到 UI。"""
        if self._config is None:
            return

        try:
            settings = {}
            self._save_path = self._config.get("save_path", DEFAULT_SAVE_PATH)
            settings["save_path"] = self._save_path

            self._concurrency = int(self._config.get("concurrency", DEFAULT_CONCURRENCY))
            settings["concurrency"] = self._concurrency

            self._chunk_size = int(self._config.get("chunk_size", DEFAULT_CHUNK_SIZE))
            settings["chunk_size"] = self._chunk_size

            self._clipboard_monitor = bool(
                self._config.get("clipboard_monitor", DEFAULT_CLIPBOARD_MONITOR)
            )
            settings["clipboard_monitor"] = self._clipboard_monitor

            self._sound_notify = bool(self._config.get("sound_notify", DEFAULT_SOUND_NOTIFY))
            settings["sound_notify"] = self._sound_notify

            self._theme = self._config.get("theme", "light")
            settings["theme"] = self._theme

            # 更新各页面
            self._parse_page.update_settings(
                save_path=self._save_path,
                concurrency=self._concurrency,
                chunk_size=self._chunk_size,
            )
            self._settings_page.load_settings(settings)

            # 更新菜单剪贴板状态
            if hasattr(self, "_clipboard_monitor_var"):
                self._clipboard_monitor_var.set(self._clipboard_monitor)

            # 应用主题
            self._theme_manager.apply_theme(self._theme)
        except Exception:
            pass

    def _on_settings_change(self, settings: dict[str, Any]) -> None:
        """设置变化回调。

        Args:
            settings: 新的设置字典。
        """
        self._save_path = settings.get("save_path", self._save_path)
        self._concurrency = settings.get("concurrency", self._concurrency)
        self._chunk_size = settings.get("chunk_size", self._chunk_size)
        self._clipboard_monitor = settings.get("clipboard_monitor", self._clipboard_monitor)
        self._sound_notify = settings.get("sound_notify", self._sound_notify)
        self._theme = settings.get("theme", self._theme)

        # 同步到解析页
        self._parse_page.update_settings(
            save_path=self._save_path,
            concurrency=self._concurrency,
            chunk_size=self._chunk_size,
        )

        # 同步剪贴板监听
        if hasattr(self, "_clipboard_monitor_var"):
            self._clipboard_monitor_var.set(self._clipboard_monitor)
        if self._clipboard_monitor and not self._clipboard_polling:
            self._start_clipboard_polling()
        elif not self._clipboard_monitor and self._clipboard_polling:
            self._clipboard_polling = False

    def _on_theme_change(self, theme_name: str) -> None:
        """主题变化回调。

        Args:
            theme_name: 主题标识。
        """
        self._theme = theme_name
        self._theme_manager.apply_theme(theme_name)
        self._status_bar.set_status(f"已切换到{theme_name}主题")

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
        self._parse_page.set_parsing(True)
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
            # 获取对应网盘的凭证
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
                    f"认证失败：{exc}\n请在「账号管理」页配置正确的登录凭证。"
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
        self._parse_page.set_files([share_info], drive)

        display = get_drive_display(drive)
        self._status_bar.set_status(
            f"解析成功：{share_info.file_name}（{format_size(share_info.file_size)}）"
        )
        self._parse_page.set_parsing(False)

    def _parse_error(self, message: str) -> None:
        """解析失败回调（主线程）。

        Args:
            message: 错误信息。
        """
        self._parse_page.set_parsing(False)
        self._status_bar.set_status("解析失败")
        messagebox.showerror("解析失败", message, parent=self)

    # ==================================================================
    # 下载流程
    # ==================================================================

    def _on_start_downloads(
        self,
        share_infos: list[ShareInfo],
        save_path: str,
        concurrency: int,
        chunk_size: int,
    ) -> None:
        """启动一批下载任务。

        Args:
            share_infos: 要下载的文件列表。
            save_path: 保存目录。
            concurrency: 并发数。
            chunk_size: 分片大小。
        """
        # 确保保存目录存在
        try:
            os.makedirs(save_path, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("错误", f"无法创建下载目录：{exc}", parent=self)
            return

        started = 0
        for info in share_infos:
            if not info.direct_url:
                messagebox.showwarning(
                    "提示", f"文件 {info.file_name} 没有可用的下载链接", parent=self
                )
                continue

            task = self._download_page.create_task(
                file_name=info.file_name,
                url=info.direct_url,
                output_dir=save_path,
                chunk_size=chunk_size,
                concurrency=concurrency,
                on_status_change=self._on_task_status_change,
                on_remove=self._on_task_remove,
            )
            self._download_tasks.append(task)
            task.start()
            started += 1

        if started > 0:
            self._status_bar.set_status(f"已启动 {started} 个下载任务")
            # 自动切换到下载管理页
            self._notebook.select(1)

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
        self._download_page._update_toolbar_state()

    def _on_task_remove(self, task: DownloadTaskWidget) -> None:
        """移除下载任务。

        Args:
            task: 要移除的任务组件。
        """
        if task in self._download_tasks:
            self._download_tasks.remove(task)
        self._download_page.remove_task(task)

    def _schedule_speed_update(self) -> None:
        """调度总速度更新（每 500ms）。"""
        self._update_total_speed()
        self.after(500, self._schedule_speed_update)

    def _update_total_speed(self) -> None:
        """更新状态栏的总下载速度。"""
        total_speed = sum(t.speed for t in self._download_tasks)
        self._status_bar.set_total_speed(total_speed)
        self._download_page.update_total_speed(total_speed)

    # ==================================================================
    # 剪贴板监听
    # ==================================================================

    def _toggle_clipboard_monitor(self) -> None:
        """切换剪贴板监听开关。"""
        enabled = self._clipboard_monitor_var.get()
        self._clipboard_monitor = enabled

        if enabled:
            self._start_clipboard_polling()
            self._status_bar.set_status("剪贴板监听已开启")
        else:
            self._clipboard_polling = False
            self._status_bar.set_status("剪贴板监听已关闭")

        # 持久化
        if self._config is not None:
            try:
                self._config.set("clipboard_monitor", enabled)
                self._config.save()
            except Exception:
                pass

    def _start_clipboard_polling(self) -> None:
        """启动剪贴板轮询。"""
        if self._clipboard_polling:
            return
        self._clipboard_polling = True
        self._last_clipboard = ""
        self._poll_clipboard()

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
                    # 在解析页显示提示条
                    self._parse_page.show_clipboard_hint(share.url, share.drive)
                    self._status_bar.set_status(
                        f"检测到剪贴板中的{get_drive_display(share.drive)}链接"
                    )
        except tk.TclError:
            pass

        self.after(1000, self._poll_clipboard)

    # ==================================================================
    # 菜单事件
    # ==================================================================

    def _menu_export_config(self) -> None:
        """文件 → 导出配置。"""
        if self._config is None:
            messagebox.showinfo("提示", "请先在「账号管理」页解锁配置", parent=self)
            self._notebook.select(2)
            return
        ExportConfigDialog(self, self._config)

    def _menu_import_config(self) -> None:
        """文件 → 导入配置。"""
        if self._config is None:
            messagebox.showinfo("提示", "请先在「账号管理」页解锁配置", parent=self)
            self._notebook.select(2)
            return
        ImportConfigDialog(self, self._config, on_imported=self._on_config_imported)

    def _menu_set_save_path(self) -> None:
        """文件 → 设置保存路径。"""
        from tkinter import filedialog

        path = filedialog.askdirectory(
            title="选择下载保存目录",
            initialdir=self._save_path or str(Path.home()),
            parent=self,
        )
        if path:
            self._save_path = path
            self._parse_page.update_settings(save_path=path)
            self._settings_page._path_var.set(path)

    def _menu_clean_temp(self) -> None:
        """工具 → 清理临时转存文件。"""
        save_path = self._save_path
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
        path = self._save_path
        if not path or not os.path.isdir(path):
            messagebox.showwarning("提示", "下载目录不存在", parent=self)
            return

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

    def _menu_help(self) -> None:
        """帮助 → 使用说明。"""
        help_text = (
            "YunX 云析 使用说明\n\n"
            "1. 复制网盘分享链接（夸克、123云盘、迅雷、百度、UC、和彩云）\n"
            "2. 在「解析」页粘贴链接，如有提取码请一并填写\n"
            "3. 点击「解析」按钮获取文件信息和下载直链\n"
            "4. 在文件列表中选择要下载的文件（支持多选/全选/反选）\n"
            "5. 设置保存路径、并发数和分片大小\n"
            "6. 点击「下载选中」或「全部下载」开始下载\n"
            "7. 在「下载管理」页查看进度，可暂停/恢复/取消任务\n\n"
            "提示：\n"
            "  • 百度网盘使用前请仔细阅读风控警告\n"
            "  • 部分网盘需要登录凭证（Cookie），可在「账号管理」页配置\n"
            "  • 凭证通过 AES-GCM 加密存储在 ~/.yunx/config.enc\n"
            "  • 配置可通过「文件 → 导出/导入配置」备份迁移\n"
            "  • 并发数建议 4-16，分片大小建议 4MB"
        )
        messagebox.showinfo("使用说明", help_text, parent=self)

    def _menu_about(self) -> None:
        """帮助 → 关于。"""
        about_text = (
            f"{__app_name__} v{__version__}\n\n"
            "全平台网盘解析 + 高速下载工具\n"
            "支持夸克、123云盘、迅雷、百度、UC、和彩云\n\n"
            "桌面端：tkinter + ttk（Material 3 风格）\n"
            "核心引擎：Python 3.10+\n"
            "下载引擎：Range 分片并发 + 断点续传\n"
            "凭证加密：AES-256-GCM\n\n"
            "开源协议：MIT License"
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

    def _menu_github(self) -> None:
        """帮助 → GitHub。"""
        import webbrowser

        try:
            webbrowser.open("https://github.com/yunx-dev/yunx-cross-platform")
        except Exception:
            messagebox.showinfo(
                "GitHub",
                "https://github.com/yunx-dev/yunx-cross-platform",
                parent=self,
            )

    def _on_quit(self) -> None:
        """退出应用。"""
        # 取消所有下载任务
        for task in self._download_tasks:
            task.cancel()
        self._clipboard_polling = False
        self.destroy()

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
                import subprocess

                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                import subprocess

                subprocess.Popen(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass
