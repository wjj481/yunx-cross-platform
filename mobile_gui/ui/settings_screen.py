"""
设置屏幕（设置 Tab）。

功能：
- 下载设置：下载目录、并发数(1-32滑块)、分片大小(1/2/4/8/16MB)、剪贴板监听开关
- 外观：主题切换（浅色/深色）
- 配置管理：导出配置 + 导入配置 按钮
- 关于：版本号、协议、免责声明、GitHub链接
"""

from __future__ import annotations

from typing import Any

from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput

from mobile_gui.core_adapter import CoreAdapter
from mobile_gui.ui.dialogs import (
    ErrorDialog,
    ExportConfigDialog,
    ImportConfigDialog,
    ImportResultDialog,
)
from mobile_gui.ui.widgets import MaterialButton, Theme, hex_to_rgba, show_toast


class SettingsScreen(Screen):
    """设置屏幕：下载配置、主题、配置管理、关于。"""

    # 分片大小选项
    CHUNK_OPTIONS = [
        ("1 MB", 1 * 1024 * 1024),
        ("2 MB", 2 * 1024 * 1024),
        ("4 MB", 4 * 1024 * 1024),
        ("8 MB", 8 * 1024 * 1024),
        ("16 MB", 16 * 1024 * 1024),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.name = "settings"
        self._chunk_index = 2  # 默认 4MB
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical")

        # 背景
        with root.canvas.before:
            self._bg_color = Color(*hex_to_rgba(Theme.get("bg")))
            self._bg_rect = RoundedRectangle(pos=root.pos, size=root.size)
        root.bind(pos=self._update_bg, size=self._update_bg)

        # 顶部栏
        top_bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=[dp(16), 0],
            spacing=dp(8),
        )
        with top_bar.canvas.before:
            Color(*hex_to_rgba("#1976D2"))
            RoundedRectangle(pos=top_bar.pos, size=top_bar.size)

        title = Label(
            text="[b]设置[/b]", markup=True,
            font_size=sp(18), color=hex_to_rgba("#FFFFFF"),
            halign="left", valign="middle",
        )
        title.bind(size=title.setter("text_size"))
        top_bar.add_widget(title)
        root.add_widget(top_bar)

        # 内容区
        content = ScrollView(size_hint=(1, 1))
        content_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(12),
            padding=dp(12),
        )
        content_box.bind(minimum_height=content_box.setter("height"))

        # -- 下载设置卡片 --
        content_box.add_widget(self._section_title("下载设置"))

        # 下载目录
        dir_card = self._make_card(dp(110))
        dir_label = Label(
            text="下载目录", font_size=sp(14), bold=True,
            halign="left", size_hint_y=None, height=dp(20),
            color=hex_to_rgba(Theme.get("text")),
        )
        dir_label.bind(size=dir_label.setter("text_size"))
        self._dir_input = TextInput(
            multiline=False, size_hint_y=None, height=dp(40),
            font_size=sp(13),
            background_color=hex_to_rgba(Theme.get("input_bg")),
            foreground_color=hex_to_rgba(Theme.get("text")),
            cursor_color=hex_to_rgba("#1976D2"),
            padding=[dp(8), dp(8)],
        )
        save_dir_btn = MaterialButton(
            text="保存", bg_color="#4CAF50",
            font_size=sp(13), size_hint_y=None, height=dp(32),
        )
        save_dir_btn.bind(on_release=self._save_download_dir)
        dir_card.add_widget(dir_label)
        dir_card.add_widget(self._dir_input)
        dir_card.add_widget(save_dir_btn)
        content_box.add_widget(dir_card)

        # 并发数
        concurrency_card = self._make_card(dp(90))
        concurrency_header = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(24),
        )
        concurrency_label = Label(
            text="并发下载数", font_size=sp(14), bold=True,
            halign="left", color=hex_to_rgba(Theme.get("text")),
        )
        concurrency_label.bind(size=concurrency_label.setter("text_size"))
        self._concurrency_value = Label(
            text="8", font_size=sp(14), bold=True,
            size_hint=(None, None), size=(dp(40), dp(24)),
            color=hex_to_rgba("#1976D2"),
        )
        concurrency_header.add_widget(concurrency_label)
        concurrency_header.add_widget(self._concurrency_value)

        self._concurrency_slider = Slider(
            min=1, max=32, value=8, step=1,
            size_hint_y=None, height=dp(30),
        )
        self._concurrency_slider.bind(value=self._on_concurrency_change)
        concurrency_card.add_widget(concurrency_header)
        concurrency_card.add_widget(self._concurrency_slider)
        content_box.add_widget(concurrency_card)

        # 分片大小
        chunk_card = self._make_card(dp(90))
        chunk_label = Label(
            text="分片大小", font_size=sp(14), bold=True,
            halign="left", size_hint_y=None, height=dp(24),
            color=hex_to_rgba(Theme.get("text")),
        )
        chunk_label.bind(size=chunk_label.setter("text_size"))
        chunk_row = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(4),
        )
        self._chunk_buttons: list[MaterialButton] = []
        for i, (label, _) in enumerate(self.CHUNK_OPTIONS):
            btn = MaterialButton(
                text=label, bg_color="#BDBDBD",
                font_size=sp(11), height=dp(32),
            )
            btn.bind(on_release=lambda inst, idx=i: self._select_chunk(idx))
            self._chunk_buttons.append(btn)
            chunk_row.add_widget(btn)
        chunk_card.add_widget(chunk_label)
        chunk_card.add_widget(chunk_row)
        content_box.add_widget(chunk_card)

        # -- 通用设置 --
        content_box.add_widget(self._section_title("通用设置"))

        # 剪贴板监听
        clipboard_card = self._make_card(dp(56))
        clipboard_row = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(40),
        )
        clipboard_label = Label(
            text="启动时自动检测剪贴板链接",
            font_size=sp(14), halign="left",
            color=hex_to_rgba(Theme.get("text")),
        )
        clipboard_label.bind(size=clipboard_label.setter("text_size"))
        self._clipboard_switch = Switch(
            active=False, size_hint=(None, None), size=(dp(50), dp(30)),
        )
        self._clipboard_switch.bind(active=self._on_clipboard_switch)
        clipboard_row.add_widget(clipboard_label)
        clipboard_row.add_widget(self._clipboard_switch)
        clipboard_card.add_widget(clipboard_row)
        content_box.add_widget(clipboard_card)

        # 主题切换
        theme_card = self._make_card(dp(56))
        theme_row = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(40),
        )
        theme_label = Label(
            text="深色主题", font_size=sp(14), halign="left",
            color=hex_to_rgba(Theme.get("text")),
        )
        theme_label.bind(size=theme_label.setter("text_size"))
        self._theme_switch = Switch(
            active=False, size_hint=(None, None), size=(dp(50), dp(30)),
        )
        self._theme_switch.bind(active=self._on_theme_switch)
        theme_row.add_widget(theme_label)
        theme_row.add_widget(self._theme_switch)
        theme_card.add_widget(theme_row)
        content_box.add_widget(theme_card)

        # -- 配置管理 --
        content_box.add_widget(self._section_title("配置管理"))

        config_card = self._make_card(dp(130))
        config_desc = Label(
            text="导出 / 导入配置文件（.yunxcfg），可在设备间迁移凭证和设置",
            font_size=sp(11),
            color=hex_to_rgba("#757575"),
            halign="left",
            size_hint_y=None,
            height=dp(30),
        )
        config_desc.bind(size=config_desc.setter("text_size"))
        config_card.add_widget(config_desc)

        # 导出按钮
        export_btn = MaterialButton(
            text="📤 导出配置",
            bg_color="#1976D2",
            font_size=sp(14),
            height=dp(40),
        )
        export_btn.bind(on_release=self._on_export_config)
        config_card.add_widget(export_btn)

        # 导入按钮
        import_btn = MaterialButton(
            text="📥 导入配置",
            bg_color="#4CAF50",
            font_size=sp(14),
            height=dp(40),
        )
        import_btn.bind(on_release=self._on_import_config)
        config_card.add_widget(import_btn)

        content_box.add_widget(config_card)

        # -- 关于 --
        content_box.add_widget(self._section_title("关于"))
        about_card = self._make_card(dp(160))
        about_text = (
            "[b]YunX 云析 v0.2.0[/b]\n\n"
            "跨平台网盘解析 + 高速下载工具\n"
            "支持：夸克、123云盘、迅雷、百度、UC、和彩云\n\n"
            "[b]GitHub：[/b]github.com/yunx-project/yunx-cross-platform\n\n"
            "[b]免责声明：[/b]\n"
            "本工具仅供学习研究使用，请勿用于商业用途。\n"
            "使用本工具产生的一切后果由使用者自行承担。"
        )
        about_label = Label(
            text=about_text, markup=True,
            font_size=sp(12), halign="left", valign="top",
            color=hex_to_rgba(Theme.get("text_secondary")),
            size_hint_y=None, height=dp(140),
        )
        about_label.bind(size=about_label.setter("text_size"))
        about_card.add_widget(about_label)
        content_box.add_widget(about_card)

        content.add_widget(content_box)
        root.add_widget(content)
        self.add_widget(root)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _section_title(self, text: str) -> Label:
        """创建分区标题。"""
        label = Label(
            text=f"[b]{text}[/b]", markup=True,
            font_size=sp(15), bold=True,
            halign="left", size_hint_y=None, height=dp(28),
            color=hex_to_rgba("#1976D2"),
            padding=[dp(4), 0],
        )
        label.bind(size=label.setter("text_size"))
        return label

    def _make_card(self, height: int) -> BoxLayout:
        """创建设置卡片。"""
        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None, height=dp(height),
            padding=dp(12), spacing=dp(8),
        )
        with card.canvas.before:
            Color(*hex_to_rgba(Theme.get("card")))
            RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(12)])
        return card

    def _update_bg(self, *args: Any) -> None:
        self._bg_rect.pos = self.children[0].pos
        self._bg_rect.size = self.children[0].size

    # ------------------------------------------------------------------
    # 设置操作
    # ------------------------------------------------------------------

    def _save_download_dir(self, *args: Any) -> None:
        """保存下载目录设置。"""
        path = self._dir_input.text.strip()
        if not path:
            show_toast(self, "下载目录不能为空")
            return
        from kivy.app import App
        app = App.get_running_app()
        app.set_setting("download_dir", path)
        show_toast(self, "下载目录已保存")

    def _on_concurrency_change(self, instance: Any, value: float) -> None:
        """并发数滑块变化。"""
        self._concurrency_value.text = str(int(value))
        from kivy.app import App
        app = App.get_running_app()
        app.set_setting("concurrency", int(value))

    def _select_chunk(self, index: int) -> None:
        """选择分片大小。"""
        self._chunk_index = index
        for i, btn in enumerate(self._chunk_buttons):
            btn.bg_color = "#1976D2" if i == index else "#BDBDBD"
        _, chunk_size = self.CHUNK_OPTIONS[index]
        from kivy.app import App
        app = App.get_running_app()
        app.set_setting("chunk_size", chunk_size)

    def _on_clipboard_switch(self, instance: Any, value: bool) -> None:
        """剪贴板监听开关。"""
        from kivy.app import App
        app = App.get_running_app()
        app.set_setting("clipboard_listen", value)

    def _on_theme_switch(self, instance: Any, value: bool) -> None:
        """主题切换。"""
        mode = "dark" if value else "light"
        Theme.set_mode(mode)
        from kivy.app import App
        app = App.get_running_app()
        app.set_setting("theme", mode)
        app.apply_theme(mode)
        show_toast(self, f"已切换为{'深色' if value else '浅色'}主题")

    # ------------------------------------------------------------------
    # 配置导出 / 导入
    # ------------------------------------------------------------------

    def _on_export_config(self, *args: Any) -> None:
        """导出配置按钮回调。"""
        from kivy.app import App
        app = App.get_running_app()
        default_path = app.get_default_export_path()

        dialog = ExportConfigDialog(
            default_path=default_path,
            on_export=self._do_export,
        )
        dialog.open()

    def _do_export(self, output_path: str, password: str | None, include_tasks: bool) -> None:
        """执行导出。"""
        from kivy.app import App
        app = App.get_running_app()
        try:
            result_path = app.export_config(output_path, password, include_tasks)
            mode_text = "加密" if password else "明文"
            show_toast(self, f"配置已{mode_text}导出：{result_path}", duration=3.0)
        except Exception as exc:
            ErrorDialog(
                title="导出失败",
                message=str(exc),
            ).open()

    def _on_import_config(self, *args: Any) -> None:
        """导入配置按钮回调。"""
        from kivy.app import App
        app = App.get_running_app()
        default_dir = app.get_setting("download_dir", CoreAdapter.default_download_dir())

        dialog = ImportConfigDialog(
            default_dir=default_dir,
            on_import=self._do_import,
        )
        dialog.open()

    def _do_import(self, file_path: str, password: str | None, merge: bool) -> None:
        """执行导入。"""
        from kivy.app import App
        app = App.get_running_app()
        try:
            result = app.import_config(file_path, password, merge)
            # 显示导入结果摘要
            ImportResultDialog(
                credentials_count=result.get("credentials", 0),
                settings_count=result.get("settings", 0),
                tasks_count=result.get("tasks", 0),
                on_ok=self._after_import,
            ).open()
        except Exception as exc:
            ErrorDialog(
                title="导入失败",
                message=str(exc),
            ).open()

    def _after_import(self) -> None:
        """导入完成后刷新相关屏幕。"""
        from kivy.app import App
        app = App.get_running_app()
        # 刷新账号 Tab
        account_screen = app.get_screen("account")
        if account_screen:
            account_screen.refresh_accounts()
        show_toast(self, "配置导入完成，账号和设置已更新")

    # ------------------------------------------------------------------
    # 屏幕生命周期
    # ------------------------------------------------------------------

    def on_pre_enter(self, *args: Any) -> None:
        """进入屏幕前加载当前设置。"""
        from kivy.app import App
        app = App.get_running_app()

        # 下载目录
        default_dir = CoreAdapter.default_download_dir()
        self._dir_input.text = app.get_setting("download_dir", default_dir)

        # 并发数
        concurrency = int(app.get_setting("concurrency", 8))
        self._concurrency_slider.value = concurrency
        self._concurrency_value.text = str(concurrency)

        # 分片大小
        chunk_size = int(app.get_setting("chunk_size", 4 * 1024 * 1024))
        for i, (_, size) in enumerate(self.CHUNK_OPTIONS):
            if size == chunk_size:
                self._select_chunk(i)
                break

        # 剪贴板监听
        self._clipboard_switch.active = bool(app.get_setting("clipboard_listen", False))

        # 主题
        theme = app.get_setting("theme", "light")
        self._theme_switch.active = theme == "dark"
