"""
主屏幕（解析 Tab）。

功能：
- 顶部标题栏「YunX 云析」
- 平台切换（SegmentedButton：网盘解析 / 视频解析 / 音乐解析）
- 网盘解析：URL 输入 + 提取码 + 文件列表 + 下载
- 视频解析：URL 输入 + 解析结果卡片（标题/封面/时长）+ 清晰度选择 + 下载
- 音乐解析：URL 输入 + 歌曲列表（多选）+ 音质选择 + 下载
- 剪贴板识别横幅
- 底部操作栏（随平台切换）
"""

from __future__ import annotations

from typing import Any

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from mobile_gui.core_adapter import CoreAdapter
from mobile_gui.ui.dialogs import BaiduRiskDialog, ErrorDialog
from mobile_gui.ui.widgets import (
    DriveBadge,
    LoadingSpinner,
    MaterialButton,
    Theme,
    hex_to_rgba,
    show_toast,
)


# ===========================================================================
# 文件列表 RecycleView（网盘）
# ===========================================================================

class FileRecycleView(RecycleView):
    """文件列表 RecycleView。

    数据项格式：
    ``{"file_name": str, "file_size": str, "file_type": str, "drive": str, "selected": bool}``
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.viewclass = "FileItemWidget"
        self.data = []
        from kivy.uix.recycleboxlayout import RecycleBoxLayout
        layout = RecycleBoxLayout(
            default_size=(None, dp(56)),
            default_size_hint=(1, None),
            size_hint_y=None,
            orientation="vertical",
            spacing=dp(4),
            padding=dp(4),
        )
        layout.bind(minimum_height=layout.setter("height"))
        self.add_widget(layout)


# ===========================================================================
# 歌曲列表 RecycleView（音乐）
# ===========================================================================

class SongRecycleView(RecycleView):
    """歌曲列表 RecycleView。

    数据项格式：
    ``{"song_name": str, "artist": str, "album": str, "duration": str,
       "source": str, "selected": bool, "copyright_restricted": bool}``
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.viewclass = "SongItemWidget"
        self.data = []
        from kivy.uix.recycleboxlayout import RecycleBoxLayout
        layout = RecycleBoxLayout(
            default_size=(None, dp(60)),
            default_size_hint=(1, None),
            size_hint_y=None,
            orientation="vertical",
            spacing=dp(4),
            padding=dp(4),
        )
        layout.bind(minimum_height=layout.setter("height"))
        self.add_widget(layout)


# ===========================================================================
# 歌曲列表项
# ===========================================================================

class SongItemWidget(RecycleDataViewBehavior, BoxLayout):
    """歌曲列表项控件，用于 RecycleView。

    显示：复选框、歌曲名、歌手/专辑、时长。
    """

    index = NumericProperty(0)
    song_name = StringProperty("")
    artist = StringProperty("")
    album = StringProperty("")
    duration = StringProperty("")
    selected = BooleanProperty(False)
    copyright_restricted = BooleanProperty(False)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(60)
        self.padding = [dp(8), dp(4)]
        self.spacing = dp(8)

        from kivy.uix.checkbox import CheckBox
        self.checkbox = CheckBox(
            size_hint=(None, None),
            size=(dp(24), dp(24)),
        )
        self.checkbox.bind(active=self._on_checkbox)
        self.add_widget(self.checkbox)

        icon = Label(
            text="🎵",
            size_hint=(None, None),
            size=(dp(32), dp(32)),
            font_size=sp(20),
        )
        self.add_widget(icon)

        info_box = BoxLayout(orientation="vertical", spacing=dp(2))
        self.name_label = Label(
            text="",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(14),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        self.name_label.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
        self.artist_label = Label(
            text="",
            size_hint_y=None,
            height=dp(16),
            font_size=sp(11),
            color=hex_to_rgba("#757575"),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        self.artist_label.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
        info_box.add_widget(self.name_label)
        info_box.add_widget(self.artist_label)
        self.add_widget(info_box)

        self.duration_label = Label(
            text="",
            size_hint=(None, None),
            size=(dp(48), dp(20)),
            font_size=sp(12),
            color=hex_to_rgba("#757575"),
        )
        self.add_widget(self.duration_label)

        with self.canvas.before:
            self._bg = Color(1, 1, 1, 1)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(6)])
        self.bind(pos=self._update_bg, size=self._update_bg)

    def _update_bg(self, *args: Any) -> None:
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _on_checkbox(self, instance: Any, value: bool) -> None:
        self.selected = value

    def refresh_view_attrs(self, rv: Any, index: int, data: dict[str, Any]) -> None:
        """RecycleView 调用：更新视图数据。"""
        self.index = index
        self.song_name = data.get("song_name", "")
        self.artist = data.get("artist", "")
        self.album = data.get("album", "")
        self.duration = data.get("duration", "")
        self.selected = data.get("selected", False)
        self.copyright_restricted = data.get("copyright_restricted", False)

        self.name_label.text = self.song_name
        artist_text = self.artist
        if self.album:
            artist_text = f"{self.artist} · {self.album}"
        if self.copyright_restricted:
            artist_text = f"[color=#F44336]🔒 版权受限[/color] {artist_text}"
            self.name_label.color = hex_to_rgba("#9E9E9E")
        else:
            self.name_label.color = hex_to_rgba(Theme.get("text"))
        self.artist_label.text = artist_text
        self.artist_label.markup = True
        self.duration_label.text = self.duration
        self.checkbox.active = self.selected
        self.checkbox.disabled = self.copyright_restricted
        return super().refresh_view_attrs(rv, index, data)


# ===========================================================================
# 剪贴板识别横幅
# ===========================================================================

class ClipboardBanner(BoxLayout):
    """剪贴板识别横幅。"""

    def __init__(self, on_fill: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(44)
        self.padding = [dp(12), 0]
        self.spacing = dp(8)
        self._on_fill = on_fill
        self.opacity = 0

        with self.canvas.before:
            self._bg = Color(*hex_to_rgba("#E3F2FD"))
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])
        self.bind(pos=self._update, size=self._update)

        icon = Label(
            text="📋",
            size_hint=(None, None),
            size=(dp(24), dp(24)),
            font_size=sp(16),
        )
        self._text_label = Label(
            text="检测到剪贴板链接，点击填入",
            font_size=sp(13),
            color=hex_to_rgba("#1565C0"),
            halign="left",
            valign="middle",
        )
        self._text_label.bind(size=self._text_label.setter("text_size"))

        fill_btn = MaterialButton(
            text="填入",
            bg_color="#1976D2",
            font_size=sp(12),
            size_hint=(None, None),
            size=(dp(56), dp(32)),
            height=dp(32),
        )
        fill_btn.bind(on_release=self._on_fill_pressed)

        self.add_widget(icon)
        self.add_widget(self._text_label)
        self.add_widget(fill_btn)

    def _update(self, *args: Any) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _on_fill_pressed(self, *args: Any) -> None:
        if self._on_fill:
            self._on_fill()
        self.hide()

    def show(self, drive_name: str = "") -> None:
        if drive_name:
            self._text_label.text = f"检测到剪贴板链接（{drive_name}），点击填入"
        self.opacity = 1
        self.height = dp(44)

    def hide(self) -> None:
        self.opacity = 0
        self.height = 0


# ===========================================================================
# 平台切换 SegmentedButton
# ===========================================================================

class PlatformSwitcher(BoxLayout):
    """平台切换分段按钮。

    三个按钮：网盘解析 / 视频解析 / 音乐解析，选中时主色高亮。
    """

    PLATFORMS = [
        ("网盘", "pan"),
        ("视频", "video"),
        ("音乐", "music"),
    ]

    def __init__(self, on_switch: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(44)
        self.spacing = dp(4)
        self.padding = [dp(12), dp(6)]
        self._on_switch = on_switch
        self._buttons: list[MaterialButton] = []
        self._active = "pan"

        with self.canvas.before:
            self._bg = Color(*hex_to_rgba(Theme.get("card")))
            self._rect = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update, size=self._update)

        for i, (label, key) in enumerate(self.PLATFORMS):
            btn = MaterialButton(
                text=label,
                bg_color="#1976D2" if i == 0 else "#E0E0E0",
                text_color="#FFFFFF" if i == 0 else "#757575",
                font_size=sp(13),
                height=dp(36),
            )
            btn.bind(on_release=lambda inst, k=key: self._switch_to(k))
            self._buttons.append(btn)
            self.add_widget(btn)

    def _update(self, *args: Any) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _switch_to(self, platform: str) -> None:
        self._active = platform
        for i, (_, key) in enumerate(self.PLATFORMS):
            btn = self._buttons[i]
            if key == platform:
                btn.bg_color = "#1976D2"
                btn.text_color = "#FFFFFF"
            else:
                btn.bg_color = "#E0E0E0"
                btn.text_color = "#757575"
        if self._on_switch:
            self._on_switch(platform)

    @property
    def active(self) -> str:
        return self._active


# ===========================================================================
# 主屏幕（解析 Tab）
# ===========================================================================

class MainScreen(Screen):
    """主屏幕：平台切换 + 网盘/视频/音乐解析。"""

    # 当前解析结果
    current_share = ObjectProperty(None, allownone=True)
    current_video = ObjectProperty(None, allownone=True)
    current_music = ObjectProperty(None, allownone=True)
    # 文件列表数据
    file_data = ListProperty([])
    song_data = ListProperty([])

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.name = "main"
        self._baidu_confirmed = False
        self._pending_parse_url = ""
        self._pending_extract_code = ""
        self._loading_spinner: LoadingSpinner | None = None
        self._current_platform = "pan"
        self._video_quality_index = 0
        self._music_quality_index = 1  # higher

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical")

        with root.canvas.before:
            self._bg_color = Color(*hex_to_rgba(Theme.get("bg")))
            self._bg_rect = RoundedRectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._update_bg, size=self._update_bg)

        # -- 顶部标题栏 --
        title_bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=[dp(16), 0],
            spacing=dp(8),
        )
        with title_bar.canvas.before:
            Color(*hex_to_rgba("#1976D2"))
            RoundedRectangle(pos=title_bar.pos, size=title_bar.size)

        title_label = Label(
            text="[b]YunX 云析[/b]",
            markup=True,
            font_size=sp(20),
            color=hex_to_rgba("#FFFFFF"),
            halign="left",
            valign="middle",
        )
        title_label.bind(size=title_label.setter("text_size"))

        self._account_status = Label(
            text="☁️",
            size_hint=(None, None),
            size=(dp(32), dp(32)),
            font_size=sp(20),
        )
        title_bar.add_widget(title_label)
        title_bar.add_widget(self._account_status)
        root.add_widget(title_bar)

        # -- 平台切换 --
        self._platform_switcher = PlatformSwitcher(on_switch=self._on_platform_switch)
        root.add_widget(self._platform_switcher)

        # -- 内容区（三个面板，只显示一个）--
        self._content_area = BoxLayout(orientation="vertical")
        root.add_widget(self._content_area)

        # 网盘面板
        self._pan_panel = self._build_pan_panel()
        # 视频面板
        self._video_panel = self._build_video_panel()
        # 音乐面板
        self._music_panel = self._build_music_panel()

        self._content_area.add_widget(self._pan_panel)
        self._current_panel = self._pan_panel

        self.add_widget(root)

    def _build_pan_panel(self) -> BoxLayout:
        """构建网盘解析面板。"""
        panel = BoxLayout(orientation="vertical")

        content = ScrollView(size_hint=(1, 1))
        content_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(12),
            padding=dp(12),
        )
        content_box.bind(minimum_height=content_box.setter("height"))

        # 剪贴板横幅
        self._clipboard_banner = ClipboardBanner(on_fill=self._fill_from_clipboard)
        content_box.add_widget(self._clipboard_banner)

        # URL 输入卡片
        url_card = self._build_url_card()
        content_box.add_widget(url_card)

        # 网盘标识区
        self._drive_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
            spacing=dp(8),
            padding=[dp(4), 0],
        )
        self._drive_badge = DriveBadge(drive="")
        self._drive_badge.opacity = 0
        self._drive_box.add_widget(self._drive_badge)
        self._drive_box.add_widget(Label())
        content_box.add_widget(self._drive_box)

        # 文件列表标题
        list_header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(32),
            padding=[dp(4), 0],
        )
        list_title = Label(
            text="分享内容",
            font_size=sp(15),
            bold=True,
            halign="left",
            color=hex_to_rgba(Theme.get("text")),
        )
        list_title.bind(size=list_title.setter("text_size"))
        list_header.add_widget(list_title)
        content_box.add_widget(list_header)

        self._file_rv = FileRecycleView(size_hint_y=None, height=dp(200))
        content_box.add_widget(self._file_rv)

        self._empty_label = Label(
            text="输入分享链接并点击「解析」\n支持夸克、123云盘、迅雷、百度、UC、和彩云",
            font_size=sp(13),
            color=hex_to_rgba("#9E9E9E"),
            halign="center",
            size_hint_y=None,
            height=dp(60),
        )
        content_box.add_widget(self._empty_label)

        content.add_widget(content_box)
        panel.add_widget(content)

        # 底部操作栏
        bottom_bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=[dp(8), dp(6)],
            spacing=dp(8),
        )
        with bottom_bar.canvas.before:
            Color(*hex_to_rgba(Theme.get("card")))
            RoundedRectangle(pos=bottom_bar.pos, size=bottom_bar.size)

        self._select_all_btn = MaterialButton(
            text="全选", bg_color="#FF9800", font_size=sp(13), height=dp(40),
        )
        self._select_all_btn.bind(on_release=self._select_all)

        self._download_btn = MaterialButton(
            text="下载选中", bg_color="#4CAF50", font_size=sp(14), height=dp(40),
        )
        self._download_btn.bind(on_release=self._download_selected)

        self._download_dir_btn = MaterialButton(
            text="下载目录", bg_color="#9E9E9E", font_size=sp(13), height=dp(40),
        )
        self._download_dir_btn.bind(on_release=self._show_download_dir)

        bottom_bar.add_widget(self._select_all_btn)
        bottom_bar.add_widget(self._download_btn)
        bottom_bar.add_widget(self._download_dir_btn)
        panel.add_widget(bottom_bar)

        return panel

    def _build_url_card(self) -> BoxLayout:
        """构建网盘 URL 输入卡片。"""
        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(200),
            padding=dp(12),
            spacing=dp(8),
        )
        with card.canvas.before:
            self._card_bg = Color(*hex_to_rgba(Theme.get("card")))
            self._card_rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(12)])
        card.bind(pos=self._update_card, size=self._update_card)

        self._url_input = TextInput(
            multiline=False,
            size_hint_y=None,
            height=dp(48),
            font_size=sp(15),
            hint_text="粘贴分享链接...",
            background_color=hex_to_rgba(Theme.get("input_bg")),
            foreground_color=hex_to_rgba(Theme.get("text")),
            cursor_color=hex_to_rgba("#1976D2"),
            padding=[dp(12), dp(12)],
        )
        card.add_widget(self._url_input)

        row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8),
        )
        self._code_input = TextInput(
            multiline=False,
            size_hint_x=0.4,
            font_size=sp(14),
            hint_text="提取码（可选）",
            background_color=hex_to_rgba(Theme.get("input_bg")),
            foreground_color=hex_to_rgba(Theme.get("text")),
            cursor_color=hex_to_rgba("#1976D2"),
            padding=[dp(10), dp(10)],
        )
        self._parse_btn = MaterialButton(
            text="🔍 解析",
            bg_color="#1976D2",
            font_size=sp(15),
            size_hint_x=0.6,
            height=dp(44),
        )
        self._parse_btn.bind(on_release=self._on_parse)
        row.add_widget(self._code_input)
        row.add_widget(self._parse_btn)
        card.add_widget(row)

        clipboard_btn = MaterialButton(
            text="📋 从剪贴板读取",
            bg_color="#78909C",
            font_size=sp(13),
            height=dp(36),
        )
        clipboard_btn.bind(on_release=self._on_clipboard)
        card.add_widget(clipboard_btn)

        return card

    def _build_video_panel(self) -> BoxLayout:
        """构建视频解析面板。"""
        panel = BoxLayout(orientation="vertical")

        content = ScrollView(size_hint=(1, 1))
        content_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(12),
            padding=dp(12),
        )
        content_box.bind(minimum_height=content_box.setter("height"))

        # 视频 URL 输入卡片
        input_card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(140),
            padding=dp(12),
            spacing=dp(8),
        )
        with input_card.canvas.before:
            Color(*hex_to_rgba(Theme.get("card")))
            RoundedRectangle(pos=input_card.pos, size=input_card.size, radius=[dp(12)])

        self._video_url_input = TextInput(
            multiline=False,
            size_hint_y=None,
            height=dp(48),
            font_size=sp(15),
            hint_text="粘贴视频链接（B站/抖音/YouTube等）",
            background_color=hex_to_rgba(Theme.get("input_bg")),
            foreground_color=hex_to_rgba(Theme.get("text")),
            cursor_color=hex_to_rgba("#1976D2"),
            padding=[dp(12), dp(12)],
        )
        input_card.add_widget(self._video_url_input)

        self._video_parse_btn = MaterialButton(
            text="🔍 解析视频",
            bg_color="#1976D2",
            font_size=sp(15),
            height=dp(44),
        )
        self._video_parse_btn.bind(on_release=self._on_video_parse)
        input_card.add_widget(self._video_parse_btn)

        video_clip_btn = MaterialButton(
            text="📋 从剪贴板读取",
            bg_color="#78909C",
            font_size=sp(13),
            height=dp(32),
        )
        video_clip_btn.bind(on_release=self._on_video_clipboard)
        input_card.add_widget(video_clip_btn)

        content_box.add_widget(input_card)

        # 视频解析结果卡片
        self._video_result_card = self._build_video_result_card()
        content_box.add_widget(self._video_result_card)

        # 空状态
        self._video_empty = Label(
            text="支持 B站、抖音、YouTube、快手、微博等平台\n实验性平台解析可能不稳定",
            font_size=sp(13),
            color=hex_to_rgba("#9E9E9E"),
            halign="center",
            size_hint_y=None,
            height=dp(50),
        )
        content_box.add_widget(self._video_empty)

        content.add_widget(content_box)
        panel.add_widget(content)

        # 视频底部操作栏
        video_bottom = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=[dp(8), dp(6)],
            spacing=dp(8),
        )
        with video_bottom.canvas.before:
            Color(*hex_to_rgba(Theme.get("card")))
            RoundedRectangle(pos=video_bottom.pos, size=video_bottom.size)

        self._video_quality_btn = MaterialButton(
            text="清晰度: 1080p",
            bg_color="#FF9800",
            font_size=sp(13),
            height=dp(40),
        )
        self._video_quality_btn.bind(on_release=self._cycle_video_quality)

        self._video_download_btn = MaterialButton(
            text="⬇️ 下载视频",
            bg_color="#4CAF50",
            font_size=sp(14),
            height=dp(40),
            disabled=True,
        )
        self._video_download_btn.bind(on_release=self._on_video_download)

        video_bottom.add_widget(self._video_quality_btn)
        video_bottom.add_widget(self._video_download_btn)
        panel.add_widget(video_bottom)

        return panel

    def _build_video_result_card(self) -> BoxLayout:
        """构建视频解析结果卡片。"""
        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(160),
            padding=dp(12),
            spacing=dp(8),
            opacity=0,
        )
        with card.canvas.before:
            self._video_card_bg = Color(*hex_to_rgba(Theme.get("card")))
            self._video_card_rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(12)])
        card.bind(pos=self._update_video_card, size=self._update_video_card)

        # 平台标签 + 时长
        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(28))
        self._video_platform_badge = Label(
            text="",
            size_hint=(None, None),
            size=(dp(100), dp(24)),
            font_size=sp(12),
            bold=True,
            color=hex_to_rgba("#FFFFFF"),
        )
        with self._video_platform_badge.canvas.before:
            self._video_badge_bg = Color(0.6, 0.6, 0.6, 1)
            self._video_badge_rect = RoundedRectangle(
                pos=self._video_platform_badge.pos,
                size=self._video_platform_badge.size,
                radius=[dp(4)],
            )
        self._video_platform_badge.bind(pos=self._update_video_badge, size=self._update_video_badge)

        self._video_duration_label = Label(
            text="",
            font_size=sp(13),
            color=hex_to_rgba("#757575"),
            halign="right",
        )
        header.add_widget(self._video_platform_badge)
        header.add_widget(self._video_duration_label)
        card.add_widget(header)

        # 标题
        self._video_title_label = Label(
            text="",
            font_size=sp(15),
            bold=True,
            halign="left",
            valign="top",
            size_hint_y=None,
            height=dp(44),
            color=hex_to_rgba(Theme.get("text")),
            text_size=(dp(320), None),
        )
        card.add_widget(self._video_title_label)

        # 封面占位 + 清晰度列表
        info_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(60), spacing=dp(8))
        self._video_cover_label = Label(
            text="🎬",
            size_hint=(None, None),
            size=(dp(80), dp(60)),
            font_size=sp(36),
        )
        with self._video_cover_label.canvas.before:
            Color(*hex_to_rgba("#F5F5F5"))
            RoundedRectangle(pos=self._video_cover_label.pos, size=self._video_cover_label.size, radius=[dp(6)])

        quality_box = BoxLayout(orientation="vertical", spacing=dp(2))
        quality_title = Label(
            text="可用清晰度",
            font_size=sp(11),
            color=hex_to_rgba("#757575"),
            halign="left",
            size_hint_y=None,
            height=dp(16),
        )
        self._video_quality_list = Label(
            text="",
            font_size=sp(12),
            color=hex_to_rgba(Theme.get("text")),
            halign="left",
            valign="top",
            size_hint_y=None,
            height=dp(40),
            text_size=(dp(220), None),
        )
        quality_box.add_widget(quality_title)
        quality_box.add_widget(self._video_quality_list)

        info_row.add_widget(self._video_cover_label)
        info_row.add_widget(quality_box)
        card.add_widget(info_row)

        return card

    def _build_music_panel(self) -> BoxLayout:
        """构建音乐解析面板。"""
        panel = BoxLayout(orientation="vertical")

        content = ScrollView(size_hint=(1, 1))
        content_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(12),
            padding=dp(12),
        )
        content_box.bind(minimum_height=content_box.setter("height"))

        # 音乐 URL 输入卡片
        input_card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(140),
            padding=dp(12),
            spacing=dp(8),
        )
        with input_card.canvas.before:
            Color(*hex_to_rgba(Theme.get("card")))
            RoundedRectangle(pos=input_card.pos, size=input_card.size, radius=[dp(12)])

        self._music_url_input = TextInput(
            multiline=False,
            size_hint_y=None,
            height=dp(48),
            font_size=sp(15),
            hint_text="粘贴音乐链接（网易云/QQ音乐/单曲/歌单）",
            background_color=hex_to_rgba(Theme.get("input_bg")),
            foreground_color=hex_to_rgba(Theme.get("text")),
            cursor_color=hex_to_rgba("#1976D2"),
            padding=[dp(12), dp(12)],
        )
        input_card.add_widget(self._music_url_input)

        self._music_parse_btn = MaterialButton(
            text="🔍 解析音乐",
            bg_color="#1976D2",
            font_size=sp(15),
            height=dp(44),
        )
        self._music_parse_btn.bind(on_release=self._on_music_parse)
        input_card.add_widget(self._music_parse_btn)

        music_clip_btn = MaterialButton(
            text="📋 从剪贴板读取",
            bg_color="#78909C",
            font_size=sp(13),
            height=dp(32),
        )
        music_clip_btn.bind(on_release=self._on_music_clipboard)
        input_card.add_widget(music_clip_btn)

        content_box.add_widget(input_card)

        # 歌曲列表标题
        self._music_list_header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(32),
            padding=[dp(4), 0],
            opacity=0,
        )
        self._music_list_title = Label(
            text="歌曲列表",
            font_size=sp(15),
            bold=True,
            halign="left",
            color=hex_to_rgba(Theme.get("text")),
        )
        self._music_list_title.bind(size=self._music_list_title.setter("text_size"))
        self._music_count_label = Label(
            text="",
            font_size=sp(12),
            color=hex_to_rgba("#757575"),
            halign="right",
        )
        self._music_list_header.add_widget(self._music_list_title)
        self._music_list_header.add_widget(self._music_count_label)
        content_box.add_widget(self._music_list_header)

        # 歌曲列表
        self._song_rv = SongRecycleView(size_hint_y=None, height=dp(240))
        content_box.add_widget(self._song_rv)

        # 空状态
        self._music_empty = Label(
            text="支持网易云音乐、QQ音乐\n单曲或歌单/专辑链接",
            font_size=sp(13),
            color=hex_to_rgba("#9E9E9E"),
            halign="center",
            size_hint_y=None,
            height=dp(50),
        )
        content_box.add_widget(self._music_empty)

        content.add_widget(content_box)
        panel.add_widget(content)

        # 音乐底部操作栏
        music_bottom = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=[dp(8), dp(6)],
            spacing=dp(8),
        )
        with music_bottom.canvas.before:
            Color(*hex_to_rgba(Theme.get("card")))
            RoundedRectangle(pos=music_bottom.pos, size=music_bottom.size)

        self._music_quality_btn = MaterialButton(
            text="音质: 高品质",
            bg_color="#FF9800",
            font_size=sp(12),
            height=dp(40),
        )
        self._music_quality_btn.bind(on_release=self._cycle_music_quality)

        self._music_download_btn = MaterialButton(
            text="⬇️ 下载选中",
            bg_color="#4CAF50",
            font_size=sp(13),
            height=dp(40),
            disabled=True,
        )
        self._music_download_btn.bind(on_release=self._on_music_download_selected)

        self._music_download_all_btn = MaterialButton(
            text="全部下载",
            bg_color="#2196F3",
            font_size=sp(13),
            height=dp(40),
            disabled=True,
        )
        self._music_download_all_btn.bind(on_release=self._on_music_download_all)

        music_bottom.add_widget(self._music_quality_btn)
        music_bottom.add_widget(self._music_download_btn)
        music_bottom.add_widget(self._music_download_all_btn)
        panel.add_widget(music_bottom)

        return panel

    # ------------------------------------------------------------------
    # 背景更新
    # ------------------------------------------------------------------

    def _update_bg(self, *args: Any) -> None:
        self._bg_rect.pos = self.children[0].pos
        self._bg_rect.size = self.children[0].size

    def _update_card(self, *args: Any) -> None:
        pass

    def _update_video_card(self, *args: Any) -> None:
        pass

    def _update_video_badge(self, *args: Any) -> None:
        self._video_badge_rect.pos = self._video_platform_badge.pos
        self._video_badge_rect.size = self._video_platform_badge.size

    # ------------------------------------------------------------------
    # 平台切换
    # ------------------------------------------------------------------

    def _on_platform_switch(self, platform: str) -> None:
        """切换解析平台面板。"""
        self._current_platform = platform
        self._content_area.remove_widget(self._current_panel)

        if platform == "pan":
            self._content_area.add_widget(self._pan_panel)
            self._current_panel = self._pan_panel
        elif platform == "video":
            self._content_area.add_widget(self._video_panel)
            self._current_panel = self._video_panel
        elif platform == "music":
            self._content_area.add_widget(self._music_panel)
            self._current_panel = self._music_panel

    # ------------------------------------------------------------------
    # 剪贴板
    # ------------------------------------------------------------------

    def _on_clipboard(self, *args: Any) -> None:
        from kivy.app import App
        app = App.get_running_app()
        results = app.core.detect_from_clipboard()
        if results:
            share = results[0]
            self._url_input.text = share.url
            if share.extract_code:
                self._code_input.text = share.extract_code
            show_toast(self, f"已识别：{CoreAdapter.drive_display(share.drive)['name']}")
        else:
            text = app.core.read_clipboard()
            if text:
                self._url_input.text = text.strip()
                show_toast(self, "已粘贴剪贴板内容")
            else:
                show_toast(self, "剪贴板为空")

    def _on_video_clipboard(self, *args: Any) -> None:
        from kivy.app import App
        app = App.get_running_app()
        text = app.core.read_clipboard()
        if text:
            self._video_url_input.text = text.strip()
            show_toast(self, "已粘贴剪贴板内容")
        else:
            show_toast(self, "剪贴板为空")

    def _on_music_clipboard(self, *args: Any) -> None:
        from kivy.app import App
        app = App.get_running_app()
        text = app.core.read_clipboard()
        if text:
            self._music_url_input.text = text.strip()
            show_toast(self, "已粘贴剪贴板内容")
        else:
            show_toast(self, "剪贴板为空")

    def _fill_from_clipboard(self) -> None:
        self._on_clipboard()

    def check_clipboard_banner(self) -> None:
        from kivy.app import App
        app = App.get_running_app()
        if not app.core:
            return
        results = app.core.detect_from_clipboard()
        if results:
            share = results[0]
            info = CoreAdapter.drive_display(share.drive)
            self._clipboard_banner.show(info["name"])
        else:
            self._clipboard_banner.hide()

    # ------------------------------------------------------------------
    # 网盘解析逻辑
    # ------------------------------------------------------------------

    def _on_parse(self, *args: Any) -> None:
        url = self._url_input.text.strip()
        extract_code = self._code_input.text.strip() or None
        if not url:
            show_toast(self, "请输入分享链接")
            return

        self._show_loading()

        from kivy.app import App
        app = App.get_running_app()

        app.core.parse_share(
            url=url,
            extract_code=extract_code,
            on_success=self._on_parse_success,
            on_error=self._on_parse_error,
            on_baidu_warning=self._on_baidu_warning,
        )

    def _show_loading(self) -> None:
        self._parse_btn.text = "解析中..."
        self._parse_btn.disabled = True

    def _hide_loading(self) -> None:
        self._parse_btn.text = "🔍 解析"
        self._parse_btn.disabled = False

    def _on_baidu_warning(self) -> bool:
        import threading
        result_holder: dict[str, bool] = {}
        event = threading.Event()

        def on_confirm() -> None:
            result_holder["confirmed"] = True
            event.set()

        def on_cancel() -> None:
            result_holder["confirmed"] = False
            event.set()

        dialog = BaiduRiskDialog(on_confirm=on_confirm, on_cancel=on_cancel)
        dialog.open()
        event.wait(timeout=300)
        return result_holder.get("confirmed", False)

    def _on_parse_success(self, share_info: Any) -> None:
        self._hide_loading()
        self.current_share = share_info

        drive = getattr(share_info, "drive", "")
        self._drive_badge.drive = drive
        self._drive_badge.opacity = 1

        size_text = CoreAdapter.format_size(share_info.file_size)
        self.file_data = [{
            "file_name": share_info.file_name,
            "file_size": size_text,
            "file_type": getattr(share_info, "file_type", ""),
            "drive": drive,
            "selected": True,
        }]
        self._file_rv.data = self.file_data
        self._empty_label.text = ""
        self._empty_label.height = 0

        show_toast(self, f"解析成功：{share_info.file_name}")

    def _on_parse_error(self, error: Exception) -> None:
        self._hide_loading()
        from core import BaiduRiskWarning
        if isinstance(error, BaiduRiskWarning):
            show_toast(self, "已取消百度网盘解析")
        else:
            ErrorDialog(title="解析失败", message=str(error)).open()

    # ------------------------------------------------------------------
    # 网盘文件列表操作
    # ------------------------------------------------------------------

    def _select_all(self, *args: Any) -> None:
        if not self.file_data:
            return
        all_selected = all(item.get("selected", False) for item in self.file_data)
        new_state = not all_selected
        for item in self.file_data:
            item["selected"] = new_state
        self._file_rv.data = self.file_data
        self._file_rv.refresh_from_data()
        self._select_all_btn.text = "取消全选" if new_state else "全选"

    def _download_selected(self, *args: Any) -> None:
        if not self.current_share:
            show_toast(self, "请先解析分享链接")
            return

        selected = [item for item in self.file_data if item.get("selected", False)]
        if not selected:
            show_toast(self, "请至少选择一个文件")
            return

        from kivy.app import App
        app = App.get_running_app()

        download_dir = app.get_setting("download_dir", CoreAdapter.default_download_dir())
        concurrency = int(app.get_setting("concurrency", 8))
        chunk_size = int(app.get_setting("chunk_size", 4 * 1024 * 1024))

        share_info = self.current_share
        task_id = app.core.start_download(
            share_info=share_info,
            output_dir=download_dir,
            concurrency=concurrency,
            chunk_size=chunk_size,
            on_progress=self._on_download_progress,
            on_status=self._on_download_status,
            on_error=self._on_download_error,
        )
        app.add_download_task_id(task_id)
        show_toast(self, "已开始下载")
        Clock.schedule_once(lambda dt: app.switch_tab("download"), 0.5)

    def _on_download_progress(self, task: Any) -> None:
        from kivy.app import App
        app = App.get_running_app()
        app.notify_download_update(task)

    def _on_download_status(self, task: Any) -> None:
        from kivy.app import App
        app = App.get_running_app()
        app.notify_download_update(task)

    def _on_download_error(self, error: Exception) -> None:
        ErrorDialog(title="下载失败", message=str(error)).open()

    def _show_download_dir(self, *args: Any) -> None:
        from kivy.app import App
        app = App.get_running_app()
        download_dir = app.get_setting("download_dir", CoreAdapter.default_download_dir())
        show_toast(self, f"下载目录：{download_dir}", duration=3.0)

    # ------------------------------------------------------------------
    # 视频解析逻辑
    # ------------------------------------------------------------------

    def _on_video_parse(self, *args: Any) -> None:
        url = self._video_url_input.text.strip()
        if not url:
            show_toast(self, "请输入视频链接")
            return

        self._video_parse_btn.text = "解析中..."
        self._video_parse_btn.disabled = True

        from kivy.app import App
        app = App.get_running_app()
        app.core.parse_video(
            url=url,
            on_success=self._on_video_parse_success,
            on_error=self._on_video_parse_error,
        )

    def _on_video_parse_success(self, video_info: Any) -> None:
        self._video_parse_btn.text = "🔍 解析视频"
        self._video_parse_btn.disabled = False
        self.current_video = video_info

        # 平台标签
        platform = getattr(video_info, "platform", "")
        display = CoreAdapter.video_platform_display(platform)
        self._video_platform_badge.text = display["name"]
        self._video_badge_bg.rgba = hex_to_rgba(display["color"])

        # 标题
        self._video_title_label.text = getattr(video_info, "title", "未知标题")

        # 时长
        duration = getattr(video_info, "duration", 0)
        self._video_duration_label.text = f"⏱ {CoreAdapter.format_duration(duration)}"

        # 清晰度列表
        quality_list = getattr(video_info, "quality_list", [])
        if quality_list:
            qualities = [q.quality for q in quality_list]
            self._video_quality_list.text = " / ".join(qualities)
        else:
            self._video_quality_list.text = "自动选择最高清晰度"

        # 显示结果卡片
        self._video_result_card.opacity = 1
        self._video_empty.text = ""
        self._video_empty.height = 0

        # 启用下载按钮
        self._video_download_btn.disabled = False

        # 同步默认清晰度
        from kivy.app import App
        app = App.get_running_app()
        default_q = app.core.get_video_default_quality()
        self._sync_video_quality_button(default_q)

        show_toast(self, f"解析成功：{getattr(video_info, 'title', '')}")

    def _on_video_parse_error(self, error: Exception) -> None:
        self._video_parse_btn.text = "🔍 解析视频"
        self._video_parse_btn.disabled = False
        ErrorDialog(
            title="视频解析失败",
            message=f"{str(error)}\n\n提示：实验性平台解析可能不稳定，请稍后重试或更换链接。",
        ).open()

    def _cycle_video_quality(self, *args: Any) -> None:
        """循环切换视频清晰度。"""
        options = CoreAdapter.get_video_quality_options()
        self._video_quality_index = (self._video_quality_index + 1) % len(options)
        quality = options[self._video_quality_index]
        self._sync_video_quality_button(quality)

    def _sync_video_quality_button(self, quality: str) -> None:
        options = CoreAdapter.get_video_quality_options()
        if quality in options:
            self._video_quality_index = options.index(quality)
        label = "自动" if quality == "auto" else quality
        self._video_quality_btn.text = f"清晰度: {label}"

    def _on_video_download(self, *args: Any) -> None:
        if not self.current_video:
            show_toast(self, "请先解析视频")
            return

        from kivy.app import App
        app = App.get_running_app()

        options = CoreAdapter.get_video_quality_options()
        quality = options[self._video_quality_index]
        output_dir = app.core.get_video_download_dir()

        task_id = app.core.download_video(
            video_info=self.current_video,
            quality=quality,
            output_dir=output_dir,
            on_progress=self._on_download_progress,
            on_status=self._on_download_status,
            on_error=self._on_download_error,
        )
        app.add_download_task_id(task_id)
        show_toast(self, "视频下载已开始")
        Clock.schedule_once(lambda dt: app.switch_tab("download"), 0.5)

    # ------------------------------------------------------------------
    # 音乐解析逻辑
    # ------------------------------------------------------------------

    def _on_music_parse(self, *args: Any) -> None:
        url = self._music_url_input.text.strip()
        if not url:
            show_toast(self, "请输入音乐链接")
            return

        self._music_parse_btn.text = "解析中..."
        self._music_parse_btn.disabled = True

        from kivy.app import App
        app = App.get_running_app()
        app.core.parse_music(
            url=url,
            on_success=self._on_music_parse_success,
            on_error=self._on_music_parse_error,
        )

    def _on_music_parse_success(self, result: Any) -> None:
        self._music_parse_btn.text = "🔍 解析音乐"
        self._music_parse_btn.disabled = False
        self.current_music = result

        # 判断是单曲还是歌单
        songs = []
        if hasattr(result, "songs"):
            # PlaylistInfo
            songs = result.songs
            self._music_list_title.text = getattr(result, "title", "歌单")
            self._music_count_label.text = f"共 {len(songs)} 首"
        else:
            # SongInfo
            songs = [result]
            self._music_list_title.text = "单曲"
            self._music_count_label.text = "1 首"

        # 构建歌曲列表数据
        self.song_data = []
        for song in songs:
            source = getattr(song, "source", "")
            display = CoreAdapter.music_platform_display(source)
            self.song_data.append({
                "song_name": getattr(song, "title", "未知"),
                "artist": getattr(song, "artist", ""),
                "album": getattr(song, "album", ""),
                "duration": CoreAdapter.format_duration(getattr(song, "duration", 0)),
                "source": display["name"],
                "selected": not getattr(song, "copyright_restricted", False),
                "copyright_restricted": getattr(song, "copyright_restricted", False),
                "song_id": getattr(song, "song_id", ""),
                "url": getattr(song, "url", ""),
            })

        self._song_rv.data = self.song_data
        self._music_list_header.opacity = 1
        self._music_empty.text = ""
        self._music_empty.height = 0
        self._music_download_btn.disabled = False
        self._music_download_all_btn.disabled = False

        # 同步默认音质
        from kivy.app import App
        app = App.get_running_app()
        default_q = app.core.get_music_default_quality()
        self._sync_music_quality_button(default_q)

        count = len(songs)
        show_toast(self, f"解析成功：{count} 首歌曲")

    def _on_music_parse_error(self, error: Exception) -> None:
        self._music_parse_btn.text = "🔍 解析音乐"
        self._music_parse_btn.disabled = False
        ErrorDialog(
            title="音乐解析失败",
            message=f"{str(error)}\n\n提示：请检查链接是否有效，实验性平台可能不稳定。",
        ).open()

    def _cycle_music_quality(self, *args: Any) -> None:
        """循环切换音乐音质。"""
        options = CoreAdapter.get_music_quality_options()
        self._music_quality_index = (self._music_quality_index + 1) % len(options)
        quality = options[self._music_quality_index]
        self._sync_music_quality_button(quality)

    def _sync_music_quality_button(self, quality: str) -> None:
        options = CoreAdapter.get_music_quality_options()
        if quality in options:
            self._music_quality_index = options.index(quality)
        labels = CoreAdapter.get_music_quality_labels()
        label = labels.get(quality, quality)
        self._music_quality_btn.text = f"音质: {label.split()[0]}"

    def _get_selected_songs(self) -> list[dict[str, Any]]:
        """获取选中的歌曲数据。"""
        return [s for s in self.song_data if s.get("selected", False) and not s.get("copyright_restricted", False)]

    def _on_music_download_selected(self, *args: Any) -> None:
        selected = self._get_selected_songs()
        if not selected:
            show_toast(self, "请至少选择一首可下载歌曲")
            return
        self._download_songs(selected)

    def _on_music_download_all(self, *args: Any) -> None:
        all_songs = [s for s in self.song_data if not s.get("copyright_restricted", False)]
        if not all_songs:
            show_toast(self, "没有可下载的歌曲")
            return
        self._download_songs(all_songs)

    def _download_songs(self, songs: list[dict[str, Any]]) -> None:
        """下载指定歌曲列表。"""
        from kivy.app import App
        app = App.get_running_app()

        options = CoreAdapter.get_music_quality_options()
        quality = options[self._music_quality_index]
        output_dir = app.core.get_music_download_dir()

        count = 0
        for song in songs:
            # 构建下载 URL
            url = song.get("url", "")
            if not url:
                source = self.current_music
                source_name = getattr(source, "source", "")
                sid = song.get("song_id", "")
                if source_name == "netease":
                    url = f"https://music.163.com/#/song?id={sid}"
                elif source_name == "qqmusic":
                    url = f"https://y.qq.com/n/ryqq/songDetail/{sid}"
                else:
                    url = sid
            if not url:
                continue

            task_id = app.core.download_music(
                url=url,
                quality=quality,
                output_dir=output_dir,
                on_progress=self._on_download_progress,
                on_status=self._on_download_status,
                on_error=self._on_download_error,
            )
            if task_id:
                app.add_download_task_id(task_id)
                count += 1

        if count > 0:
            show_toast(self, f"已开始下载 {count} 首歌曲")
            Clock.schedule_once(lambda dt: app.switch_tab("download"), 0.5)
        else:
            show_toast(self, "没有可下载的歌曲")

    # ------------------------------------------------------------------
    # 屏幕生命周期
    # ------------------------------------------------------------------

    def on_pre_enter(self, *args: Any) -> None:
        Theme.set_mode("light")
        Clock.schedule_once(lambda dt: self.check_clipboard_banner(), 0.3)
