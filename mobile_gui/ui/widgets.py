"""
自定义 UI 控件。

提供 Material Design 3 风格的自定义控件，包括：
- 底部导航栏（BottomNavigationBar + BottomNavItem）
- 圆角按钮（带按下效果）
- 网盘标识彩色标签
- 文件列表项（RecycleView 行）
- 下载任务卡片
- Toast 轻提示
- 自定义进度条
- 圆角卡片容器
- 启动页（SplashScreen）
- 浮动操作按钮（FAB）

所有控件使用 ``dp()`` / ``sp()`` 单位以适配不同屏幕密度，
并支持浅色 / 深色主题切换。
"""

from __future__ import annotations

from typing import Any

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import (
    BooleanProperty,
    ColorProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.widget import Widget


# ===========================================================================
# 主题色板（Material 3 风格，参考云析原版）
# ===========================================================================

class Theme:
    """应用主题色板（浅色 / 深色）。

    使用类属性存储当前主题，各控件通过 ``Theme.get()`` 获取。
    主色调采用夸克蓝 #1976D2。
    """

    _mode: str = "light"

    # 主色调（夸克蓝）
    PRIMARY = "#1976D2"
    PRIMARY_DARK = "#1565C0"
    PRIMARY_LIGHT = "#42A5F5"
    # 辅助色
    ACCENT = "#FF9800"          # 迅雷橙
    DANGER = "#F44336"          # 百度红
    SUCCESS = "#4CAF50"         # 123云盘绿
    INFO = "#00BCD4"            # 和彩云青
    PURPLE = "#9C27B0"          # UC紫

    # 浅色主题（Material 3）
    LIGHT = {
        "bg":              "#FAFAFA",
        "card":            "#FFFFFF",
        "text":            "#212121",
        "text_secondary":  "#757575",
        "divider":         "#E0E0E0",
        "input_bg":        "#F5F5F5",
        "shadow":          "#000000",
        "nav_bg":          "#FFFFFF",
        "nav_inactive":    "#9E9E9E",
        "nav_active":      "#1976D2",
        "ripple":          "#1976D2",
    }

    # 深色主题（Material 3）
    DARK = {
        "bg":              "#121212",
        "card":            "#1E1E1E",
        "text":            "#FFFFFF",
        "text_secondary":  "#B0B0B0",
        "divider":         "#333333",
        "input_bg":        "#2A2A2A",
        "shadow":          "#000000",
        "nav_bg":          "#1E1E1E",
        "nav_inactive":    "#757575",
        "nav_active":      "#42A5F5",
        "ripple":          "#42A5F5",
    }

    @classmethod
    def set_mode(cls, mode: str) -> None:
        """设置主题模式（``"light"`` 或 ``"dark"``）。"""
        cls._mode = mode if mode in ("light", "dark") else "light"

    @classmethod
    def mode(cls) -> str:
        """返回当前主题模式。"""
        return cls._mode

    @classmethod
    def colors(cls) -> dict[str, str]:
        """返回当前主题的颜色字典。"""
        return cls.DARK if cls._mode == "dark" else cls.LIGHT

    @classmethod
    def get(cls, key: str) -> str:
        """获取当前主题的指定颜色。"""
        return cls.colors().get(key, "#FFFFFF")


# ===========================================================================
# 工具函数
# ===========================================================================

def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> list[float]:
    """将十六进制颜色（``#RRGGBB``）转换为 Kivy RGBA 列表。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return [r, g, b, alpha]


# ===========================================================================
# 底部导航栏项
# ===========================================================================

class BottomNavItem(ButtonBehavior, BoxLayout):
    """底部导航栏单个 Tab 项。

    包含图标（文字 emoji）和标签文字，选中时高亮主色调。
    """

    icon = StringProperty("")
    label = StringProperty("")
    active = BooleanProperty(False)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_y = 1
        self.spacing = dp(2)
        self.padding = [0, dp(6), 0, dp(4)]

        self._icon_label = Label(
            text=self.icon,
            font_size=sp(22),
            size_hint_y=None,
            height=dp(26),
        )
        self._text_label = Label(
            text=self.label,
            font_size=sp(11),
            size_hint_y=None,
            height=dp(16),
        )
        self.add_widget(self._icon_label)
        self.add_widget(self._text_label)

        # 选中指示器（顶部小圆点/横条）
        with self.canvas.before:
            self._indicator_color = Color(0, 0, 0, 0)
            self._indicator_rect = RoundedRectangle(
                pos=self.pos, size=(dp(0), dp(0)), radius=[dp(2)]
            )

        self.bind(
            pos=self._update_indicator,
            size=self._update_indicator,
            active=self._update_active,
            icon=self._update_icon,
            label=self._update_label,
        )
        self._update_active()

    def _update_indicator(self, *args: Any) -> None:
        if self.active:
            self._indicator_rect.pos = (self.center_x - dp(12), self.top - dp(4))
            self._indicator_rect.size = (dp(24), dp(3))
        else:
            self._indicator_rect.size = (0, 0)

    def _update_active(self, *args: Any) -> None:
        color = Theme.get("nav_active") if self.active else Theme.get("nav_inactive")
        rgba = hex_to_rgba(color)
        self._icon_label.color = rgba
        self._text_label.color = rgba
        if self.active:
            self._indicator_color.rgba = hex_to_rgba(Theme.get("nav_active"))
        else:
            self._indicator_color.rgba = [0, 0, 0, 0]
        self._update_indicator()

    def _update_icon(self, *args: Any) -> None:
        self._icon_label.text = self.icon

    def _update_label(self, *args: Any) -> None:
        self._text_label.text = self.label

    def on_state(self, widget: Widget, value: str) -> None:
        """按下时轻微缩放效果。"""
        if value == "down":
            self._icon_label.font_size = sp(20)
        else:
            self._icon_label.font_size = sp(22)


# ===========================================================================
# 底部导航栏
# ===========================================================================

class BottomNavigationBar(BoxLayout):
    """底部导航栏（Material 3 Bottom Navigation）。

    固定高度 56dp，包含多个 BottomNavItem，点击切换屏幕。
    白色/深色背景，顶部细线分隔。
    """

    def __init__(
        self,
        items: list[dict[str, str]] | None = None,
        on_tab_select: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(56)
        self._items: list[BottomNavItem] = []
        self._on_tab_select = on_tab_select
        self._active_index = 0

        # 背景
        with self.canvas.before:
            self._bg_color = Color(*hex_to_rgba(Theme.get("nav_bg")))
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size)
            # 顶部分隔线
            self._divider_color = Color(*hex_to_rgba(Theme.get("divider")))
            self._divider_rect = RoundedRectangle(pos=self.pos, size=(self.width, dp(1)))
        self.bind(pos=self._update_bg, size=self._update_bg)

        if items:
            for i, item in enumerate(items):
                nav_item = BottomNavItem(
                    icon=item.get("icon", ""),
                    label=item.get("label", ""),
                    active=(i == 0),
                )
                nav_item.bind(on_release=lambda inst, idx=i: self._on_item_press(idx))
                self._items.append(nav_item)
                self.add_widget(nav_item)

    def _update_bg(self, *args: Any) -> None:
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._divider_rect.pos = (self.x, self.top - dp(1))
        self._divider_rect.size = (self.width, dp(1))

    def _on_item_press(self, index: int) -> None:
        """Tab 项被点击。"""
        self.set_active(index)
        if self._on_tab_select:
            self._on_tab_select(index)

    def set_active(self, index: int) -> None:
        """设置当前激活的 Tab。"""
        self._active_index = index
        for i, item in enumerate(self._items):
            item.active = (i == index)

    def apply_theme(self) -> None:
        """主题切换后刷新颜色。"""
        self._bg_color.rgba = hex_to_rgba(Theme.get("nav_bg"))
        self._divider_color.rgba = hex_to_rgba(Theme.get("divider"))
        for item in self._items:
            item._update_active()


# ===========================================================================
# 浮动操作按钮（FAB）
# ===========================================================================

class FloatingActionButton(ButtonBehavior, Label):
    """Material Design 浮动操作按钮。

    圆形主色按钮，通常悬浮在右下角。
    """

    bg_color = ColorProperty("#1976D2")
    icon_text = StringProperty("+")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.text = self.icon_text
        self.font_size = sp(24)
        self.bold = True
        self.color = hex_to_rgba("#FFFFFF")
        self.size_hint = (None, None)
        self.size = (dp(56), dp(56))
        with self.canvas.before:
            self._bg = Color(*hex_to_rgba(self.bg_color) if isinstance(self.bg_color, str) else self.bg_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(28)])
        self.bind(pos=self._update, size=self._update, bg_color=self._update_bg)

    def _update(self, *args: Any) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _update_bg(self, *args: Any) -> None:
        color = self.bg_color
        if isinstance(color, str):
            color = hex_to_rgba(color)
        self._bg.rgba = color

    def on_state(self, widget: Widget, value: str) -> None:
        if value == "down":
            self._bg.rgba = [c * 0.85 for c in self._bg.rgba[:3]] + [self._bg.rgba[3]]
        else:
            self._update_bg()


# ===========================================================================
# 圆角按钮
# ===========================================================================

class MaterialButton(ButtonBehavior, Label):
    """Material Design 风格圆角按钮。

    支持自定义背景色、文字颜色、圆角半径，以及按下时的颜色加深效果。
    """

    bg_color = ColorProperty("#1976D2")
    text_color = ColorProperty("#FFFFFF")
    radius = NumericProperty(dp(8))
    font_size = NumericProperty(sp(15))

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.markup = True
        self.size_hint_y = None
        self.height = dp(44)
        self._original_bg: list[float] | None = None
        with self.canvas.before:
            self._bg_instruction = Color(*hex_to_rgba(self.bg_color) if isinstance(self.bg_color, str) else self.bg_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
        self.bind(pos=self._update_rect, size=self._update_rect, bg_color=self._update_bg)

    def _update_rect(self, *args: Any) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _update_bg(self, *args: Any) -> None:
        color = self.bg_color
        if isinstance(color, str):
            color = hex_to_rgba(color)
        self._bg_instruction.rgba = color

    def on_state(self, widget: Widget, value: str) -> None:
        """按下时加深背景色。"""
        if value == "down":
            self._original_bg = self._bg_instruction.rgba[:]
            r, g, b, a = self._original_bg
            self._bg_instruction.rgba = [r * 0.8, g * 0.8, b * 0.8, a]
        else:
            if self._original_bg:
                self._bg_instruction.rgba = self._original_bg


# ===========================================================================
# 次要按钮（透明背景 + 主色文字 + 边框）
# ===========================================================================

class OutlinedButton(ButtonBehavior, Label):
    """Material Design 次要按钮（描边样式）。

    透明背景、主色文字、主色边框。
    """

    text_color = ColorProperty("#1976D2")
    border_color = ColorProperty("#1976D2")
    radius = NumericProperty(dp(8))

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.markup = True
        self.size_hint_y = None
        self.height = dp(44)
        self.font_size = sp(15)
        with self.canvas.before:
            self._bg = Color(0, 0, 0, 0)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
            self._border = Color(*hex_to_rgba(self.border_color) if isinstance(self.border_color, str) else self.border_color)
            self._border_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
        self.bind(pos=self._update, size=self._update, border_color=self._update_border)

    def _update(self, *args: Any) -> None:
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._border_rect.pos = self.pos
        self._border_rect.size = self.size

    def _update_border(self, *args: Any) -> None:
        color = self.border_color
        if isinstance(color, str):
            color = hex_to_rgba(color)
        self._border.rgba = color

    def on_state(self, widget: Widget, value: str) -> None:
        if value == "down":
            self._bg.rgba = hex_to_rgba(self.border_color if isinstance(self.border_color, str) else "#1976D2", 0.1)
        else:
            self._bg.rgba = [0, 0, 0, 0]


# ===========================================================================
# 网盘标识标签
# ===========================================================================

class DriveBadge(Label):
    """网盘标识彩色标签。

    根据网盘标识自动设置背景色和文字。
    """

    drive = StringProperty("")
    radius = NumericProperty(dp(4))

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.width = dp(80)
        self.height = dp(28)
        self.font_size = sp(12)
        self.bold = True
        self.color = hex_to_rgba("#FFFFFF")
        with self.canvas.before:
            self._bg = Color(0.6, 0.6, 0.6, 1)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
        self.bind(pos=self._update, size=self._update, drive=self._update_drive)
        if self.drive:
            self._update_drive()

    def _update(self, *args: Any) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _update_drive(self, *args: Any) -> None:
        from mobile_gui.core_adapter import CoreAdapter
        info = CoreAdapter.drive_display(self.drive)
        self.text = info["name"]
        self._bg.rgba = hex_to_rgba(info["color"])


# ===========================================================================
# 圆角卡片容器
# ===========================================================================

class CardWidget(BoxLayout):
    """圆角卡片容器，带轻微阴影效果。

    用作文件列表项、下载任务卡片等的基类。
    """

    radius = NumericProperty(dp(12))
    card_color = StringProperty("#FFFFFF")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = dp(12)
        self.spacing = dp(8)
        with self.canvas.before:
            self._shadow_color = Color(0, 0, 0, 0.08)
            self._shadow_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
            self._bg_color = Color(*hex_to_rgba(self.card_color))
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
        self.bind(pos=self._update, size=self._update, card_color=self._update_color)

    def _update(self, *args: Any) -> None:
        # 阴影略微偏移
        self._shadow_rect.pos = (self.x + dp(1), self.y - dp(1))
        self._shadow_rect.size = self.size
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _update_color(self, *args: Any) -> None:
        self._bg_color.rgba = hex_to_rgba(self.card_color)


# ===========================================================================
# 自定义进度条
# ===========================================================================

class ThemedProgressBar(ProgressBar):
    """自定义颜色的进度条。

    支持设置进度颜色和背景颜色，圆角显示。
    """

    progress_color = StringProperty("#1976D2")
    track_color = StringProperty("#E0E0E0")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(8)
        # 清除默认样式，使用自定义绘制
        with self.canvas:
            self._track = Color(*hex_to_rgba(self.track_color))
            self._track_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(4)])
            self._bar = Color(*hex_to_rgba(self.progress_color))
            self._bar_rect = RoundedRectangle(pos=self.pos, size=(0, self.height), radius=[dp(4)])
        self.bind(pos=self._update, size=self._update, value=self._update, progress_color=self._update_colors)

    def _update(self, *args: Any) -> None:
        self._track_rect.pos = self.pos
        self._track_rect.size = self.size
        ratio = self.value / max(self.max, 1)
        bar_width = self.width * ratio
        self._bar_rect.pos = self.pos
        self._bar_rect.size = (bar_width, self.height)

    def _update_colors(self, *args: Any) -> None:
        self._bar.rgba = hex_to_rgba(self.progress_color)


# ===========================================================================
# 文件列表项（RecycleView 行）
# ===========================================================================

class FileItemWidget(RecycleDataViewBehavior, BoxLayout):
    """文件列表项控件，用于 RecycleView。

    显示：复选框、文件类型图标、文件名、文件大小、网盘标签。
    """

    index = NumericProperty(0)
    file_name = StringProperty("")
    file_size = StringProperty("")
    file_type = StringProperty("")
    drive = StringProperty("")
    selected = BooleanProperty(False)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(56)
        self.padding = [dp(8), dp(4)]
        self.spacing = dp(8)

        # 复选框
        from kivy.uix.checkbox import CheckBox
        self.checkbox = CheckBox(
            size_hint=(None, None),
            size=(dp(24), dp(24)),
            active=self.selected,
        )
        self.checkbox.bind(active=self._on_checkbox)
        self.add_widget(self.checkbox)

        # 类型图标（用文字 emoji 代替，避免外部图片依赖）
        self.icon_label = Label(
            text=self._type_icon(self.file_type),
            size_hint=(None, None),
            size=(dp(32), dp(32)),
            font_size=sp(20),
        )
        self.add_widget(self.icon_label)

        # 文件名 + 大小
        info_box = BoxLayout(orientation="vertical", spacing=dp(2))
        self.name_label = Label(
            text=self.file_name,
            size_hint_y=None,
            height=dp(20),
            font_size=sp(14),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        self.name_label.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
        self.size_label = Label(
            text=self.file_size,
            size_hint_y=None,
            height=dp(16),
            font_size=sp(11),
            color=hex_to_rgba("#757575"),
            halign="left",
            valign="middle",
        )
        info_box.add_widget(self.name_label)
        info_box.add_widget(self.size_label)
        self.add_widget(info_box)

        # 网盘标签
        self.badge = DriveBadge(drive=self.drive)
        self.add_widget(self.badge)

        # 背景
        with self.canvas.before:
            self._bg = Color(1, 1, 1, 1)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(6)])
        self.bind(pos=self._update_bg, size=self._update_bg)

    def _update_bg(self, *args: Any) -> None:
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _on_checkbox(self, instance: Any, value: bool) -> None:
        self.selected = value

    @staticmethod
    def _type_icon(file_type: str) -> str:
        """根据文件类型返回图标 emoji。"""
        type_map = {
            "dir": "📁",
            "mp4": "🎬", "mkv": "🎬", "avi": "🎬", "mov": "🎬",
            "mp3": "🎵", "flac": "🎵", "wav": "🎵", "m4a": "🎵",
            "jpg": "🖼️", "jpeg": "🖼️", "png": "🖼️", "gif": "🖼️", "webp": "🖼️",
            "pdf": "📕",
            "doc": "📘", "docx": "📘",
            "xls": "📗", "xlsx": "📗",
            "zip": "📦", "rar": "📦", "7z": "📦", "tar": "📦", "gz": "📦",
            "txt": "📄", "md": "📄",
            "apk": "📱", "exe": "⚙️",
        }
        return type_map.get(file_type.lower(), "📄")

    def refresh_view_attrs(self, rv: Any, index: int, data: dict[str, Any]) -> None:
        """RecycleView 调用：更新视图数据。"""
        self.index = index
        self.file_name = data.get("file_name", "")
        self.file_size = data.get("file_size", "")
        self.file_type = data.get("file_type", "")
        self.drive = data.get("drive", "")
        self.selected = data.get("selected", False)
        self.name_label.text = self.file_name
        self.size_label.text = self.file_size
        self.icon_label.text = self._type_icon(self.file_type)
        self.badge.drive = self.drive
        self.checkbox.active = self.selected
        return super().refresh_view_attrs(rv, index, data)


# ===========================================================================
# 下载任务卡片
# ===========================================================================

class DownloadTaskCard(CardWidget):
    """下载任务卡片。

    显示文件名、进度条、百分比、速度、已下载/总大小、状态标签，
    以及暂停 / 恢复 / 取消 / 删除按钮。
    """

    task_id = StringProperty("")
    file_name = StringProperty("")
    percent = NumericProperty(0)
    speed_text = StringProperty("0 B/s")
    size_text = StringProperty("0 / 0 B")
    status = StringProperty("waiting")

    STATUS_TEXT = {
        "waiting": "等待中",
        "downloading": "下载中",
        "paused": "已暂停",
        "completed": "已完成",
        "error": "错误",
        "canceled": "已取消",
    }
    STATUS_COLOR = {
        "waiting": "#9E9E9E",
        "downloading": "#1976D2",
        "paused": "#FF9800",
        "completed": "#4CAF50",
        "error": "#F44336",
        "canceled": "#9E9E9E",
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(140)

        # 第一行：文件名 + 状态
        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
        self.name_label = Label(
            text=self.file_name,
            font_size=sp(14),
            bold=True,
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        self.name_label.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
        self.status_label = Label(
            text=self.STATUS_TEXT.get(self.status, self.status),
            size_hint=(None, None),
            size=(dp(60), dp(24)),
            font_size=sp(12),
            bold=True,
            color=hex_to_rgba(self.STATUS_COLOR.get(self.status, "#9E9E9E")),
        )
        header.add_widget(self.name_label)
        header.add_widget(self.status_label)
        self.add_widget(header)

        # 进度条 + 百分比
        progress_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(28), spacing=dp(8))
        self.progress_bar = ThemedProgressBar(
            value=self.percent,
            size_hint_y=None,
            height=dp(10),
        )
        self.percent_label = Label(
            text=f"{self.percent:.1f}%",
            size_hint=(None, None),
            size=(dp(56), dp(28)),
            font_size=sp(13),
            bold=True,
        )
        progress_row.add_widget(self.progress_bar)
        progress_row.add_widget(self.percent_label)
        self.add_widget(progress_row)

        # 速度 + 大小
        info_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(20))
        self.speed_label = Label(
            text=self.speed_text,
            font_size=sp(12),
            color=hex_to_rgba("#757575"),
            halign="left",
        )
        self.size_label = Label(
            text=self.size_text,
            font_size=sp(12),
            color=hex_to_rgba("#757575"),
            halign="right",
        )
        info_row.add_widget(self.speed_label)
        info_row.add_widget(self.size_label)
        self.add_widget(info_row)

        # 控制按钮
        btn_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(8))
        self.pause_btn = MaterialButton(
            text="暂停",
            bg_color="#FF9800",
            font_size=sp(13),
            height=dp(32),
        )
        self.pause_btn.bind(on_release=self._on_pause)
        self.cancel_btn = MaterialButton(
            text="取消",
            bg_color="#F44336",
            font_size=sp(13),
            height=dp(32),
        )
        self.cancel_btn.bind(on_release=self._on_cancel)
        self.delete_btn = MaterialButton(
            text="删除",
            bg_color="#9E9E9E",
            font_size=sp(13),
            height=dp(32),
            disabled=True,
        )
        self.delete_btn.bind(on_release=self._on_delete)
        btn_row.add_widget(self.pause_btn)
        btn_row.add_widget(self.cancel_btn)
        btn_row.add_widget(self.delete_btn)
        self.add_widget(btn_row)

        # 绑定属性更新
        self.bind(
            file_name=self._update_name,
            percent=self._update_progress,
            speed_text=self._update_speed,
            size_text=self._update_size,
            status=self._update_status,
        )

    def _update_name(self, *args: Any) -> None:
        self.name_label.text = self.file_name

    def _update_progress(self, *args: Any) -> None:
        self.progress_bar.value = self.percent
        self.percent_label.text = f"{self.percent:.1f}%"

    def _update_speed(self, *args: Any) -> None:
        self.speed_label.text = self.speed_text

    def _update_size(self, *args: Any) -> None:
        self.size_label.text = self.size_text

    def _update_status(self, *args: Any) -> None:
        self.status_label.text = self.STATUS_TEXT.get(self.status, self.status)
        self.status_label.color = hex_to_rgba(self.STATUS_COLOR.get(self.status, "#9E9E9E"))
        # 根据状态更新按钮
        if self.status == "downloading":
            self.pause_btn.text = "暂停"
            self.pause_btn.bg_color = "#FF9800"
            self.pause_btn.disabled = False
            self.cancel_btn.disabled = False
            self.delete_btn.disabled = True
        elif self.status == "paused":
            self.pause_btn.text = "恢复"
            self.pause_btn.bg_color = "#4CAF50"
            self.pause_btn.disabled = False
            self.cancel_btn.disabled = False
            self.delete_btn.disabled = True
        elif self.status in ("completed", "error", "canceled"):
            self.pause_btn.disabled = True
            self.cancel_btn.disabled = True
            self.delete_btn.disabled = False

    def _on_pause(self, instance: Any) -> None:
        """暂停 / 恢复按钮回调。"""
        app = self.get_app_instance()
        if app and self.task_id:
            if self.status == "downloading":
                app.core.pause_task(self.task_id)
                self.status = "paused"
            elif self.status == "paused":
                app.core.resume_task(self.task_id)
                self.status = "downloading"

    def _on_cancel(self, instance: Any) -> None:
        """取消按钮回调。"""
        app = self.get_app_instance()
        if app and self.task_id:
            app.core.cancel_task(self.task_id)

    def _on_delete(self, instance: Any) -> None:
        """删除已完成/出错/取消的任务。"""
        app = self.get_app_instance()
        if app and self.task_id:
            app.core.remove_task(self.task_id)
            # 从父布局移除
            parent = self.parent
            if parent:
                parent.remove_widget(self)
            # 通知下载屏幕刷新
            if hasattr(app, 'root') and app.root:
                # 通过 ScreenManager 找到 download screen
                sm = app.root if hasattr(app.root, 'get_screen') else None
                if sm and sm.has_screen("download"):
                    sm.get_screen("download")._task_cards.pop(self.task_id, None)

    def get_app_instance(self) -> Any:
        """获取 App 实例（通过 Window 遍历）。"""
        from kivy.app import App
        return App.get_running_app()


# ===========================================================================
# Toast 轻提示
# ===========================================================================

class Toast(Label):
    """轻量级 Toast 提示。

    显示在屏幕底部中央，2 秒后自动淡出消失。
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.text = message
        self.size_hint = (None, None)
        self.width = dp(280)
        self.height = dp(48)
        self.font_size = sp(14)
        self.color = hex_to_rgba("#FFFFFF")
        self.opacity = 0
        with self.canvas.before:
            self._bg = Color(0.15, 0.15, 0.15, 0.9)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(24)])
        self.bind(pos=self._update, size=self._update)

    def _update(self, *args: Any) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def show(self, parent: Widget, duration: float = 2.0) -> None:
        """在指定父控件中显示 Toast。"""
        parent.add_widget(self)
        self.center_x = parent.center_x
        self.y = parent.y + dp(80)
        # 淡入
        anim = Animation(opacity=1, duration=0.2)
        anim += Animation(opacity=1, duration=duration)
        anim += Animation(opacity=0, duration=0.3)
        anim.bind(on_complete=lambda *a: parent.remove_widget(self))
        anim.start(self)


def show_toast(parent: Widget, message: str, duration: float = 2.0) -> None:
    """便捷函数：在父控件中显示 Toast。"""
    toast = Toast(message)
    toast.show(parent, duration)


# ===========================================================================
# 加载旋转指示器
# ===========================================================================

class LoadingSpinner(Widget):
    """旋转加载指示器（Material Design Circular Progress）。

    使用 Canvas 绘制圆弧并旋转动画。
    """

    def __init__(self, color: str = "#1976D2", size: int = 32, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (dp(size), dp(size))
        self._angle = 0
        self._color = color
        with self.canvas:
            self._arc_color = Color(*hex_to_rgba(color))
            from kivy.graphics import Line
            self._arc = Line(circle=(self.center_x, self.center_y, dp(size/2 - 2), 0, 270), width=dp(3))
        self.bind(pos=self._update, size=self._update)
        self._anim = Animation()
        self._start_rotation()

    def _update(self, *args: Any) -> None:
        self._arc.circle = (self.center_x, self.center_y, self.width / 2 - dp(2), self._angle, self._angle + 270)

    def _start_rotation(self) -> None:
        """启动旋转动画。"""
        def _rotate(dt: float) -> None:
            self._angle = (self._angle + 12) % 360
            self._update()
        self._event = Clock.schedule_interval(_rotate, 1 / 30)

    def stop(self) -> None:
        """停止旋转动画。"""
        if hasattr(self, '_event'):
            self._event.cancel()
