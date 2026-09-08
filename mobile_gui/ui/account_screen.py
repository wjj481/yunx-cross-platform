"""
账号屏幕（账号 Tab）。

功能：
- 顶部：标题「账号管理」+ 添加账号按钮
- 网盘账号列表（卡片式：网盘名称/图标/登录状态/凭证预览）
- 凭证脱敏显示（前4位+***+后4位）
- 操作：测试连接、删除
- 添加账号对话框（6种网盘选择 + Cookie/JWT 输入 + 百度风控警告）
- 凭证经 AES-GCM 加密存储（由核心引擎 ConfigManager 实现）
"""

from __future__ import annotations

from typing import Any

from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from mobile_gui.core_adapter import CoreAdapter
from mobile_gui.ui.dialogs import AddAccountDialog, ConfirmDialog
from mobile_gui.ui.widgets import DriveBadge, MaterialButton, Theme, hex_to_rgba, show_toast


class AccountScreen(Screen):
    """账号屏幕：管理各网盘登录凭证。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.name = "account"
        self._account_widgets: dict[str, BoxLayout] = {}
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
            size_hint_y=None, height=dp(56),
            padding=[dp(16), 0], spacing=dp(8),
        )
        with top_bar.canvas.before:
            Color(*hex_to_rgba("#1976D2"))
            RoundedRectangle(pos=top_bar.pos, size=top_bar.size)

        title = Label(
            text="[b]账号管理[/b]", markup=True,
            font_size=sp(18), color=hex_to_rgba("#FFFFFF"),
            halign="left", valign="middle",
        )
        title.bind(size=title.setter("text_size"))

        add_btn = MaterialButton(
            text="+ 添加账号", bg_color="#4CAF50",
            size_hint=(None, None), size=(dp(100), dp(36)),
            font_size=sp(12), height=dp(36),
        )
        add_btn.bind(on_release=self._add_account)

        top_bar.add_widget(title)
        top_bar.add_widget(add_btn)
        root.add_widget(top_bar)

        # 账号列表
        self._scroll = ScrollView(size_hint=(1, 1))
        self._account_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None, spacing=dp(8), padding=dp(12),
        )
        self._account_list.bind(minimum_height=self._account_list.setter("height"))
        self._scroll.add_widget(self._account_list)
        root.add_widget(self._scroll)

        # 空状态
        self._empty_box = BoxLayout(
            orientation="vertical",
            size_hint=(1, 1),
            spacing=dp(16),
            padding=dp(40),
            opacity=1,
        )
        empty_icon = Label(
            text="👤",
            size_hint_y=None,
            height=dp(80),
            font_size=sp(64),
        )
        empty_text = Label(
            text="暂无账号\n点击右上角「+ 添加账号」添加网盘账号\n\n"
                 "添加账号后可解析需要登录的分享链接。\n"
                 "凭证经 AES-GCM 加密存储。",
            font_size=sp(13), color=hex_to_rgba("#9E9E9E"),
            halign="center", valign="middle",
            size_hint_y=None, height=dp(100),
        )
        self._empty_box.add_widget(empty_icon)
        self._empty_box.add_widget(empty_text)
        root.add_widget(self._empty_box)

        # 底部提示
        tip = Label(
            text="🔒 凭证仅存储在本地设备，经 AES-GCM 加密保护",
            font_size=sp(11), color=hex_to_rgba("#9E9E9E"),
            size_hint_y=None, height=dp(28),
        )
        root.add_widget(tip)

        self.add_widget(root)

    def _update_bg(self, *args: Any) -> None:
        self._bg_rect.pos = self.children[0].pos
        self._bg_rect.size = self.children[0].size

    # ------------------------------------------------------------------
    # 账号列表管理
    # ------------------------------------------------------------------

    def refresh_accounts(self) -> None:
        """从配置管理器刷新账号列表。"""
        from kivy.app import App
        app = App.get_running_app()
        drives = app.core.list_credentials()

        # 清除旧列表
        self._account_list.clear_widgets()
        self._account_widgets.clear()

        if not drives:
            self._empty_box.opacity = 1
            return

        self._empty_box.opacity = 0

        for drive in drives:
            widget = self._create_account_item(drive)
            self._account_widgets[drive] = widget
            self._account_list.add_widget(widget)

    def _create_account_item(self, drive: str) -> BoxLayout:
        """创建单个账号列表项（卡片式）。"""
        info = CoreAdapter.drive_display(drive)
        credential = None
        from kivy.app import App
        app = App.get_running_app()
        credential = app.core.get_credential(drive)

        item = BoxLayout(
            orientation="vertical",
            size_hint_y=None, height=dp(100),
            padding=dp(12), spacing=dp(6),
        )
        with item.canvas.before:
            Color(*hex_to_rgba(Theme.get("card")))
            RoundedRectangle(pos=item.pos, size=item.size, radius=[dp(12)])

        # 第一行：网盘标签 + 登录状态（圆点）
        row1 = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(32),
        )
        badge = DriveBadge(drive=drive)

        # 状态：绿色圆点=已登录，灰色=未设置
        status_box = BoxLayout(
            orientation="horizontal",
            size_hint=(None, None),
            size=(dp(80), dp(32)),
            spacing=dp(6),
        )
        status_dot = Label(
            text="●",
            font_size=sp(14),
            color=hex_to_rgba("#4CAF50" if credential else "#9E9E9E"),
            size_hint=(None, None),
            size=(dp(16), dp(32)),
        )
        status_text = Label(
            text="已登录" if credential else "未设置",
            font_size=sp(12),
            color=hex_to_rgba("#4CAF50" if credential else "#9E9E9E"),
            size_hint=(None, None),
            size=(dp(56), dp(32)),
        )
        status_box.add_widget(status_dot)
        status_box.add_widget(status_text)

        row1.add_widget(badge)
        row1.add_widget(Label())  # 占位撑开
        row1.add_widget(status_box)
        item.add_widget(row1)

        # 第二行：凭证预览（脱敏）
        cred_preview = self._mask_credential(credential)
        preview_label = Label(
            text=cred_preview,
            font_size=sp(11),
            color=hex_to_rgba("#757575"),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(20),
            shorten=True,
            shorten_from="right",
        )
        preview_label.bind(size=preview_label.setter("text_size"))
        item.add_widget(preview_label)

        # 第三行：操作按钮
        row3 = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(32), spacing=dp(8),
        )
        test_btn = MaterialButton(
            text="测试连接", bg_color="#1976D2",
            font_size=sp(11), height=dp(28),
        )
        test_btn.bind(on_release=lambda inst, d=drive: self._test_connection(d))

        delete_btn = MaterialButton(
            text="删除", bg_color="#F44336",
            font_size=sp(11), height=dp(28),
        )
        delete_btn.bind(on_release=lambda inst, d=drive: self._delete_account(d))

        row3.add_widget(test_btn)
        row3.add_widget(Label())  # 占位
        row3.add_widget(delete_btn)
        item.add_widget(row3)

        return item

    @staticmethod
    def _mask_credential(credential: dict[str, Any] | None) -> str:
        """凭证脱敏显示：前4位 + *** + 后4位。"""
        if not credential:
            return "未配置凭证"
        # 优先取 cookie，其次 access_token
        raw = ""
        if "cookie" in credential:
            raw = str(credential["cookie"])
        elif "access_token" in credential:
            raw = str(credential["access_token"])
        elif "token" in credential:
            raw = str(credential["token"])
        else:
            return "已配置（自定义格式）"

        if len(raw) <= 12:
            return raw[:4] + "***" + raw[-4:] if len(raw) > 8 else raw
        return raw[:4] + "***" + raw[-4:]

    # ------------------------------------------------------------------
    # 账号操作
    # ------------------------------------------------------------------

    def _add_account(self, *args: Any) -> None:
        """添加账号。"""
        dialog = AddAccountDialog(on_save=self._on_account_saved)
        dialog.open()

    def _on_account_saved(self, drive: str, credential: dict[str, str]) -> None:
        """账号保存回调。"""
        from kivy.app import App
        app = App.get_running_app()
        app.core.set_credential(drive, credential)
        self.refresh_accounts()
        info = CoreAdapter.drive_display(drive)
        show_toast(self, f"{info['name']}账号已保存")

    def _test_connection(self, drive: str) -> None:
        """测试网盘连接（模拟：检查凭证是否存在）。"""
        from kivy.app import App
        app = App.get_running_app()
        credential = app.core.get_credential(drive)
        info = CoreAdapter.drive_display(drive)
        if credential:
            show_toast(self, f"{info['name']}凭证已配置（实际连接测试需网络请求）")
        else:
            show_toast(self, f"{info['name']}未配置凭证")

    def _delete_account(self, drive: str) -> None:
        """删除账号（带确认）。"""
        info = CoreAdapter.drive_display(drive)

        def on_confirm() -> None:
            from kivy.app import App
            app = App.get_running_app()
            app.core.remove_credential(drive)
            self.refresh_accounts()
            show_toast(self, f"{info['name']}账号已删除")

        ConfirmDialog(
            title="删除账号",
            message=f"确定要删除{info['name']}的凭证吗？",
            confirm_text="删除",
            on_confirm=on_confirm,
        ).open()

    # ------------------------------------------------------------------
    # 屏幕生命周期
    # ------------------------------------------------------------------

    def on_pre_enter(self, *args: Any) -> None:
        """进入屏幕前刷新账号列表。"""
        self.refresh_accounts()
