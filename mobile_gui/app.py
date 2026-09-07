"""
YunX 移动端主应用类。

负责：
- Kivy App 生命周期管理
- ScreenManager 屏幕管理（主屏幕 / 下载屏幕 / 设置屏幕 / 账号屏幕）
- 核心引擎适配器（CoreAdapter）的全局实例
- 应用级设置读写（下载目录、并发数、主题等）
- 下载任务 ID 集中管理与更新通知
- 中文字体配置
- Android 运行时权限请求
- 主题切换应用

所有 UI 更新均在主线程执行；耗时操作通过 CoreAdapter 在子线程完成。
"""

from __future__ import annotations

import os
import platform
from typing import Any

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivy.utils import platform as kivy_platform

from mobile_gui.core_adapter import CoreAdapter
from mobile_gui.ui.account_screen import AccountScreen
from mobile_gui.ui.download_screen import DownloadScreen
from mobile_gui.ui.main_screen import MainScreen
from mobile_gui.ui.settings_screen import SettingsScreen
from mobile_gui.ui.widgets import Theme


# ===========================================================================
# 中文字体注册
# ===========================================================================

def register_chinese_font() -> None:
    """注册中文字体。

    Kivy 默认 Roboto 字体不含中文字形，需注册系统中文字体。
    按平台尝试常见字体路径，均失败时回退到 Roboto（中文将显示为方框）。

    Android：系统字体通常在 ``/system/fonts/`` 下。
    iOS：系统字体在 ``/System/Library/Fonts/`` 下。
    桌面：尝试常见中文字体。

    注意：若需在 APK 中内置中文字体，可将字体文件放入 ``assets/fonts/``
    并在 buildozer.spec 的 ``source.include_exts`` 中包含 ttf，
    然后在此处注册。
    """
    font_candidates = [
        # Android
        "/system/fonts/NotoSansCJK-Regular.ttc",
        "/system/fonts/NotoSansSC-Regular.otf",
        "/system/fonts/DroidSansFallback.ttf",
        # iOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        # Linux 桌面
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        # macOS
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]

    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                LabelBase.register(name="Roboto", fn_regular=font_path)
                print(f"[YunX] 已注册中文字体: {font_path}")
                return
            except Exception as exc:
                print(f"[YunX] 字体注册失败 {font_path}: {exc}")
                continue

    print("[YunX] 警告：未找到中文字体，中文可能显示为方框。")
    print("[YunX] 建议：在 assets/fonts/ 中放置 NotoSansSC-Regular.otf 并注册。")


# ===========================================================================
# 自定义 ScreenManager（携带主题模式）
# ===========================================================================

class YunXScreenManager(ScreenManager):
    """带主题模式属性的 ScreenManager。"""

    theme_mode: str = "light"


# ===========================================================================
# 主应用
# ===========================================================================

class YunXApp(App):
    """YunX 移动端主应用。

    使用 Kivy 2.x API，支持 Android + iOS。
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.core: CoreAdapter | None = None
        self._download_task_ids: list[str] = []
        self._settings_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Kivy 生命周期
    # ------------------------------------------------------------------

    def build(self) -> ScreenManager:
        """构建应用界面。"""
        # 注册中文字体
        register_chinese_font()

        # 初始化核心引擎适配器
        self.core = CoreAdapter()

        # 加载主题设置
        theme_mode = self.get_setting("theme", "light")
        Theme.set_mode(theme_mode)

        # 窗口配置（桌面调试用）
        if kivy_platform in ("win", "linux", "macosx"):
            Window.size = (dp(390), dp(700))

        # 创建 ScreenManager
        sm = YunXScreenManager(transition=SlideTransition(duration=0.2))
        sm.theme_mode = theme_mode

        # 添加四个屏幕
        sm.add_widget(MainScreen(name="main"))
        sm.add_widget(DownloadScreen(name="download"))
        sm.add_widget(SettingsScreen(name="settings"))
        sm.add_widget(AccountScreen(name="account"))

        sm.current = "main"
        return sm

    def on_start(self) -> None:
        """应用启动完成。"""
        # 请求 Android 存储权限
        self._request_android_permissions()

        # 剪贴板自动检测
        if self.get_setting("clipboard_listen", False):
            self._check_clipboard_on_start()

    def on_stop(self) -> None:
        """应用退出。"""
        # 暂停所有下载任务
        if self.core:
            self.core.pause_all()

    # ------------------------------------------------------------------
    # 设置管理（内存缓存 + 持久化）
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取应用设置。

        优先从内存缓存读取，未命中则从加密配置读取。
        """
        if key in self._settings_cache:
            return self._settings_cache[key]
        if self.core:
            value = self.core.get_setting(key, default)
            self._settings_cache[key] = value
            return value
        return default

    def set_setting(self, key: str, value: Any) -> None:
        """写入应用设置（内存缓存 + 持久化）。"""
        self._settings_cache[key] = value
        if self.core:
            self.core.set_setting(key, value)

    # ------------------------------------------------------------------
    # 下载任务管理
    # ------------------------------------------------------------------

    def add_download_task_id(self, task_id: str) -> None:
        """记录下载任务 ID。"""
        if task_id not in self._download_task_ids:
            self._download_task_ids.append(task_id)
        # 通知下载屏幕
        self._notify_download_screen(task_id)

    def notify_download_update(self, task: Any) -> None:
        """通知下载屏幕更新任务进度。"""
        sm = self.root
        if sm and sm.has_screen("download"):
            download_screen = sm.get_screen("download")
            download_screen.update_task_card(task)

    def _notify_download_screen(self, task_id: str) -> None:
        """通知下载屏幕添加新任务卡片。"""
        sm = self.root
        if sm and sm.has_screen("download"):
            download_screen = sm.get_screen("download")
            download_screen.add_task_card(task_id)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------

    def apply_theme(self, mode: str) -> None:
        """应用主题到所有屏幕。"""
        Theme.set_mode(mode)
        sm = self.root
        if isinstance(sm, YunXScreenManager):
            sm.theme_mode = mode
        # 通知各屏幕刷新（通过 on_pre_enter 时自动读取）
        # 当前屏幕立即刷新背景
        current = sm.current_screen if sm else None
        if current and hasattr(current, "_bg_color"):
            from mobile_gui.ui.widgets import hex_to_rgba
            current._bg_color.rgba = hex_to_rgba(Theme.get("bg"))

    # ------------------------------------------------------------------
    # Android 权限
    # ------------------------------------------------------------------

    def _request_android_permissions(self) -> None:
        """请求 Android 运行时权限（存储）。

        在 Android 6.0+ 上，WRITE_EXTERNAL_STORAGE 需要运行时请求。
        使用 ``android.permissions`` 模块（python-for-android 提供）。
        """
        if kivy_platform != "android":
            return

        try:
            from android.permissions import request_permissions, Permission  # type: ignore
            request_permissions([
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
                Permission.INTERNET,
                Permission.ACCESS_NETWORK_STATE,
            ])
            print("[YunX] Android 运行时权限已请求")
        except ImportError:
            print("[YunX] android.permissions 模块不可用，跳过权限请求")
        except Exception as exc:
            print(f"[YunX] Android 权限请求失败: {exc}")

    # ------------------------------------------------------------------
    # 剪贴板启动检测
    # ------------------------------------------------------------------

    def _check_clipboard_on_start(self) -> None:
        """启动时检测剪贴板中的分享链接。"""
        if not self.core:
            return
        results = self.core.detect_from_clipboard()
        if results:
            share = results[0]
            info = CoreAdapter.drive_display(share.drive)
            # 在主屏幕填入 URL
            sm = self.root
            if sm and sm.has_screen("main"):
                main_screen = sm.get_screen("main")
                main_screen._url_input.text = share.url
                if share.extract_code:
                    main_screen._code_input.text = share.extract_code
                from mobile_gui.ui.widgets import show_toast
                show_toast(main_screen, f"检测到剪贴板链接：{info['name']}")
