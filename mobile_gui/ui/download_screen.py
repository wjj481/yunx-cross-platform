"""
下载屏幕（DownloadScreen）。

功能：
- 下载任务列表（每个任务卡片显示文件名、进度条、百分比、速度、状态、控制按钮）
- 顶部：返回按钮 + 「全部暂停」「全部恢复」
- 空状态提示
- 定时刷新任务进度
"""

from __future__ import annotations

from typing import Any

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from mobile_gui.core_adapter import CoreAdapter
from mobile_gui.ui.widgets import (
    DownloadTaskCard,
    MaterialButton,
    Theme,
    hex_to_rgba,
)


class DownloadScreen(Screen):
    """下载屏幕：管理所有下载任务。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.name = "download"
        self._task_cards: dict[str, DownloadTaskCard] = {}
        self._refresh_event: ClockEvent | None = None  # type: ignore[name-defined]

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

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
            padding=[dp(8), 0],
            spacing=dp(8),
        )
        with top_bar.canvas.before:
            Color(*hex_to_rgba("#2196F3"))
            RoundedRectangle(pos=top_bar.pos, size=top_bar.size)

        back_btn = MaterialButton(
            text="←",
            bg_color="#1976D2",
            size_hint=(None, None),
            size=(dp(40), dp(40)),
            font_size=sp(20),
            radius=dp(20),
        )
        back_btn.bind(on_release=self._go_back)

        title = Label(
            text="[b]下载管理[/b]",
            markup=True,
            font_size=sp(18),
            color=hex_to_rgba("#FFFFFF"),
            halign="left",
            valign="middle",
        )
        title.bind(size=title.setter("text_size"))

        self._pause_all_btn = MaterialButton(
            text="全部暂停",
            bg_color="#FF9800",
            size_hint=(None, None),
            size=(dp(80), dp(36)),
            font_size=sp(12),
        )
        self._pause_all_btn.bind(on_release=self._pause_all)

        self._resume_all_btn = MaterialButton(
            text="全部恢复",
            bg_color="#4CAF50",
            size_hint=(None, None),
            size=(dp(80), dp(36)),
            font_size=sp(12),
        )
        self._resume_all_btn.bind(on_release=self._resume_all)

        top_bar.add_widget(back_btn)
        top_bar.add_widget(title)
        top_bar.add_widget(self._pause_all_btn)
        top_bar.add_widget(self._resume_all_btn)
        root.add_widget(top_bar)

        # 任务列表（可滚动）
        self._scroll = ScrollView(size_hint=(1, 1))
        self._task_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(8),
            padding=dp(12),
        )
        self._task_list.bind(minimum_height=self._task_list.setter("height"))
        self._scroll.add_widget(self._task_list)
        root.add_widget(self._scroll)

        # 空状态提示
        self._empty_label = Label(
            text="暂无下载任务\n在主屏幕解析链接后点击「下载选中」",
            font_size=sp(14),
            color=hex_to_rgba("#9E9E9E"),
            halign="center",
            valign="middle",
        )
        root.add_widget(self._empty_label)

        self.add_widget(root)

    def _update_bg(self, *args: Any) -> None:
        self._bg_rect.pos = self.children[0].pos
        self._bg_rect.size = self.children[0].size

    # ------------------------------------------------------------------
    # 任务管理
    # ------------------------------------------------------------------

    def add_task_card(self, task_id: str) -> None:
        """添加一个任务卡片。"""
        from kivy.app import App
        app = App.get_running_app()
        task = app.core.get_task(task_id)
        if not task:
            return

        if task_id in self._task_cards:
            return

        card = DownloadTaskCard(
            task_id=task_id,
            file_name=task.file_name,
            percent=task.percent,
            speed_text=CoreAdapter.format_speed(task.speed),
            size_text=f"{CoreAdapter.format_size(task.downloaded)} / {CoreAdapter.format_size(task.total_size)}",
            status=task.status,
        )
        self._task_cards[task_id] = card
        self._task_list.add_widget(card)
        self._task_list.height += card.height + dp(8)
        self._empty_label.opacity = 0

    def update_task_card(self, task: Any) -> None:
        """更新任务卡片进度。"""
        card = self._task_cards.get(task.task_id)
        if card:
            card.percent = task.percent
            card.speed_text = CoreAdapter.format_speed(task.speed)
            card.size_text = (
                f"{CoreAdapter.format_size(task.downloaded)} / "
                f"{CoreAdapter.format_size(task.total_size)}"
            )
            card.status = task.status

    def refresh_all_tasks(self) -> None:
        """从核心适配器刷新所有任务状态。"""
        from kivy.app import App
        app = App.get_running_app()
        tasks = app.core.get_all_tasks()
        for task in tasks:
            if task.task_id not in self._task_cards:
                self.add_task_card(task.task_id)
            else:
                self.update_task_card(task)

        # 更新空状态
        if not tasks:
            self._empty_label.opacity = 1
        else:
            self._empty_label.opacity = 0

    # ------------------------------------------------------------------
    # 批量操作
    # ------------------------------------------------------------------

    def _pause_all(self, *args: Any) -> None:
        """暂停所有下载任务。"""
        from kivy.app import App
        app = App.get_running_app()
        app.core.pause_all()
        self.refresh_all_tasks()

    def _resume_all(self, *args: Any) -> None:
        """恢复所有暂停的任务。"""
        from kivy.app import App
        app = App.get_running_app()
        app.core.resume_all()
        self.refresh_all_tasks()

    # ------------------------------------------------------------------
    # 屏幕生命周期
    # ------------------------------------------------------------------

    def on_enter(self, *args: Any) -> None:
        """进入屏幕时启动定时刷新。"""
        self.refresh_all_tasks()
        # 每 0.5 秒刷新一次进度
        self._refresh_event = Clock.schedule_interval(
            lambda dt: self.refresh_all_tasks(), 0.5
        )

    def on_leave(self, *args: Any) -> None:
        """离开屏幕时停止定时刷新。"""
        if self._refresh_event:
            self._refresh_event.cancel()
            self._refresh_event = None

    def _go_back(self, *args: Any) -> None:
        self.manager.current = "main"
