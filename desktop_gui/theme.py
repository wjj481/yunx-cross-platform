"""
Material 3 风格主题模块。

提供浅色 / 深色 / 跟随系统三种主题的配色方案与 ttk.Style 配置，
参考云析(YunX)原版 Material 3 设计语言，确保跨平台视觉一致。

主色调：夸克蓝 #1976D2
辅助色：123云盘绿 #43A047、迅雷橙 #FB8C00、百度红 #E53935
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

# ==================================================================
# 配色常量
# ==================================================================

# 主色（夸克蓝）
PRIMARY = "#1976D2"
PRIMARY_DARK = "#1565C0"
PRIMARY_LIGHT = "#42A5F5"
PRIMARY_CONTAINER = "#D1E4FF"

# 辅助色
SUCCESS = "#43A047"       # 123云盘绿 / 完成
WARNING = "#FB8C00"       # 迅雷橙 / 暂停
ERROR = "#E53935"         # 百度红 / 错误
INFO = "#1976D2"          # 信息蓝

# 网盘品牌色
DRIVE_BRAND_COLORS: dict[str, str] = {
    "quark": "#1976D2",    # 夸克蓝
    "pan123": "#43A047",   # 123云盘绿
    "xunlei": "#FB8C00",   # 迅雷橙
    "baidu": "#E53935",    # 百度红
    "uc": "#5C6BC0",       # UC 靛蓝
    "caiyun": "#00897B",   # 和彩云 青绿
}

# 浅色主题
LIGHT_THEME: dict[str, str] = {
    "bg": "#FAFAFA",              # 页面背景
    "surface": "#FFFFFF",         # 卡片/容器背景
    "surface_variant": "#F5F5F5", # 次级表面
    "primary": PRIMARY,
    "primary_container": PRIMARY_CONTAINER,
    "on_primary": "#FFFFFF",
    "on_surface": "#1C1B1F",      # 主文字
    "on_surface_variant": "#49454F",  # 次文字
    "outline": "#79747E",         # 描边
    "outline_variant": "#CAC4D0", # 弱描边
    "error": ERROR,
    "success": SUCCESS,
    "warning": WARNING,
    "divider": "#E0E0E0",
    "hover": "#E3F2FD",
    "disabled_bg": "#EEEEEE",
    "disabled_fg": "#9E9E9E",
}

# 深色主题
DARK_THEME: dict[str, str] = {
    "bg": "#121212",              # 页面背景
    "surface": "#1E1E1E",         # 卡片/容器背景
    "surface_variant": "#2D2D2D", # 次级表面
    "primary": "#42A5F5",
    "primary_container": "#0D47A1",
    "on_primary": "#001F33",
    "on_surface": "#E0E0E0",      # 主文字
    "on_surface_variant": "#9E9E9E",  # 次文字
    "outline": "#79747E",
    "outline_variant": "#49454F",
    "error": "#EF5350",
    "success": "#66BB6A",
    "warning": "#FFA726",
    "divider": "#333333",
    "hover": "#1A3A5C",
    "disabled_bg": "#2A2A2A",
    "disabled_fg": "#616161",
}

THEMES = {
    "light": LIGHT_THEME,
    "dark": DARK_THEME,
}

# 主题显示名映射
THEME_DISPLAY_NAMES = {
    "light": "浅色",
    "dark": "深色",
    "system": "跟随系统",
}


# ==================================================================
# 主题管理器
# ==================================================================

class ThemeManager:
    """Material 3 主题管理器。

    负责维护当前主题配色、配置 ttk.Style，并提供主题切换能力。
    所有需要应用主题的组件通过 :meth:`get_colors` 获取当前配色。
    """

    def __init__(self, root: tk.Tk) -> None:
        """初始化主题管理器。

        Args:
            root: 主窗口 Tk 实例。
        """
        self._root = root
        self._current_theme = "light"
        self._style = ttk.Style(root)
        self._on_theme_change: list[Any] = []

        # 尝试使用 clam 主题作为基础（跨平台一致性最好）
        try:
            self._style.theme_use("clam")
        except tk.TclError:
            pass

        self.apply_theme("light")

    @property
    def current_theme(self) -> str:
        """当前主题标识（light / dark）。"""
        return self._current_theme

    def get_colors(self) -> dict[str, str]:
        """获取当前主题的配色字典。"""
        return THEMES[self._current_theme]

    def register_callback(self, callback: Any) -> None:
        """注册主题变化回调。

        Args:
            callback: 无参数回调函数，主题切换时调用。
        """
        self._on_theme_change.append(callback)

    def apply_theme(self, theme_name: str) -> None:
        """应用指定主题。

        Args:
            theme_name: 主题标识（light / dark / system）。
        """
        if theme_name == "system":
            theme_name = self._detect_system_theme()

        if theme_name not in THEMES:
            theme_name = "light"

        self._current_theme = theme_name
        colors = THEMES[theme_name]
        self._configure_styles(colors)

        # 通知回调
        for cb in self._on_theme_change:
            try:
                cb()
            except Exception:
                pass

    @staticmethod
    def _detect_system_theme() -> str:
        """检测系统主题偏好（浅色/深色）。

        Returns:
            "light" 或 "dark"。
        """
        import sys

        if sys.platform == "win32":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                return "light" if value == 1 else "dark"
            except Exception:
                return "light"
        elif sys.platform == "darwin":
            try:
                import subprocess

                result = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                return "dark" if result.returncode == 0 and "Dark" in result.stdout else "light"
            except Exception:
                return "light"
        else:
            # Linux: 检查 GTK 主题名或桌面环境设置
            try:
                import subprocess

                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if "dark" in result.stdout.lower():
                    return "dark"
            except Exception:
                pass
            return "light"

    def _configure_styles(self, c: dict[str, str]) -> None:
        """根据配色配置 ttk.Style。

        Args:
            c: 配色字典。
        """
        s = self._style

        # ---- 全局 ----
        s.configure(".", background=c["bg"], foreground=c["on_surface"])
        s.configure("TFrame", background=c["bg"])
        s.configure("Card.TFrame", background=c["surface"])
        s.configure("Surface.TFrame", background=c["surface"])

        # ---- 标签 ----
        s.configure("TLabel", background=c["bg"], foreground=c["on_surface"])
        s.configure("Card.TLabel", background=c["surface"], foreground=c["on_surface"])
        s.configure("Title.TLabel", background=c["bg"], foreground=c["on_surface"], font=("", 14, "bold"))
        s.configure("Heading.TLabel", background=c["bg"], foreground=c["on_surface"], font=("", 11, "bold"))
        s.configure("Subtitle.TLabel", background=c["bg"], foreground=c["on_surface_variant"], font=("", 9))
        s.configure("CardTitle.TLabel", background=c["surface"], foreground=c["on_surface"], font=("", 10, "bold"))
        s.configure("CardSubtitle.TLabel", background=c["surface"], foreground=c["on_surface_variant"], font=("", 9))
        s.configure("Muted.TLabel", background=c["bg"], foreground=c["on_surface_variant"])
        s.configure("CardMuted.TLabel", background=c["surface"], foreground=c["on_surface_variant"])
        s.configure("Error.TLabel", background=c["bg"], foreground=c["error"])
        s.configure("Success.TLabel", background=c["bg"], foreground=c["success"])
        s.configure("Warning.TLabel", background=c["bg"], foreground=c["warning"])

        # ---- 按钮 ----
        # 主按钮：填充主色
        s.configure(
            "Primary.TButton",
            background=c["primary"],
            foreground=c["on_primary"],
            borderwidth=0,
            focusthickness=0,
            padding=(16, 8),
            font=("", 10, "bold"),
        )
        s.map(
            "Primary.TButton",
            background=[("active", c["primary_dark"] if "primary_dark" in c else PRIMARY_DARK),
                       ("disabled", c["disabled_bg"])],
            foreground=[("disabled", c["disabled_fg"])],
        )

        # 次按钮：描边
        s.configure(
            "Secondary.TButton",
            background=c["surface"],
            foreground=c["primary"],
            borderwidth=1,
            bordercolor=c["primary"],
            focusthickness=0,
            padding=(14, 6),
        )
        s.map(
            "Secondary.TButton",
            background=[("active", c["hover"]), ("disabled", c["disabled_bg"])],
            foreground=[("disabled", c["disabled_fg"])],
        )

        # 危险按钮
        s.configure(
            "Danger.TButton",
            background=c["error"],
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(14, 6),
        )
        s.map(
            "Danger.TButton",
            background=[("active", "#C62828"), ("disabled", c["disabled_bg"])],
            foreground=[("disabled", c["disabled_fg"])],
        )

        # 普通按钮
        s.configure(
            "TButton",
            background=c["surface_variant"],
            foreground=c["on_surface"],
            borderwidth=1,
            bordercolor=c["outline_variant"],
            padding=(12, 5),
        )
        s.map(
            "TButton",
            background=[("active", c["hover"]), ("disabled", c["disabled_bg"])],
            foreground=[("disabled", c["disabled_fg"])],
        )

        # ---- 输入框 ----
        s.configure(
            "TEntry",
            fieldbackground=c["surface"],
            foreground=c["on_surface"],
            bordercolor=c["outline_variant"],
            lightcolor=c["outline_variant"],
            darkcolor=c["outline_variant"],
            insertcolor=c["on_surface"],
            padding=6,
        )
        s.map(
            "TEntry",
            bordercolor=[("focus", c["primary"])],
            lightcolor=[("focus", c["primary"])],
            darkcolor=[("focus", c["primary"])],
        )

        # ---- 下拉框 ----
        s.configure(
            "TCombobox",
            fieldbackground=c["surface"],
            background=c["surface"],
            foreground=c["on_surface"],
            bordercolor=c["outline_variant"],
            arrowcolor=c["on_surface_variant"],
            padding=4,
        )
        s.map(
            "TCombobox",
            fieldbackground=[("readonly", c["surface"])],
            foreground=[("readonly", c["on_surface"])],
        )

        # ---- 复选框 / 单选框 ----
        s.configure("TCheckbutton", background=c["bg"], foreground=c["on_surface"])
        s.configure("TRadiobutton", background=c["bg"], foreground=c["on_surface"])
        s.map(
            "TCheckbutton",
            background=[("active", c["hover"])],
            foreground=[("disabled", c["disabled_fg"])],
        )
        s.map(
            "TRadiobutton",
            background=[("active", c["hover"])],
            foreground=[("disabled", c["disabled_fg"])],
        )

        # ---- 标签页 Notebook ----
        s.configure(
            "TNotebook",
            background=c["bg"],
            borderwidth=0,
            tabmargins=(4, 4, 4, 0),
        )
        s.configure(
            "TNotebook.Tab",
            background=c["surface_variant"],
            foreground=c["on_surface_variant"],
            padding=(20, 10),
            font=("", 10),
        )
        s.map(
            "TNotebook.Tab",
            background=[("selected", c["primary"]), ("active", c["hover"])],
            foreground=[("selected", c["on_primary"]), ("active", c["on_surface"])],
            expand=[("selected", (2, 2, 2, 0))],
        )
        s.configure("TNotebook.Tab", borderwidth=0)

        # ---- LabelFrame ----
        s.configure(
            "TLabelframe",
            background=c["surface"],
            foreground=c["on_surface"],
            bordercolor=c["outline_variant"],
            borderwidth=1,
        )
        s.configure(
            "TLabelframe.Label",
            background=c["surface"],
            foreground=c["primary"],
            font=("", 10, "bold"),
        )
        s.configure(
            "Card.TLabelframe",
            background=c["surface"],
            foreground=c["on_surface"],
            bordercolor=c["outline_variant"],
            borderwidth=1,
        )
        s.configure(
            "Card.TLabelframe.Label",
            background=c["surface"],
            foreground=c["primary"],
            font=("", 10, "bold"),
        )

        # ---- 进度条 ----
        s.configure(
            "Download.Horizontal.TProgressbar",
            troughcolor=c["surface_variant"],
            background=c["primary"],
            borderwidth=0,
            thickness=8,
        )
        s.configure(
            "Paused.Horizontal.TProgressbar",
            troughcolor=c["surface_variant"],
            background=c["warning"],
            borderwidth=0,
            thickness=8,
        )
        s.configure(
            "Completed.Horizontal.TProgressbar",
            troughcolor=c["surface_variant"],
            background=c["success"],
            borderwidth=0,
            thickness=8,
        )
        s.configure(
            "Error.Horizontal.TProgressbar",
            troughcolor=c["surface_variant"],
            background=c["error"],
            borderwidth=0,
            thickness=8,
        )

        # ---- 滚动条 ----
        s.configure(
            "Vertical.TScrollbar",
            background=c["surface_variant"],
            troughcolor=c["bg"],
            borderwidth=0,
            arrowcolor=c["on_surface_variant"],
        )
        s.configure(
            "Horizontal.TScrollbar",
            background=c["surface_variant"],
            troughcolor=c["bg"],
            borderwidth=0,
            arrowcolor=c["on_surface_variant"],
        )

        # ---- 分隔线 ----
        s.configure("TSeparator", background=c["divider"])

        # ---- 滑块 ----
        s.configure(
            "Horizontal.TScale",
            background=c["bg"],
            troughcolor=c["surface_variant"],
        )

        # ---- Treeview ----
        s.configure(
            "Treeview",
            background=c["surface"],
            fieldbackground=c["surface"],
            foreground=c["on_surface"],
            bordercolor=c["outline_variant"],
            rowheight=28,
        )
        s.configure(
            "Treeview.Heading",
            background=c["surface_variant"],
            foreground=c["on_surface_variant"],
            font=("", 9, "bold"),
            borderwidth=0,
            padding=(8, 6),
        )
        s.map(
            "Treeview",
            background=[("selected", c["primary_container"])],
            foreground=[("selected", c["on_surface"])],
        )
        s.map(
            "Treeview.Heading",
            background=[("active", c["hover"])],
        )

        # ---- 状态栏 ----
        s.configure(
            "Status.TFrame",
            background=c["surface_variant"],
            relief=tk.FLAT,
        )
        s.configure(
            "Status.TLabel",
            background=c["surface_variant"],
            foreground=c["on_surface_variant"],
            padding=(8, 3),
            font=("", 9),
        )


# ==================================================================
# 工具函数
# ==================================================================

def get_drive_brand_color(drive: str) -> str:
    """获取网盘品牌色。

    Args:
        drive: 网盘标识。

    Returns:
        十六进制颜色字符串。
    """
    return DRIVE_BRAND_COLORS.get(drive, "#757575")


def create_drive_badge(
    parent: tk.Misc,
    drive: str,
    theme_manager: ThemeManager | None = None,
) -> tk.Label:
    """创建网盘彩色徽章标签（tk.Label 模拟圆角徽章）。

    Args:
        parent: 父容器。
        drive: 网盘标识。
        theme_manager: 主题管理器（可选，用于深色模式文字色）。

    Returns:
        配置好的 tk.Label 实例。
    """
    from .utils import get_drive_display

    color = get_drive_brand_color(drive)
    name = get_drive_display(drive)
    label = tk.Label(
        parent,
        text=f"  {name}  ",
        bg=color,
        fg="#FFFFFF",
        font=("", 8, "bold"),
        padx=2,
        pady=1,
    )
    return label
