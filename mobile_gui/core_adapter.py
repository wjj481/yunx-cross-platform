"""
核心引擎适配器。

将核心引擎（``core`` 包）的同步阻塞 API 封装为移动端 GUI 可用的
异步线程模型：

- 解析在子线程执行，通过回调在主线程（``Clock.schedule_once``）通知结果。
- 下载在子线程执行，进度回调通过 ``Clock.schedule_once`` 调度到主线程。
- 统一管理下载任务（暂停 / 恢复 / 取消 / 状态查询）。
- 封装配置管理器（AES-GCM 加密存储凭证）。
- 封装剪贴板分享链接识别。

本模块不得在核心引擎中添加任何 GUI 依赖。
"""

from __future__ import annotations

import os
import platform
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from kivy.clock import Clock
from kivy.core.clipboard import Clipboard

# ---------------------------------------------------------------------------
# 核心引擎导入（延迟到函数内，避免无显示环境下导入失败时影响整个模块）
# ---------------------------------------------------------------------------
from core import (
    AuthenticationError,
    BaiduRiskWarning,
    DownloadError,
    NetworkError,
    ParserError,
    YunXError,
)
from core.exceptions import UploadError
from core.clipboard import ShareURL, detect_share_url
from core.config import ConfigManager
from core.downloader.engine import DownloadEngine
from core.downloader.progress import DownloadProgress
from core.parsers.base import ShareInfo, get_parser, list_supported_drives
from core.uploader.base import DirInfo, ShareInfo as UploadShareInfo, UploadResult
from core.uploader.engine import UploadEngine


# ===========================================================================
# 常量
# ===========================================================================

# 网盘显示名称与标识色（与视觉设计要求一致）
DRIVE_DISPLAY: dict[str, dict[str, str]] = {
    "quark":   {"name": "夸克网盘", "color": "#2196F3"},
    "pan123":  {"name": "123云盘",  "color": "#4CAF50"},
    "xunlei":  {"name": "迅雷云盘", "color": "#FF9800"},
    "baidu":   {"name": "百度网盘", "color": "#F44336"},
    "uc":      {"name": "UC网盘",   "color": "#9C27B0"},
    "caiyun":  {"name": "和彩云",   "color": "#00BCD4"},
}

# 视频平台显示名称与标识色
VIDEO_PLATFORM_DISPLAY: dict[str, dict[str, str]] = {
    "bilibili":    {"name": "哔哩哔哩", "color": "#00A1D6"},
    "douyin":      {"name": "抖音",     "color": "#000000"},
    "youtube":     {"name": "YouTube",  "color": "#FF0000"},
    "kuaishou":    {"name": "快手",     "color": "#FF4906"},
    "weibo":       {"name": "微博",     "color": "#E6162D"},
    "xiaohongshu": {"name": "小红书",   "color": "#FF2442"},
    "xigua":       {"name": "西瓜视频", "color": "#FF4400"},
    "zhihu":       {"name": "知乎",     "color": "#0066FF"},
    "twitter":     {"name": "Twitter",  "color": "#1DA1F2"},
    "tiktok":      {"name": "TikTok",   "color": "#000000"},
    "instagram":   {"name": "Instagram","color": "#E4405F"},
    "facebook":    {"name": "Facebook", "color": "#1877F2"},
}

# 音乐平台显示名称与标识色
MUSIC_PLATFORM_DISPLAY: dict[str, dict[str, str]] = {
    "netease":  {"name": "网易云音乐", "color": "#C20C0C"},
    "qqmusic":  {"name": "QQ音乐",     "color": "#31C27C"},
    "kugou":    {"name": "酷狗音乐",   "color": "#2CA2FF"},
    "kuwo":     {"name": "酷我音乐",   "color": "#FFD100"},
}

# 视频默认清晰度选项
VIDEO_QUALITY_OPTIONS = ["1080p", "720p", "480p", "auto"]
# 音乐音质选项
MUSIC_QUALITY_OPTIONS = ["standard", "higher", "lossless"]
MUSIC_QUALITY_LABELS = {
    "standard": "标准 128kbps",
    "higher":   "高品质 320kbps",
    "lossless": "无损 FLAC",
}

# 默认下载目录（按平台适配）
def default_download_dir() -> str:
    """返回当前平台的默认下载目录。

    - Android: ``/sdcard/Download/YunX/``（公共下载目录）
    - iOS: App 沙盒 Documents 目录
    - 其他（开发调试）: ``~/Downloads/YunX/``
    """
    system = platform.system()
    if system == "Android":
        # Android 公共下载目录；需要 WRITE_EXTERNAL_STORAGE 权限
        return "/sdcard/Download/YunX"
    if system == "Darwin" and _is_ios():
        # iOS 沙盒 Documents 目录
        return os.path.expanduser("~/Documents/YunX")
    # 桌面 / 开发环境
    return os.path.join(os.path.expanduser("~"), "Downloads", "YunX")


def _is_ios() -> bool:
    """判断是否运行在 iOS 上。

    kivy-ios 构建的应用在 ``platform.system()`` 上仍可能返回 Darwin，
    需通过架构或环境变量进一步区分。
    """
    try:
        # kivy-ios 环境下通常存在此模块
        import ios  # noqa: F401
        return True
    except ImportError:
        pass
    # 兜底：检查架构（iOS 设备为 arm64 且无 macOS 系统库特征）
    return os.environ.get("YUNX_IOS", "0") == "1"


# ===========================================================================
# 数据类
# ===========================================================================

@dataclass
class DownloadTask:
    """下载任务运行时状态。

    Attributes:
        task_id: 任务唯一标识。
        file_name: 文件名。
        url: 下载直链。
        output_path: 输出文件完整路径。
        total_size: 文件总大小（字节）。
        downloaded: 已下载字节数。
        speed: 当前速度（字节/秒）。
        percent: 完成百分比（0-100）。
        status: 任务状态（waiting / downloading / paused / completed / error / canceled）。
        error_msg: 错误信息（status 为 error 时有效）。
        engine: 关联的 DownloadEngine 实例。
        thread: 执行下载的子线程。
        drive: 网盘标识。
    """

    task_id: str
    file_name: str
    url: str
    output_path: str
    total_size: int = 0
    downloaded: int = 0
    speed: float = 0.0
    percent: float = 0.0
    status: str = "waiting"
    error_msg: str = ""
    engine: DownloadEngine | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)
    drive: str = ""


# 回调类型别名
ParseSuccessCB = Callable[[ShareInfo], None]
ParseErrorCB = Callable[[Exception], None]
BaiduWarningCB = Callable[[], bool]  # 返回 True 表示用户确认继续
ProgressCB = Callable[[DownloadTask], None]
TaskStatusCB = Callable[[DownloadTask], None]

# 视频/音乐解析回调
VideoParseSuccessCB = Callable[[Any], None]  # VideoInfo
MusicParseSuccessCB = Callable[[Any], None]  # SongInfo | PlaylistInfo

# 上传回调
UploadProgressCB = Callable[["UploadTask"], None]
UploadStatusCB = Callable[["UploadTask"], None]
RemoteDirsCB = Callable[[list[DirInfo]], None]
ShareLinkCB = Callable[[UploadShareInfo], None]


@dataclass
class UploadTask:
    """上传任务运行时状态。

    Attributes:
        task_id: 任务唯一标识。
        file_path: 本地文件路径。
        file_name: 文件名。
        drive: 网盘标识。
        remote_dir: 远程目标目录。
        total_size: 文件总大小（字节）。
        uploaded: 已上传字节数。
        speed: 当前速度（字节/秒）。
        percent: 完成百分比（0-100）。
        status: 任务状态（waiting / uploading / completed / error / canceled）。
        error_msg: 错误信息。
        result: 上传结果（完成时有效）。
        engine: 关联的 UploadEngine 实例。
        thread: 执行上传的子线程。
        task_type: 固定为 "upload"，用于下载 Tab 区分上传/下载。
    """

    task_id: str
    file_path: str
    file_name: str
    drive: str = ""
    remote_dir: str = ""
    total_size: int = 0
    uploaded: int = 0
    speed: float = 0.0
    percent: float = 0.0
    status: str = "waiting"
    error_msg: str = ""
    result: UploadResult | None = field(default=None, repr=False)
    engine: UploadEngine | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)
    task_type: str = "upload"


# ===========================================================================
# 核心适配器
# ===========================================================================

class CoreAdapter:
    """核心引擎适配器：线程封装 + 回调调度 + 任务管理。

    所有耗时操作（解析、下载）均在子线程执行，结果通过
    ``Clock.schedule_once`` 回调到主线程，确保 Kivy UI 安全更新。
    """

    def __init__(self, master_password: str = "yunx_default_master") -> None:
        """初始化适配器。

        Args:
            master_password: 配置加密主密码。移动端默认使用应用级密码，
                用户可在设置中修改。凭证本身仍经 AES-GCM 加密落盘。
        """
        self._tasks: dict[str, DownloadTask] = {}
        self._tasks_lock = threading.Lock()
        self._upload_tasks: dict[str, UploadTask] = {}
        self._upload_tasks_lock = threading.Lock()
        self._config: ConfigManager | None = None
        self._master_password = master_password
        self._init_config()

    # ------------------------------------------------------------------
    # 配置管理
    # ------------------------------------------------------------------

    def _init_config(self) -> None:
        """初始化加密配置管理器。

        在移动端，配置文件路径适配应用沙盒或内部存储。
        """
        try:
            config_dir = self._app_config_dir()
            config_path = os.path.join(config_dir, "config.enc")
            salt_path = os.path.join(config_dir, "salt.bin")
            self._config = ConfigManager(
                password=self._master_password,
                config_path=config_path,
                salt_path=salt_path,
            )
        except Exception as exc:
            # 配置初始化失败不应阻塞应用启动；降级为内存配置
            print(f"[CoreAdapter] 配置管理器初始化失败，使用内存模式: {exc}")
            self._config = None

    @staticmethod
    def _app_config_dir() -> str:
        """返回应用配置目录（按平台适配）。"""
        system = platform.system()
        if system == "Android":
            return "/data/data/com.yunx.app/shared_prefs/yunx"
        if system == "Darwin" and _is_ios():
            return os.path.expanduser("~/Documents/.yunx")
        return os.path.join(os.path.expanduser("~"), ".yunx")

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取通用配置项。"""
        if self._config is None:
            return default
        return self._config.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """写入通用配置项。"""
        if self._config is None:
            return
        self._config.set(key, value)

    # -- 凭证管理 --

    def list_credentials(self) -> list[str]:
        """列出已保存凭证的网盘标识列表。"""
        if self._config is None:
            return []
        return self._config.list_drives()

    def get_credential(self, drive: str) -> dict[str, Any] | None:
        """获取指定网盘的凭证。"""
        if self._config is None:
            return None
        return self._config.get_credential(drive)

    def set_credential(self, drive: str, credential: dict[str, Any]) -> None:
        """保存指定网盘的凭证（AES-GCM 加密存储）。"""
        if self._config is None:
            return
        self._config.set_credential(drive, credential)

    def remove_credential(self, drive: str) -> None:
        """删除指定网盘的凭证。"""
        if self._config is None:
            return
        self._config.remove_credential(drive)

    # ------------------------------------------------------------------
    # 配置导出 / 导入
    # ------------------------------------------------------------------

    def export_config(
        self,
        output_path: str,
        password: str | None = None,
        include_tasks: bool = True,
    ) -> str:
        """导出配置到文件。

        Args:
            output_path: 输出文件路径（.yunxcfg）。
            password: 加密密码；None 表示明文导出。
            include_tasks: 是否包含已保存下载任务。

        Returns:
            实际写入的文件路径。

        Raises:
            RuntimeError: 配置管理器未初始化。
        """
        if self._config is None:
            raise RuntimeError("配置管理器未初始化，无法导出")
        from core import export_config as _export_config
        result = _export_config(
            self._config,
            output_path,
            password=password,
            include_tasks=include_tasks,
        )
        return str(result)

    def is_config_encrypted(self, input_path: str) -> bool:
        """检测配置文件是否为加密格式。

        Args:
            input_path: 配置文件路径。

        Returns:
            True 表示加密文件。
        """
        from core import is_encrypted as _is_encrypted
        return _is_encrypted(input_path)

    def import_config(
        self,
        input_path: str,
        password: str | None = None,
        merge: bool = True,
    ) -> dict[str, int]:
        """导入配置文件并应用到当前配置。

        Args:
            input_path: 配置文件路径（.yunxcfg）。
            password: 解密密码；明文文件可省略。
            merge: True=合并模式，False=完全替换。

        Returns:
            包含 credentials / settings / tasks 数量的字典。

        Raises:
            RuntimeError: 配置管理器未初始化。
            AuthenticationError: 加密文件密码错误。
            ValueError: 文件格式不完整。
        """
        if self._config is None:
            raise RuntimeError("配置管理器未初始化，无法导入")
        from core import import_config as _import_config
        from core import apply_imported_config as _apply

        imported_data = _import_config(input_path, password=password)
        _apply(self._config, imported_data, merge=merge)

        # 返回摘要
        return {
            "credentials": len(imported_data.get("credentials", {})),
            "settings": len(imported_data.get("settings", {})),
            "tasks": len(imported_data.get("tasks", [])),
        }

    def get_config_manager(self) -> Any:
        """获取内部 ConfigManager 实例（供高级操作使用）。"""
        return self._config

    # ------------------------------------------------------------------
    # 网盘信息
    # ------------------------------------------------------------------

    @staticmethod
    def supported_drives() -> list[dict[str, Any]]:
        """列出所有支持的网盘。"""
        return list_supported_drives()

    @staticmethod
    def default_download_dir() -> str:
        """返回当前平台的默认下载目录。"""
        return default_download_dir()

    @staticmethod
    def drive_display(drive: str) -> dict[str, str]:
        """获取网盘显示名称和颜色。"""
        return DRIVE_DISPLAY.get(drive, {"name": drive, "color": "#9E9E9E"})

    # ------------------------------------------------------------------
    # 剪贴板
    # ------------------------------------------------------------------

    @staticmethod
    def read_clipboard() -> str:
        """读取系统剪贴板文本。"""
        try:
            return Clipboard.paste() or ""
        except Exception:
            return ""

    @staticmethod
    def detect_in_text(text: str) -> list[ShareURL]:
        """从文本中识别网盘分享链接。"""
        if not text:
            return []
        return detect_share_url(text)

    def detect_from_clipboard(self) -> list[ShareURL]:
        """从剪贴板识别分享链接。"""
        return self.detect_in_text(self.read_clipboard())

    # ------------------------------------------------------------------
    # 解析（子线程）
    # ------------------------------------------------------------------

    def parse_share(
        self,
        url: str,
        extract_code: str | None = None,
        on_success: ParseSuccessCB | None = None,
        on_error: ParseErrorCB | None = None,
        on_baidu_warning: BaiduWarningCB | None = None,
    ) -> None:
        """在子线程中解析网盘分享链接。

        Args:
            url: 分享链接。
            extract_code: 提取码（可选）。
            on_success: 解析成功回调，参数为 ShareInfo。在主线程调用。
            on_error: 解析失败回调，参数为异常。在主线程调用。
            on_baidu_warning: 百度网盘风控警告回调。在主线程调用，
                需返回 True（用户确认）才继续解析；返回 False 则取消。
        """
        if not url or not url.strip():
            self._dispatch_error(on_error, ParserError("请输入分享链接"))
            return

        url = url.strip()
        extract_code = extract_code.strip() if extract_code else None

        thread = threading.Thread(
            target=self._parse_worker,
            args=(url, extract_code, on_success, on_error, on_baidu_warning),
            daemon=True,
            name="yunx-parse",
        )
        thread.start()

    def _parse_worker(
        self,
        url: str,
        extract_code: str | None,
        on_success: ParseSuccessCB | None,
        on_error: ParseErrorCB | None,
        on_baidu_warning: BaiduWarningCB | None,
    ) -> None:
        """解析工作线程。"""
        try:
            # 先匹配解析器以判断网盘类型
            parser = get_parser(url)
            drive = getattr(parser, "drive_name", "")

            # 百度网盘：触发风控警告，需用户确认
            if drive == "baidu" and on_baidu_warning is not None:
                confirmed = self._ask_baidu_confirmation(on_baidu_warning)
                if not confirmed:
                    self._dispatch_error(
                        on_error, BaiduRiskWarning("用户取消百度网盘解析")
                    )
                    return

            # 传入已保存的凭证（如果有）
            credential = self.get_credential(drive)
            if credential:
                parser.credential = credential

            share_info = parser.parse_share_url(url, extract_code=extract_code)
            self._dispatch_success(on_success, share_info)

        except YunXError as exc:
            self._dispatch_error(on_error, exc)
        except Exception as exc:
            self._dispatch_error(on_error, ParserError(f"解析异常: {exc}"))

    def _ask_baidu_confirmation(self, callback: BaiduWarningCB) -> bool:
        """在主线程弹出百度风控警告并等待用户确认。

        使用 threading.Event 阻塞工作线程，直到主线程回调返回结果。
        """
        result_holder: dict[str, bool] = {}
        event = threading.Event()

        def _show(dt: float) -> None:
            try:
                result_holder["confirmed"] = bool(callback())
            except Exception:
                result_holder["confirmed"] = False
            finally:
                event.set()

        Clock.schedule_once(_show, 0)
        event.wait(timeout=300)  # 最多等待 5 分钟
        return result_holder.get("confirmed", False)

    # ------------------------------------------------------------------
    # 下载（子线程 + 任务管理）
    # ------------------------------------------------------------------

    def start_download(
        self,
        share_info: ShareInfo,
        output_dir: str,
        concurrency: int = 8,
        chunk_size: int = 4 * 1024 * 1024,
        on_progress: ProgressCB | None = None,
        on_status: TaskStatusCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> str:
        """启动一个下载任务（在子线程中执行）。

        Args:
            share_info: 解析得到的分享信息（含 direct_url、file_name 等）。
            output_dir: 下载目录。
            concurrency: 并发数（1-32）。
            chunk_size: 分片大小（字节）。
            on_progress: 进度更新回调（主线程）。
            on_status: 状态变更回调（主线程）。
            on_error: 错误回调（主线程）。

        Returns:
            任务 ID（task_id），可用于暂停 / 恢复 / 取消。
        """
        task_id = uuid.uuid4().hex[:12]
        output_path = os.path.join(output_dir, share_info.file_name)

        # 确保输出目录存在
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            self._dispatch_error(on_error, DownloadError(f"无法创建下载目录: {exc}"))
            return task_id

        engine = DownloadEngine(
            concurrency=concurrency,
            chunk_size=chunk_size,
        )

        task = DownloadTask(
            task_id=task_id,
            file_name=share_info.file_name,
            url=share_info.direct_url,
            output_path=output_path,
            total_size=share_info.file_size,
            engine=engine,
            drive=getattr(share_info, "drive", ""),
        )

        with self._tasks_lock:
            self._tasks[task_id] = task

        thread = threading.Thread(
            target=self._download_worker,
            args=(task, share_info, on_progress, on_status, on_error),
            daemon=True,
            name=f"yunx-download-{task_id}",
        )
        task.thread = thread
        thread.start()

        self._dispatch_status(on_status, task, "downloading")
        return task_id

    def _download_worker(
        self,
        task: DownloadTask,
        share_info: ShareInfo,
        on_progress: ProgressCB | None,
        on_status: TaskStatusCB | None,
        on_error: ParseErrorCB | None,
    ) -> None:
        """下载工作线程。"""
        engine = task.engine
        assert engine is not None

        def progress_cb(progress: DownloadProgress) -> None:
            """下载引擎进度回调（在下载子线程中被调用）。

            将进度数据更新到 task，并通过 Clock.schedule_once 调度到主线程。
            """
            task.downloaded = progress.downloaded_bytes
            task.total_size = progress.total_bytes or task.total_size
            task.speed = progress.speed
            task.percent = progress.percent
            if on_progress:
                Clock.schedule_once(lambda dt: on_progress(task), 0)

        try:
            engine.download(
                url=task.url,
                output_path=task.output_path,
                progress_callback=progress_cb,
            )
            task.status = "completed"
            task.percent = 100.0
            task.downloaded = task.total_size
            task.speed = 0.0
            self._dispatch_status(on_status, task, "completed")

        except DownloadError as exc:
            if "已取消" in str(exc) or "cancel" in str(exc).lower():
                task.status = "canceled"
                self._dispatch_status(on_status, task, "canceled")
            else:
                task.status = "error"
                task.error_msg = str(exc)
                self._dispatch_status(on_status, task, "error")
                self._dispatch_error(on_error, exc)
        except Exception as exc:
            task.status = "error"
            task.error_msg = str(exc)
            self._dispatch_status(on_status, task, "error")
            self._dispatch_error(on_error, DownloadError(str(exc)))

    # -- 任务控制 --

    def pause_task(self, task_id: str) -> bool:
        """暂停下载任务。"""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
        if task and task.engine and task.status == "downloading":
            task.engine.pause()
            task.status = "paused"
            return True
        return False

    def resume_task(self, task_id: str) -> bool:
        """恢复下载任务。"""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
        if task and task.engine and task.status == "paused":
            task.engine.resume()
            task.status = "downloading"
            return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        """取消下载任务。"""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
        if task and task.engine:
            task.engine.cancel()
            task.status = "canceled"
            return True
        return False

    def pause_all(self) -> None:
        """暂停所有下载中的任务。"""
        with self._tasks_lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            if task.status == "downloading":
                self.pause_task(task.task_id)

    def resume_all(self) -> None:
        """恢复所有暂停的任务。"""
        with self._tasks_lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            if task.status == "paused":
                self.resume_task(task.task_id)

    def get_task(self, task_id: str) -> DownloadTask | None:
        """获取任务状态。"""
        with self._tasks_lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[DownloadTask]:
        """获取所有下载任务（按创建顺序）。"""
        with self._tasks_lock:
            return list(self._tasks.values())

    def remove_task(self, task_id: str) -> None:
        """从任务列表中移除已完成 / 已取消 / 出错的任务。"""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task and task.status in ("completed", "canceled", "error"):
                del self._tasks[task_id]

    # ------------------------------------------------------------------
    # 视频 / 音乐平台显示
    # ------------------------------------------------------------------

    @staticmethod
    def video_platform_display(platform: str) -> dict[str, str]:
        """获取视频平台显示名称和颜色。"""
        return VIDEO_PLATFORM_DISPLAY.get(
            platform, {"name": platform, "color": "#9E9E9E"}
        )

    @staticmethod
    def music_platform_display(source: str) -> dict[str, str]:
        """获取音乐平台显示名称和颜色。"""
        return MUSIC_PLATFORM_DISPLAY.get(
            source, {"name": source, "color": "#9E9E9E"}
        )

    @staticmethod
    def get_video_quality_options() -> list[str]:
        """获取视频清晰度选项列表。"""
        return list(VIDEO_QUALITY_OPTIONS)

    @staticmethod
    def get_music_quality_options() -> list[str]:
        """获取音乐音质选项列表。"""
        return list(MUSIC_QUALITY_OPTIONS)

    @staticmethod
    def get_music_quality_labels() -> dict[str, str]:
        """获取音乐音质描述映射。"""
        return dict(MUSIC_QUALITY_LABELS)

    @staticmethod
    def format_duration(seconds: int) -> str:
        """将秒数格式化为 mm:ss 或 h:mm:ss。"""
        if seconds <= 0:
            return "00:00"
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    # ------------------------------------------------------------------
    # 视频解析（子线程）
    # ------------------------------------------------------------------

    def parse_video(
        self,
        url: str,
        on_success: VideoParseSuccessCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> None:
        """在子线程中解析视频链接。

        Args:
            url: 视频页面链接。
            on_success: 解析成功回调，参数为 VideoInfo。在主线程调用。
            on_error: 解析失败回调，参数为异常。在主线程调用。
        """
        if not url or not url.strip():
            self._dispatch_error(on_error, ParserError("请输入视频链接"))
            return

        thread = threading.Thread(
            target=self._parse_video_worker,
            args=(url.strip(), on_success, on_error),
            daemon=True,
            name="yunx-video-parse",
        )
        thread.start()

    def _parse_video_worker(
        self,
        url: str,
        on_success: VideoParseSuccessCB | None,
        on_error: ParseErrorCB | None,
    ) -> None:
        """视频解析工作线程。"""
        try:
            from core.video import VideoDownloader
            dl = VideoDownloader(concurrency=8)
            video_info = dl.parse(url)
            self._dispatch_success(on_success, video_info)
        except YunXError as exc:
            self._dispatch_error(on_error, exc)
        except Exception as exc:
            self._dispatch_error(on_error, ParserError(f"视频解析异常: {exc}"))

    # ------------------------------------------------------------------
    # 视频下载（子线程 + 任务管理）
    # ------------------------------------------------------------------

    def download_video(
        self,
        video_info: Any,
        quality: str = "auto",
        output_dir: str | None = None,
        on_progress: ProgressCB | None = None,
        on_status: TaskStatusCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> str:
        """启动视频下载任务（在子线程中执行）。

        Args:
            video_info: parse_video 返回的 VideoInfo。
            quality: 清晰度（1080p/720p/480p/auto）；auto 选择最高清晰度。
            output_dir: 下载目录；None 时使用视频默认目录。
            on_progress: 进度更新回调（主线程）。
            on_status: 状态变更回调（主线程）。
            on_error: 错误回调（主线程）。

        Returns:
            任务 ID。
        """
        if output_dir is None:
            output_dir = self.get_video_download_dir()

        task_id = uuid.uuid4().hex[:12]
        file_name = getattr(video_info, "title", "video") + ".mp4"
        output_path = os.path.join(output_dir, file_name)

        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            self._dispatch_error(on_error, DownloadError(f"无法创建下载目录: {exc}"))
            return task_id

        # 视频下载复用 DownloadTask 结构，drive 字段标记平台
        task = DownloadTask(
            task_id=task_id,
            file_name=file_name,
            url="",
            output_path=output_path,
            total_size=getattr(video_info, "file_size", 0),
            drive=f"video:{getattr(video_info, 'platform', '')}",
        )

        with self._tasks_lock:
            self._tasks[task_id] = task

        thread = threading.Thread(
            target=self._download_video_worker,
            args=(task, video_info, quality, output_dir, on_progress, on_status, on_error),
            daemon=True,
            name=f"yunx-video-dl-{task_id}",
        )
        task.thread = thread
        thread.start()

        self._dispatch_status(on_status, task, "downloading")
        return task_id

    def _download_video_worker(
        self,
        task: DownloadTask,
        video_info: Any,
        quality: str,
        output_dir: str,
        on_progress: ProgressCB | None,
        on_status: TaskStatusCB | None,
        on_error: ParseErrorCB | None,
    ) -> None:
        """视频下载工作线程。"""
        try:
            from core.video import VideoDownloader
            dl = VideoDownloader(concurrency=8)

            def progress_cb(progress: DownloadProgress) -> None:
                task.downloaded = progress.downloaded_bytes
                task.total_size = progress.total_bytes or task.total_size
                task.speed = progress.speed
                task.percent = progress.percent
                if on_progress:
                    Clock.schedule_once(lambda dt: on_progress(task), 0)

            actual_quality = "" if quality == "auto" else quality
            dl.download(
                video_info,
                quality=actual_quality,
                output_dir=output_dir,
                progress_callback=progress_cb,
            )
            task.status = "completed"
            task.percent = 100.0
            task.downloaded = task.total_size
            task.speed = 0.0
            self._dispatch_status(on_status, task, "completed")
        except DownloadError as exc:
            if "已取消" in str(exc) or "cancel" in str(exc).lower():
                task.status = "canceled"
                self._dispatch_status(on_status, task, "canceled")
            else:
                task.status = "error"
                task.error_msg = str(exc)
                self._dispatch_status(on_status, task, "error")
                self._dispatch_error(on_error, exc)
        except Exception as exc:
            task.status = "error"
            task.error_msg = str(exc)
            self._dispatch_status(on_status, task, "error")
            self._dispatch_error(on_error, DownloadError(str(exc)))

    # ------------------------------------------------------------------
    # 音乐解析（子线程）
    # ------------------------------------------------------------------

    def parse_music(
        self,
        url: str,
        on_success: MusicParseSuccessCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> None:
        """在子线程中解析音乐链接（单曲或歌单）。

        自动判断链接类型：单曲返回 SongInfo，歌单/专辑返回 PlaylistInfo。

        Args:
            url: 音乐分享链接。
            on_success: 解析成功回调，参数为 SongInfo 或 PlaylistInfo。
            on_error: 解析失败回调。
        """
        if not url or not url.strip():
            self._dispatch_error(on_error, ParserError("请输入音乐链接"))
            return

        thread = threading.Thread(
            target=self._parse_music_worker,
            args=(url.strip(), on_success, on_error),
            daemon=True,
            name="yunx-music-parse",
        )
        thread.start()

    def _parse_music_worker(
        self,
        url: str,
        on_success: MusicParseSuccessCB | None,
        on_error: ParseErrorCB | None,
    ) -> None:
        """音乐解析工作线程。"""
        try:
            from core.music import MusicDownloader
            dl = MusicDownloader(output_dir=self.get_music_download_dir())

            # 尝试解析为歌单，失败则解析为单曲
            try:
                playlist = dl.parse_playlist(url)
                if playlist and playlist.songs:
                    self._dispatch_success(on_success, playlist)
                    return
            except Exception:
                pass

            song = dl.parse_song(url)
            self._dispatch_success(on_success, song)
        except YunXError as exc:
            self._dispatch_error(on_error, exc)
        except Exception as exc:
            self._dispatch_error(on_error, ParserError(f"音乐解析异常: {exc}"))

    # ------------------------------------------------------------------
    # 音乐下载（子线程 + 任务管理）
    # ------------------------------------------------------------------

    def download_music(
        self,
        url: str,
        quality: str = "higher",
        output_dir: str | None = None,
        on_progress: ProgressCB | None = None,
        on_status: TaskStatusCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> str:
        """启动音乐下载任务（单曲）。

        Args:
            url: 单曲分享链接。
            quality: 音质（standard/higher/lossless）。
            output_dir: 下载目录；None 时使用音乐默认目录。
            on_progress: 进度更新回调。
            on_status: 状态变更回调。
            on_error: 错误回调。

        Returns:
            任务 ID。
        """
        if output_dir is None:
            output_dir = self.get_music_download_dir()

        task_id = uuid.uuid4().hex[:12]
        file_name = "music.mp3"
        output_path = os.path.join(output_dir, file_name)

        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            self._dispatch_error(on_error, DownloadError(f"无法创建下载目录: {exc}"))
            return task_id

        task = DownloadTask(
            task_id=task_id,
            file_name=file_name,
            url=url,
            output_path=output_path,
            drive="music",
        )

        with self._tasks_lock:
            self._tasks[task_id] = task

        thread = threading.Thread(
            target=self._download_music_worker,
            args=(task, url, quality, output_dir, on_progress, on_status, on_error),
            daemon=True,
            name=f"yunx-music-dl-{task_id}",
        )
        task.thread = thread
        thread.start()

        self._dispatch_status(on_status, task, "downloading")
        return task_id

    def _download_music_worker(
        self,
        task: DownloadTask,
        url: str,
        quality: str,
        output_dir: str,
        on_progress: ProgressCB | None,
        on_status: TaskStatusCB | None,
        on_error: ParseErrorCB | None,
    ) -> None:
        """音乐下载工作线程。"""
        try:
            from core.music import MusicDownloader
            embed_tags = self.get_setting("music_embed_id3", True)
            download_cover = self.get_setting("music_download_cover", True)

            dl = MusicDownloader(
                output_dir=output_dir,
                embed_tags=embed_tags,
                download_cover=download_cover,
            )

            def progress_cb(progress: DownloadProgress) -> None:
                task.downloaded = progress.downloaded_bytes
                task.total_size = progress.total_bytes or task.total_size
                task.speed = progress.speed
                task.percent = progress.percent
                if on_progress:
                    Clock.schedule_once(lambda dt: on_progress(task), 0)

            path = dl.download_song(url, quality=quality, progress_callback=progress_cb)
            # 更新实际文件名
            task.file_name = os.path.basename(str(path))
            task.output_path = str(path)
            task.status = "completed"
            task.percent = 100.0
            task.downloaded = task.total_size
            task.speed = 0.0
            self._dispatch_status(on_status, task, "completed")
        except DownloadError as exc:
            task.status = "error"
            task.error_msg = str(exc)
            self._dispatch_status(on_status, task, "error")
            self._dispatch_error(on_error, exc)
        except Exception as exc:
            task.status = "error"
            task.error_msg = str(exc)
            self._dispatch_status(on_status, task, "error")
            self._dispatch_error(on_error, DownloadError(str(exc)))

    def download_music_playlist(
        self,
        playlist_url: str,
        quality: str = "higher",
        output_dir: str | None = None,
        on_progress: ProgressCB | None = None,
        on_status: TaskStatusCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> list[str]:
        """批量下载歌单中的所有歌曲。

        为每首歌创建独立的下载任务。

        Returns:
            任务 ID 列表。
        """
        if output_dir is None:
            output_dir = self.get_music_download_dir()

        task_ids: list[str] = []
        try:
            from core.music import MusicDownloader
            dl = MusicDownloader(output_dir=output_dir)
            playlist = dl.parse_playlist(playlist_url)
            for song in playlist.songs:
                if song.copyright_restricted:
                    continue
                # 构建单曲 URL（使用 song_id 构造）
                song_url = self._build_song_url(song, playlist.source)
                tid = self.download_music(
                    url=song_url,
                    quality=quality,
                    output_dir=output_dir,
                    on_progress=on_progress,
                    on_status=on_status,
                    on_error=on_error,
                )
                task_ids.append(tid)
        except Exception as exc:
            self._dispatch_error(on_error, DownloadError(f"歌单下载失败: {exc}"))
        return task_ids

    @staticmethod
    def _build_song_url(song: Any, source: str) -> str:
        """根据 SongInfo 和来源平台构建可解析的单曲链接。"""
        sid = getattr(song, "song_id", "")
        if source == "netease":
            return f"https://music.163.com/#/song?id={sid}"
        if source == "qqmusic":
            return f"https://y.qq.com/n/ryqq/songDetail/{sid}"
        return getattr(song, "url", "") or str(sid)

    # ------------------------------------------------------------------
    # 云盘上传（子线程 + 任务管理）
    # ------------------------------------------------------------------

    def get_remote_dirs(
        self,
        drive_name: str,
        parent_dir: str | None = None,
        on_success: RemoteDirsCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> None:
        """在子线程中获取远程目录列表。

        Args:
            drive_name: 网盘标识。
            parent_dir: 父目录 ID；None 表示根目录。
            on_success: 成功回调，参数为 DirInfo 列表。
            on_error: 失败回调。
        """
        credential = self.get_credential(drive_name)
        if not credential:
            self._dispatch_error(on_error, UploadError(f"未登录 {drive_name} 账号"))
            return

        thread = threading.Thread(
            target=self._remote_dirs_worker,
            args=(drive_name, credential, parent_dir, on_success, on_error),
            daemon=True,
            name="yunx-remote-dirs",
        )
        thread.start()

    def _remote_dirs_worker(
        self,
        drive_name: str,
        credential: dict[str, Any],
        parent_dir: str | None,
        on_success: RemoteDirsCB | None,
        on_error: ParseErrorCB | None,
    ) -> None:
        """远程目录获取工作线程。"""
        try:
            from core.uploader import get_uploader
            uploader = get_uploader(drive_name, credential=credential)
            dirs = uploader.get_remote_dirs(parent_dir=parent_dir)
            if on_success:
                Clock.schedule_once(lambda dt: on_success(dirs), 0)
        except YunXError as exc:
            self._dispatch_error(on_error, exc)
        except Exception as exc:
            self._dispatch_error(on_error, UploadError(f"获取目录失败: {exc}"))

    def upload_to_cloud(
        self,
        file_path: str,
        drive_name: str,
        remote_dir: str = "",
        on_progress: UploadProgressCB | None = None,
        on_status: UploadStatusCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> str:
        """启动云盘上传任务（在子线程中执行）。

        Args:
            file_path: 本地文件路径。
            drive_name: 网盘标识。
            remote_dir: 远程目标目录 ID。
            on_progress: 进度更新回调（主线程）。
            on_status: 状态变更回调（主线程）。
            on_error: 错误回调（主线程）。

        Returns:
            上传任务 ID。
        """
        credential = self.get_credential(drive_name)
        if not credential:
            self._dispatch_error(on_error, UploadError(f"未登录 {drive_name} 账号"))
            return ""

        if not os.path.exists(file_path):
            self._dispatch_error(on_error, UploadError(f"文件不存在: {file_path}"))
            return ""

        task_id = uuid.uuid4().hex[:12]
        file_name = os.path.basename(file_path)
        total_size = os.path.getsize(file_path)

        engine = UploadEngine(concurrency=4)

        task = UploadTask(
            task_id=task_id,
            file_path=file_path,
            file_name=file_name,
            drive=drive_name,
            remote_dir=remote_dir,
            total_size=total_size,
            engine=engine,
        )

        with self._upload_tasks_lock:
            self._upload_tasks[task_id] = task

        thread = threading.Thread(
            target=self._upload_worker,
            args=(task, drive_name, credential, remote_dir, on_progress, on_status, on_error),
            daemon=True,
            name=f"yunx-upload-{task_id}",
        )
        task.thread = thread
        thread.start()

        self._dispatch_upload_status(on_status, task, "uploading")
        return task_id

    def _upload_worker(
        self,
        task: UploadTask,
        drive_name: str,
        credential: dict[str, Any],
        remote_dir: str,
        on_progress: UploadProgressCB | None,
        on_status: UploadStatusCB | None,
        on_error: ParseErrorCB | None,
    ) -> None:
        """上传工作线程。"""
        try:
            from core.uploader import get_uploader
            uploader = get_uploader(drive_name, credential=credential)
            assert task.engine is not None

            def progress_cb(
                uploaded: int, total: int, speed: float, percent: float
            ) -> None:
                task.uploaded = uploaded
                task.total_size = total or task.total_size
                task.speed = speed
                task.percent = percent
                if on_progress:
                    Clock.schedule_once(lambda dt: on_progress(task), 0)

            result = task.engine.upload_file(
                file_path=task.file_path,
                remote_dir=remote_dir,
                uploader=uploader,
                progress_callback=progress_cb,
            )
            task.result = result
            task.status = "completed"
            task.percent = 100.0
            task.uploaded = task.total_size
            task.speed = 0.0
            self._dispatch_upload_status(on_status, task, "completed")
        except UploadError as exc:
            if "取消" in str(exc) or "cancel" in str(exc).lower():
                task.status = "canceled"
                self._dispatch_upload_status(on_status, task, "canceled")
            else:
                task.status = "error"
                task.error_msg = str(exc)
                self._dispatch_upload_status(on_status, task, "error")
                self._dispatch_error(on_error, exc)
        except Exception as exc:
            task.status = "error"
            task.error_msg = str(exc)
            self._dispatch_upload_status(on_status, task, "error")
            self._dispatch_error(on_error, UploadError(str(exc)))

    def create_share_link(
        self,
        drive_name: str,
        file_id: str,
        on_success: ShareLinkCB | None = None,
        on_error: ParseErrorCB | None = None,
    ) -> None:
        """在子线程中为已上传文件生成分享链接。

        Args:
            drive_name: 网盘标识。
            file_id: 文件 ID（来自 UploadResult.file_id）。
            on_success: 成功回调，参数为 ShareInfo。
            on_error: 失败回调。
        """
        credential = self.get_credential(drive_name)
        if not credential:
            self._dispatch_error(on_error, UploadError(f"未登录 {drive_name} 账号"))
            return

        thread = threading.Thread(
            target=self._share_link_worker,
            args=(drive_name, credential, file_id, on_success, on_error),
            daemon=True,
            name="yunx-share-link",
        )
        thread.start()

    def _share_link_worker(
        self,
        drive_name: str,
        credential: dict[str, Any],
        file_id: str,
        on_success: ShareLinkCB | None,
        on_error: ParseErrorCB | None,
    ) -> None:
        """分享链接生成工作线程。"""
        try:
            from core.uploader import get_uploader
            uploader = get_uploader(drive_name, credential=credential)
            share = uploader.create_share_link(file_id)
            if on_success:
                Clock.schedule_once(lambda dt: on_success(share), 0)
        except YunXError as exc:
            self._dispatch_error(on_error, exc)
        except Exception as exc:
            self._dispatch_error(on_error, UploadError(f"生成分享链接失败: {exc}"))

    # -- 上传任务控制 --

    def get_upload_task(self, task_id: str) -> UploadTask | None:
        """获取上传任务状态。"""
        with self._upload_tasks_lock:
            return self._upload_tasks.get(task_id)

    def get_all_upload_tasks(self) -> list[UploadTask]:
        """获取所有上传任务。"""
        with self._upload_tasks_lock:
            return list(self._upload_tasks.values())

    def cancel_upload_task(self, task_id: str) -> bool:
        """取消上传任务。"""
        with self._upload_tasks_lock:
            task = self._upload_tasks.get(task_id)
        if task and task.engine:
            task.engine.cancel()
            task.status = "canceled"
            return True
        return False

    def remove_upload_task(self, task_id: str) -> None:
        """从列表中移除已完成/出错/取消的上传任务。"""
        with self._upload_tasks_lock:
            task = self._upload_tasks.get(task_id)
            if task and task.status in ("completed", "canceled", "error"):
                del self._upload_tasks[task_id]

    # ------------------------------------------------------------------
    # 视频 / 音乐设置
    # ------------------------------------------------------------------

    def get_video_default_quality(self) -> str:
        """获取视频默认清晰度。"""
        return self.get_setting("video_default_quality", "1080p")

    def set_video_default_quality(self, quality: str) -> None:
        """设置视频默认清晰度。"""
        self.set_setting("video_default_quality", quality)

    def get_video_download_dir(self) -> str:
        """获取视频下载目录。"""
        default = os.path.join(default_download_dir(), "videos")
        return self.get_setting("video_download_dir", default)

    def set_video_download_dir(self, path: str) -> None:
        """设置视频下载目录。"""
        self.set_setting("video_download_dir", path)

    def get_music_default_quality(self) -> str:
        """获取音乐默认音质。"""
        return self.get_setting("music_default_quality", "higher")

    def set_music_default_quality(self, quality: str) -> None:
        """设置音乐默认音质。"""
        self.set_setting("music_default_quality", quality)

    def get_music_download_dir(self) -> str:
        """获取音乐下载目录。"""
        default = os.path.join(default_download_dir(), "music")
        return self.get_setting("music_download_dir", default)

    def set_music_download_dir(self, path: str) -> None:
        """设置音乐下载目录。"""
        self.set_setting("music_download_dir", path)

    def get_music_embed_id3(self) -> bool:
        """获取是否自动嵌入 ID3 标签。"""
        return bool(self.get_setting("music_embed_id3", True))

    def set_music_embed_id3(self, value: bool) -> None:
        """设置是否自动嵌入 ID3 标签。"""
        self.set_setting("music_embed_id3", value)

    def get_music_download_cover(self) -> bool:
        """获取是否自动下载封面。"""
        return bool(self.get_setting("music_download_cover", True))

    def set_music_download_cover(self, value: bool) -> None:
        """设置是否自动下载封面。"""
        self.set_setting("music_download_cover", value)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """将字节数格式化为人类可读字符串。"""
        if size_bytes <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        size = float(size_bytes)
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024
            idx += 1
        return f"{size:.1f} {units[idx]}"

    @staticmethod
    def format_speed(speed_bytes: float) -> str:
        """将速度（字节/秒）格式化为人类可读字符串。"""
        if speed_bytes <= 0:
            return "0 B/s"
        return f"{CoreAdapter.format_size(int(speed_bytes))}/s"

    # ------------------------------------------------------------------
    # 内部：主线程调度
    # ------------------------------------------------------------------

    @staticmethod
    def _dispatch_success(callback: ParseSuccessCB | None, result: ShareInfo) -> None:
        """在主线程调用成功回调。"""
        if callback:
            Clock.schedule_once(lambda dt: callback(result), 0)

    @staticmethod
    def _dispatch_error(callback: ParseErrorCB | None, error: Exception) -> None:
        """在主线程调用错误回调。"""
        if callback:
            Clock.schedule_once(lambda dt: callback(error), 0)

    @staticmethod
    def _dispatch_status(
        callback: TaskStatusCB | None, task: DownloadTask, status: str
    ) -> None:
        """在主线程调用状态变更回调。"""
        task.status = status
        if callback:
            Clock.schedule_once(lambda dt: callback(task), 0)

    @staticmethod
    def _dispatch_upload_status(
        callback: UploadStatusCB | None, task: "UploadTask", status: str
    ) -> None:
        """在主线程调用上传状态变更回调。"""
        task.status = status
        if callback:
            Clock.schedule_once(lambda dt: callback(task), 0)
