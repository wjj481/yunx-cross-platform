"""
上传器单元测试（mock HTTP）。

使用 unittest.mock 模拟 requests 响应，测试：
- 工厂函数 drive_name 匹配 / 未知 drive_name 异常
- UploadTask 数据类
- 分片构建（不同文件大小 / 分片大小）
- 断点续传元数据持久化（写入→读取→验证）
- 进度追踪（百分比 / 速度计算）
- 上传引擎配置（并发数截断 / 分片大小最小值）
- 远程目录列表（mock）
- 分享链接生成（mock）
- 暂停 / 恢复 / 取消事件控制
- 错误处理（网络错误 / 空间不足 / 凭证失效）
- 百度网盘风控警告
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from core.exceptions import (
    AuthenticationError,
    BaiduRiskWarning,
    NetworkError,
    QuotaExceededError,
    UploadError,
    YunXError,
)
from core.uploader.base import (
    BaseUploader,
    DirInfo,
    ShareInfo,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_UPLOADING,
    UploadResult,
    UploadTask,
    get_uploader,
    list_supported_upload_drives,
)
from core.uploader.engine import (
    DEFAULT_CHUNK_SIZE,
    MAX_CONCURRENCY,
    UploadChunkInfo,
    UploadEngine,
    UploadMetadata,
)
from core.uploader.quark_uploader import QuarkUploader
from core.uploader.pan123_uploader import Pan123Uploader, _make_sign as pan123_make_sign
from core.uploader.baidu_uploader import BaiduUploader
from core.uploader.xunlei_uploader import XunleiUploader, _build_captcha_sign


# ============================================================
# 1. 工厂函数测试
# ============================================================

class TestFactory:
    """工厂函数 get_uploader 测试。"""

    def test_quark_matching(self):
        """drive_name='quark' 应返回 QuarkUploader 实例。"""
        uploader = get_uploader("quark")
        assert isinstance(uploader, QuarkUploader)
        assert uploader.drive_name == "quark"

    def test_pan123_matching(self):
        """drive_name='pan123' 应返回 Pan123Uploader 实例。"""
        uploader = get_uploader("pan123")
        assert isinstance(uploader, Pan123Uploader)
        assert uploader.drive_name == "pan123"

    def test_baidu_matching(self):
        """drive_name='baidu' 应返回 BaiduUploader 实例。"""
        uploader = get_uploader("baidu")
        assert isinstance(uploader, BaiduUploader)
        assert uploader.drive_name == "baidu"

    def test_xunlei_matching(self):
        """drive_name='xunlei' 应返回 XunleiUploader 实例。"""
        uploader = get_uploader("xunlei")
        assert isinstance(uploader, XunleiUploader)
        assert uploader.drive_name == "xunlei"

    def test_case_insensitive(self):
        """drive_name 大小写不敏感。"""
        uploader = get_uploader("QUARK")
        assert isinstance(uploader, QuarkUploader)

    def test_whitespace_trimmed(self):
        """drive_name 前后空白应被去除。"""
        uploader = get_uploader("  quark  ")
        assert isinstance(uploader, QuarkUploader)

    def test_unknown_drive_raises(self):
        """未知 drive_name 应抛出 UploadError。"""
        with pytest.raises(UploadError, match="不支持的网盘标识"):
            get_uploader("unknown_drive")

    def test_credential_passed_through(self):
        """credential 应传递给上传器实例。"""
        cred = {"cookie": "test_cookie"}
        uploader = get_uploader("quark", credential=cred)
        assert uploader.credential == cred

    def test_list_supported_drives(self):
        """list_supported_upload_drives 应返回所有支持的网盘。"""
        drives = list_supported_upload_drives()
        drive_names = [d["drive"] for d in drives]
        assert "quark" in drive_names
        assert "pan123" in drive_names
        assert "baidu" in drive_names
        assert "xunlei" in drive_names
        # 百度应为 experimental
        baidu = next(d for d in drives if d["drive"] == "baidu")
        assert baidu["status"] == "experimental"


# ============================================================
# 2. UploadTask 数据类测试
# ============================================================

class TestUploadTask:
    """UploadTask 数据类测试。"""

    def test_default_values(self):
        """UploadTask 默认值应正确。"""
        task = UploadTask(file_path="/tmp/test.zip", remote_path="/test.zip")
        assert task.total_bytes == 0
        assert task.uploaded_bytes == 0
        assert task.speed == 0.0
        assert task.status == STATUS_PENDING

    def test_custom_values(self):
        """UploadTask 自定义值应正确。"""
        task = UploadTask(
            file_path="/tmp/test.zip",
            remote_path="/test.zip",
            total_bytes=1024,
            uploaded_bytes=512,
            speed=100.5,
            status=STATUS_UPLOADING,
        )
        assert task.total_bytes == 1024
        assert task.uploaded_bytes == 512
        assert task.speed == 100.5
        assert task.status == STATUS_UPLOADING

    def test_percent_calculation(self):
        """可从 UploadTask 字段计算百分比。"""
        task = UploadTask(
            file_path="/tmp/test.zip",
            remote_path="/test.zip",
            total_bytes=1000,
            uploaded_bytes=250,
        )
        percent = task.uploaded_bytes / task.total_bytes * 100.0
        assert percent == 25.0


# ============================================================
# 3. 分片构建测试
# ============================================================

class TestChunkBuilding:
    """上传引擎分片构建测试。"""

    def test_exact_chunks(self):
        """文件大小恰好是分片整数倍。"""
        chunk = 64 * 1024
        engine = UploadEngine(chunk_size=chunk)
        chunks = engine._build_chunks(chunk * 4)
        assert len(chunks) == 4
        assert chunks[0].start == 0
        assert chunks[0].end == chunk - 1
        assert chunks[-1].end == chunk * 4 - 1

    def test_partial_last_chunk(self):
        """最后一个分片不足完整大小。"""
        chunk = 64 * 1024
        engine = UploadEngine(chunk_size=chunk)
        total = chunk + 1000
        chunks = engine._build_chunks(total)
        assert len(chunks) == 2
        assert chunks[1].start == chunk
        assert chunks[1].end == total - 1

    def test_single_chunk(self):
        """文件小于分片大小。"""
        engine = UploadEngine(chunk_size=128 * 1024)
        chunks = engine._build_chunks(1024)
        assert len(chunks) == 1
        assert chunks[0].start == 0
        assert chunks[0].end == 1023

    def test_zero_size(self):
        """零字节文件应返回一个分片。"""
        engine = UploadEngine()
        chunks = engine._build_chunks(0)
        assert len(chunks) == 1
        assert chunks[0].start == 0
        assert chunks[0].end == 0

    def test_large_file_many_chunks(self):
        """大文件应生成多个分片。"""
        chunk = 4 * 1024 * 1024  # 4MB
        engine = UploadEngine(chunk_size=chunk)
        total = 50 * 1024 * 1024  # 50MB
        chunks = engine._build_chunks(total)
        assert len(chunks) == 13  # 12 full + 1 partial
        assert chunks[-1].end == total - 1

    def test_chunk_indexes_sequential(self):
        """分片序号应从 0 开始连续递增。"""
        engine = UploadEngine(chunk_size=1024)
        chunks = engine._build_chunks(5000)
        for i, c in enumerate(chunks):
            assert c.index == i


# ============================================================
# 4. 元数据持久化测试
# ============================================================

class TestMetadataPersistence:
    """上传元数据持久化测试。"""

    def test_metadata_roundtrip(self):
        """元数据序列化/反序列化应一致。"""
        meta = UploadMetadata(
            file_path="/tmp/file.zip",
            remote_path="/file.zip",
            total_size=100000,
            chunk_size=4096,
            drive_name="quark",
            chunks=[
                UploadChunkInfo(index=0, start=0, end=4095, uploaded=True,
                                result={"etag": "abc123"}),
                UploadChunkInfo(index=1, start=4096, end=8191, uploaded=False),
            ],
            upload_context={"upload_token": "token123", "upload_url": "https://oss.example.com"},
        )
        data = meta.to_dict()
        restored = UploadMetadata.from_dict(data)
        assert restored.file_path == meta.file_path
        assert restored.remote_path == meta.remote_path
        assert restored.total_size == meta.total_size
        assert restored.chunk_size == meta.chunk_size
        assert restored.drive_name == meta.drive_name
        assert len(restored.chunks) == 2
        assert restored.chunks[0].uploaded is True
        assert restored.chunks[0].result == {"etag": "abc123"}
        assert restored.chunks[1].uploaded is False
        assert restored.upload_context == {"upload_token": "token123", "upload_url": "https://oss.example.com"}

    def test_metadata_save_and_load(self):
        """元数据写入文件→读取→验证应一致。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.zip"
            file_path.write_bytes(b"x" * 1000)

            meta = UploadMetadata(
                file_path=str(file_path),
                remote_path="/test.zip",
                total_size=1000,
                chunk_size=512,
                drive_name="quark",
                chunks=[
                    UploadChunkInfo(index=0, start=0, end=511, uploaded=True),
                    UploadChunkInfo(index=1, start=512, end=999, uploaded=False),
                ],
                upload_context={"upload_token": "tok"},
            )

            engine = UploadEngine()
            engine._meta = meta
            engine._save_metadata()

            meta_path = file_path.parent / f"{file_path.name}.yunx_upload.json"
            assert meta_path.exists()

            loaded = engine._load_metadata(meta_path)
            assert loaded.file_path == str(file_path)
            assert loaded.total_size == 1000
            assert len(loaded.chunks) == 2
            assert loaded.chunks[0].uploaded is True
            assert loaded.chunks[1].uploaded is False
            assert loaded.upload_context == {"upload_token": "tok"}

    def test_metadata_cleanup(self):
        """清理应删除元数据文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.zip"
            file_path.write_bytes(b"x" * 100)

            meta = UploadMetadata(
                file_path=str(file_path),
                remote_path="/test.zip",
                total_size=100,
                chunk_size=1024,
                drive_name="quark",
                chunks=[UploadChunkInfo(index=0, start=0, end=99, uploaded=True)],
                upload_context={},
            )
            engine = UploadEngine()
            engine._meta = meta
            engine._save_metadata()

            meta_path = file_path.parent / f"{file_path.name}.yunx_upload.json"
            assert meta_path.exists()

            engine._cleanup(file_path)
            assert not meta_path.exists()
            assert engine._meta is None


# ============================================================
# 5. 进度追踪测试
# ============================================================

class TestProgressTracking:
    """上传进度追踪测试（通过引擎回调验证）。"""

    def test_progress_callback_invoked(self):
        """上传过程中应触发进度回调。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_size = 256 * 1024  # 256KB，确保至少 2 个 64KB 分片
            file_path = Path(tmpdir) / "small.bin"
            file_path.write_bytes(b"x" * file_size)

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.supports_chunked_upload.return_value = True
            mock_uploader.init_upload.return_value = {
                "upload_token": "tok",
                "upload_url": "https://oss.example.com/upload",
                "instant_upload": False,
            }
            mock_uploader.upload_chunk.return_value = {"etag": "abc", "part_number": 1}
            mock_uploader.complete_upload.return_value = UploadResult(
                file_id="fid123",
                file_name="small.bin",
                file_size=file_size,
                remote_path="/small.bin",
                drive="quark",
            )

            progress_calls = []
            engine = UploadEngine(chunk_size=64 * 1024, concurrency=1)
            result = engine.upload_file(
                file_path=str(file_path),
                remote_dir="/",
                uploader=mock_uploader,
                progress_callback=lambda u, t, s, p: progress_calls.append((u, t, s, p)),
            )

            assert len(progress_calls) >= 2  # 至少每个分片一次
            # 最后一次回调应为 100%
            last = progress_calls[-1]
            assert last[0] == file_size  # uploaded
            assert last[1] == file_size  # total
            assert last[3] == 100.0  # percent

    def test_progress_percent_accumulates(self):
        """进度百分比应随上传递增。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_size = 256 * 1024  # 256KB → 4 个 64KB 分片
            file_path = Path(tmpdir) / "multi.bin"
            file_path.write_bytes(b"y" * file_size)

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.supports_chunked_upload.return_value = True
            mock_uploader.init_upload.return_value = {
                "upload_token": "tok",
                "upload_url": "https://oss.example.com/upload",
                "instant_upload": False,
            }
            mock_uploader.upload_chunk.return_value = {"etag": "e", "part_number": 1}
            mock_uploader.complete_upload.return_value = UploadResult(
                file_id="fid", file_name="multi.bin", file_size=file_size,
                remote_path="/multi.bin", drive="quark",
            )

            percents = []
            engine = UploadEngine(chunk_size=64 * 1024, concurrency=1)
            engine.upload_file(
                file_path=str(file_path),
                remote_dir="/",
                uploader=mock_uploader,
                progress_callback=lambda u, t, s, p: percents.append(p),
            )

            # 百分比应递增
            for i in range(1, len(percents)):
                assert percents[i] >= percents[i - 1]
            assert percents[-1] == 100.0

    def test_speed_is_non_negative(self):
        """速度值应为非负数。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "speed.bin"
            file_path.write_bytes(b"z" * 1024)

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.supports_chunked_upload.return_value = True
            mock_uploader.init_upload.return_value = {
                "upload_token": "tok", "upload_url": "https://oss.example.com",
                "instant_upload": False,
            }
            mock_uploader.upload_chunk.return_value = {"etag": "e", "part_number": 1}
            mock_uploader.complete_upload.return_value = UploadResult(
                file_id="fid", file_name="speed.bin", file_size=1024,
                remote_path="/speed.bin", drive="quark",
            )

            speeds = []
            engine = UploadEngine(chunk_size=512, concurrency=1)
            engine.upload_file(
                file_path=str(file_path),
                remote_dir="/",
                uploader=mock_uploader,
                progress_callback=lambda u, t, s, p: speeds.append(s),
            )
            for speed in speeds:
                assert speed >= 0.0


# ============================================================
# 6. 上传引擎配置测试
# ============================================================

class TestUploadEngineConfig:
    """上传引擎配置测试。"""

    def test_concurrency_capped(self):
        """并发数超过上限应被截断。"""
        engine = UploadEngine(concurrency=100)
        assert engine.concurrency == MAX_CONCURRENCY

    def test_concurrency_minimum(self):
        """并发数低于 1 应被提升到 1。"""
        engine = UploadEngine(concurrency=0)
        assert engine.concurrency == 1

    def test_concurrency_negative(self):
        """负数并发数应被提升到 1。"""
        engine = UploadEngine(concurrency=-5)
        assert engine.concurrency == 1

    def test_chunk_size_minimum(self):
        """分片大小低于 64KB 应被提升。"""
        engine = UploadEngine(chunk_size=1024)
        assert engine.chunk_size == 64 * 1024

    def test_default_chunk_size(self):
        """默认分片大小应为 4MB。"""
        engine = UploadEngine()
        assert engine.chunk_size == DEFAULT_CHUNK_SIZE

    def test_default_concurrency(self):
        """默认并发数应为 4。"""
        engine = UploadEngine()
        assert engine.concurrency == 4


# ============================================================
# 7. 远程目录列表测试（mock）
# ============================================================

class TestRemoteDirs:
    """远程目录列表获取测试（mock）。"""

    def _make_response(self, status_code=200, json_data=None, headers=None):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.headers = headers or {}
        resp.text = json.dumps(json_data or {})
        return resp

    @patch("core.uploader.quark_uploader.requests.Session")
    def test_quark_get_remote_dirs(self, mock_session_cls):
        """夸克网盘获取远程目录列表应正确解析。"""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        api_resp = self._make_response(json_data={
            "status": 200,
            "data": {
                "list": [
                    {"fid": "dir1", "file_name": "文档", "dir": True},
                    {"fid": "file1", "file_name": "readme.txt", "dir": False},
                    {"fid": "dir2", "file_name": "图片", "dir": True},
                ]
            },
        })
        mock_session.request.return_value = api_resp

        uploader = QuarkUploader(credential={"cookie": "__pus=test"})
        uploader._session = mock_session
        dirs = uploader.get_remote_dirs()

        assert len(dirs) == 2
        assert dirs[0].dir_name == "文档"
        assert dirs[0].dir_id == "dir1"
        assert dirs[1].dir_name == "图片"
        assert all(isinstance(d, DirInfo) for d in dirs)

    @patch("core.uploader.pan123_uploader.requests.Session")
    def test_pan123_get_remote_dirs(self, mock_session_cls):
        """123 云盘获取远程目录列表应正确解析。"""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        api_resp = self._make_response(json_data={
            "code": 0,
            "data": {
                "InfoList": [
                    {"FileId": 101, "FileName": "视频", "Type": 1},
                    {"FileId": 102, "FileName": "song.mp3", "Type": 0},
                    {"FileId": 103, "FileName": "备份", "Type": 1},
                ]
            },
        })
        mock_session.request.return_value = api_resp

        uploader = Pan123Uploader(credential={"access_token": "test_token"})
        uploader._session = mock_session
        dirs = uploader.get_remote_dirs()

        assert len(dirs) == 2
        assert dirs[0].dir_name == "视频"
        assert dirs[1].dir_name == "备份"


# ============================================================
# 8. 分享链接生成测试（mock）
# ============================================================

class TestShareLink:
    """分享链接生成测试（mock）。"""

    def _make_response(self, status_code=200, json_data=None):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.text = json.dumps(json_data or {})
        return resp

    @patch("core.uploader.quark_uploader.requests.Session")
    def test_quark_create_share_link(self, mock_session_cls):
        """夸克网盘生成分享链接应正确解析。"""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        api_resp = self._make_response(json_data={
            "status": 200,
            "data": {"share_id": "abc123", "passcode": "1234"},
        })
        mock_session.request.return_value = api_resp

        uploader = QuarkUploader(credential={"cookie": "__pus=test"})
        uploader._session = mock_session
        share = uploader.create_share_link("fid_test")

        assert isinstance(share, ShareInfo)
        assert share.share_id == "abc123"
        assert share.extract_code == "1234"
        assert "abc123" in share.share_url
        assert share.drive == "quark"

    @patch("core.uploader.pan123_uploader.requests.Session")
    def test_pan123_create_share_link(self, mock_session_cls):
        """123 云盘生成分享链接应正确解析。"""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        api_resp = self._make_response(json_data={
            "code": 0,
            "data": {"ShareKey": "xyz789", "SharePwd": "5678"},
        })
        mock_session.request.return_value = api_resp

        uploader = Pan123Uploader(credential={"access_token": "test"})
        uploader._session = mock_session
        share = uploader.create_share_link("123")

        assert share.share_id == "xyz789"
        assert share.extract_code == "5678"
        assert "xyz789" in share.share_url


# ============================================================
# 9. 暂停/恢复/取消事件控制测试
# ============================================================

class TestPauseResumeCancel:
    """暂停/恢复/取消事件控制测试。"""

    def test_pause_event_initial_state(self):
        """初始状态下暂停事件应为 set（运行中）。"""
        engine = UploadEngine()
        assert engine._pause_event.is_set() is True
        assert engine._cancel_event.is_set() is False

    def test_pause_sets_event(self):
        """调用 pause() 应清除暂停事件。"""
        engine = UploadEngine()
        engine.pause()
        assert engine._pause_event.is_set() is False

    def test_resume_sets_event(self):
        """调用 resume() 应设置暂停事件。"""
        engine = UploadEngine()
        engine.pause()
        engine.resume()
        assert engine._pause_event.is_set() is True

    def test_cancel_sets_events(self):
        """调用 cancel() 应设置取消事件并解除暂停。"""
        engine = UploadEngine()
        engine.pause()
        engine.cancel()
        assert engine._cancel_event.is_set() is True
        assert engine._pause_event.is_set() is True

    def test_check_pause_and_cancel_no_block(self):
        """运行状态下 _check_pause_and_cancel 不应阻塞或抛异常。"""
        engine = UploadEngine()
        engine._check_pause_and_cancel()  # 不应抛异常

    def test_cancel_raises_upload_error(self):
        """取消状态下 _check_pause_and_cancel 应抛出 UploadError。"""
        engine = UploadEngine()
        engine.cancel()
        with pytest.raises(UploadError, match="上传已取消"):
            engine._check_pause_and_cancel()

    def test_pause_blocks_then_resume(self):
        """暂停时 _check_pause_and_cancel 应阻塞，恢复后继续。"""
        engine = UploadEngine()
        engine.pause()

        result = {"passed": False}

        def worker():
            engine._check_pause_and_cancel()
            result["passed"] = True

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.2)
        assert result["passed"] is False  # 仍在阻塞
        engine.resume()
        t.join(timeout=2)
        assert result["passed"] is True

    def test_task_status_on_pause(self):
        """暂停时上传中任务状态应变为 paused。"""
        engine = UploadEngine()
        task = UploadTask(
            file_path="/tmp/test.zip",
            remote_path="/test.zip",
            total_bytes=100,
            uploaded_bytes=50,
            status=STATUS_UPLOADING,
        )
        engine._register_task(task)
        engine.pause()
        assert engine.get_task("/tmp/test.zip").status == "paused"

    def test_task_status_on_cancel(self):
        """取消时任务状态应变为 cancelled。"""
        engine = UploadEngine()
        task = UploadTask(
            file_path="/tmp/test.zip",
            remote_path="/test.zip",
            status=STATUS_UPLOADING,
        )
        engine._register_task(task)
        engine.cancel()
        assert engine.get_task("/tmp/test.zip").status == STATUS_CANCELLED


# ============================================================
# 10. 错误处理测试
# ============================================================

class TestErrorHandling:
    """错误处理测试（网络错误 / 空间不足 / 凭证失效）。"""

    def test_upload_nonexistent_file(self):
        """上传不存在的文件应抛出 UploadError。"""
        engine = UploadEngine()
        mock_uploader = MagicMock(spec=BaseUploader)
        with pytest.raises(UploadError, match="文件不存在"):
            engine.upload_file(
                file_path="/nonexistent/path/file.zip",
                remote_dir="/",
                uploader=mock_uploader,
            )

    def test_upload_directory_raises(self):
        """上传目录（非文件）应抛出 UploadError。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = UploadEngine()
            mock_uploader = MagicMock(spec=BaseUploader)
            with pytest.raises(UploadError, match="不是文件"):
                engine.upload_file(
                    file_path=tmpdir,
                    remote_dir="/",
                    uploader=mock_uploader,
                )

    def test_network_error_retries_then_fails(self):
        """网络错误应自动重试，超过次数后抛出 UploadError。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "net.bin"
            file_path.write_bytes(b"x" * 1024)

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.supports_chunked_upload.return_value = True
            mock_uploader.init_upload.return_value = {
                "upload_token": "tok", "upload_url": "https://oss.example.com",
                "instant_upload": False,
            }
            mock_uploader.upload_chunk.side_effect = NetworkError("连接超时")

            engine = UploadEngine(chunk_size=512, concurrency=1)
            with pytest.raises(UploadError, match="分片.*上传失败"):
                engine.upload_file(
                    file_path=str(file_path),
                    remote_dir="/",
                    uploader=mock_uploader,
                )
            # 应重试了 MAX_RETRIES 次
            assert mock_uploader.upload_chunk.call_count == 5

    def test_quota_exceeded_from_quark(self):
        """夸克网盘空间不足应抛出 QuotaExceededError。"""
        uploader = QuarkUploader(credential={"cookie": "__pus=test"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": 500,
            "code": 4101,
            "message": "空间不足，请清理文件后重试",
        }
        with pytest.raises(QuotaExceededError):
            uploader._parse_response(mock_resp)

    def test_authentication_error_from_quark(self):
        """夸克凭证失效应抛出 AuthenticationError。"""
        uploader = QuarkUploader(credential={"cookie": "__pus=test"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": 401,
            "code": 401,
            "message": "登录已过期，请重新登录",
        }
        with pytest.raises(AuthenticationError):
            uploader._parse_response(mock_resp)

    def test_quota_exceeded_from_pan123(self):
        """123 云盘空间不足应抛出 QuotaExceededError。"""
        with pytest.raises(QuotaExceededError):
            Pan123Uploader._check_ok(
                {"code": 4101, "message": "空间不足"}, "初始化失败"
            )

    def test_authentication_error_from_pan123(self):
        """123 云盘凭证失效应抛出 AuthenticationError。"""
        with pytest.raises(AuthenticationError):
            Pan123Uploader._check_ok(
                {"code": 401, "message": "登录已过期"}, "请求失败"
            )

    def test_baidu_error_handling(self):
        """百度网盘 errno 应映射到对应异常。"""
        # 空间不足
        with pytest.raises(QuotaExceededError):
            BaiduUploader._handle_baidu_error(31071, "空间不足")
        # 认证失败
        with pytest.raises(AuthenticationError):
            BaiduUploader._handle_baidu_error(-1, "未登录")
        # 频率限制
        with pytest.raises(UploadError):
            BaiduUploader._handle_baidu_error(31031, "操作太频繁")

    def test_xunlei_error_handling(self):
        """迅雷网盘错误应映射到对应异常。"""
        with pytest.raises(QuotaExceededError):
            XunleiUploader._handle_xunlei_error(
                {"error": "quota_exceeded", "error_description": "空间不足"}
            )
        with pytest.raises(AuthenticationError):
            XunleiUploader._handle_xunlei_error(
                {"error": "invalid_token", "error_description": "token 失效"}
            )

    def test_upload_error_inherits_yunx(self):
        """UploadError 应继承自 YunXError。"""
        assert issubclass(UploadError, YunXError)
        assert issubclass(QuotaExceededError, YunXError)


# ============================================================
# 11. 百度网盘风控警告测试
# ============================================================

class TestBaiduRiskWarning:
    """百度网盘风控警告测试。"""

    def test_risk_not_acknowledged_by_default(self):
        """百度上传器默认未确认风控风险。"""
        uploader = BaiduUploader(credential={"cookie": "BDUSS=test"})
        assert uploader._risk_acknowledged is False

    def test_acknowledge_risk(self):
        """调用 acknowledge_risk 后应标记为已确认。"""
        uploader = BaiduUploader(credential={"cookie": "BDUSS=test"})
        uploader.acknowledge_risk()
        assert uploader._risk_acknowledged is True

    def test_init_upload_raises_without_ack(self):
        """未确认风控风险时 init_upload 应抛出 BaiduRiskWarning。"""
        uploader = BaiduUploader(credential={"cookie": "BDUSS=test"})
        with pytest.raises(BaiduRiskWarning):
            uploader.init_upload(
                file_path="/tmp/test.zip",
                remote_dir="/",
                file_name="test.zip",
                file_size=100,
            )

    def test_upload_chunk_raises_without_ack(self):
        """未确认风控风险时 upload_chunk 应抛出 BaiduRiskWarning。"""
        uploader = BaiduUploader(credential={"cookie": "BDUSS=test"})
        with pytest.raises(BaiduRiskWarning):
            uploader.upload_chunk(
                context={"instant_upload": False},
                chunk_index=0,
                chunk_data=b"test",
                total_chunks=1,
            )

    def test_complete_upload_raises_without_ack(self):
        """未确认风控风险时 complete_upload 应抛出 BaiduRiskWarning。"""
        uploader = BaiduUploader(credential={"cookie": "BDUSS=test"})
        with pytest.raises(BaiduRiskWarning):
            uploader.complete_upload(
                context={"instant_upload": False, "remote_path": "/test.zip",
                         "file_size": 100, "uploadid": "uid", "block_list": []},
                chunk_results=[],
            )

    def test_get_remote_dirs_raises_without_ack(self):
        """未确认风控风险时 get_remote_dirs 应抛出 BaiduRiskWarning。"""
        uploader = BaiduUploader(credential={"cookie": "BDUSS=test"})
        with pytest.raises(BaiduRiskWarning):
            uploader.get_remote_dirs()

    def test_baidu_risk_warning_is_yunx_error(self):
        """BaiduRiskWarning 应继承自 YunXError。"""
        assert issubclass(BaiduRiskWarning, YunXError)

    def test_baidu_status_experimental(self):
        """百度上传器状态应为 experimental。"""
        assert BaiduUploader.status == "experimental"


# ============================================================
# 12. 签名算法测试
# ============================================================

class TestSignatureAlgorithms:
    """各网盘签名算法测试。"""

    def test_pan123_make_sign_returns_tuple(self):
        """123 云盘签名应返回 (auth_key, auth_value) 元组。"""
        auth_key, auth_value = pan123_make_sign("/b/api/file/upload/create", ts=1700000000)
        assert isinstance(auth_key, str)
        assert isinstance(auth_value, str)
        assert len(auth_key) == 8  # CRC32 hex
        # auth_value 格式: ts-random-crc32
        parts = auth_value.split("-")
        assert len(parts) == 3
        assert parts[0] == "1700000000"

    def test_pan123_sign_deterministic_for_same_ts(self):
        """相同 ts 下 auth_key 应确定（auth_value 含 random 所以不同）。"""
        key1, _ = pan123_make_sign("/b/api/test", ts=1234567890)
        key2, _ = pan123_make_sign("/b/api/test", ts=1234567890)
        assert key1 == key2

    def test_xunlei_captcha_sign_format(self):
        """迅雷 captcha_sign 应以 '1.' 前缀 + 32 位 MD5。"""
        sign = _build_captcha_sign("test_device_id", "1700000000000")
        assert sign.startswith("1.")
        assert len(sign) == 34  # "1." + 32 hex chars

    def test_xunlei_captcha_sign_deterministic(self):
        """相同输入下 captcha_sign 应确定。"""
        sign1 = _build_captcha_sign("dev123", "1700000000000")
        sign2 = _build_captcha_sign("dev123", "1700000000000")
        assert sign1 == sign2


# ============================================================
# 13. 完整上传流程测试（mock）
# ============================================================

class TestFullUploadFlow:
    """完整上传流程测试（mock 上传器）。"""

    def test_successful_upload(self):
        """完整上传流程应成功并返回 UploadResult。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "success.zip"
            file_path.write_bytes(b"a" * 3000)

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.supports_chunked_upload.return_value = True
            mock_uploader.init_upload.return_value = {
                "upload_token": "tok123",
                "upload_url": "https://oss.example.com/upload",
                "instant_upload": False,
            }
            mock_uploader.upload_chunk.return_value = {"etag": "etag1", "part_number": 1}
            expected_result = UploadResult(
                file_id="fid_abc",
                file_name="success.zip",
                file_size=3000,
                remote_path="/success.zip",
                drive="quark",
                raw_response={"status": "ok"},
            )
            mock_uploader.complete_upload.return_value = expected_result

            engine = UploadEngine(chunk_size=1024, concurrency=2)
            result = engine.upload_file(
                file_path=str(file_path),
                remote_dir="/",
                uploader=mock_uploader,
            )

            assert isinstance(result, UploadResult)
            assert result.file_id == "fid_abc"
            assert result.file_name == "success.zip"
            assert result.file_size == 3000
            assert result.drive == "quark"
            mock_uploader.init_upload.assert_called_once()
            mock_uploader.complete_upload.assert_called_once()

    def test_instant_upload_skips_chunks(self):
        """秒传命中时应跳过分片上传。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "instant.bin"
            file_path.write_bytes(b"b" * 1000)

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.init_upload.return_value = {
                "instant_upload": True,
                "fid": "instant_fid",
            }
            mock_uploader.complete_upload.return_value = UploadResult(
                file_id="instant_fid", file_name="instant.bin",
                file_size=1000, remote_path="/instant.bin", drive="quark",
            )

            engine = UploadEngine()
            result = engine.upload_file(
                file_path=str(file_path),
                remote_dir="/",
                uploader=mock_uploader,
            )

            mock_uploader.upload_chunk.assert_not_called()
            assert result.file_id == "instant_fid"

    def test_single_thread_fallback(self):
        """上传器不支持分片时应单线程上传。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "single.bin"
            file_path.write_bytes(b"c" * 2048)

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.supports_chunked_upload.return_value = False
            mock_uploader.init_upload.return_value = {
                "upload_token": "tok", "upload_url": "https://oss.example.com",
                "instant_upload": False,
            }
            mock_uploader.upload_chunk.return_value = {"etag": "e", "part_number": 1}
            mock_uploader.complete_upload.return_value = UploadResult(
                file_id="fid", file_name="single.bin", file_size=2048,
                remote_path="/single.bin", drive="quark",
            )

            engine = UploadEngine(chunk_size=1024, concurrency=4)
            result = engine.upload_file(
                file_path=str(file_path),
                remote_dir="/",
                uploader=mock_uploader,
            )

            assert result.file_id == "fid"
            # 单线程模式下应按顺序调用
            call_indexes = [
                c.kwargs["chunk_index"] for c in mock_uploader.upload_chunk.call_args_list
            ]
            assert call_indexes == sorted(call_indexes)

    def test_resume_upload_skips_completed_chunks(self):
        """断点续传应跳过已完成的分片。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "resume.bin"
            file_path.write_bytes(b"d" * 3072)  # 3 chunks of 1024

            # 预创建元数据：前 2 个分片已完成
            meta = UploadMetadata(
                file_path=str(file_path),
                remote_path="/resume.bin",
                total_size=3072,
                chunk_size=1024,
                drive_name="quark",
                chunks=[
                    UploadChunkInfo(index=0, start=0, end=1023, uploaded=True,
                                    result={"etag": "e0"}),
                    UploadChunkInfo(index=1, start=1024, end=2047, uploaded=True,
                                    result={"etag": "e1"}),
                    UploadChunkInfo(index=2, start=2048, end=3071, uploaded=False),
                ],
                upload_context={
                    "upload_token": "tok", "upload_url": "https://oss.example.com",
                    "instant_upload": False,
                },
            )
            meta_path = file_path.parent / f"{file_path.name}.yunx_upload.json"
            meta_path.write_text(json.dumps(meta.to_dict()), encoding="utf-8")

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.supports_chunked_upload.return_value = True
            mock_uploader.upload_chunk.return_value = {"etag": "e2", "part_number": 3}
            mock_uploader.complete_upload.return_value = UploadResult(
                file_id="fid", file_name="resume.bin", file_size=3072,
                remote_path="/resume.bin", drive="quark",
            )

            engine = UploadEngine(chunk_size=1024, concurrency=1)
            result = engine.upload_file(
                file_path=str(file_path),
                remote_dir="/",
                uploader=mock_uploader,
            )

            # 只应上传第 3 个分片（index=2）
            assert mock_uploader.upload_chunk.call_count == 1
            assert mock_uploader.upload_chunk.call_args.kwargs["chunk_index"] == 2
            # init_upload 不应被调用（恢复模式）
            mock_uploader.init_upload.assert_not_called()

    def test_task_registration_and_status(self):
        """上传过程中任务状态应正确更新。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "task.bin"
            file_path.write_bytes(b"e" * 1024)

            mock_uploader = MagicMock(spec=BaseUploader)
            mock_uploader.drive_name = "quark"
            mock_uploader.supports_chunked_upload.return_value = True
            mock_uploader.init_upload.return_value = {
                "upload_token": "tok", "upload_url": "https://oss.example.com",
                "instant_upload": False,
            }
            mock_uploader.upload_chunk.return_value = {"etag": "e", "part_number": 1}
            mock_uploader.complete_upload.return_value = UploadResult(
                file_id="fid", file_name="task.bin", file_size=1024,
                remote_path="/task.bin", drive="quark",
            )

            engine = UploadEngine(chunk_size=512, concurrency=1)
            engine.upload_file(
                file_path=str(file_path),
                remote_dir="/",
                uploader=mock_uploader,
            )

            task = engine.get_task(str(file_path))
            assert task is not None
            assert task.status == STATUS_COMPLETED
            assert task.uploaded_bytes == 1024
            assert task.total_bytes == 1024
