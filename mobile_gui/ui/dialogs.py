"""
自定义弹窗。

包括：
- 百度网盘风控警告弹窗（全屏 ModalView，必须用户确认）
- 错误提示弹窗
- 通用确认弹窗
- 添加账号弹窗

所有弹窗均使用 Material Design 风格，圆角卡片 + 半透明遮罩。
"""

from __future__ import annotations

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

from mobile_gui.ui.widgets import MaterialButton, hex_to_rgba


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
            bg_color="#2196F3",
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
        confirm_btn = MaterialButton(text=confirm_text, bg_color="#2196F3", font_size=sp(14))
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
        self.height = dp(340)
        self._on_save = on_save
        self._drive_index = 0

        card = self._make_card(340)

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
            cursor_color=hex_to_rgba("#2196F3"),
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

    def _next_drive(self, *args: Any) -> None:
        self._drive_index = (self._drive_index + 1) % len(self.DRIVE_OPTIONS)
        self._drive_label.text = self.DRIVE_OPTIONS[self._drive_index]

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
