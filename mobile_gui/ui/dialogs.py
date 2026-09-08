"""
自定义弹窗。

包括：
- 百度网盘风控警告弹窗（全屏 ModalView，必须用户确认）
- 错误提示弹窗
- 通用确认弹窗
- 添加账号弹窗
- 配置导出弹窗（路径选择 + 明文/加密 + 密码）
- 配置导入弹窗（文件选择 + 密码 + 合并/替换）
- 密码输入弹窗

所有弹窗均使用 Material Design 风格，圆角卡片 + 半透明遮罩。
"""

from __future__ import annotations

import os
from typing import Any, Callable

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from mobile_gui.ui.widgets import MaterialButton, OutlinedButton, hex_to_rgba, show_toast


# ===========================================================================
# 弹窗基类
# ===========================================================================

class BaseDialog(ModalView):
    """弹窗基类：半透明遮罩 + 居中圆角卡片。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.background_color = [0, 0, 0, 0.5]
        self.background = ""  # 不使用默认背景图
        self.auto_dismiss = False
        self.size_hint = (0.85, None)

    def _make_card(self, height: int) -> BoxLayout:
        """创建圆角卡片容器。"""
        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(height),
            padding=dp(20),
            spacing=dp(12),
        )
        with card.canvas.before:
            self._card_bg = Color(*hex_to_rgba("#FFFFFF"))
            self._card_rect = RoundedRectangle(
                pos=card.pos, size=card.size, radius=[dp(12)]
            )
        card.bind(pos=self._update_card, size=self._update_card)
        return card

    def _update_card(self, *args: Any) -> None:
        if hasattr(self, "_card_rect"):
            # 获取第一个子控件（卡片）的位置和大小
            if self.children:
                card = self.children[0]
                self._card_rect.pos = card.pos
                self._card_rect.size = card.size


# ===========================================================================
# 百度网盘风控警告弹窗（全屏）
# ===========================================================================

class BaiduRiskDialog(BaseDialog):
    """百度网盘风控警告弹窗（全屏 ModalView）。

    百度网盘对自动化解析有严格的风控策略，频繁调用可能导致账号被封。
    此弹窗必须在用户确认后才继续解析。

    回调 ``on_confirm`` 在用户点击"我已知晓，继续解析"时触发；
    回调 ``on_cancel`` 在用户点击"取消"时触发。
    """

    def __init__(
        self,
        on_confirm: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self.size_hint = (1, 1)  # 全屏

        # 主容器
        root = BoxLayout(
            orientation="vertical",
            padding=dp(30),
            spacing=dp(16),
        )
        with root.canvas.before:
            Color(*hex_to_rgba("#FFF3E0"))  # 浅橙色警告背景
            RoundedRectangle(pos=root.pos, size=root.size, radius=[dp(0)])

        # 警告图标
        icon = Label(
            text="⚠️",
            size_hint_y=None,
            height=dp(60),
            font_size=sp(48),
        )
        root.add_widget(icon)

        # 标题
        title = Label(
            text="[b][color=#F44336]百度网盘风控警告[/color][/b]",
            markup=True,
            size_hint_y=None,
            height=dp(36),
            font_size=sp(20),
        )
        root.add_widget(title)

        # 警告内容（可滚动）
        content_scroll = ScrollView(size_hint=(1, 1))
        content_text = (
            "百度网盘对自动化解析和下载有严格的风控策略。\n\n"
            "使用本工具解析百度网盘分享链接可能导致：\n\n"
            "• 您的百度账号被临时或永久封禁\n"
            "• IP 地址被百度服务器拉黑\n"
            "• 分享链接被强制失效\n"
            "• 触发验证码或安全验证\n\n"
            "[b]建议：[/b]\n"
            "1. 不要频繁解析百度网盘链接\n"
            "2. 使用低并发数（建议 1-4）\n"
            "3. 优先使用其他网盘（夸克、123、迅雷）\n"
            "4. 本工具仅供学习研究使用\n\n"
            "[b][color=#F44336]继续使用即表示您已知晓并愿意承担上述风险。[/color][/b]"
        )
        content_label = Label(
            text=content_text,
            markup=True,
            font_size=sp(14),
            halign="left",
            valign="top",
            size_hint_y=None,
            text_size=(dp(320), None),
        )
        content_label.bind(texture_size=content_label.setter("size"))
        content_scroll.add_widget(content_label)
        root.add_widget(content_scroll)

        # 按钮
        btn_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(12),
        )
        cancel_btn = MaterialButton(
            text="取消",
            bg_color="#9E9E9E",
            font_size=sp(15),
        )
        cancel_btn.bind(on_release=self._on_cancel_pressed)
        confirm_btn = MaterialButton(
            text="我已知晓，继续解析",
            bg_color="#F44336",
            font_size=sp(15),
        )
        confirm_btn.bind(on_release=self._on_confirm_pressed)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(confirm_btn)
        root.add_widget(btn_box)

        self.add_widget(root)

    def _on_confirm_pressed(self, *args: Any) -> None:
        self.dismiss()
        if self._on_confirm:
            self._on_confirm()

    def _on_cancel_pressed(self, *args: Any) -> None:
        self.dismiss()
        if self._on_cancel:
            self._on_cancel()


# ===========================================================================
# 错误提示弹窗
# ===========================================================================

class ErrorDialog(BaseDialog):
    """错误提示弹窗。

    显示错误标题和详细信息，提供"确定"按钮关闭。
    """

    def __init__(
        self,
        title: str = "操作失败",
        message: str = "",
        on_dismiss_cb: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.height = dp(200)
        self._on_dismiss_cb = on_dismiss_cb

        card = self._make_card(200)

        # 图标
        icon = Label(
            text="❌",
            size_hint_y=None,
            height=dp(40),
            font_size=sp(32),
        )
        card.add_widget(icon)

        # 标题
        title_label = Label(
            text=f"[b]{title}[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(28),
            font_size=sp(17),
            color=hex_to_rgba("#F44336"),
        )
        card.add_widget(title_label)

        # 消息
        msg_label = Label(
            text=message,
            size_hint_y=None,
            height=dp(60),
            font_size=sp(14),
            color=hex_to_rgba("#424242"),
            halign="center",
            valign="middle",
            text_size=(dp(280), None),
        )
        card.add_widget(msg_label)

        # 按钮
        ok_btn = MaterialButton(
            text="确定",
            bg_color="#1976D2",
            font_size=sp(15),
        )
        ok_btn.bind(on_release=self._on_ok)
        card.add_widget(ok_btn)

        self.add_widget(card)

    def _on_ok(self, *args: Any) -> None:
        self.dismiss()
        if self._on_dismiss_cb:
            self._on_dismiss_cb()


# ===========================================================================
# 通用确认弹窗
# ===========================================================================

class ConfirmDialog(BaseDialog):
    """通用确认弹窗。

    显示标题和消息，提供"确认"和"取消"按钮。
    """

    def __init__(
        self,
        title: str = "确认操作",
        message: str = "",
        confirm_text: str = "确认",
        cancel_text: str = "取消",
        on_confirm: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.height = dp(180)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel

        card = self._make_card(180)

        title_label = Label(
            text=f"[b]{title}[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(30),
            font_size=sp(17),
        )
        card.add_widget(title_label)

        msg_label = Label(
            text=message,
            size_hint_y=None,
            height=dp(50),
            font_size=sp(14),
            color=hex_to_rgba("#616161"),
            halign="center",
            valign="middle",
            text_size=(dp(280), None),
        )
        card.add_widget(msg_label)

        btn_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(12),
        )
        cancel_btn = MaterialButton(text=cancel_text, bg_color="#9E9E9E", font_size=sp(14))
        cancel_btn.bind(on_release=self._on_cancel_pressed)
        confirm_btn = MaterialButton(text=confirm_text, bg_color="#1976D2", font_size=sp(14))
        confirm_btn.bind(on_release=self._on_confirm_pressed)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(confirm_btn)
        card.add_widget(btn_box)

        self.add_widget(card)

    def _on_confirm_pressed(self, *args: Any) -> None:
        self.dismiss()
        if self._on_confirm:
            self._on_confirm()

    def _on_cancel_pressed(self, *args: Any) -> None:
        self.dismiss()
        if self._on_cancel:
            self._on_cancel()


# ===========================================================================
# 添加账号弹窗
# ===========================================================================

class AddAccountDialog(BaseDialog):
    """添加网盘账号弹窗。

    选择网盘类型，输入 Cookie / JWT 等凭证，保存到加密配置。
    """

    DRIVE_OPTIONS = ["夸克网盘", "123云盘", "迅雷云盘", "百度网盘", "UC网盘", "和彩云"]
    DRIVE_KEYS = ["quark", "pan123", "xunlei", "baidu", "uc", "caiyun"]

    def __init__(
        self,
        on_save: Callable[[str, dict[str, str]], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.size_hint = (0.9, None)
        self.height = dp(360)
        self._on_save = on_save
        self._drive_index = 0

        card = self._make_card(360)

        # 标题
        title = Label(
            text="[b]添加网盘账号[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(28),
            font_size=sp(17),
        )
        card.add_widget(title)

        # 网盘选择（用按钮循环切换，避免 Spinner 依赖）
        drive_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(8))
        self._drive_label = Label(
            text=self.DRIVE_OPTIONS[0],
            size_hint_x=0.7,
            font_size=sp(15),
            bold=True,
        )
        prev_btn = MaterialButton(text="<", bg_color="#BDBDBD", font_size=sp(16), size_hint_x=0.15, height=dp(36))
        next_btn = MaterialButton(text=">", bg_color="#BDBDBD", font_size=sp(16), size_hint_x=0.15, height=dp(36))
        prev_btn.bind(on_release=self._prev_drive)
        next_btn.bind(on_release=self._next_drive)
        drive_box.add_widget(prev_btn)
        drive_box.add_widget(self._drive_label)
        drive_box.add_widget(next_btn)
        card.add_widget(drive_box)

        # 百度网盘风控警告提示
        self._baidu_warning = Label(
            text="[color=#F44336]⚠️ 百度网盘存在风控风险，频繁使用可能导致账号被封[/color]",
            markup=True,
            size_hint_y=None,
            height=dp(20),
            font_size=sp(11),
            opacity=0,
        )
        card.add_widget(self._baidu_warning)

        # 凭证类型标签
        type_label = Label(
            text="Cookie / Token（粘贴完整凭证）",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(12),
            color=hex_to_rgba("#757575"),
            halign="left",
        )
        card.add_widget(type_label)

        # 凭证输入框
        self._credential_input = TextInput(
            multiline=True,
            size_hint_y=None,
            height=dp(100),
            font_size=sp(13),
            background_color=hex_to_rgba("#F5F5F5"),
            foreground_color=hex_to_rgba("#212121"),
            cursor_color=hex_to_rgba("#1976D2"),
            hint_text="例如：cookie=...; 或 {\"access_token\": \"...\"}",
        )
        card.add_widget(self._credential_input)

        # 按钮
        btn_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(12),
        )
        cancel_btn = MaterialButton(text="取消", bg_color="#9E9E9E", font_size=sp(14))
        cancel_btn.bind(on_release=lambda *a: self.dismiss())
        save_btn = MaterialButton(text="保存", bg_color="#4CAF50", font_size=sp(14))
        save_btn.bind(on_release=self._on_save_pressed)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(save_btn)
        card.add_widget(btn_box)

        self.add_widget(card)

    def _prev_drive(self, *args: Any) -> None:
        self._drive_index = (self._drive_index - 1) % len(self.DRIVE_OPTIONS)
        self._drive_label.text = self.DRIVE_OPTIONS[self._drive_index]
        self._update_baidu_warning()

    def _next_drive(self, *args: Any) -> None:
        self._drive_index = (self._drive_index + 1) % len(self.DRIVE_OPTIONS)
        self._drive_label.text = self.DRIVE_OPTIONS[self._drive_index]
        self._update_baidu_warning()

    def _update_baidu_warning(self) -> None:
        """切换到百度网盘时显示风控警告。"""
        if self.DRIVE_KEYS[self._drive_index] == "baidu":
            self._baidu_warning.opacity = 1
        else:
            self._baidu_warning.opacity = 0

    def _on_save_pressed(self, *args: Any) -> None:
        drive_key = self.DRIVE_KEYS[self._drive_index]
        credential_text = self._credential_input.text.strip()
        if not credential_text:
            return
        # 尝试解析为 JSON，否则作为 cookie 字符串
        credential: dict[str, str]
        if credential_text.startswith("{"):
            import json
            try:
                credential = json.loads(credential_text)
            except json.JSONDecodeError:
                credential = {"cookie": credential_text}
        else:
            credential = {"cookie": credential_text}

        self.dismiss()
        if self._on_save:
            self._on_save(drive_key, credential)


# ===========================================================================
# 密码输入弹窗
# ===========================================================================

class PasswordDialog(BaseDialog):
    """密码输入弹窗。

    用于加密配置导出时设置密码，或加密配置导入时输入密码。
    支持两次确认（设置密码模式）和单次输入（验证密码模式）。
    """

    def __init__(
        self,
        title: str = "输入密码",
        message: str = "",
        confirm: bool = False,
        on_submit: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.height = dp(220 if confirm else 180)
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self._confirm_mode = confirm

        card = self._make_card(220 if confirm else 180)

        # 标题
        title_label = Label(
            text=f"[b]{title}[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(28),
            font_size=sp(17),
        )
        card.add_widget(title_label)

        # 提示消息
        if message:
            msg_label = Label(
                text=message,
                size_hint_y=None,
                height=dp(24),
                font_size=sp(12),
                color=hex_to_rgba("#757575"),
                halign="center",
            )
            card.add_widget(msg_label)

        # 密码输入框
        self._password_input = TextInput(
            multiline=False,
            password=True,
            size_hint_y=None,
            height=dp(40),
            font_size=sp(14),
            background_color=hex_to_rgba("#F5F5F5"),
            foreground_color=hex_to_rgba("#212121"),
            cursor_color=hex_to_rgba("#1976D2"),
            hint_text="请输入密码",
        )
        card.add_widget(self._password_input)

        # 确认密码输入框（仅设置模式）
        if confirm:
            self._confirm_input = TextInput(
                multiline=False,
                password=True,
                size_hint_y=None,
                height=dp(40),
                font_size=sp(14),
                background_color=hex_to_rgba("#F5F5F5"),
                foreground_color=hex_to_rgba("#212121"),
                cursor_color=hex_to_rgba("#1976D2"),
                hint_text="请再次输入密码",
            )
            card.add_widget(self._confirm_input)

            # 密码强度提示
            self._strength_label = Label(
                text="",
                size_hint_y=None,
                height=dp(18),
                font_size=sp(11),
                halign="left",
            )
            card.add_widget(self._strength_label)
            self._password_input.bind(text=self._on_password_text)

        # 按钮
        btn_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(12),
        )
        cancel_btn = MaterialButton(text="取消", bg_color="#9E9E9E", font_size=sp(14))
        cancel_btn.bind(on_release=self._on_cancel_pressed)
        submit_btn = MaterialButton(text="确定", bg_color="#1976D2", font_size=sp(14))
        submit_btn.bind(on_release=self._on_submit_pressed)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(submit_btn)
        card.add_widget(btn_box)

        self.add_widget(card)

    def _on_password_text(self, instance: Any, value: str) -> None:
        """密码强度提示。"""
        if not value:
            self._strength_label.text = ""
            return
        score = 0
        if len(value) >= 6:
            score += 1
        if len(value) >= 10:
            score += 1
        if any(c.isdigit() for c in value):
            score += 1
        if any(c.isalpha() for c in value):
            score += 1
        if any(not c.isalnum() for c in value):
            score += 1

        if score <= 2:
            self._strength_label.text = "[color=#F44336]密码强度：弱[/color]"
            self._strength_label.markup = True
        elif score <= 3:
            self._strength_label.text = "[color=#FF9800]密码强度：中[/color]"
            self._strength_label.markup = True
        else:
            self._strength_label.text = "[color=#4CAF50]密码强度：强[/color]"
            self._strength_label.markup = True

    def _on_submit_pressed(self, *args: Any) -> None:
        password = self._password_input.text
        if not password:
            return
        if self._confirm_mode:
            confirm = self._confirm_input.text
            if password != confirm:
                self._strength_label.text = "[color=#F44336]两次输入的密码不一致[/color]"
                self._strength_label.markup = True
                return
        self.dismiss()
        if self._on_submit:
            self._on_submit(password)

    def _on_cancel_pressed(self, *args: Any) -> None:
        self.dismiss()
        if self._on_cancel:
            self._on_cancel()


# ===========================================================================
# 配置导出弹窗
# ===========================================================================

class ExportConfigDialog(BaseDialog):
    """配置导出弹窗。

    选择保存路径，选择明文/加密导出，加密时设置密码。
    回调 ``on_export`` 参数为 (output_path, password_or_None, include_tasks)。
    """

    def __init__(
        self,
        default_path: str = "",
        on_export: Callable[[str, str | None, bool], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.size_hint = (0.9, None)
        self.height = dp(340)
        self._on_export = on_export
        self._encrypted = False
        self._password: str | None = None

        card = self._make_card(340)

        # 标题
        title = Label(
            text="[b]导出配置[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(28),
            font_size=sp(17),
        )
        card.add_widget(title)

        # 说明
        desc = Label(
            text="导出内容：所有网盘凭证、下载设置、已保存任务",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(11),
            color=hex_to_rgba("#757575"),
            halign="left",
        )
        card.add_widget(desc)

        # 保存路径
        path_label = Label(
            text="保存路径",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(13),
            bold=True,
            halign="left",
        )
        card.add_widget(path_label)

        self._path_input = TextInput(
            multiline=False,
            text=default_path,
            size_hint_y=None,
            height=dp(40),
            font_size=sp(12),
            background_color=hex_to_rgba("#F5F5F5"),
            foreground_color=hex_to_rgba("#212121"),
            cursor_color=hex_to_rgba("#1976D2"),
        )
        card.add_widget(self._path_input)

        # 导出模式选择
        mode_label = Label(
            text="导出模式",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(13),
            bold=True,
            halign="left",
        )
        card.add_widget(mode_label)

        mode_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(8),
        )
        self._plain_btn = MaterialButton(
            text="明文导出",
            bg_color="#1976D2",
            font_size=sp(13),
            height=dp(36),
        )
        self._plain_btn.bind(on_release=lambda *a: self._set_mode(False))
        self._encrypt_btn = MaterialButton(
            text="加密导出",
            bg_color="#BDBDBD",
            font_size=sp(13),
            height=dp(36),
        )
        self._encrypt_btn.bind(on_release=lambda *a: self._set_mode(True))
        mode_row.add_widget(self._plain_btn)
        mode_row.add_widget(self._encrypt_btn)
        card.add_widget(mode_row)

        # 密码状态标签
        self._password_status = Label(
            text="",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(12),
            halign="left",
        )
        card.add_widget(self._password_status)

        # 包含任务开关
        from kivy.uix.switch import Switch
        task_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
        )
        task_label = Label(
            text="包含已保存下载任务",
            font_size=sp(13),
            halign="left",
        )
        self._task_switch = Switch(active=True, size_hint=(None, None), size=(dp(44), dp(26)))
        task_row.add_widget(task_label)
        task_row.add_widget(self._task_switch)
        card.add_widget(task_row)

        # 按钮
        btn_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(12),
        )
        cancel_btn = MaterialButton(text="取消", bg_color="#9E9E9E", font_size=sp(14))
        cancel_btn.bind(on_release=lambda *a: self.dismiss())
        export_btn = MaterialButton(text="导出", bg_color="#4CAF50", font_size=sp(14))
        export_btn.bind(on_release=self._on_export_pressed)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(export_btn)
        card.add_widget(btn_box)

        self.add_widget(card)

    def _set_mode(self, encrypted: bool) -> None:
        """设置导出模式。"""
        self._encrypted = encrypted
        if encrypted:
            self._plain_btn.bg_color = "#BDBDBD"
            self._encrypt_btn.bg_color = "#1976D2"
            # 弹出密码设置
            PasswordDialog(
                title="设置加密密码",
                message="密码将用于加密配置文件，请牢记",
                confirm=True,
                on_submit=self._on_password_set,
                on_cancel=lambda: self._set_mode(False),
            ).open()
        else:
            self._plain_btn.bg_color = "#1976D2"
            self._encrypt_btn.bg_color = "#BDBDBD"
            self._password = None
            self._password_status.text = ""

    def _on_password_set(self, password: str) -> None:
        """密码设置完成回调。"""
        self._password = password
        self._password_status.text = "[color=#4CAF50]✓ 已设置加密密码[/color]"
        self._password_status.markup = True

    def _on_export_pressed(self, *args: Any) -> None:
        """导出按钮回调。"""
        output_path = self._path_input.text.strip()
        if not output_path:
            return
        if self._encrypted and not self._password:
            # 重新要求设置密码
            self._set_mode(True)
            return
        self.dismiss()
        if self._on_export:
            self._on_export(
                output_path,
                self._password if self._encrypted else None,
                self._task_switch.active,
            )


# ===========================================================================
# 配置导入弹窗
# ===========================================================================

class ImportConfigDialog(BaseDialog):
    """配置导入弹窗。

    输入文件路径，自动检测加密，加密时输入密码，选择合并/替换模式。
    回调 ``on_import`` 参数为 (file_path, password_or_None, merge)。
    """

    def __init__(
        self,
        default_dir: str = "",
        on_import: Callable[[str, str | None, bool], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.size_hint = (0.9, None)
        self.height = dp(320)
        self._on_import = on_import
        self._default_dir = default_dir
        self._merge = True
        self._password: str | None = None
        self._file_encrypted = False

        card = self._make_card(320)

        # 标题
        title = Label(
            text="[b]导入配置[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(28),
            font_size=sp(17),
        )
        card.add_widget(title)

        # 文件路径
        path_label = Label(
            text="配置文件路径（.yunxcfg）",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(13),
            bold=True,
            halign="left",
        )
        card.add_widget(path_label)

        path_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(8),
        )
        self._path_input = TextInput(
            multiline=False,
            size_hint_x=0.75,
            font_size=sp(12),
            background_color=hex_to_rgba("#F5F5F5"),
            foreground_color=hex_to_rgba("#212121"),
            cursor_color=hex_to_rgba("#1976D2"),
            hint_text="输入或粘贴 .yunxcfg 文件路径",
        )
        scan_btn = MaterialButton(
            text="扫描",
            bg_color="#78909C",
            font_size=sp(12),
            size_hint_x=0.25,
            height=dp(36),
        )
        scan_btn.bind(on_release=self._on_scan)
        path_row.add_widget(self._path_input)
        path_row.add_widget(scan_btn)
        card.add_widget(path_row)

        # 加密状态标签
        self._encrypt_status = Label(
            text="",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(12),
            halign="left",
        )
        card.add_widget(self._encrypt_status)

        # 导入模式
        mode_label = Label(
            text="导入模式",
            size_hint_y=None,
            height=dp(20),
            font_size=sp(13),
            bold=True,
            halign="left",
        )
        card.add_widget(mode_label)

        mode_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(8),
        )
        self._merge_btn = MaterialButton(
            text="合并导入",
            bg_color="#1976D2",
            font_size=sp(13),
            height=dp(36),
        )
        self._merge_btn.bind(on_release=lambda *a: self._set_merge(True))
        self._replace_btn = MaterialButton(
            text="替换现有",
            bg_color="#BDBDBD",
            font_size=sp(13),
            height=dp(36),
        )
        self._replace_btn.bind(on_release=lambda *a: self._set_merge(False))
        mode_row.add_widget(self._merge_btn)
        mode_row.add_widget(self._replace_btn)
        card.add_widget(mode_row)

        # 模式说明
        self._mode_desc = Label(
            text="合并：保留现有配置，同名项被导入值覆盖",
            size_hint_y=None,
            height=dp(18),
            font_size=sp(11),
            color=hex_to_rgba("#757575"),
            halign="left",
        )
        card.add_widget(self._mode_desc)

        # 按钮
        btn_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(12),
        )
        cancel_btn = MaterialButton(text="取消", bg_color="#9E9E9E", font_size=sp(14))
        cancel_btn.bind(on_release=lambda *a: self.dismiss())
        import_btn = MaterialButton(text="导入", bg_color="#4CAF50", font_size=sp(14))
        import_btn.bind(on_release=self._on_import_pressed)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(import_btn)
        card.add_widget(btn_box)

        self.add_widget(card)

        # 路径变化时自动检测加密
        self._path_input.bind(text=self._on_path_change)

    def _on_path_change(self, instance: Any, value: str) -> None:
        """路径变化时检测文件加密状态。"""
        path = value.strip()
        if not path or not os.path.exists(path):
            self._encrypt_status.text = ""
            self._file_encrypted = False
            return
        try:
            from core import is_encrypted
            self._file_encrypted = is_encrypted(path)
            if self._file_encrypted:
                self._encrypt_status.text = "[color=#FF9800]🔒 检测到加密文件，导入时需输入密码[/color]"
                self._encrypt_status.markup = True
            else:
                self._encrypt_status.text = "[color=#4CAF50]✓ 明文配置文件[/color]"
                self._encrypt_status.markup = True
        except Exception:
            self._encrypt_status.text = ""
            self._file_encrypted = False

    def _on_scan(self, *args: Any) -> None:
        """扫描默认目录下的 .yunxcfg 文件。"""
        scan_dir = self._default_dir or os.path.expanduser("~")
        found = []
        try:
            for f in os.listdir(scan_dir):
                if f.endswith(".yunxcfg"):
                    found.append(os.path.join(scan_dir, f))
        except OSError:
            pass

        if not found:
            # 也扫描 Downloads 目录
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            try:
                for f in os.listdir(downloads):
                    if f.endswith(".yunxcfg"):
                        found.append(os.path.join(downloads, f))
            except OSError:
                pass

        if found:
            self._path_input.text = found[0]
        else:
            self._encrypt_status.text = f"[color=#F44336]未在 {scan_dir} 找到 .yunxcfg 文件[/color]"
            self._encrypt_status.markup = True

    def _set_merge(self, merge: bool) -> None:
        """设置导入模式。"""
        self._merge = merge
        if merge:
            self._merge_btn.bg_color = "#1976D2"
            self._replace_btn.bg_color = "#BDBDBD"
            self._mode_desc.text = "合并：保留现有配置，同名项被导入值覆盖"
        else:
            self._merge_btn.bg_color = "#BDBDBD"
            self._replace_btn.bg_color = "#F44336"
            self._mode_desc.text = "替换：清空现有配置后写入导入数据（不可恢复）"

    def _on_import_pressed(self, *args: Any) -> None:
        """导入按钮回调。"""
        file_path = self._path_input.text.strip()
        if not file_path or not os.path.exists(file_path):
            self._encrypt_status.text = "[color=#F44336]请输入有效的配置文件路径[/color]"
            self._encrypt_status.markup = True
            return

        if self._file_encrypted:
            # 需要密码
            PasswordDialog(
                title="输入解密密码",
                message="该配置文件已加密，请输入密码",
                confirm=False,
                on_submit=self._on_password_submit,
            ).open()
        else:
            self._password = None
            self._do_import()

    def _on_password_submit(self, password: str) -> None:
        """密码输入完成回调。"""
        self._password = password
        self._do_import()

    def _do_import(self) -> None:
        """执行导入。"""
        file_path = self._path_input.text.strip()
        self.dismiss()
        if self._on_import:
            self._on_import(file_path, self._password, self._merge)


# ===========================================================================
# 导入结果摘要弹窗
# ===========================================================================

class ImportResultDialog(BaseDialog):
    """导入结果摘要弹窗。

    显示导入的凭证数、设置数、任务数。
    """

    def __init__(
        self,
        credentials_count: int = 0,
        settings_count: int = 0,
        tasks_count: int = 0,
        on_ok: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.height = dp(220)
        self._on_ok = on_ok

        card = self._make_card(220)

        # 图标
        icon = Label(
            text="✅",
            size_hint_y=None,
            height=dp(40),
            font_size=sp(32),
        )
        card.add_widget(icon)

        # 标题
        title = Label(
            text="[b]配置导入成功[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(28),
            font_size=sp(17),
            color=hex_to_rgba("#4CAF50"),
        )
        card.add_widget(title)

        # 摘要
        summary = (
            f"网盘凭证：{credentials_count} 个\n"
            f"配置项：{settings_count} 项\n"
            f"下载任务：{tasks_count} 个"
        )
        summary_label = Label(
            text=summary,
            size_hint_y=None,
            height=dp(60),
            font_size=sp(14),
            halign="center",
            valign="middle",
        )
        card.add_widget(summary_label)

        # 按钮
        ok_btn = MaterialButton(
            text="确定",
            bg_color="#1976D2",
            font_size=sp(15),
        )
        ok_btn.bind(on_release=self._on_ok_pressed)
        card.add_widget(ok_btn)

        self.add_widget(card)

    def _on_ok_pressed(self, *args: Any) -> None:
        self.dismiss()
        if self._on_ok:
            self._on_ok()


# ===========================================================================
# 云盘上传对话框
# ===========================================================================

class UploadDialog(BaseDialog):
    """云盘上传对话框。

    流程：选择网盘 → 浏览远程目录 → 上传（进度条+速度）→ 完成后生成分享链接。
    百度网盘上传前显示风控警告。
    """

    def __init__(
        self,
        file_path: str,
        file_name: str = "",
        on_upload_start: Callable[[str, str, str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Args:
            file_path: 本地文件路径。
            file_name: 显示文件名。
            on_upload_start: 上传开始回调 (drive_name, remote_dir, task_id)。
        """
        super().__init__(**kwargs)
        self.size_hint = (0.92, None)
        self.height = dp(480)
        self._file_path = file_path
        self._file_name = file_name or os.path.basename(file_path)
        self._on_upload_start = on_upload_start
        self._drive_index = 0
        self._drive_keys: list[str] = []
        self._current_dir: str | None = None
        self._dir_stack: list[str | None] = []
        self._upload_task_id: str = ""
        self._stage = "select"  # select / browsing / uploading / done

        self._card = self._make_card(480)

        # 标题
        title = Label(
            text="[b]上传到云盘[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(28),
            font_size=sp(17),
        )
        self._card.add_widget(title)

        # 文件信息
        file_info = Label(
            text=f"📄 {self._file_name}",
            font_size=sp(13),
            halign="left",
            size_hint_y=None,
            height=dp(24),
            color=hex_to_rgba("#757575"),
        )
        file_info.bind(size=file_info.setter("text_size"))
        self._card.add_widget(file_info)

        # -- 网盘选择 --
        drive_label = Label(
            text="目标网盘",
            font_size=sp(13),
            bold=True,
            halign="left",
            size_hint_y=None,
            height=dp(20),
        )
        self._card.add_widget(drive_label)

        drive_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(8),
        )
        self._drive_label = Label(
            text="加载账号...",
            size_hint_x=0.7,
            font_size=sp(14),
            bold=True,
            halign="left",
        )
        self._drive_label.bind(size=self._drive_label.setter("text_size"))
        self._drive_prev = MaterialButton(
            text="<", bg_color="#BDBDBD", font_size=sp(16),
            size_hint_x=0.15, height=dp(36),
        )
        self._drive_prev.bind(on_release=self._prev_drive)
        self._drive_next = MaterialButton(
            text=">", bg_color="#BDBDBD", font_size=sp(16),
            size_hint_x=0.15, height=dp(36),
        )
        self._drive_next.bind(on_release=self._next_drive)
        drive_row.add_widget(self._drive_prev)
        drive_row.add_widget(self._drive_label)
        drive_row.add_widget(self._drive_next)
        self._card.add_widget(drive_row)

        # 百度风控警告
        self._baidu_warn = Label(
            text="[color=#F44336]⚠️ 百度网盘上传存在风控风险，频繁上传可能导致账号被封[/color]",
            markup=True,
            size_hint_y=None,
            height=dp(20),
            font_size=sp(11),
            opacity=0,
        )
        self._card.add_widget(self._baidu_warn)

        # -- 远程目录 --
        dir_label = Label(
            text="远程目录",
            font_size=sp(13),
            bold=True,
            halign="left",
            size_hint_y=None,
            height=dp(20),
        )
        self._card.add_widget(dir_label)

        # 目录导航栏
        nav_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
            spacing=dp(8),
        )
        self._back_btn = MaterialButton(
            text="← 返回上级",
            bg_color="#78909C",
            font_size=sp(12),
            size_hint_x=0.4,
            height=dp(32),
            disabled=True,
        )
        self._back_btn.bind(on_release=self._go_parent)
        self._refresh_btn = MaterialButton(
            text="🔄 刷新",
            bg_color="#78909C",
            font_size=sp(12),
            size_hint_x=0.3,
            height=dp(32),
        )
        self._refresh_btn.bind(on_release=self._refresh_dirs)
        self._path_label = Label(
            text="根目录",
            font_size=sp(11),
            color=hex_to_rgba("#757575"),
            halign="right",
            size_hint_x=0.3,
        )
        nav_row.add_widget(self._back_btn)
        nav_row.add_widget(self._refresh_btn)
        nav_row.add_widget(self._path_label)
        self._card.add_widget(nav_row)

        # 目录列表
        self._dir_scroll = ScrollView(size_hint=(1, 1))
        self._dir_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(2),
            padding=dp(4),
        )
        self._dir_list.bind(minimum_height=self._dir_list.setter("height"))
        self._dir_scroll.add_widget(self._dir_list)
        self._card.add_widget(self._dir_scroll)

        # -- 上传进度区（初始隐藏）--
        self._progress_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(0),
            spacing=dp(6),
            opacity=0,
        )
        from mobile_gui.ui.widgets import ThemedProgressBar
        self._upload_progress = ThemedProgressBar(
            value=0, progress_color="#4CAF50", height=dp(10),
        )
        self._upload_info = Label(
            text="准备上传...",
            font_size=sp(12),
            color=hex_to_rgba("#757575"),
            size_hint_y=None,
            height=dp(20),
        )
        self._progress_box.add_widget(self._upload_progress)
        self._progress_box.add_widget(self._upload_info)
        self._card.add_widget(self._progress_box)

        # -- 分享链接区（初始隐藏）--
        self._share_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(0),
            spacing=dp(6),
            opacity=0,
        )
        self._share_label = Label(
            text="",
            font_size=sp(12),
            color=hex_to_rgba("#4CAF50"),
            halign="left",
            size_hint_y=None,
            height=dp(40),
        )
        self._share_label.bind(size=self._share_label.setter("text_size"))
        self._share_btn = MaterialButton(
            text="📋 复制分享链接",
            bg_color="#2196F3",
            font_size=sp(13),
            height=dp(36),
        )
        self._share_btn.bind(on_release=self._copy_share_link)
        self._share_box.add_widget(self._share_label)
        self._share_box.add_widget(self._share_btn)
        self._card.add_widget(self._share_box)

        # -- 按钮区 --
        btn_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(12),
        )
        self._cancel_btn = MaterialButton(
            text="取消", bg_color="#9E9E9E", font_size=sp(14),
        )
        self._cancel_btn.bind(on_release=lambda *a: self.dismiss())
        self._upload_btn = MaterialButton(
            text="⬆️ 开始上传",
            bg_color="#4CAF50",
            font_size=sp(14),
        )
        self._upload_btn.bind(on_release=self._on_upload_pressed)
        btn_row.add_widget(self._cancel_btn)
        btn_row.add_widget(self._upload_btn)
        self._card.add_widget(btn_row)

        self.add_widget(self._card)

        # 加载已登录账号
        Clock.schedule_once(lambda dt: self._load_drives(), 0.1)

    def _load_drives(self) -> None:
        """加载已登录的网盘账号列表。"""
        from kivy.app import App
        app = App.get_running_app()
        drives = app.core.list_credentials()
        if not drives:
            self._drive_label.text = "无已登录账号"
            self._upload_btn.disabled = True
            return
        self._drive_keys = drives
        self._drive_index = 0
        self._update_drive_display()
        self._load_dirs()

    def _update_drive_display(self) -> None:
        """更新当前网盘显示。"""
        if not self._drive_keys:
            return
        drive = self._drive_keys[self._drive_index]
        from mobile_gui.core_adapter import CoreAdapter
        info = CoreAdapter.drive_display(drive)
        self._drive_label.text = f"{info['name']}（已登录）"
        self._drive_label.color = hex_to_rgba(info["color"])
        # 百度警告
        self._baidu_warn.opacity = 1 if drive == "baidu" else 0

    def _prev_drive(self, *args: Any) -> None:
        if not self._drive_keys:
            return
        self._drive_index = (self._drive_index - 1) % len(self._drive_keys)
        self._update_drive_display()
        self._current_dir = None
        self._dir_stack = []
        self._load_dirs()

    def _next_drive(self, *args: Any) -> None:
        if not self._drive_keys:
            return
        self._drive_index = (self._drive_index + 1) % len(self._drive_keys)
        self._update_drive_display()
        self._current_dir = None
        self._dir_stack = []
        self._load_dirs()

    def _load_dirs(self) -> None:
        """加载当前网盘的远程目录列表。"""
        if not self._drive_keys:
            return
        drive = self._drive_keys[self._drive_index]
        self._path_label.text = "根目录" if self._current_dir is None else "..."
        self._dir_list.clear_widgets()

        loading = Label(
            text="加载目录中...",
            font_size=sp(13),
            color=hex_to_rgba("#9E9E9E"),
            size_hint_y=None,
            height=dp(40),
        )
        self._dir_list.add_widget(loading)

        from kivy.app import App
        app = App.get_running_app()
        app.core.get_remote_dirs(
            drive_name=drive,
            parent_dir=self._current_dir,
            on_success=self._on_dirs_loaded,
            on_error=self._on_dirs_error,
        )

    def _on_dirs_loaded(self, dirs: list) -> None:
        """目录加载成功。"""
        self._dir_list.clear_widgets()

        # 根目录选项
        root_btn = self._make_dir_item("📁 根目录（上传到此）", None, is_root=True)
        self._dir_list.add_widget(root_btn)

        if not dirs:
            empty = Label(
                text="（无子目录）",
                font_size=sp(12),
                color=hex_to_rgba("#BDBDBD"),
                size_hint_y=None,
                height=dp(32),
            )
            self._dir_list.add_widget(empty)
            return

        for d in dirs:
            dir_name = getattr(d, "dir_name", str(d))
            dir_id = getattr(d, "dir_id", "")
            btn = self._make_dir_item(f"📁 {dir_name}", dir_id)
            self._dir_list.add_widget(btn)

    def _make_dir_item(self, text: str, dir_id: str | None, is_root: bool = False) -> MaterialButton:
        """创建目录项按钮。"""
        btn = MaterialButton(
            text=text,
            bg_color="#E3F2FD" if is_root else "#F5F5F5",
            text_color="#1565C0" if is_root else "#424242",
            font_size=sp(13),
            height=dp(36),
        )
        if is_root:
            btn.bind(on_release=lambda *a: self._select_dir(None))
        else:
            btn.bind(on_release=lambda *a: self._enter_dir(dir_id))
        return btn

    def _enter_dir(self, dir_id: str | None) -> None:
        """进入子目录。"""
        self._dir_stack.append(self._current_dir)
        self._current_dir = dir_id
        self._back_btn.disabled = False
        self._path_label.text = "子目录"
        self._load_dirs()

    def _go_parent(self, *args: Any) -> None:
        """返回上级目录。"""
        if self._dir_stack:
            self._current_dir = self._dir_stack.pop()
            self._back_btn.disabled = len(self._dir_stack) == 0
            self._path_label.text = "根目录" if self._current_dir is None else "子目录"
            self._load_dirs()

    def _select_dir(self, dir_id: str | None) -> None:
        """选择上传目标目录。"""
        self._current_dir = dir_id
        label = "根目录" if dir_id is None else "已选子目录"
        self._path_label.text = f"✓ {label}"

    def _refresh_dirs(self, *args: Any) -> None:
        self._load_dirs()

    def _on_dirs_error(self, error: Exception) -> None:
        """目录加载失败。"""
        self._dir_list.clear_widgets()
        err = Label(
            text=f"目录加载失败：{error}",
            font_size=sp(12),
            color=hex_to_rgba("#F44336"),
            size_hint_y=None,
            height=dp(40),
            halign="center",
        )
        self._dir_list.add_widget(err)

    def _on_upload_pressed(self, *args: Any) -> None:
        """点击开始上传。"""
        if not self._drive_keys:
            show_toast(self, "无已登录账号")
            return

        drive = self._drive_keys[self._drive_index]

        # 百度网盘：风控确认
        if drive == "baidu":
            confirmed = self._ask_baidu_confirm()
            if not confirmed:
                return

        self._stage = "uploading"
        self._upload_btn.disabled = True
        self._upload_btn.text = "上传中..."
        self._drive_prev.disabled = True
        self._drive_next.disabled = True

        # 显示进度区
        self._progress_box.height = dp(60)
        self._progress_box.opacity = 1
        self._upload_info.text = "正在初始化上传..."

        from kivy.app import App
        app = App.get_running_app()

        remote_dir = self._current_dir or ""

        task_id = app.core.upload_to_cloud(
            file_path=self._file_path,
            drive_name=drive,
            remote_dir=remote_dir,
            on_progress=self._on_upload_progress,
            on_status=self._on_upload_status,
            on_error=self._on_upload_error,
        )
        self._upload_task_id = task_id

        if self._on_upload_start:
            self._on_upload_start(drive, remote_dir, task_id)

    def _ask_baidu_confirm(self) -> bool:
        """百度网盘上传风控确认。"""
        import threading
        result_holder: dict[str, bool] = {}
        event = threading.Event()

        def on_confirm() -> None:
            result_holder["confirmed"] = True
            event.set()

        def on_cancel() -> None:
            result_holder["confirmed"] = False
            event.set()

        BaiduRiskDialog(on_confirm=on_confirm, on_cancel=on_cancel).open()
        event.wait(timeout=300)
        return result_holder.get("confirmed", False)

    def _on_upload_progress(self, task: Any) -> None:
        """上传进度回调（主线程）。"""
        self._upload_progress.value = task.percent
        from mobile_gui.core_adapter import CoreAdapter
        speed = CoreAdapter.format_speed(task.speed)
        uploaded = CoreAdapter.format_size(task.uploaded)
        total = CoreAdapter.format_size(task.total_size)
        self._upload_info.text = f"{task.percent:.1f}%  {uploaded}/{total}  {speed}"

    def _on_upload_status(self, task: Any) -> None:
        """上传状态回调（主线程）。"""
        if task.status == "completed":
            self._stage = "done"
            self._upload_progress.value = 100
            self._upload_info.text = "✅ 上传完成！"
            self._upload_btn.text = "完成"
            self._upload_btn.disabled = False
            self._upload_btn.unbind(on_release=self._on_upload_pressed)
            self._upload_btn.bind(on_release=lambda *a: self.dismiss())

            # 显示分享链接选项
            self._share_box.height = dp(90)
            self._share_box.opacity = 1
            self._share_label.text = "上传完成，可生成分享链接"

            # 自动尝试生成分享链接
            if task.result and hasattr(task.result, "file_id"):
                self._generate_share_link(task.drive, task.result.file_id)

            from kivy.app import App
            app = App.get_running_app()
            show_toast(app.root, "上传完成")

        elif task.status == "error":
            self._upload_info.text = f"❌ 上传失败：{task.error_msg}"
            self._upload_btn.text = "重试"
            self._upload_btn.disabled = False

    def _on_upload_error(self, error: Exception) -> None:
        """上传错误回调。"""
        self._upload_info.text = f"❌ 上传失败：{error}"
        self._upload_btn.text = "关闭"
        self._upload_btn.disabled = False
        self._upload_btn.unbind(on_release=self._on_upload_pressed)
        self._upload_btn.bind(on_release=lambda *a: self.dismiss())

    def _generate_share_link(self, drive: str, file_id: str) -> None:
        """生成分享链接。"""
        from kivy.app import App
        app = App.get_running_app()
        app.core.create_share_link(
            drive_name=drive,
            file_id=file_id,
            on_success=self._on_share_link,
            on_error=self._on_share_error,
        )

    def _on_share_link(self, share: Any) -> None:
        """分享链接生成成功。"""
        url = getattr(share, "share_url", "")
        code = getattr(share, "extract_code", "")
        text = f"🔗 分享链接：{url}"
        if code:
            text += f"\n📌 提取码：{code}"
        self._share_label.text = text
        self._share_url = url

    def _on_share_error(self, error: Exception) -> None:
        self._share_label.text = f"分享链接生成失败：{error}"

    def _copy_share_link(self, *args: Any) -> None:
        """复制分享链接到剪贴板。"""
        url = getattr(self, "_share_url", "")
        if url:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(url)
            show_toast(self, "分享链接已复制")
        else:
            show_toast(self, "暂无分享链接")


# ===========================================================================
# 导入结果摘要弹窗
# ===========================================================================
