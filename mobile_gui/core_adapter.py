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
from core.clipboard import ShareURL, detect_share_url
from core.config import ConfigManager
from core.downloader.engine import DownloadEngine
from core.downloader.progress import DownloadProgress
from core.parsers.base import ShareInfo, get_parser, list_supported_drives


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
