"""
主屏幕（解析 Tab）。

功能：
- 顶部标题栏「YunX 云析」
- 剪贴板识别横幅（检测到分享链接时提示点击填入）
- URL 输入区（大输入框、提取码输入框、「解析」按钮）
- 解析中加载动画
- 网盘标识（解析后显示彩色标签）
- 文件列表（RecycleView，每行含复选框）
- 底部操作栏（「全选」「下载选中」「下载目录」）
"""

from __future__ import annotations

from typing import Any

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import ListProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.recycleview import RecycleView
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
# 文件列表 RecycleView
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
        # 布局
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
# 剪贴板识别横幅
# ===========================================================================

class ClipboardBanner(BoxLayout):
    """剪贴板识别横幅。

    检测到剪贴板中有分享链接时显示，点击可填入输入框。
    """

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
        """显示横幅。"""
        if drive_name:
            self._text_label.text = f"检测到剪贴板链接（{drive_name}），点击填入"
        self.opacity = 1
        self.height = dp(44)

    def hide(self) -> None:
        """隐藏横幅。"""
        self.opacity = 0
        self.height = 0


# ===========================================================================
# 主屏幕（解析 Tab）
# ===========================================================================

class MainScreen(Screen):
    """主屏幕：URL 输入 + 解析 + 文件列表 + 下载操作。"""

    # 当前解析结果（ShareInfo）
    current_share = ObjectProperty(None, allownone=True)
    # 文件列表数据
    file_data = ListProperty([])

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.name = "main"
        self._baidu_confirmed = False
        self._pending_parse_url = ""
        self._pending_extract_code = ""
        self._loading_spinner: LoadingSpinner | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """构建主屏幕 UI。"""
        root = BoxLayout(orientation="vertical")

        # 背景色
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

        # 账号状态图标
        self._account_status = Label(
            text="☁️",
            size_hint=(None, None),
            size=(dp(32), dp(32)),
            font_size=sp(20),
        )
        title_bar.add_widget(title_label)
        title_bar.add_widget(self._account_status)
        root.add_widget(title_bar)

        # -- 内容区（可滚动）--
        content = ScrollView(size_hint=(1, 1))
        content_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(12),
            padding=dp(12),
        )
        content_box.bind(minimum_height=content_box.setter("height"))

        # 剪贴板识别横幅
        self._clipboard_banner = ClipboardBanner(on_fill=self._fill_from_clipboard)
        content_box.add_widget(self._clipboard_banner)

        # URL 输入卡片
        url_card = self._build_url_card()
        content_box.add_widget(url_card)

        # 网盘标识区（解析后显示）
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
        self._drive_box.add_widget(Label())  # 占位
        content_box.add_widget(self._drive_box)

        # 文件列表
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

        self._file_rv = FileRecycleView(
            size_hint_y=None,
            height=dp(200),
        )
        content_box.add_widget(self._file_rv)

        # 空状态提示
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
        root.add_widget(content)

        # -- 底部操作栏 --
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
        bottom_bar.bind(pos=self._update_bottom, size=self._update_bottom)

        self._select_all_btn = MaterialButton(
            text="全选",
            bg_color="#FF9800",
            font_size=sp(13),
            height=dp(40),
        )
        self._select_all_btn.bind(on_release=self._select_all)

        self._download_btn = MaterialButton(
            text="下载选中",
            bg_color="#4CAF50",
            font_size=sp(14),
            height=dp(40),
        )
        self._download_btn.bind(on_release=self._download_selected)

        self._download_dir_btn = MaterialButton(
            text="下载目录",
            bg_color="#9E9E9E",
            font_size=sp(13),
            height=dp(40),
        )
        self._download_dir_btn.bind(on_release=self._show_download_dir)

        bottom_bar.add_widget(self._select_all_btn)
        bottom_bar.add_widget(self._download_btn)
        bottom_bar.add_widget(self._download_dir_btn)
        root.add_widget(bottom_bar)

        self.add_widget(root)

    def _build_url_card(self) -> BoxLayout:
        """构建 URL 输入卡片。"""
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

        # URL 输入框（大尺寸）
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

        # 提取码 + 解析按钮
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

        # 剪贴板按钮
        clipboard_btn = MaterialButton(
            text="📋 从剪贴板读取",
            bg_color="#78909C",
            font_size=sp(13),
            height=dp(36),
        )
        clipboard_btn.bind(on_release=self._on_clipboard)
        card.add_widget(clipboard_btn)

        return card

    # ------------------------------------------------------------------
    # 背景更新
    # ------------------------------------------------------------------

    def _update_bg(self, *args: Any) -> None:
        self._bg_rect.pos = self.children[0].pos
        self._bg_rect.size = self.children[0].size

    def _update_title_bar(self, instance: Any, value: Any) -> None:
        pass  # canvas 指令已绑定到实例自身

    def _update_bottom(self, *args: Any) -> None:
        pass

    def _update_card(self, *args: Any) -> None:
        pass

    # ------------------------------------------------------------------
    # 剪贴板
    # ------------------------------------------------------------------

    def _on_clipboard(self, *args: Any) -> None:
        """从剪贴板读取分享链接。"""
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
            # 即使没识别到网盘格式，也把剪贴板文本填入
            text = app.core.read_clipboard()
            if text:
                self._url_input.text = text.strip()
                show_toast(self, "已粘贴剪贴板内容")
            else:
                show_toast(self, "剪贴板为空")

    def _fill_from_clipboard(self) -> None:
        """横幅点击：从剪贴板填入。"""
        self._on_clipboard()

    def check_clipboard_banner(self) -> None:
        """检查剪贴板并显示横幅（如果有分享链接）。"""
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
    # 解析逻辑
    # ------------------------------------------------------------------

    def _on_parse(self, *args: Any) -> None:
        """点击「解析」按钮。"""
        url = self._url_input.text.strip()
        extract_code = self._code_input.text.strip() or None
        if not url:
            show_toast(self, "请输入分享链接")
            return

        # 显示加载状态
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
        """显示解析中加载状态。"""
        self._parse_btn.text = "解析中..."
        self._parse_btn.disabled = True
        # 在按钮位置显示加载动画
        if self._loading_spinner is None:
            self._loading_spinner = LoadingSpinner(color="#FFFFFF", size=20)
        # 简单起见，用按钮文字变化表示加载

    def _hide_loading(self) -> None:
        """隐藏加载状态。"""
        self._parse_btn.text = "🔍 解析"
        self._parse_btn.disabled = False

    def _on_baidu_warning(self) -> bool:
        """百度网盘风控警告回调（在主线程调用）。

        弹出全屏警告弹窗，返回用户是否确认。
        """
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
        """解析成功回调（主线程）。"""
        self._hide_loading()
        self.current_share = share_info

        # 显示网盘标识
        drive = getattr(share_info, "drive", "")
        self._drive_badge.drive = drive
        self._drive_badge.opacity = 1

        # 更新文件列表
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
        """解析失败回调（主线程）。"""
        self._hide_loading()

        from core import BaiduRiskWarning
        if isinstance(error, BaiduRiskWarning):
            show_toast(self, "已取消百度网盘解析")
        else:
            ErrorDialog(
                title="解析失败",
                message=str(error),
            ).open()

    # ------------------------------------------------------------------
    # 文件列表操作
    # ------------------------------------------------------------------

    def _select_all(self, *args: Any) -> None:
        """全选 / 取消全选。"""
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
        """下载选中的文件。"""
        if not self.current_share:
            show_toast(self, "请先解析分享链接")
            return

        selected = [item for item in self.file_data if item.get("selected", False)]
        if not selected:
            show_toast(self, "请至少选择一个文件")
            return

        from kivy.app import App
        app = App.get_running_app()

        # 获取下载设置
        download_dir = app.get_setting("download_dir", CoreAdapter.default_download_dir())
        concurrency = int(app.get_setting("concurrency", 8))
        chunk_size = int(app.get_setting("chunk_size", 4 * 1024 * 1024))

        # 当前 API 返回单个 ShareInfo，直接下载
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

        # 跳转到下载 Tab
        Clock.schedule_once(lambda dt: app.switch_tab("download"), 0.5)

    def _on_download_progress(self, task: Any) -> None:
        """下载进度回调（主线程）。"""
        from kivy.app import App
        app = App.get_running_app()
        app.notify_download_update(task)

    def _on_download_status(self, task: Any) -> None:
        """下载状态变更回调（主线程）。"""
        from kivy.app import App
        app = App.get_running_app()
        app.notify_download_update(task)

    def _on_download_error(self, error: Exception) -> None:
        """下载错误回调（主线程）。"""
        ErrorDialog(title="下载失败", message=str(error)).open()

    def _show_download_dir(self, *args: Any) -> None:
        """显示当前下载目录。"""
        from kivy.app import App
        app = App.get_running_app()
        download_dir = app.get_setting("download_dir", CoreAdapter.default_download_dir())
        show_toast(self, f"下载目录：{download_dir}", duration=3.0)

    # ------------------------------------------------------------------
    # 屏幕生命周期
    # ------------------------------------------------------------------

    def on_pre_enter(self, *args: Any) -> None:
        """进入屏幕前刷新主题色和剪贴板横幅。"""
        Theme.set_mode("light")  # 主题由 App 统一管理
        # 检查剪贴板横幅
        Clock.schedule_once(lambda dt: self.check_clipboard_banner(), 0.3)
