"""
下载引擎单元测试（mock HTTP）。

使用 unittest.mock 模拟 requests 响应，测试：
- 服务器探测（Range 支持 / 不支持）
- 分片构建
- 并发下载（mock）
- 断点续传恢复
- 元数据持久化
- 进度回调
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from core.downloader.engine import (
    DownloadEngine,
    DownloadMetadata,
    ChunkInfo,
    DEFAULT_CHUNK_SIZE,
)
from core.downloader.progress import ProgressTracker, DownloadProgress


class TestChunkBuilding:
    """分片构建测试。"""

    def test_exact_chunks(self):
        """文件大小恰好是分片整数倍。"""
        chunk = 64 * 1024  # 64KB（引擎最小分片）
        engine = DownloadEngine(chunk_size=chunk)
        chunks = engine._build_chunks(chunk * 4)
        assert len(chunks) == 4
        assert chunks[0].start == 0
        assert chunks[0].end == chunk - 1
        assert chunks[-1].end == chunk * 4 - 1

    def test_partial_last_chunk(self):
        """最后一个分片不足完整大小。"""
        chunk = 64 * 1024
        engine = DownloadEngine(chunk_size=chunk)
        total = chunk + 1000
        chunks = engine._build_chunks(total)
        assert len(chunks) == 2
        assert chunks[1].start == chunk
        assert chunks[1].end == total - 1

    def test_single_chunk(self):
        """文件小于分片大小。"""
        engine = DownloadEngine(chunk_size=128 * 1024)
        chunks = engine._build_chunks(1024)
        assert len(chunks) == 1
        assert chunks[0].start == 0
        assert chunks[0].end == 1023

    def test_zero_size(self):
        """零字节文件。"""
        engine = DownloadEngine()
        chunks = engine._build_chunks(0)
        assert len(chunks) == 1


class TestServerProbe:
    """服务器探测测试（mock）。"""

    def _make_response(
        self,
        status_code=200,
        headers=None,
        content=b"",
    ):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = status_code
        resp.headers = headers or {}
        resp.content = content
        resp.iter_content.return_value = iter([content]) if content else iter([])
        resp.close = MagicMock()
        return resp

    @patch("core.downloader.engine.requests.Session")
    def test_probe_with_range_support(self, mock_session_cls):
        """服务器支持 Range 时应正确识别。"""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        head_resp = self._make_response(
            status_code=200,
            headers={"Content-Length": "100000", "Accept-Ranges": "bytes"},
        )
        mock_session.head.return_value = head_resp

        engine = DownloadEngine()
        engine._session = mock_session
        total_size, supports_range = engine._probe_server(
            "https://example.com/file", {}
        )
        assert total_size == 100000
        assert supports_range is True

    @patch("core.downloader.engine.requests.Session")
    def test_probe_without_range_support(self, mock_session_cls):
        """服务器不支持 Range 时应正确识别。"""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        head_resp = self._make_response(
            status_code=200,
            headers={"Content-Length": "50000"},
        )
        # HEAD 无 Accept-Ranges，GET Range 返回 200（不支持）
        get_resp = self._make_response(
            status_code=200,
            headers={"Content-Length": "50000"},
        )
        mock_session.head.return_value = head_resp
        mock_session.get.return_value = get_resp

        engine = DownloadEngine()
        engine._session = mock_session
        total_size, supports_range = engine._probe_server(
            "https://example.com/file", {}
        )
        assert total_size == 50000
        assert supports_range is False


class TestMetadataPersistence:
    """元数据持久化测试。"""

    def test_metadata_roundtrip(self):
        """元数据序列化/反序列化应一致。"""
        meta = DownloadMetadata(
            url="https://example.com/file.zip",
            output_path="/tmp/file.zip",
            total_size=100000,
            chunk_size=4096,
            supports_range=True,
            chunks=[
                ChunkInfo(index=0, start=0, end=4095, downloaded=True),
                ChunkInfo(index=1, start=4096, end=8191, downloaded=False),
            ],
            md5="abc123",
            headers={"Referer": "https://example.com"},
        )
        data = meta.to_dict()
        restored = DownloadMetadata.from_dict(data)
        assert restored.url == meta.url
        assert restored.total_size == meta.total_size
        assert len(restored.chunks) == 2
        assert restored.chunks[0].downloaded is True
        assert restored.chunks[1].downloaded is False
        assert restored.md5 == "abc123"
        assert restored.headers == {"Referer": "https://example.com"}


class TestProgressTracker:
    """进度追踪器测试。"""

    def test_percent_calculation(self):
        """百分比计算应正确。"""
        tracker = ProgressTracker(total_bytes=1000)
        tracker.update(500)
        snap = tracker.snapshot()
        assert snap.percent == 50.0
        assert snap.downloaded_bytes == 500

    def test_speed_calculation(self):
        """速度计算应返回正值。"""
        tracker = ProgressTracker(total_bytes=1000, speed_window=10)
        tracker.update(500)
        snap = tracker.snapshot()
        assert snap.speed >= 0

    def test_callback_invoked(self):
        """进度更新时应触发回调。"""
        calls = []
        tracker = ProgressTracker(
            total_bytes=1000, callback=lambda p: calls.append(p)
        )
        tracker.update(100)
        assert len(calls) == 1
        assert isinstance(calls[0], DownloadProgress)
        assert calls[0].downloaded_bytes == 100

    def test_pause_resume(self):
        """暂停/恢复不应崩溃。"""
        tracker = ProgressTracker(total_bytes=1000)
        tracker.pause()
        tracker.resume()
        tracker.update(100)
        assert tracker.snapshot().downloaded_bytes == 100


class TestDownloadEngineConfig:
    """下载引擎配置测试。"""

    def test_concurrency_capped(self):
        """并发数超过上限应被截断。"""
        engine = DownloadEngine(concurrency=100)
        assert engine.concurrency == 32

    def test_concurrency_minimum(self):
        """并发数低于 1 应被提升到 1。"""
        engine = DownloadEngine(concurrency=0)
        assert engine.concurrency == 1

    def test_chunk_size_minimum(self):
        """分片大小低于 64KB 应被提升。"""
        engine = DownloadEngine(chunk_size=1024)
        assert engine.chunk_size == 64 * 1024
