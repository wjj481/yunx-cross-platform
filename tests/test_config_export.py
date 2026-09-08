"""
配置导出 / 导入模块测试。

覆盖明文与加密导出导入往返、密码校验、文件格式检测、合并/替换模式、
损坏文件处理、特殊字符、大配置性能、元信息校验及跨平台路径兼容性。
"""

import json
import os
import time
from pathlib import Path

import pytest

from core.config import ConfigManager
from core.config_export import (
    export_config,
    import_config,
    is_encrypted,
    apply_imported_config,
    _EXPORT_FORMAT_VERSION,
)
from core.exceptions import AuthenticationError


# ---------- 辅助函数 ----------


def _make_config_manager(tmp_path: Path, password: str = "test_pwd") -> ConfigManager:
    """创建一个使用临时路径的 ConfigManager。"""
    return ConfigManager(
        password,
        config_path=tmp_path / "config.enc",
        salt_path=tmp_path / "salt.bin",
    )


def _populate_config(cfg: ConfigManager) -> None:
    """向 ConfigManager 填充测试数据。"""
    cfg.set_credential("quark", {"cookie": "__pus=quark_secret; __puus=abc"})
    cfg.set_credential("pan123", {"access_token": "token_123", "refresh_token": "refresh_456"})
    cfg.set("download_dir", "/home/user/Downloads")
    cfg.set("thread_count", 8)
    cfg.set("chunk_size", 10 * 1024 * 1024)
    cfg.set("clipboard_monitor", True)
    # 直接写入 tasks 字段（模拟已保存的下载任务）
    cfg._data["tasks"] = [
        {"id": "task_001", "name": "file1.zip", "status": "completed", "drive": "quark"},
        {"id": "task_002", "name": "file2.mp4", "status": "paused", "drive": "pan123"},
    ]
    cfg.save()


# ---------- 明文导出 / 导入 ----------


class TestPlaintextExportImport:
    """明文导出与导入往返测试。"""

    def test_plaintext_roundtrip_credentials(self, tmp_path):
        """明文导出后导入，凭证应完整保留。"""
        cfg = _make_config_manager(tmp_path)
        _populate_config(cfg)

        out = tmp_path / "backup.yunxcfg"
        export_config(cfg, out, password=None)

        data = import_config(out, password=None)
        assert data["credentials"]["quark"] == {"cookie": "__pus=quark_secret; __puus=abc"}
        assert data["credentials"]["pan123"] == {
            "access_token": "token_123",
            "refresh_token": "refresh_456",
        }

    def test_plaintext_roundtrip_settings(self, tmp_path):
        """明文导出后导入，通用设置应完整保留（排除 credentials）。"""
        cfg = _make_config_manager(tmp_path)
        _populate_config(cfg)

        out = tmp_path / "backup.yunxcfg"
        export_config(cfg, out, password=None)

        data = import_config(out, password=None)
        assert data["settings"]["download_dir"] == "/home/user/Downloads"
        assert data["settings"]["thread_count"] == 8
        assert data["settings"]["chunk_size"] == 10 * 1024 * 1024
        assert data["settings"]["clipboard_monitor"] is True
        # credentials 不应出现在 settings 中
        assert "credentials" not in data["settings"]

    def test_plaintext_roundtrip_tasks(self, tmp_path):
        """明文导出后导入，下载任务应完整保留。"""
        cfg = _make_config_manager(tmp_path)
        _populate_config(cfg)

        out = tmp_path / "backup.yunxcfg"
        export_config(cfg, out, password=None)

        data = import_config(out, password=None)
        assert len(data["tasks"]) == 2
        assert data["tasks"][0]["id"] == "task_001"
        assert data["tasks"][1]["name"] == "file2.mp4"

    def test_plaintext_exclude_tasks(self, tmp_path):
        """include_tasks=False 时导出的 tasks 应为空列表。"""
        cfg = _make_config_manager(tmp_path)
        _populate_config(cfg)

        out = tmp_path / "backup.yunxcfg"
        export_config(cfg, out, password=None, include_tasks=False)

        data = import_config(out, password=None)
        assert data["tasks"] == []


# ---------- 加密导出 / 导入 ----------


class TestEncryptedExportImport:
    """加密导出与导入往返测试。"""

    def test_encrypted_roundtrip_correct_password(self, tmp_path):
        """加密导出后用正确密码导入，数据应完整。"""
        cfg = _make_config_manager(tmp_path)
        _populate_config(cfg)

        out = tmp_path / "encrypted.yunxcfg"
        export_config(cfg, out, password="export_secret")

        data = import_config(out, password="export_secret")
        assert data["credentials"]["quark"]["cookie"] == "__pus=quark_secret; __puus=abc"
        assert data["settings"]["thread_count"] == 8
        assert len(data["tasks"]) == 2

    def test_encrypted_wrong_password_raises(self, tmp_path):
        """加密文件用错误密码导入应抛出 AuthenticationError。"""
        cfg = _make_config_manager(tmp_path)
        _populate_config(cfg)

        out = tmp_path / "encrypted.yunxcfg"
        export_config(cfg, out, password="correct_password")

        with pytest.raises(AuthenticationError):
            import_config(out, password="wrong_password")

    def test_encrypted_without_password_raises(self, tmp_path):
        """加密文件不提供密码应抛出 AuthenticationError。"""
        cfg = _make_config_manager(tmp_path)
        _populate_config(cfg)

        out = tmp_path / "encrypted.yunxcfg"
        export_config(cfg, out, password="secret")

        with pytest.raises(AuthenticationError):
            import_config(out, password=None)

    def test_encrypted_file_not_plaintext(self, tmp_path):
        """加密文件在磁盘上不应包含明文凭据。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "SENSITIVE_PLAINTEXT_VALUE"})

        out = tmp_path / "encrypted.yunxcfg"
        export_config(cfg, out, password="secret")

        content = out.read_text(encoding="utf-8")
        assert "SENSITIVE_PLAINTEXT_VALUE" not in content


# ---------- is_encrypted 检测 ----------


class TestIsEncrypted:
    """is_encrypted 文件格式检测测试。"""

    def test_plaintext_returns_false(self, tmp_path):
        """明文文件应返回 False。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "test"})

        out = tmp_path / "plain.yunxcfg"
        export_config(cfg, out, password=None)
        assert is_encrypted(out) is False

    def test_encrypted_returns_true(self, tmp_path):
        """加密文件应返回 True。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "test"})

        out = tmp_path / "enc.yunxcfg"
        export_config(cfg, out, password="secret")
        assert is_encrypted(out) is True


# ---------- 文件扩展名 ----------


class TestFileExtension:
    """导出文件扩展名与路径处理测试。"""

    def test_export_with_yunxcfg_extension(self, tmp_path):
        """使用 .yunxcfg 扩展名导出应成功。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "test"})

        out = tmp_path / "config_backup.yunxcfg"
        result = export_config(cfg, out, password=None)
        assert result.exists()
        assert result.suffix == ".yunxcfg"

    def test_export_creates_parent_dirs(self, tmp_path):
        """导出时应自动创建不存在的父目录。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "test"})

        out = tmp_path / "nested" / "deep" / "dir" / "backup.yunxcfg"
        result = export_config(cfg, out, password=None)
        assert result.exists()

    def test_export_returns_path_object(self, tmp_path):
        """export_config 应返回 Path 对象。"""
        cfg = _make_config_manager(tmp_path)
        out = tmp_path / "backup.yunxcfg"
        result = export_config(cfg, out, password=None)
        assert isinstance(result, Path)


# ---------- 空配置 ----------


class TestEmptyConfig:
    """空配置导出导入测试。"""

    def test_empty_config_export_import(self, tmp_path):
        """空 ConfigManager 导出后导入应得到空凭证和空设置。"""
        cfg = _make_config_manager(tmp_path)

        out = tmp_path / "empty.yunxcfg"
        export_config(cfg, out, password=None)

        data = import_config(out, password=None)
        assert data["credentials"] == {}
        assert data["settings"] == {}
        assert data["tasks"] == []
        assert "meta" in data


# ---------- 合并 / 替换模式 ----------


class TestApplyImportedConfig:
    """apply_imported_config 合并与替换模式测试。"""

    def test_merge_mode_combines_credentials(self, tmp_path):
        """合并模式：新凭证应与旧凭证合并，同名网盘被覆盖。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "old_quark_cookie"})
        cfg.set_credential("baidu", {"cookie": "old_baidu_cookie"})

        imported = {
            "credentials": {
                "quark": {"cookie": "new_quark_cookie"},
                "pan123": {"access_token": "new_pan123_token"},
            },
            "settings": {"thread_count": 16},
            "tasks": [],
            "meta": {"export_time": "2026-01-01T00:00:00+00:00", "format_version": "v0.2.0", "engine_version": "0.1.0"},
        }

        apply_imported_config(cfg, imported, merge=True)

        # quark 被覆盖
        assert cfg.get_credential("quark") == {"cookie": "new_quark_cookie"}
        # baidu 保留
        assert cfg.get_credential("baidu") == {"cookie": "old_baidu_cookie"}
        # pan123 新增
        assert cfg.get_credential("pan123") == {"access_token": "new_pan123_token"}

    def test_merge_mode_combines_settings(self, tmp_path):
        """合并模式：设置应合并，同键被覆盖。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set("download_dir", "/old/path")
        cfg.set("thread_count", 4)

        imported = {
            "credentials": {},
            "settings": {"thread_count": 8, "chunk_size": 5242880},
            "tasks": [],
            "meta": {"export_time": "2026-01-01T00:00:00+00:00", "format_version": "v0.2.0", "engine_version": "0.1.0"},
        }

        apply_imported_config(cfg, imported, merge=True)

        assert cfg.get("download_dir") == "/old/path"  # 保留
        assert cfg.get("thread_count") == 8  # 被覆盖
        assert cfg.get("chunk_size") == 5242880  # 新增

    def test_replace_mode_overwrites_everything(self, tmp_path):
        """替换模式：现有配置应被完全替换。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "old"})
        cfg.set("download_dir", "/old")

        imported = {
            "credentials": {"pan123": {"access_token": "new"}},
            "settings": {"thread_count": 32},
            "tasks": [],
            "meta": {"export_time": "2026-01-01T00:00:00+00:00", "format_version": "v0.2.0", "engine_version": "0.1.0"},
        }

        apply_imported_config(cfg, imported, merge=False)

        assert cfg.get_credential("quark") is None  # 旧凭证被清除
        assert cfg.get_credential("pan123") == {"access_token": "new"}
        assert cfg.get("download_dir") is None  # 旧设置被清除
        assert cfg.get("thread_count") == 32

    def test_apply_calls_save(self, tmp_path):
        """应用配置后应自动调用 save（磁盘文件应更新）。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "old"})

        imported = {
            "credentials": {"quark": {"cookie": "new_after_apply"}},
            "settings": {},
            "tasks": [],
            "meta": {"export_time": "2026-01-01T00:00:00+00:00", "format_version": "v0.2.0", "engine_version": "0.1.0"},
        }

        apply_imported_config(cfg, imported, merge=True)

        # 重新加载验证持久化
        cfg2 = _make_config_manager(tmp_path)
        assert cfg2.get_credential("quark") == {"cookie": "new_after_apply"}


# ---------- 损坏文件 / 格式校验 ----------


class TestCorruptedAndInvalidFiles:
    """损坏文件与格式不完整测试。"""

    def test_corrupted_encrypted_file_raises(self, tmp_path):
        """损坏的加密文件导入应抛出异常。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "test"})

        out = tmp_path / "corrupted.yunxcfg"
        export_config(cfg, out, password="secret")

        # 篡改文件内容
        content = out.read_text(encoding="utf-8")
        corrupted = content[:-10] + "AAAAAAAAAA"
        out.write_text(corrupted, encoding="utf-8")

        with pytest.raises((AuthenticationError, ValueError)):
            import_config(out, password="secret")

    def test_invalid_json_raises_value_error(self, tmp_path):
        """非 JSON 明文文件应抛出 ValueError。"""
        bad_file = tmp_path / "bad.yunxcfg"
        bad_file.write_text("this is not json at all", encoding="utf-8")

        with pytest.raises(ValueError):
            import_config(bad_file, password=None)

    def test_missing_required_fields_raises(self, tmp_path):
        """缺少必要字段的 JSON 文件应抛出 ValueError。"""
        incomplete = tmp_path / "incomplete.yunxcfg"
        incomplete.write_text(json.dumps({"credentials": {}}), encoding="utf-8")

        with pytest.raises(ValueError, match="缺少必要字段"):
            import_config(incomplete, password=None)

    def test_non_dict_json_raises(self, tmp_path):
        """顶层不是对象的 JSON 应抛出 ValueError。"""
        arr_file = tmp_path / "array.yunxcfg"
        arr_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        with pytest.raises(ValueError):
            import_config(arr_file, password=None)


# ---------- 特殊字符 ----------


class TestSpecialCharacters:
    """包含特殊字符（中文、Unicode）的凭证导出导入测试。"""

    def test_chinese_credentials_roundtrip(self, tmp_path):
        """包含中文字符的凭证应完整往返。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "用户=张三; 令牌=中文密钥123"})
        cfg.set("download_dir", "/home/用户/下载目录")

        out = tmp_path / "chinese.yunxcfg"
        export_config(cfg, out, password=None)

        data = import_config(out, password=None)
        assert data["credentials"]["quark"]["cookie"] == "用户=张三; 令牌=中文密钥123"
        assert data["settings"]["download_dir"] == "/home/用户/下载目录"

    def test_unicode_emoji_credentials(self, tmp_path):
        """包含 emoji 和特殊 Unicode 的凭证应完整往返。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("test", {"note": "测试🚀✨\n换行\t制表符"})

        out = tmp_path / "unicode.yunxcfg"
        export_config(cfg, out, password="加密密码🔐")

        data = import_config(out, password="加密密码🔐")
        assert data["credentials"]["test"]["note"] == "测试🚀✨\n换行\t制表符"


# ---------- 大配置性能 ----------


class TestLargeConfigPerformance:
    """大配置导出导入性能测试。"""

    def test_large_config_export_import_performance(self, tmp_path):
        """包含大量凭证和设置的配置应在合理时间内完成导出导入。"""
        cfg = _make_config_manager(tmp_path)

        # 生成 200 个网盘凭证
        for i in range(200):
            cfg.set_credential(
                f"drive_{i:03d}",
                {"cookie": f"cookie_value_{i}" * 10, "token": f"token_{i}"},
            )

        # 生成 100 个设置项
        for i in range(100):
            cfg.set(f"setting_key_{i:03d}", f"setting_value_{i}" * 5)

        # 生成 50 个任务
        cfg._data["tasks"] = [
            {"id": f"task_{i:03d}", "name": f"file_{i}.dat", "size": i * 1024}
            for i in range(50)
        ]
        cfg.save()

        out = tmp_path / "large.yunxcfg"

        start = time.time()
        export_config(cfg, out, password="large_secret")
        export_time = time.time() - start

        start = time.time()
        data = import_config(out, password="large_secret")
        import_time = time.time() - start

        # 数据完整性校验
        assert len(data["credentials"]) == 200
        assert data["credentials"]["drive_199"]["cookie"] == "cookie_value_199" * 10
        assert len(data["settings"]) == 100
        assert len(data["tasks"]) == 50

        # 性能断言：导出导入均应在 10 秒内完成（CI 环境宽松）
        assert export_time < 10, f"导出耗时过长: {export_time:.2f}s"
        assert import_time < 10, f"导入耗时过长: {import_time:.2f}s"


# ---------- meta 字段校验 ----------


class TestMetaFields:
    """导出文件 meta 字段校验测试。"""

    def test_meta_contains_version_and_time(self, tmp_path):
        """meta 应包含格式版本号、引擎版本和导出时间。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "test"})

        out = tmp_path / "meta.yunxcfg"
        export_config(cfg, out, password=None)

        data = import_config(out, password=None)
        meta = data["meta"]

        assert "format_version" in meta
        assert meta["format_version"] == _EXPORT_FORMAT_VERSION
        assert "engine_version" in meta
        assert isinstance(meta["engine_version"], str)
        assert "export_time" in meta
        # export_time 应为 ISO 格式字符串
        assert "T" in meta["export_time"]

    def test_encrypted_meta_intact(self, tmp_path):
        """加密导出后 meta 字段应完整保留。"""
        cfg = _make_config_manager(tmp_path)
        out = tmp_path / "enc_meta.yunxcfg"
        export_config(cfg, out, password="secret")

        data = import_config(out, password="secret")
        assert data["meta"]["format_version"] == _EXPORT_FORMAT_VERSION
        assert "export_time" in data["meta"]


# ---------- 跨平台路径兼容性 ----------


class TestCrossPlatformPaths:
    """跨平台路径兼容性测试。"""

    def test_windows_style_paths_in_settings(self, tmp_path):
        """Windows 风格路径（反斜杠）应在设置中完整保留。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set("download_dir", "C:\\Users\\Test\\Downloads\\网盘文件")

        out = tmp_path / "win_path.yunxcfg"
        export_config(cfg, out, password=None)

        data = import_config(out, password=None)
        assert data["settings"]["download_dir"] == "C:\\Users\\Test\\Downloads\\网盘文件"

    def test_unix_style_paths_in_settings(self, tmp_path):
        """Unix 风格路径应完整保留。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set("download_dir", "/mnt/storage/downloads/中文目录")

        out = tmp_path / "unix_path.yunxcfg"
        export_config(cfg, out, password=None)

        data = import_config(out, password=None)
        assert data["settings"]["download_dir"] == "/mnt/storage/downloads/中文目录"

    def test_export_import_with_string_path(self, tmp_path):
        """使用字符串路径（而非 Path 对象）应正常工作。"""
        cfg = _make_config_manager(tmp_path)
        cfg.set_credential("quark", {"cookie": "test"})

        out_str = str(tmp_path / "string_path.yunxcfg")
        result = export_config(cfg, out_str, password=None)
        assert isinstance(result, Path)
        assert result.exists()

        data = import_config(out_str, password=None)
        assert data["credentials"]["quark"]["cookie"] == "test"


# ---------- 端到端：导出 -> 新 ConfigManager 导入应用 ----------


class TestEndToEndMigration:
    """端到端配置迁移测试：从一个 ConfigManager 导出，应用到另一个。"""

    def test_full_migration_plaintext(self, tmp_path):
        """明文完整迁移：导出 -> 导入 -> 应用到全新 ConfigManager。"""
        # 源配置
        src = _make_config_manager(tmp_path / "src")
        _populate_config(src)

        # 导出
        backup = tmp_path / "migration.yunxcfg"
        export_config(src, backup, password=None)

        # 导入
        data = import_config(backup, password=None)

        # 目标配置（全新空配置）
        dst = _make_config_manager(tmp_path / "dst")
        apply_imported_config(dst, data, merge=False)

        # 验证
        assert dst.get_credential("quark") == {"cookie": "__pus=quark_secret; __puus=abc"}
        assert dst.get_credential("pan123") == {
            "access_token": "token_123",
            "refresh_token": "refresh_456",
        }
        assert dst.get("download_dir") == "/home/user/Downloads"
        assert dst.get("thread_count") == 8
        assert len(dst._data.get("tasks", [])) == 2

    def test_full_migration_encrypted(self, tmp_path):
        """加密完整迁移：导出 -> 导入 -> 应用到全新 ConfigManager。"""
        src = _make_config_manager(tmp_path / "src")
        _populate_config(src)

        backup = tmp_path / "migration_enc.yunxcfg"
        export_config(src, backup, password="migration_pwd")

        data = import_config(backup, password="migration_pwd")

        dst = _make_config_manager(tmp_path / "dst")
        apply_imported_config(dst, data, merge=False)

        assert dst.get_credential("quark")["cookie"] == "__pus=quark_secret; __puus=abc"
        assert dst.get("thread_count") == 8
