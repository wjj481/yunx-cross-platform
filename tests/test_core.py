"""
剪贴板识别 + 配置管理 + 异常定义测试。
"""

import os
import tempfile
from pathlib import Path

import pytest

from core.clipboard import detect_share_url, ShareURL
from core.config import ConfigManager
from core.exceptions import (
    YunXError,
    ParserError,
    NetworkError,
    DownloadError,
    BaiduRiskWarning,
    AuthenticationError,
)


class TestClipboardDetection:
    """剪贴板分享链接识别测试。"""

    def test_detect_quark(self):
        results = detect_share_url("https://pan.quark.cn/s/abc123")
        assert len(results) == 1
        assert results[0].drive == "quark"
        assert results[0].share_id == "abc123"

    def test_detect_xunlei(self):
        results = detect_share_url("https://pan.xunlei.com/s/xyz-789")
        assert len(results) == 1
        assert results[0].drive == "xunlei"

    def test_detect_pan123(self):
        results = detect_share_url("https://www.123pan.com/s/abc-def")
        assert len(results) == 1
        assert results[0].drive == "pan123"

    def test_detect_baidu(self):
        results = detect_share_url("https://pan.baidu.com/s/1abc123")
        assert len(results) == 1
        assert results[0].drive == "baidu"
        # 百度 surl 去掉开头的 1
        assert results[0].share_id == "abc123"

    def test_detect_with_extract_code_in_url(self):
        results = detect_share_url(
            "https://pan.baidu.com/s/1abc?pwd=abcd"
        )
        assert results[0].extract_code == "abcd"

    def test_detect_with_extract_code_in_text(self):
        text = "分享链接：https://pan.quark.cn/s/abc 提取码: 1234"
        results = detect_share_url(text)
        assert results[0].extract_code == "1234"

    def test_detect_multiple_urls(self):
        text = (
            "https://pan.quark.cn/s/aaa 和 "
            "https://pan.xunlei.com/s/bbb"
        )
        results = detect_share_url(text)
        assert len(results) == 2

    def test_deduplicate_urls(self):
        text = "https://pan.quark.cn/s/aaa https://pan.quark.cn/s/aaa"
        results = detect_share_url(text)
        assert len(results) == 1

    def test_no_url_in_text(self):
        results = detect_share_url("这段文字没有链接")
        assert len(results) == 0


class TestConfigManager:
    """配置管理器测试（AES-GCM 加密）。"""

    def test_credential_roundtrip(self, tmp_path):
        """凭证设置后应能正确读取。"""
        salt_path = tmp_path / "salt.bin"
        config_path = tmp_path / "config.enc"
        cfg = ConfigManager(
            "test_password",
            config_path=config_path,
            salt_path=salt_path,
        )
        cfg.set_credential("quark", {"cookie": "__pus=secret123"})
        cred = cfg.get_credential("quark")
        assert cred == {"cookie": "__pus=secret123"}

    def test_wrong_password_fails(self, tmp_path):
        """错误密码应无法解密。"""
        salt_path = tmp_path / "salt.bin"
        config_path = tmp_path / "config.enc"
        cfg1 = ConfigManager(
            "password1", config_path=config_path, salt_path=salt_path
        )
        cfg1.set_credential("quark", {"cookie": "test"})

        with pytest.raises(AuthenticationError):
            ConfigManager(
                "password2", config_path=config_path, salt_path=salt_path
            )

    def test_remove_credential(self, tmp_path):
        """删除凭证后应返回 None。"""
        salt_path = tmp_path / "salt.bin"
        config_path = tmp_path / "config.enc"
        cfg = ConfigManager(
            "pwd", config_path=config_path, salt_path=salt_path
        )
        cfg.set_credential("quark", {"cookie": "test"})
        cfg.remove_credential("quark")
        assert cfg.get_credential("quark") is None

    def test_list_drives(self, tmp_path):
        """列出已保存凭证的网盘。"""
        salt_path = tmp_path / "salt.bin"
        config_path = tmp_path / "config.enc"
        cfg = ConfigManager(
            "pwd", config_path=config_path, salt_path=salt_path
        )
        cfg.set_credential("quark", {"cookie": "1"})
        cfg.set_credential("pan123", {"access_token": "2"})
        drives = cfg.list_drives()
        assert set(drives) == {"quark", "pan123"}

    def test_generic_config(self, tmp_path):
        """通用配置项读写。"""
        salt_path = tmp_path / "salt.bin"
        config_path = tmp_path / "config.enc"
        cfg = ConfigManager(
            "pwd", config_path=config_path, salt_path=salt_path
        )
        cfg.set("download_dir", "/tmp/downloads")
        assert cfg.get("download_dir") == "/tmp/downloads"
        assert cfg.get("nonexistent", "default") == "default"

    def test_encrypted_on_disk(self, tmp_path):
        """配置文件在磁盘上应是加密的（不包含明文）。"""
        salt_path = tmp_path / "salt.bin"
        config_path = tmp_path / "config.enc"
        cfg = ConfigManager(
            "pwd", config_path=config_path, salt_path=salt_path
        )
        cfg.set_credential("quark", {"cookie": "SECRET_VALUE_12345"})
        content = config_path.read_text(encoding="utf-8")
        assert "SECRET_VALUE_12345" not in content


class TestExceptions:
    """异常定义测试。"""

    def test_exception_hierarchy(self):
        """所有异常应继承自 YunXError。"""
        assert issubclass(ParserError, YunXError)
        assert issubclass(NetworkError, YunXError)
        assert issubclass(DownloadError, YunXError)
        assert issubclass(BaiduRiskWarning, YunXError)
        assert issubclass(AuthenticationError, YunXError)

    def test_parser_error_with_code(self):
        """ParserError 应携带 code。"""
        err = ParserError("test error", code=21001)
        assert str(err) == "test error"
        assert err.code == 21001
