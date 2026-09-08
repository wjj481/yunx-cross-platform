"""
解析页标签页（v0.3.0 三标签子页）。

包含三个子标签页：
- 网盘解析：链接输入+提取码+文件列表+下载（原有功能）
- 视频解析：视频链接输入+解析+清晰度选择+下载（B站/抖音/YouTube等）
- 音乐解析：音乐链接输入+解析+歌曲列表+音质选择+下载（网易云/QQ音乐等）

所有网络操作在子线程执行，通过 root.after() 更新 UI。
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from core.clipboard import detect_share_url
from core.exceptions import NetworkError, ParserError, YunXError
from core.music import (
    MusicDownloader,
    PlaylistInfo,
    QUALITY_LABELS,
    SongInfo,
    get_music_parser,
)
from core.parsers.base import ShareInfo
from core.video import VideoInfo, VideoDownloader, get_video_parser

from ..dialogs.settings import (
    CHUNK_SIZE_OPTIONS,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CONCURRENCY,
    DEFAULT_MUSIC_OUTPUT_DIR,
    DEFAULT_MUSIC_QUALITY,
    DEFAULT_SAVE_PATH,
    DEFAULT_VIDEO_OUTPUT_DIR,
    DEFAULT_VIDEO_QUALITY,
    MUSIC_QUALITY_OPTIONS,
    VIDEO_QUALITY_OPTIONS,
)
from ..utils import format_size, get_drive_display, get_drive_color, needs_risk_warning
from ..widgets.file_list import FileListWidget


# ==================================================================
# 网盘解析子页（原有功能）
# ==================================================================

class NetdiskParseFrame(ttk.Frame):
    """网盘解析子页：链接输入+提取码+文件列表+下载操作。"""

    def __init__(
        self,
        master: tk.Misc,
        on_parse: Callable[[str, str | None], None],
        on_download: Callable[[list[ShareInfo], str, int, int], None],
    ) -> None:
        super().__init__(master, padding=4)
        self._on_parse = on_parse
        self._on_download = on_download

        self._save_path = DEFAULT_SAVE_PATH
        self._concurrency = DEFAULT_CONCURRENCY
        self._chunk_size = DEFAULT_CHUNK_SIZE
        self._clipboard_hint_url = ""

        self._build_ui()

    def _build_ui(self) -> None:
        # ---- URL 输入区 ----
        url_frame = ttk.LabelFrame(self, text="分享链接", padding=10)
        url_frame.pack(fill=tk.X, pady=(0, 10))

        self._url_text = tk.Text(
            url_frame, height=3, wrap=tk.WORD, font=("", 11),
            relief=tk.SOLID, borderwidth=1, padx=8, pady=6,
        )
        self._url_text.pack(fill=tk.X, pady=(0, 6))
        self._url_text.bind("<Return>", lambda _e: self._handle_parse())
        self._setup_drag_drop()

        # 剪贴板提示条
        self._clipboard_hint_frame = ttk.Frame(url_frame)
        self._clipboard_hint_label = ttk.Label(
            self._clipboard_hint_frame, text="", foreground="#1976D2",
            cursor="hand2", font=("", 9),
        )
        self._clipboard_hint_label.pack(side=tk.LEFT)
        self._clipboard_hint_label.bind(
            "<Button-1>", lambda _e: self._apply_clipboard_url()
        )

        row2 = ttk.Frame(url_frame)
        row2.pack(fill=tk.X)

        ttk.Label(row2, text="提取码：").pack(side=tk.LEFT)
        self._code_var = tk.StringVar()
        self._code_entry = ttk.Entry(row2, textvariable=self._code_var, width=14)
        self._code_entry.pack(side=tk.LEFT, padx=(4, 12))
        self._code_entry.bind("<Return>", lambda _e: self._handle_parse())

        ttk.Label(row2, text="（可选，自动识别时预填）", foreground="#888", font=("", 9)).pack(side=tk.LEFT)

        self._clipboard_btn = ttk.Button(
            row2, text="从剪贴板粘贴", command=self._handle_clipboard
        )
        self._clipboard_btn.pack(side=tk.LEFT, padx=(12, 0))

        self._parse_btn = ttk.Button(
            row2, text="🔍 解析", style="Primary.TButton", command=self._handle_parse
        )
        self._parse_btn.pack(side=tk.RIGHT)

        # ---- 文件列表区 ----
        self._file_list = FileListWidget(self)
        self._file_list.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # ---- 下载操作栏 ----
        dl_frame = ttk.LabelFrame(self, text="下载操作", padding=10)
        dl_frame.pack(fill=tk.X)

        btn_row = ttk.Frame(dl_frame)
        btn_row.pack(fill=tk.X, pady=(0, 8))

        self._download_selected_btn = ttk.Button(
            btn_row, text="下载选中", style="Primary.TButton",
            command=self._on_download_selected,
        )
        self._download_selected_btn.pack(side=tk.LEFT)

        self._download_all_btn = ttk.Button(
            btn_row, text="全部下载", command=self._on_download_all
        )
        self._download_all_btn.pack(side=tk.LEFT, padx=(8, 0))

        self._select_all_btn = ttk.Button(btn_row, text="全选", command=self._select_all)
        self._select_all_btn.pack(side=tk.LEFT, padx=(8, 0))

        self._invert_btn = ttk.Button(btn_row, text="反选", command=self._invert_selection)
        self._invert_btn.pack(side=tk.LEFT, padx=(4, 0))

        path_row = ttk.Frame(dl_frame)
        path_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(path_row, text="保存到：").pack(side=tk.LEFT)
        self._save_path_var = tk.StringVar(value=self._save_path)
        ttk.Entry(path_row, textvariable=self._save_path_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6)
        )
        ttk.Button(path_row, text="浏览...", width=8, command=self._browse_save_path).pack(side=tk.LEFT)

        opt_row = ttk.Frame(dl_frame)
        opt_row.pack(fill=tk.X)

        ttk.Label(opt_row, text="并发数：").pack(side=tk.LEFT)
        self._concurrency_var = tk.IntVar(value=self._concurrency)
        self._concurrency_scale = ttk.Scale(
            opt_row, from_=1, to=32, orient=tk.HORIZONTAL,
            variable=self._concurrency_var, length=140,
            command=self._on_concurrency_change,
        )
        self._concurrency_scale.pack(side=tk.LEFT)
        self._concurrency_label = ttk.Label(
            opt_row, text=f"{self._concurrency}", width=4, font=("", 10, "bold")
        )
        self._concurrency_label.pack(side=tk.LEFT, padx=(4, 16))

        ttk.Label(opt_row, text="分片大小：").pack(side=tk.LEFT)
        self._chunk_var = tk.StringVar()
        self._chunk_combo = ttk.Combobox(
            opt_row, textvariable=self._chunk_var,
            values=list(CHUNK_SIZE_OPTIONS.keys()), state="readonly", width=8,
        )
        for name, size in CHUNK_SIZE_OPTIONS.items():
            if size == self._chunk_size:
                self._chunk_var.set(name)
                break
        self._chunk_combo.pack(side=tk.LEFT, padx=(4, 0))

    def _setup_drag_drop(self) -> None:
        try:
            self._url_text.drop_target_register("DND_Text")  # type: ignore[attr-defined]
            self._url_text.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_drop(self, event: Any) -> None:
        text = getattr(event, "data", "")
        if text:
            self._url_text.delete("1.0", tk.END)
            self._url_text.insert("1.0", text.strip())

    # ---- 公共方法 ----

    def get_url(self) -> str:
        return self._url_text.get("1.0", tk.END).strip()

    def get_extract_code(self) -> str | None:
        code = self._code_var.get().strip()
        return code if code else None

    def set_url(self, url: str) -> None:
        self._url_text.delete("1.0", tk.END)
        self._url_text.insert("1.0", url)

    def set_extract_code(self, code: str | None) -> None:
        self._code_var.set(code or "")

    def set_parsing(self, parsing: bool) -> None:
        state = tk.DISABLED if parsing else tk.NORMAL
        self._parse_btn.config(state=state)
        self._clipboard_btn.config(state=state)
        self._parse_btn.config(text="解析中..." if parsing else "🔍 解析")

    def set_files(self, share_infos: list[ShareInfo], drive: str = "") -> None:
        self._file_list.set_files(share_infos, drive)

    def show_clipboard_hint(self, url: str, drive: str = "") -> None:
        self._clipboard_hint_url = url
        display = get_drive_display(drive) if drive else "网盘"
        self._clipboard_hint_label.config(
            text=f"📋 检测到剪贴板中的{display}分享链接，点击填入"
        )
        self._clipboard_hint_frame.pack(fill=tk.X, pady=(0, 6))

    def hide_clipboard_hint(self) -> None:
        self._clipboard_hint_frame.pack_forget()
        self._clipboard_hint_url = ""

    def update_settings(
        self, save_path: str | None = None,
        concurrency: int | None = None, chunk_size: int | None = None,
    ) -> None:
        if save_path is not None:
            self._save_path = save_path
            self._save_path_var.set(save_path)
        if concurrency is not None:
            self._concurrency = concurrency
            self._concurrency_var.set(concurrency)
            self._concurrency_label.config(text=str(concurrency))
        if chunk_size is not None:
            self._chunk_size = chunk_size
            for name, size in CHUNK_SIZE_OPTIONS.items():
                if size == chunk_size:
                    self._chunk_var.set(name)
                    break

    def clear(self) -> None:
        self._url_text.delete("1.0", tk.END)
        self._code_var.set("")
        self._file_list.clear()

    # ---- 事件处理 ----

    def _handle_parse(self) -> None:
        url = self.get_url()
        if not url:
            return
        code = self.get_extract_code()
        self._on_parse(url, code)

    def _handle_clipboard(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        if not text:
            return
        urls = detect_share_url(text)
        if urls:
            share = urls[0]
            self.set_url(share.url)
            if share.extract_code:
                self.set_extract_code(share.extract_code)
        else:
            self.set_url(text.strip())

    def _apply_clipboard_url(self) -> None:
        if self._clipboard_hint_url:
            self.set_url(self._clipboard_hint_url)
            self.hide_clipboard_hint()

    def _on_download_selected(self) -> None:
        selected = self._file_list.get_selected_files()
        if not selected:
            messagebox.showinfo("提示", "请先在文件列表中选择要下载的文件", parent=self)
            return
        self._start_downloads(selected)

    def _on_download_all(self) -> None:
        all_files = self._file_list.get_all_files()
        if not all_files:
            messagebox.showinfo("提示", "文件列表为空，请先解析分享链接", parent=self)
            return
        self._start_downloads(all_files)

    def _start_downloads(self, share_infos: list[ShareInfo]) -> None:
        save_path = self._save_path_var.get().strip() or DEFAULT_SAVE_PATH
        concurrency = int(self._concurrency_var.get())
        chunk_size = CHUNK_SIZE_OPTIONS.get(self._chunk_var.get(), DEFAULT_CHUNK_SIZE)
        self._on_download(share_infos, save_path, concurrency, chunk_size)

    def _select_all(self) -> None:
        tree = self._file_list._tree
        for item in tree.get_children():
            tree.selection_add(item)

    def _invert_selection(self) -> None:
        tree = self._file_list._tree
        all_items = set(tree.get_children())
        selected = set(tree.selection())
        tree.selection_remove(*selected)
        tree.selection_add(*(all_items - selected))

    def _on_concurrency_change(self, _value: str) -> None:
        self._concurrency_label.config(text=str(int(self._concurrency_var.get())))

    def _browse_save_path(self) -> None:
        path = filedialog.askdirectory(
            title="选择下载保存目录",
            initialdir=self._save_path_var.get() or str(Path.home()),
            parent=self,
        )
        if path:
            self._save_path_var.set(path)
            self._save_path = path


# ==================================================================
# 视频解析子页
# ==================================================================

class VideoParseFrame(ttk.Frame):
    """视频解析子页：链接输入+解析+清晰度选择+下载。"""

    # 平台显示名映射
    PLATFORM_NAMES = {
        "bilibili": "哔哩哔哩",
        "douyin": "抖音",
        "youtube": "YouTube",
        "kuaishou": "快手",
        "weibo": "微博",
        "xiaohongshu": "小红书",
        "xigua": "西瓜视频",
        "zhihu": "知乎",
        "twitter": "Twitter",
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "facebook": "Facebook",
    }

    def __init__(
        self,
        master: tk.Misc,
        on_add_task: Callable[..., None],
        get_config: Callable[[], Any],
        concurrency: int = DEFAULT_CONCURRENCY,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        super().__init__(master, padding=4)
        self._on_add_task = on_add_task
        self._get_config = get_config
        self._concurrency = concurrency
        self._chunk_size = chunk_size
        self._video_info: VideoInfo | None = None
        self._output_dir = DEFAULT_VIDEO_OUTPUT_DIR
        self._default_quality = DEFAULT_VIDEO_QUALITY

        self._build_ui()

    def _build_ui(self) -> None:
        # ---- 链接输入区 ----
        input_frame = ttk.LabelFrame(self, text="视频链接", padding=10)
        input_frame.pack(fill=tk.X, pady=(0, 10))

        self._url_var = tk.StringVar()
        self._url_entry = ttk.Entry(input_frame, textvariable=self._url_var, font=("", 11))
        self._url_entry.pack(fill=tk.X, pady=(0, 6))
        self._url_entry.bind("<Return>", lambda _e: self._handle_parse())

        row = ttk.Frame(input_frame)
        row.pack(fill=tk.X)

        self._platform_label = ttk.Label(row, text="平台：未识别", foreground="#888", font=("", 9))
        self._platform_label.pack(side=tk.LEFT)

        self._paste_btn = ttk.Button(row, text="从剪贴板粘贴", width=12, command=self._handle_paste)
        self._paste_btn.pack(side=tk.LEFT, padx=(12, 0))

        self._parse_btn = ttk.Button(
            row, text="🔍 解析视频", style="Primary.TButton", command=self._handle_parse
        )
        self._parse_btn.pack(side=tk.RIGHT)

        # ---- 解析结果区 ----
        result_frame = ttk.LabelFrame(self, text="解析结果", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 封面 + 信息
        info_row = ttk.Frame(result_frame)
        info_row.pack(fill=tk.BOTH, expand=True)

        # 封面占位
        self._cover_label = ttk.Label(
            info_row, text="🎬\n视频封面",
            font=("", 24), foreground="#AAA",
            width=16, anchor=tk.CENTER,
            relief=tk.SOLID, borderwidth=1,
        )
        self._cover_label.pack(side=tk.LEFT, padx=(0, 12))

        # 视频信息
        info_detail = ttk.Frame(info_row)
        info_detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._title_label = ttk.Label(
            info_detail, text="等待解析...", font=("", 11, "bold"),
            wraplength=400, justify=tk.LEFT,
        )
        self._title_label.pack(anchor=tk.W, pady=(0, 4))

        self._meta_label = ttk.Label(info_detail, text="", foreground="#666", font=("", 9))
        self._meta_label.pack(anchor=tk.W, pady=(0, 4))

        self._exp_label = ttk.Label(info_detail, text="", foreground="#FB8C00", font=("", 9))
        self._exp_label.pack(anchor=tk.W)

        # ---- 下载操作区 ----
        dl_frame = ttk.LabelFrame(self, text="下载设置", padding=10)
        dl_frame.pack(fill=tk.X)

        # 清晰度选择
        q_row = ttk.Frame(dl_frame)
        q_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(q_row, text="清晰度：", width=10).pack(side=tk.LEFT)
        self._quality_var = tk.StringVar()
        self._quality_combo = ttk.Combobox(
            q_row, textvariable=self._quality_var, state="readonly", width=20,
        )
        self._quality_combo.pack(side=tk.LEFT, padx=(4, 0))

        # 输出目录
        path_row = ttk.Frame(dl_frame)
        path_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(path_row, text="保存到：", width=10).pack(side=tk.LEFT)
        self._output_var = tk.StringVar(value=self._output_dir)
        ttk.Entry(path_row, textvariable=self._output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6)
        )
        ttk.Button(path_row, text="浏览...", width=8, command=self._browse_output).pack(side=tk.LEFT)

        # 下载按钮
        btn_row = ttk.Frame(dl_frame)
        btn_row.pack(fill=tk.X)

        self._download_btn = ttk.Button(
            btn_row, text="⬇ 下载视频", style="Primary.TButton",
            command=self._handle_download, state=tk.DISABLED,
        )
        self._download_btn.pack(side=tk.RIGHT)

        ttk.Label(
            dl_frame,
            text="⚠ 仅供个人学习研究使用，请尊重版权，下载内容请于24小时内删除",
            foreground="#999", font=("", 8),
        ).pack(anchor=tk.W, pady=(6, 0))

    # ---- 公共方法 ----

    def update_settings(
        self, output_dir: str | None = None, default_quality: str | None = None,
        concurrency: int | None = None, chunk_size: int | None = None,
    ) -> None:
        if output_dir is not None:
            self._output_dir = output_dir
            self._output_var.set(output_dir)
        if default_quality is not None:
            self._default_quality = default_quality
        if concurrency is not None:
            self._concurrency = concurrency
        if chunk_size is not None:
            self._chunk_size = chunk_size

    # ---- 事件处理 ----

    def _handle_paste(self) -> None:
        try:
            text = self.clipboard_get().strip()
            if text:
                self._url_var.set(text)
                self._detect_platform(text)
        except tk.TclError:
            pass

    def _detect_platform(self, url: str) -> None:
        """识别视频链接所属平台并更新提示。"""
        try:
            parser = get_video_parser(url)
            platform = parser.platform_name
            display = self.PLATFORM_NAMES.get(platform, platform)
            experimental = getattr(parser, "experimental", False)
            exp_text = "（实验性支持，接口可能失效）" if experimental else ""
            self._platform_label.config(
                text=f"平台：{display}{exp_text}",
                foreground="#FB8C00" if experimental else "#43A047",
            )
        except ParserError:
            self._platform_label.config(text="平台：未识别", foreground="#888")

    def _handle_parse(self) -> None:
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入视频链接", parent=self)
            return

        self._detect_platform(url)
        self._parse_btn.config(state=tk.DISABLED, text="解析中...")
        self._title_label.config(text="正在解析...", foreground="#1976D2")
        self._meta_label.config(text="")
        self._exp_label.config(text="")
        self._download_btn.config(state=tk.DISABLED)
        self._quality_combo["values"] = []

        thread = threading.Thread(target=self._parse_worker, args=(url,), daemon=True)
        thread.start()

    def _parse_worker(self, url: str) -> None:
        try:
            credential = None
            config = self._get_config()
            if config is not None:
                # 视频平台凭证（如果有配置）
                pass

            dl = VideoDownloader(concurrency=self._concurrency)
            info = dl.parse(url, credential=credential)
            self.after(0, lambda: self._parse_success(info))
        except ParserError as exc:
            self.after(0, lambda: self._parse_error(f"解析失败：{exc}"))
        except NetworkError as exc:
            self.after(0, lambda: self._parse_error(f"网络错误：{exc}"))
        except YunXError as exc:
            self.after(0, lambda: self._parse_error(f"错误：{exc}"))
        except Exception as exc:
            self.after(0, lambda: self._parse_error(f"未知错误：{exc}"))

    def _parse_success(self, info: VideoInfo) -> None:
        self._video_info = info
        self._parse_btn.config(state=tk.NORMAL, text="🔍 解析视频")
        self._title_label.config(text=info.title, foreground="#1C1B1F")

        # 时长格式化
        duration_str = self._format_duration(info.duration)
        platform_display = self.PLATFORM_NAMES.get(info.platform, info.platform)
        meta_parts = [f"平台：{platform_display}", f"时长：{duration_str}"]
        if info.file_size > 0:
            meta_parts.append(f"大小：{format_size(info.file_size)}")
        self._meta_label.config(text="  |  ".join(meta_parts))

        # 实验性提示
        try:
            parser = get_video_parser(f"https://{info.platform}.com")
            if getattr(parser, "experimental", False):
                self._exp_label.config(text="⚠ 该平台为实验性支持，接口可能失效")
            else:
                self._exp_label.config(text="")
        except Exception:
            self._exp_label.config(text="")

        # 填充清晰度下拉框
        quality_labels = []
        for q in info.quality_list:
            label = q.description if q.description else q.quality
            if q.file_size > 0:
                label += f" ({format_size(q.file_size)})"
            quality_labels.append(label)
        self._quality_combo["values"] = quality_labels

        # 默认选择
        if info.quality_list:
            # 尝试匹配默认清晰度
            default_idx = 0
            for i, q in enumerate(info.quality_list):
                if q.quality.lower() == self._default_quality.lower():
                    default_idx = i
                    break
            self._quality_combo.current(default_idx)

        self._download_btn.config(state=tk.NORMAL if info.quality_list else tk.DISABLED)

    def _parse_error(self, message: str) -> None:
        self._parse_btn.config(state=tk.NORMAL, text="🔍 解析视频")
        self._title_label.config(text="解析失败", foreground="#C62828")
        self._meta_label.config(text=message, foreground="#C62828")
        self._video_info = None
        messagebox.showerror("视频解析失败", message, parent=self)

    def _handle_download(self) -> None:
        if self._video_info is None:
            messagebox.showwarning("提示", "请先解析视频", parent=self)
            return

        quality_idx = self._quality_combo.current()
        if quality_idx < 0 or quality_idx >= len(self._video_info.quality_list):
            messagebox.showwarning("提示", "请选择清晰度", parent=self)
            return

        quality = self._video_info.quality_list[quality_idx].quality
        output_dir = self._output_var.get().strip() or DEFAULT_VIDEO_OUTPUT_DIR

        # 在子线程中获取直链并创建下载任务
        self._download_btn.config(state=tk.DISABLED, text="准备下载...")
        thread = threading.Thread(
            target=self._download_worker,
            args=(self._video_info, quality, output_dir),
            daemon=True,
        )
        thread.start()

    def _download_worker(self, info: VideoInfo, quality: str, output_dir: str) -> None:
        try:
            # 获取解析器和直链
            parser = get_video_parser(f"https://{info.platform}.com")
            download_url = parser.get_download_url(info, quality)

            # 构建请求头
            headers = {"User-Agent": "YunX-Downloader/1.0"}
            referer_map = {
                "bilibili": "https://www.bilibili.com",
                "douyin": "https://www.douyin.com/",
                "youtube": "https://www.youtube.com/",
            }
            if info.platform in referer_map:
                headers["Referer"] = referer_map[info.platform]

            # 构建文件名
            import re
            safe_title = re.sub(r'[\\/:*?"<>|]', "_", info.title).strip()
            option = info.find_quality(quality)
            ext = option.format if option else "mp4"
            file_name = f"{safe_title}_{quality}.{ext}"

            # 通知主应用创建下载任务
            self.after(0, lambda: self._on_add_task(
                file_name=file_name,
                url=download_url,
                output_dir=output_dir,
                chunk_size=self._chunk_size,
                concurrency=self._concurrency,
                headers=headers,
                task_type="video",
            ))
            self.after(0, lambda: self._download_btn.config(
                state=tk.NORMAL, text="⬇ 下载视频"
            ))
        except ParserError as exc:
            self.after(0, lambda: self._download_error(f"获取下载链接失败：{exc}"))
        except Exception as exc:
            self.after(0, lambda: self._download_error(f"下载准备失败：{exc}"))

    def _download_error(self, message: str) -> None:
        self._download_btn.config(state=tk.NORMAL, text="⬇ 下载视频")
        messagebox.showerror("下载失败", message, parent=self)

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(
            title="选择视频保存目录",
            initialdir=self._output_var.get() or str(Path.home()),
            parent=self,
        )
        if path:
            self._output_var.set(path)
            self._output_dir = path

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds <= 0:
            return "未知"
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:d}:{s:02d}"


# ==================================================================
# 音乐解析子页
# ==================================================================

class MusicParseFrame(ttk.Frame):
    """音乐解析子页：链接输入+解析+歌曲列表+音质选择+下载。"""

    SOURCE_NAMES = {
        "netease": "网易云音乐",
        "qqmusic": "QQ音乐",
        "kugou": "酷狗音乐",
        "kuwo": "酷我音乐",
    }

    def __init__(
        self,
        master: tk.Misc,
        on_add_task: Callable[..., None],
        get_config: Callable[[], Any],
        concurrency: int = DEFAULT_CONCURRENCY,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        super().__init__(master, padding=4)
        self._on_add_task = on_add_task
        self._get_config = get_config
        self._concurrency = concurrency
        self._chunk_size = chunk_size
        self._songs: list[SongInfo] = []
        self._playlist_info: PlaylistInfo | None = None
        self._output_dir = DEFAULT_MUSIC_OUTPUT_DIR
        self._default_quality = DEFAULT_MUSIC_QUALITY
        self._embed_id3 = True
        self._download_cover = True

        self._build_ui()

    def _build_ui(self) -> None:
        # ---- 链接输入区 ----
        input_frame = ttk.LabelFrame(self, text="音乐链接（单曲/歌单/专辑）", padding=10)
        input_frame.pack(fill=tk.X, pady=(0, 10))

        self._url_var = tk.StringVar()
        self._url_entry = ttk.Entry(input_frame, textvariable=self._url_var, font=("", 11))
        self._url_entry.pack(fill=tk.X, pady=(0, 6))
        self._url_entry.bind("<Return>", lambda _e: self._handle_parse())

        row = ttk.Frame(input_frame)
        row.pack(fill=tk.X)

        self._source_label = ttk.Label(row, text="来源：未识别", foreground="#888", font=("", 9))
        self._source_label.pack(side=tk.LEFT)

        self._paste_btn = ttk.Button(row, text="从剪贴板粘贴", width=12, command=self._handle_paste)
        self._paste_btn.pack(side=tk.LEFT, padx=(12, 0))

        self._parse_btn = ttk.Button(
            row, text="🔍 解析音乐", style="Primary.TButton", command=self._handle_parse
        )
        self._parse_btn.pack(side=tk.RIGHT)

        # ---- 歌曲列表区 ----
        list_frame = ttk.LabelFrame(self, text="歌曲列表", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 列表操作按钮
        list_btn_row = ttk.Frame(list_frame)
        list_btn_row.pack(fill=tk.X, pady=(0, 6))

        self._select_all_btn = ttk.Button(list_btn_row, text="全选", width=8, command=self._select_all)
        self._select_all_btn.pack(side=tk.LEFT)

        self._invert_btn = ttk.Button(list_btn_row, text="反选", width=8, command=self._invert_selection)
        self._invert_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._count_label = ttk.Label(list_frame, text="共 0 首", foreground="#888", font=("", 9))
        self._count_label.pack(anchor=tk.E, pady=(0, 4))

        # Treeview 歌曲列表
        tree_container = ttk.Frame(list_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        self._song_tree = ttk.Treeview(
            tree_container,
            columns=("title", "artist", "album", "duration"),
            show="headings",
            selectmode="extended",
            height=8,
        )
        self._song_tree.heading("title", text="歌曲名")
        self._song_tree.heading("artist", text="歌手")
        self._song_tree.heading("album", text="专辑")
        self._song_tree.heading("duration", text="时长")
        self._song_tree.column("title", width=200)
        self._song_tree.column("artist", width=120)
        self._song_tree.column("album", width=140)
        self._song_tree.column("duration", width=70, anchor=tk.CENTER)
        self._song_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        song_scroll = ttk.Scrollbar(
            tree_container, orient=tk.VERTICAL, command=self._song_tree.yview
        )
        self._song_tree.configure(yscrollcommand=song_scroll.set)
        song_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # ---- 下载操作区 ----
        dl_frame = ttk.LabelFrame(self, text="下载设置", padding=10)
        dl_frame.pack(fill=tk.X)

        q_row = ttk.Frame(dl_frame)
        q_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(q_row, text="音质：", width=10).pack(side=tk.LEFT)
        self._quality_var = tk.StringVar()
        quality_display = [MUSIC_QUALITY_OPTIONS.get(k, k) for k in ["standard", "higher", "lossless"]]
        self._quality_combo = ttk.Combobox(
            q_row, textvariable=self._quality_var,
            values=quality_display, state="readonly", width=20,
        )
        # 设置默认音质
        default_display = MUSIC_QUALITY_OPTIONS.get(self._default_quality, self._default_quality)
        self._quality_var.set(default_display)
        self._quality_combo.pack(side=tk.LEFT, padx=(4, 0))

        path_row = ttk.Frame(dl_frame)
        path_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(path_row, text="保存到：", width=10).pack(side=tk.LEFT)
        self._output_var = tk.StringVar(value=self._output_dir)
        ttk.Entry(path_row, textvariable=self._output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6)
        )
        ttk.Button(path_row, text="浏览...", width=8, command=self._browse_output).pack(side=tk.LEFT)

        btn_row = ttk.Frame(dl_frame)
        btn_row.pack(fill=tk.X)

        self._download_btn = ttk.Button(
            btn_row, text="⬇ 下载选中", style="Primary.TButton",
            command=self._handle_download, state=tk.DISABLED,
        )
        self._download_btn.pack(side=tk.RIGHT)

        self._download_all_btn = ttk.Button(
            btn_row, text="下载全部", command=self._handle_download_all, state=tk.DISABLED
        )
        self._download_all_btn.pack(side=tk.RIGHT, padx=(0, 8))

        ttk.Label(
            dl_frame,
            text="⚠ 仅供个人学习研究使用，请尊重版权，下载内容请于24小时内删除",
            foreground="#999", font=("", 8),
        ).pack(anchor=tk.W, pady=(6, 0))

    # ---- 公共方法 ----

    def update_settings(
        self, output_dir: str | None = None, default_quality: str | None = None,
        embed_id3: bool | None = None, download_cover: bool | None = None,
        concurrency: int | None = None, chunk_size: int | None = None,
    ) -> None:
        if output_dir is not None:
            self._output_dir = output_dir
            self._output_var.set(output_dir)
        if default_quality is not None:
            self._default_quality = default_quality
            display = MUSIC_QUALITY_OPTIONS.get(default_quality, default_quality)
            self._quality_var.set(display)
        if embed_id3 is not None:
            self._embed_id3 = embed_id3
        if download_cover is not None:
            self._download_cover = download_cover
        if concurrency is not None:
            self._concurrency = concurrency
        if chunk_size is not None:
            self._chunk_size = chunk_size

    # ---- 事件处理 ----

    def _handle_paste(self) -> None:
        try:
            text = self.clipboard_get().strip()
            if text:
                self._url_var.set(text)
                self._detect_source(text)
        except tk.TclError:
            pass

    def _detect_source(self, url: str) -> None:
        try:
            parser = get_music_parser(url)
            source = parser.source_name
            display = self.SOURCE_NAMES.get(source, source)
            experimental = getattr(parser, "experimental", False) or parser.status == "experimental"
            exp_text = "（实验性支持）" if experimental else ""
            self._source_label.config(
                text=f"来源：{display}{exp_text}",
                foreground="#FB8C00" if experimental else "#43A047",
            )
        except ParserError:
            self._source_label.config(text="来源：未识别", foreground="#888")

    def _handle_parse(self) -> None:
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入音乐链接", parent=self)
            return

        self._detect_source(url)
        self._parse_btn.config(state=tk.DISABLED, text="解析中...")
        self._song_tree.delete(*self._song_tree.get_children())
        self._count_label.config(text="解析中...")
        self._download_btn.config(state=tk.DISABLED)
        self._download_all_btn.config(state=tk.DISABLED)

        thread = threading.Thread(target=self._parse_worker, args=(url,), daemon=True)
        thread.start()

    def _parse_worker(self, url: str) -> None:
        try:
            credential = None
            config = self._get_config()
            if config is not None:
                pass  # 音乐平台凭证可在此扩展

            dl = MusicDownloader(output_dir=self._output_dir, concurrency=self._concurrency)

            # 尝试解析为歌单/专辑，失败则解析为单曲
            songs: list[SongInfo] = []
            playlist_info: PlaylistInfo | None = None
            is_playlist = False

            try:
                playlist_info = dl.parse_playlist(url)
                songs = playlist_info.songs
                is_playlist = True
            except Exception:
                # 不是歌单，尝试单曲
                song = dl.parse_song(url)
                songs = [song]

            self.after(0, lambda: self._parse_success(songs, playlist_info, is_playlist))
        except ParserError as exc:
            self.after(0, lambda: self._parse_error(f"解析失败：{exc}"))
        except NetworkError as exc:
            self.after(0, lambda: self._parse_error(f"网络错误：{exc}"))
        except YunXError as exc:
            self.after(0, lambda: self._parse_error(f"错误：{exc}"))
        except Exception as exc:
            self.after(0, lambda: self._parse_error(f"未知错误：{exc}"))

    def _parse_success(
        self, songs: list[SongInfo], playlist_info: PlaylistInfo | None, is_playlist: bool
    ) -> None:
        self._songs = songs
        self._playlist_info = playlist_info
        self._parse_btn.config(state=tk.NORMAL, text="🔍 解析音乐")

        self._song_tree.delete(*self._song_tree.get_children())
        for i, song in enumerate(songs):
            duration = self._format_duration(song.duration)
            restricted = " [版权受限]" if song.copyright_restricted else ""
            self._song_tree.insert(
                "", tk.END, iid=str(i),
                values=(song.title + restricted, song.artist, song.album, duration),
            )

        count_text = f"共 {len(songs)} 首"
        if is_playlist and playlist_info:
            count_text = f"歌单「{playlist_info.title}」共 {len(songs)} 首"
        self._count_label.config(text=count_text)

        has_downloadable = any(not s.copyright_restricted for s in songs)
        self._download_btn.config(state=tk.NORMAL if has_downloadable else tk.DISABLED)
        self._download_all_btn.config(state=tk.NORMAL if has_downloadable else tk.DISABLED)

        # 实验性平台提示
        if songs:
            try:
                parser = get_music_parser(f"https://{songs[0].source}.com")
                if getattr(parser, "experimental", False) or parser.status == "experimental":
                    messagebox.showinfo(
                        "提示",
                        "该音乐平台为实验性支持，接口可能失效。\n如解析失败请稍后重试或更换平台。",
                        parent=self,
                    )
            except Exception:
                pass

    def _parse_error(self, message: str) -> None:
        self._parse_btn.config(state=tk.NORMAL, text="🔍 解析音乐")
        self._count_label.config(text="解析失败")
        messagebox.showerror("音乐解析失败", message, parent=self)

    def _handle_download(self) -> None:
        selected = self._song_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要下载的歌曲", parent=self)
            return
        indices = [int(i) for i in selected]
        self._download_songs(indices)

    def _handle_download_all(self) -> None:
        if not self._songs:
            return
        indices = list(range(len(self._songs)))
        self._download_songs(indices)

    def _download_songs(self, indices: list[int]) -> None:
        quality_display = self._quality_var.get()
        # 反查音质标识
        quality = self._default_quality
        for k, v in MUSIC_QUALITY_OPTIONS.items():
            if v == quality_display:
                quality = k
                break

        output_dir = self._output_var.get().strip() or DEFAULT_MUSIC_OUTPUT_DIR
        songs_to_download = [self._songs[i] for i in indices if not self._songs[i].copyright_restricted]

        if not songs_to_download:
            messagebox.showwarning("提示", "选中的歌曲均因版权限制无法下载", parent=self)
            return

        self._download_btn.config(state=tk.DISABLED, text="准备下载...")
        self._download_all_btn.config(state=tk.DISABLED)

        thread = threading.Thread(
            target=self._download_worker,
            args=(songs_to_download, quality, output_dir),
            daemon=True,
        )
        thread.start()

    def _download_worker(self, songs: list[SongInfo], quality: str, output_dir: str) -> None:
        try:
            credential = None
            config = self._get_config()
            if config is not None:
                pass

            for song in songs:
                try:
                    parser = get_music_parser(
                        f"https://{song.source}.com", credential=credential
                    )
                    download_url = parser.get_download_url(song, quality)

                    # 确定实际音质和扩展名
                    actual_quality = quality
                    if song.get_quality(quality) is None:
                        best = song.best_available_quality()
                        actual_quality = best.quality if best else quality

                    from core.music.base import QUALITY_EXTENSIONS
                    ext = QUALITY_EXTENSIONS.get(actual_quality, "mp3")

                    import re
                    artist = song.artist or "Unknown Artist"
                    title = song.title or "Unknown Title"
                    safe_name = re.sub(r'[\\/:*?"<>|]', "_", f"{artist} - {title}")
                    if len(safe_name) > 200:
                        safe_name = safe_name[:200]
                    file_name = f"{safe_name}.{ext}"

                    # ID3 标签嵌入钩子
                    song_ref = song
                    embed = self._embed_id3
                    dl_cover = self._download_cover

                    def post_hook(path: str, s=song_ref, do_embed=embed, do_cover=dl_cover) -> None:
                        if not do_embed:
                            return
                        try:
                            from core.music import embed_id3_tags
                            cover_bytes = None
                            if do_cover and s.cover:
                                import requests
                                try:
                                    resp = requests.get(s.cover, timeout=15)
                                    if resp.status_code == 200 and resp.content:
                                        cover_bytes = resp.content
                                except Exception:
                                    pass
                            embed_id3_tags(path, s, cover_bytes)
                        except Exception:
                            pass

                    self.after(0, lambda fn=file_name, url=download_url, hook=post_hook: self._on_add_task(
                        file_name=fn,
                        url=url,
                        output_dir=output_dir,
                        chunk_size=self._chunk_size,
                        concurrency=self._concurrency,
                        headers={"User-Agent": "Mozilla/5.0"},
                        post_download_hook=hook,
                        task_type="music",
                    ))
                except Exception:
                    continue  # 单首失败跳过

            self.after(0, lambda: self._download_btn.config(state=tk.NORMAL, text="⬇ 下载选中"))
            self.after(0, lambda: self._download_all_btn.config(state=tk.NORMAL))
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("下载失败", str(exc), parent=self))
            self.after(0, lambda: self._download_btn.config(state=tk.NORMAL, text="⬇ 下载选中"))
            self.after(0, lambda: self._download_all_btn.config(state=tk.NORMAL))

    def _select_all(self) -> None:
        for item in self._song_tree.get_children():
            self._song_tree.selection_add(item)

    def _invert_selection(self) -> None:
        all_items = set(self._song_tree.get_children())
        selected = set(self._song_tree.selection())
        self._song_tree.selection_remove(*selected)
        self._song_tree.selection_add(*(all_items - selected))

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(
            title="选择音乐保存目录",
            initialdir=self._output_var.get() or str(Path.home()),
            parent=self,
        )
        if path:
            self._output_var.set(path)
            self._output_dir = path

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds <= 0:
            return "--:--"
        m, s = divmod(seconds, 60)
        return f"{m:d}:{s:02d}"


# ==================================================================
# 解析页主容器（三标签子页）
# ==================================================================

class ParsePage(ttk.Frame):
    """解析页标签页（v0.3.0）。

    包含三个子标签：网盘解析、视频解析、音乐解析。
    保留原有公共 API（set_parsing / set_files / show_clipboard_hint 等），
    委托给网盘解析子页。

    Signals:
        on_parse(url, extract_code): 网盘解析回调。
        on_download(share_infos, save_path, concurrency, chunk_size): 网盘下载回调。
        on_add_task(**kwargs): 视频/音乐下载任务创建回调。
    """

    def __init__(
        self,
        master: tk.Misc,
        on_parse: Callable[[str, str | None], None],
        on_download: Callable[[list[ShareInfo], str, int, int], None],
        on_add_task: Callable[..., None] | None = None,
        get_config: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(master, padding=12)
        self._on_parse = on_parse
        self._on_download = on_download
        self._on_add_task = on_add_task or (lambda **kw: None)
        self._get_config = get_config or (lambda: None)

        self._save_path = DEFAULT_SAVE_PATH
        self._concurrency = DEFAULT_CONCURRENCY
        self._chunk_size = DEFAULT_CHUNK_SIZE

        self._build_ui()

    def _build_ui(self) -> None:
        # 子标签页
        self._sub_notebook = ttk.Notebook(self)
        self._sub_notebook.pack(fill=tk.BOTH, expand=True)

        # 网盘解析
        self._netdisk_frame = NetdiskParseFrame(
            self._sub_notebook,
            on_parse=self._on_parse,
            on_download=self._on_download,
        )
        self._sub_notebook.add(self._netdisk_frame, text="  ☁ 网盘解析  ")

        # 视频解析
        self._video_frame = VideoParseFrame(
            self._sub_notebook,
            on_add_task=self._on_add_task,
            get_config=self._get_config,
            concurrency=self._concurrency,
            chunk_size=self._chunk_size,
        )
        self._sub_notebook.add(self._video_frame, text="  🎬 视频解析  ")

        # 音乐解析
        self._music_frame = MusicParseFrame(
            self._sub_notebook,
            on_add_task=self._on_add_task,
            get_config=self._get_config,
            concurrency=self._concurrency,
            chunk_size=self._chunk_size,
        )
        self._sub_notebook.add(self._music_frame, text="  🎵 音乐解析  ")

    # ==================================================================
    # 公共 API（委托给网盘子页，保持向后兼容）
    # ==================================================================

    def get_url(self) -> str:
        return self._netdisk_frame.get_url()

    def get_extract_code(self) -> str | None:
        return self._netdisk_frame.get_extract_code()

    def set_url(self, url: str) -> None:
        self._netdisk_frame.set_url(url)
        self._sub_notebook.select(0)  # 切换到网盘解析

    def set_extract_code(self, code: str | None) -> None:
        self._netdisk_frame.set_extract_code(code)

    def set_parsing(self, parsing: bool) -> None:
        self._netdisk_frame.set_parsing(parsing)

    def set_files(self, share_infos: list[ShareInfo], drive: str = "") -> None:
        self._netdisk_frame.set_files(share_infos, drive)

    def show_clipboard_hint(self, url: str, drive: str = "") -> None:
        self._netdisk_frame.show_clipboard_hint(url, drive)
        self._sub_notebook.select(0)

    def hide_clipboard_hint(self) -> None:
        self._netdisk_frame.hide_clipboard_hint()

    def update_settings(
        self,
        save_path: str | None = None,
        concurrency: int | None = None,
        chunk_size: int | None = None,
        video_output_dir: str | None = None,
        video_default_quality: str | None = None,
        music_output_dir: str | None = None,
        music_default_quality: str | None = None,
        music_embed_id3: bool | None = None,
        music_download_cover: bool | None = None,
    ) -> None:
        if save_path is not None:
            self._save_path = save_path
        if concurrency is not None:
            self._concurrency = concurrency
        if chunk_size is not None:
            self._chunk_size = chunk_size

        self._netdisk_frame.update_settings(save_path, concurrency, chunk_size)
        self._video_frame.update_settings(
            output_dir=video_output_dir, default_quality=video_default_quality,
            concurrency=concurrency, chunk_size=chunk_size,
        )
        self._music_frame.update_settings(
            output_dir=music_output_dir, default_quality=music_default_quality,
            embed_id3=music_embed_id3, download_cover=music_download_cover,
            concurrency=concurrency, chunk_size=chunk_size,
        )

    def clear(self) -> None:
        self._netdisk_frame.clear()
