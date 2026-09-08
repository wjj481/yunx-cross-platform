"""
设置页标签页（v0.3.0）。

包含下载设置（默认目录、并发数、分片大小、剪贴板监听）、
视频下载设置（默认清晰度、视频目录）、
音乐下载设置（默认音质、音乐目录、ID3标签、封面下载）、
外观（主题切换）、配置管理（导出/导入）、关于信息。
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .. import __app_name__, __version__
from ..dialogs.config_export import ExportConfigDialog, ImportConfigDialog
from ..dialogs.settings import (
    CHUNK_SIZE_OPTIONS,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CLIPBOARD_MONITOR,
    DEFAULT_CONCURRENCY,
    DEFAULT_MUSIC_DOWNLOAD_COVER,
    DEFAULT_MUSIC_EMBED_ID3,
    DEFAULT_MUSIC_OUTPUT_DIR,
    DEFAULT_MUSIC_QUALITY,
    DEFAULT_SAVE_PATH,
    DEFAULT_SOUND_NOTIFY,
    DEFAULT_VIDEO_OUTPUT_DIR,
    DEFAULT_VIDEO_QUALITY,
    MUSIC_QUALITY_OPTIONS,
    VIDEO_QUALITY_OPTIONS,
)
from ..theme import THEME_DISPLAY_NAMES


class SettingsPage(ttk.Frame):
    """设置页标签页。

    分区展示下载设置、视频设置、音乐设置、外观、配置管理和关于信息。
    """

    def __init__(
        self,
        master: tk.Misc,
        get_config: Any,
        on_settings_change: Any | None = None,
        on_theme_change: Any | None = None,
        on_config_imported: Any | None = None,
    ) -> None:
        """初始化设置页。

        Args:
            master: 父容器。
            get_config: 回调函数，返回当前 ConfigManager 或 None。
            on_settings_change: 设置变化回调 (settings_dict)。
            on_theme_change: 主题变化回调 (theme_name)。
            on_config_imported: 配置导入成功回调。
        """
        super().__init__(master, padding=12)
        self._get_config = get_config
        self._on_settings_change = on_settings_change
        self._on_theme_change = on_theme_change
        self._on_config_imported = on_config_imported

        # 当前设置
        self._save_path = DEFAULT_SAVE_PATH
        self._concurrency = DEFAULT_CONCURRENCY
        self._chunk_size = DEFAULT_CHUNK_SIZE
        self._clipboard_monitor = DEFAULT_CLIPBOARD_MONITOR
        self._sound_notify = DEFAULT_SOUND_NOTIFY
        self._theme = "light"

        # 视频设置
        self._video_quality = DEFAULT_VIDEO_QUALITY
        self._video_output_dir = DEFAULT_VIDEO_OUTPUT_DIR

        # 音乐设置
        self._music_quality = DEFAULT_MUSIC_QUALITY
        self._music_output_dir = DEFAULT_MUSIC_OUTPUT_DIR
        self._music_embed_id3 = DEFAULT_MUSIC_EMBED_ID3
        self._music_download_cover = DEFAULT_MUSIC_DOWNLOAD_COVER

        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI 布局。"""
        # 使用 Canvas + Scrollbar 实现可滚动设置页
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            container, orient=tk.VERTICAL, command=self._canvas.yview
        )
        self._scroll_frame = ttk.Frame(self._canvas)

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        content = self._scroll_frame

        # ==================================================================
        # 下载设置
        # ==================================================================
        dl_section = ttk.LabelFrame(content, text="下载设置", padding=12)
        dl_section.pack(fill=tk.X, padx=2, pady=(0, 10))

        # 默认保存路径
        row = ttk.Frame(dl_section)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="默认下载目录：", width=14).pack(side=tk.LEFT)
        self._path_var = tk.StringVar(value=self._save_path)
        ttk.Entry(row, textvariable=self._path_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(row, text="浏览...", width=8, command=self._browse_path).pack(
            side=tk.LEFT
        )

        # 并发数
        row = ttk.Frame(dl_section)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="并发数：", width=14).pack(side=tk.LEFT)
        self._conc_var = tk.IntVar(value=self._concurrency)
        self._conc_scale = ttk.Scale(
            row, from_=1, to=32, orient=tk.HORIZONTAL,
            variable=self._conc_var, length=200,
            command=self._on_conc_change,
        )
        self._conc_scale.pack(side=tk.LEFT)
        self._conc_label = ttk.Label(
            row, text=f"{self._concurrency}", width=4, font=("", 10, "bold")
        )
        self._conc_label.pack(side=tk.LEFT, padx=(8, 0))

        # 分片大小
        row = ttk.Frame(dl_section)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="分片大小：", width=14).pack(side=tk.LEFT)
        self._chunk_var = tk.StringVar()
        chunk_combo = ttk.Combobox(
            row, textvariable=self._chunk_var,
            values=list(CHUNK_SIZE_OPTIONS.keys()),
            state="readonly", width=10,
        )
        chunk_combo.pack(side=tk.LEFT)
        for name, size in CHUNK_SIZE_OPTIONS.items():
            if size == self._chunk_size:
                self._chunk_var.set(name)
                break
        chunk_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())

        # 剪贴板监听
        self._clipboard_var = tk.BooleanVar(value=self._clipboard_monitor)
        ttk.Checkbutton(
            dl_section, text="启用剪贴板自动监听（复制分享链接时自动填充）",
            variable=self._clipboard_var, command=self._save_settings,
        ).pack(anchor=tk.W, pady=(0, 4))

        # 下载完成提示音
        self._sound_var = tk.BooleanVar(value=self._sound_notify)
        ttk.Checkbutton(
            dl_section, text="下载完成时播放提示音",
            variable=self._sound_var, command=self._save_settings,
        ).pack(anchor=tk.W)

        # 保存按钮
        ttk.Button(
            dl_section, text="保存设置", style="Primary.TButton",
            command=self._save_settings,
        ).pack(anchor=tk.E, pady=(8, 0))

        # ==================================================================
        # 视频下载设置
        # ==================================================================
        video_section = ttk.LabelFrame(content, text="视频下载设置", padding=12)
        video_section.pack(fill=tk.X, padx=2, pady=(0, 10))

        # 默认清晰度
        row = ttk.Frame(video_section)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="默认清晰度：", width=14).pack(side=tk.LEFT)
        self._video_quality_var = tk.StringVar()
        video_quality_combo = ttk.Combobox(
            row, textvariable=self._video_quality_var,
            values=VIDEO_QUALITY_OPTIONS,
            state="readonly", width=12,
        )
        video_quality_combo.pack(side=tk.LEFT)
        # 设置默认值
        default_vq = "自动最佳" if self._video_quality == "auto" else self._video_quality
        if default_vq in VIDEO_QUALITY_OPTIONS:
            self._video_quality_var.set(default_vq)
        else:
            self._video_quality_var.set(VIDEO_QUALITY_OPTIONS[0])
        video_quality_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())

        # 视频下载目录
        row = ttk.Frame(video_section)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="视频下载目录：", width=14).pack(side=tk.LEFT)
        self._video_path_var = tk.StringVar(value=self._video_output_dir)
        ttk.Entry(row, textvariable=self._video_path_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(row, text="浏览...", width=8, command=self._browse_video_path).pack(
            side=tk.LEFT
        )

        ttk.Label(
            video_section,
            text="支持平台：哔哩哔哩、抖音、YouTube（完整）；其他平台实验性支持",
            foreground="#888", font=("", 9),
        ).pack(anchor=tk.W)

        # ==================================================================
        # 音乐下载设置
        # ==================================================================
        music_section = ttk.LabelFrame(content, text="音乐下载设置", padding=12)
        music_section.pack(fill=tk.X, padx=2, pady=(0, 10))

        # 默认音质
        row = ttk.Frame(music_section)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="默认音质：", width=14).pack(side=tk.LEFT)
        self._music_quality_var = tk.StringVar()
        music_quality_values = list(MUSIC_QUALITY_OPTIONS.values())
        music_quality_combo = ttk.Combobox(
            row, textvariable=self._music_quality_var,
            values=music_quality_values,
            state="readonly", width=16,
        )
        music_quality_combo.pack(side=tk.LEFT)
        default_mq = MUSIC_QUALITY_OPTIONS.get(self._music_quality, self._music_quality)
        self._music_quality_var.set(default_mq)
        music_quality_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())

        # 音乐下载目录
        row = ttk.Frame(music_section)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="音乐下载目录：", width=14).pack(side=tk.LEFT)
        self._music_path_var = tk.StringVar(value=self._music_output_dir)
        ttk.Entry(row, textvariable=self._music_path_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(row, text="浏览...", width=8, command=self._browse_music_path).pack(
            side=tk.LEFT
        )

        # 自动嵌入ID3标签
        self._music_embed_id3_var = tk.BooleanVar(value=self._music_embed_id3)
        ttk.Checkbutton(
            music_section, text="自动嵌入 ID3 标签（歌名/歌手/专辑/封面）",
            variable=self._music_embed_id3_var, command=self._save_settings,
        ).pack(anchor=tk.W, pady=(0, 4))

        # 自动下载封面
        self._music_cover_var = tk.BooleanVar(value=self._music_download_cover)
        ttk.Checkbutton(
            music_section, text="自动下载封面并嵌入标签",
            variable=self._music_cover_var, command=self._save_settings,
        ).pack(anchor=tk.W)

        ttk.Label(
            music_section,
            text="支持平台：网易云音乐、QQ音乐（完整）；酷狗、酷我实验性支持",
            foreground="#888", font=("", 9),
        ).pack(anchor=tk.W, pady=(4, 0))

        # ==================================================================
        # 外观
        # ==================================================================
        appearance_section = ttk.LabelFrame(content, text="外观", padding=12)
        appearance_section.pack(fill=tk.X, padx=2, pady=(0, 10))

        row = ttk.Frame(appearance_section)
        row.pack(fill=tk.X)
        ttk.Label(row, text="界面主题：", width=14).pack(side=tk.LEFT)
        self._theme_var = tk.StringVar(value=THEME_DISPLAY_NAMES.get(self._theme, "浅色"))
        theme_combo = ttk.Combobox(
            row, textvariable=self._theme_var,
            values=list(THEME_DISPLAY_NAMES.values()),
            state="readonly", width=12,
        )
        theme_combo.pack(side=tk.LEFT)
        theme_combo.bind("<<ComboboxSelected>>", self._on_theme_selected)

        # ==================================================================
        # 配置管理
        # ==================================================================
        config_section = ttk.LabelFrame(content, text="配置管理", padding=12)
        config_section.pack(fill=tk.X, padx=2, pady=(0, 10))

        ttk.Label(
            config_section,
            text="导出或导入配置文件（包含网盘凭证、下载设置和任务），\n用于备份或在设备间迁移配置。",
            foreground="#666", justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 10))

        btn_row = ttk.Frame(config_section)
        btn_row.pack(fill=tk.X)

        ttk.Button(
            btn_row, text="📤 导出配置", style="Primary.TButton",
            command=self._on_export, width=14,
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            btn_row, text="📥 导入配置", width=14,
            command=self._on_import,
        ).pack(side=tk.LEFT)

        # ==================================================================
        # 关于
        # ==================================================================
        about_section = ttk.LabelFrame(content, text="关于", padding=12)
        about_section.pack(fill=tk.X, padx=2, pady=(0, 10))

        ttk.Label(
            about_section, text=__app_name__, font=("", 14, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            about_section, text=f"版本 v{__version__}", foreground="#888",
        ).pack(anchor=tk.W, pady=(2, 0))

        ttk.Separator(about_section).pack(fill=tk.X, pady=8)

        about_text = (
            "全平台网盘解析 + 高速下载工具\n"
            "支持夸克、123云盘、迅雷、百度、UC、和彩云\n"
            "新增：视频解析下载、音乐解析下载、云盘上传\n\n"
            "桌面端：tkinter + ttk（Material 3 风格）\n"
            "核心引擎：Python 3.10+\n"
            "下载引擎：Range 分片并发 + 断点续传\n"
            "凭证加密：AES-256-GCM\n\n"
            "开源协议：MIT License\n"
            "GitHub：https://github.com/yunx-dev/yunx-cross-platform"
        )
        ttk.Label(
            about_section, text=about_text, justify=tk.LEFT, foreground="#555",
            font=("", 9),
        ).pack(anchor=tk.W)

        # 免责声明按钮
        ttk.Button(
            about_section, text="查看免责声明",
            command=self._show_disclaimer,
        ).pack(anchor=tk.W, pady=(8, 0))

    # ==================================================================
    # 公共方法
    # ==================================================================

    def load_settings(self, settings: dict[str, Any]) -> None:
        """从字典加载设置到 UI。

        Args:
            settings: 设置字典。
        """
        self._save_path = settings.get("save_path", DEFAULT_SAVE_PATH)
        self._concurrency = int(settings.get("concurrency", DEFAULT_CONCURRENCY))
        self._chunk_size = int(settings.get("chunk_size", DEFAULT_CHUNK_SIZE))
        self._clipboard_monitor = bool(settings.get("clipboard_monitor", DEFAULT_CLIPBOARD_MONITOR))
        self._sound_notify = bool(settings.get("sound_notify", DEFAULT_SOUND_NOTIFY))
        self._theme = settings.get("theme", "light")

        # 视频设置
        self._video_quality = settings.get("video_quality", DEFAULT_VIDEO_QUALITY)
        self._video_output_dir = settings.get("video_output_dir", DEFAULT_VIDEO_OUTPUT_DIR)

        # 音乐设置
        self._music_quality = settings.get("music_quality", DEFAULT_MUSIC_QUALITY)
        self._music_output_dir = settings.get("music_output_dir", DEFAULT_MUSIC_OUTPUT_DIR)
        self._music_embed_id3 = bool(settings.get("music_embed_id3", DEFAULT_MUSIC_EMBED_ID3))
        self._music_download_cover = bool(settings.get("music_download_cover", DEFAULT_MUSIC_DOWNLOAD_COVER))

        # 更新 UI
        self._path_var.set(self._save_path)
        self._conc_var.set(self._concurrency)
        self._conc_label.config(text=str(self._concurrency))

        for name, size in CHUNK_SIZE_OPTIONS.items():
            if size == self._chunk_size:
                self._chunk_var.set(name)
                break

        self._clipboard_var.set(self._clipboard_monitor)
        self._sound_var.set(self._sound_notify)
        self._theme_var.set(THEME_DISPLAY_NAMES.get(self._theme, "浅色"))

        # 视频
        vq_display = "自动最佳" if self._video_quality == "auto" else self._video_quality
        if vq_display in VIDEO_QUALITY_OPTIONS:
            self._video_quality_var.set(vq_display)
        self._video_path_var.set(self._video_output_dir)

        # 音乐
        mq_display = MUSIC_QUALITY_OPTIONS.get(self._music_quality, self._music_quality)
        self._music_quality_var.set(mq_display)
        self._music_path_var.set(self._music_output_dir)
        self._music_embed_id3_var.set(self._music_embed_id3)
        self._music_cover_var.set(self._music_download_cover)

    def get_settings(self) -> dict[str, Any]:
        """获取当前设置。"""
        # 视频清晰度反查
        vq_display = self._video_quality_var.get()
        video_quality = "auto" if vq_display == "自动最佳" else vq_display

        # 音乐音质反查
        mq_display = self._music_quality_var.get()
        music_quality = self._music_quality
        for k, v in MUSIC_QUALITY_OPTIONS.items():
            if v == mq_display:
                music_quality = k
                break

        return {
            "save_path": self._path_var.get().strip() or DEFAULT_SAVE_PATH,
            "concurrency": int(self._conc_var.get()),
            "chunk_size": CHUNK_SIZE_OPTIONS.get(self._chunk_var.get(), DEFAULT_CHUNK_SIZE),
            "clipboard_monitor": self._clipboard_var.get(),
            "sound_notify": self._sound_var.get(),
            "theme": self._theme,
            # 视频
            "video_quality": video_quality,
            "video_output_dir": self._video_path_var.get().strip() or DEFAULT_VIDEO_OUTPUT_DIR,
            # 音乐
            "music_quality": music_quality,
            "music_output_dir": self._music_path_var.get().strip() or DEFAULT_MUSIC_OUTPUT_DIR,
            "music_embed_id3": self._music_embed_id3_var.get(),
            "music_download_cover": self._music_cover_var.get(),
        }

    # ==================================================================
    # 事件处理
    # ==================================================================

    def _browse_path(self) -> None:
        """浏览选择保存路径。"""
        path = filedialog.askdirectory(
            title="选择默认下载目录",
            initialdir=self._path_var.get() or str(Path.home()),
            parent=self,
        )
        if path:
            self._path_var.set(path)
            self._save_settings()

    def _browse_video_path(self) -> None:
        """浏览选择视频下载目录。"""
        path = filedialog.askdirectory(
            title="选择视频下载目录",
            initialdir=self._video_path_var.get() or str(Path.home()),
            parent=self,
        )
        if path:
            self._video_path_var.set(path)
            self._save_settings()

    def _browse_music_path(self) -> None:
        """浏览选择音乐下载目录。"""
        path = filedialog.askdirectory(
            title="选择音乐下载目录",
            initialdir=self._music_path_var.get() or str(Path.home()),
            parent=self,
        )
        if path:
            self._music_path_var.set(path)
            self._save_settings()

    def _on_conc_change(self, _value: str) -> None:
        """并发数滑块变化。"""
        self._conc_label.config(text=str(int(self._conc_var.get())))

    def _on_theme_selected(self, _event: tk.Event) -> None:
        """主题选择变化。"""
        display = self._theme_var.get()
        for key, name in THEME_DISPLAY_NAMES.items():
            if name == display:
                self._theme = key
                break

        if self._on_theme_change:
            self._on_theme_change(self._theme)

        self._save_settings()

    def _save_settings(self) -> None:
        """保存设置到 ConfigManager 并通知回调。"""
        settings = self.get_settings()

        config = self._get_config()
        if config is not None:
            try:
                for key, value in settings.items():
                    config.set(key, value)
                config.save()
            except Exception:
                pass

        if self._on_settings_change:
            self._on_settings_change(settings)

    def _on_export(self) -> None:
        """导出配置。"""
        config = self._get_config()
        if config is None:
            messagebox.showinfo("提示", "请先在「账号」页解锁配置", parent=self)
            return
        ExportConfigDialog(self, config)

    def _on_import(self) -> None:
        """导入配置。"""
        config = self._get_config()
        if config is None:
            messagebox.showinfo("提示", "请先在「账号」页解锁配置", parent=self)
            return

        def _on_imported():
            if self._on_config_imported:
                self._on_config_imported()

        ImportConfigDialog(self, config, on_imported=_on_imported)

    def _show_disclaimer(self) -> None:
        """显示免责声明。"""
        disclaimer = (
            "免责声明\n\n"
            "本工具仅供学习和研究使用，用户应遵守相关法律法规和\n"
            "各网盘平台的用户协议。\n\n"
            "  • 不得用于下载侵权、违法或未经授权的内容\n"
            "  • 不得用于商业用途或大规模批量下载\n"
            "  • 视频/音乐内容仅供个人学习，下载后请于24小时内删除\n"
            "  • 使用本工具导致的账号封禁等后果由用户自行承担\n"
            "  • 开发者不对因使用本工具造成的任何损失负责\n\n"
            "请合理、合法地使用本工具。"
        )
        messagebox.showwarning("免责声明", disclaimer, parent=self)
