"""
配置文件导出 / 导入模块。

支持将 ConfigManager 中的全部数据（凭证、设置、任务）导出为单个 ``.yunxcfg`` 文件，
并可选择是否使用密码加密。导出文件可在另一台设备上导入，实现配置迁移与备份。

文件格式：
- 明文：标准 JSON 文本，包含 ``credentials`` / ``settings`` / ``tasks`` / ``meta`` 四个顶层字段。
- 加密：base64( magic(4) + salt(16) + nonce(12) + ciphertext+tag )，
  其中 magic 为 ``YNC1``（YunX Config v1），加密参数与 ConfigManager 一致。
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from .config import ConfigManager
from .exceptions import AuthenticationError

# ---------- 加密常量（与 config.py 保持一致） ----------

# PBKDF2 迭代次数
_PBKDF2_ITERATIONS = 100_000
# AES-256 密钥长度
_KEY_LENGTH = 32
# GCM nonce 长度（96 bit）
_NONCE_LENGTH = 12
# 盐值长度
_SALT_LENGTH = 16
# 加密文件 magic header（YunX Config v1）
_MAGIC_HEADER = b"YNC1"
# 导出文件扩展名
_EXPORT_EXTENSION = ".yunxcfg"
# 导出格式版本
_EXPORT_FORMAT_VERSION = "v0.2.0"
# 必要顶层字段
_REQUIRED_FIELDS = ("credentials", "settings", "tasks", "meta")


def _derive_key(password: str, salt: bytes) -> bytes:
    """通过 PBKDF2-HMAC-SHA256 从密码派生 32 字节 AES-256 密钥。

    Args:
        password: 用户密码。
        salt: 盐值（16 字节）。

    Returns:
        32 字节密钥。
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def _extract_export_data(
    config_manager: ConfigManager,
    include_tasks: bool = True,
) -> dict[str, Any]:
    """从 ConfigManager 提取导出数据。

    Args:
        config_manager: 配置管理器实例。
        include_tasks: 是否包含下载任务。

    Returns:
        包含 credentials / settings / tasks / meta 的字典。
    """
    data = config_manager._data

    # 凭证
    credentials = dict(data.get("credentials", {}))

    # 通用设置：排除 credentials 和 tasks
    settings = {
        k: v for k, v in data.items() if k not in ("credentials", "tasks")
    }

    # 任务
    tasks = list(data.get("tasks", [])) if include_tasks else []

    # 元信息
    from . import __version__ as _engine_version

    meta = {
        "export_time": datetime.now(timezone.utc).isoformat(),
        "format_version": _EXPORT_FORMAT_VERSION,
        "engine_version": _engine_version,
    }

    return {
        "credentials": credentials,
        "settings": settings,
        "tasks": tasks,
        "meta": meta,
    }


def _encrypt_payload(plaintext_bytes: bytes, password: str) -> bytes:
    """将明文加密为带 magic header 的二进制载荷。

    格式：magic(4) + salt(16) + nonce(12) + ciphertext+tag

    Args:
        plaintext_bytes: 明文字节（通常是 JSON 序列化结果）。
        password: 加密密码。

    Returns:
        加密后的二进制载荷。
    """
    salt = os.urandom(_SALT_LENGTH)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LENGTH)
    ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)
    return _MAGIC_HEADER + salt + nonce + ciphertext


def _decrypt_payload(payload: bytes, password: str) -> bytes:
    """解密带 magic header 的二进制载荷。

    Args:
        payload: 加密二进制载荷。
        password: 解密密码。

    Returns:
        明文字节。

    Raises:
        AuthenticationError: 密码错误或数据损坏。
    """
    if not payload.startswith(_MAGIC_HEADER):
        raise AuthenticationError("无效的加密配置文件：缺少 magic header")

    offset = len(_MAGIC_HEADER)
    salt = payload[offset : offset + _SALT_LENGTH]
    offset += _SALT_LENGTH
    nonce = payload[offset : offset + _NONCE_LENGTH]
    offset += _NONCE_LENGTH
    ciphertext = payload[offset:]

    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise AuthenticationError(
            f"配置文件解密失败，可能是密码错误或文件已损坏: {exc}"
        ) from exc


def _validate_imported_data(data: dict[str, Any]) -> None:
    """校验导入数据的必要字段是否完整。

    Args:
        data: 解析后的配置字典。

    Raises:
        ValueError: 缺少必要字段。
    """
    if not isinstance(data, dict):
        raise ValueError("导入文件内容不是有效的 JSON 对象")
    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        raise ValueError(f"导入文件缺少必要字段: {', '.join(missing)}")


# ---------- 公开 API ----------


def export_config(
    config_manager: ConfigManager,
    output_path: str | Path,
    password: str | None = None,
    include_tasks: bool = True,
) -> Path:
    """将 ConfigManager 中的配置导出到文件。

    Args:
        config_manager: 配置管理器实例。
        output_path: 输出文件路径，建议使用 ``.yunxcfg`` 扩展名。
        password: 加密密码；为 ``None`` 时导出明文 JSON。
        include_tasks: 是否包含已保存的下载任务，默认 ``True``。

    Returns:
        实际写入的文件路径（``Path`` 对象）。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    export_data = _extract_export_data(config_manager, include_tasks=include_tasks)
    plaintext = json.dumps(export_data, ensure_ascii=False, indent=2).encode("utf-8")

    if password is not None:
        # 加密导出：base64(magic + salt + nonce + ciphertext+tag)
        payload = _encrypt_payload(plaintext, password)
        encoded = base64.b64encode(payload).decode("ascii")
        output_path.write_text(encoded, encoding="utf-8")
    else:
        # 明文导出：直接写 JSON
        output_path.write_bytes(plaintext)

    return output_path


def is_encrypted(input_path: str | Path) -> bool:
    """检测导出文件是否为加密格式。

    通过读取文件内容并 base64 解码后检查 magic header ``YNC1`` 来判断。

    Args:
        input_path: 待检测的文件路径。

    Returns:
        ``True`` 表示加密文件，``False`` 表示明文文件。
    """
    input_path = Path(input_path)
    try:
        content = input_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return False

    if not content:
        return False

    try:
        raw = base64.b64decode(content, validate=True)
    except (ValueError, base64.binascii.Error):
        # 不是有效的 base64，视为明文 JSON
        return False

    return raw.startswith(_MAGIC_HEADER)


def import_config(
    input_path: str | Path,
    password: str | None = None,
) -> dict[str, Any]:
    """从导出文件中读取配置数据。

    自动检测文件是否加密；加密文件必须提供正确密码。

    Args:
        input_path: 导出文件路径。
        password: 解密密码；明文文件可省略。

    Returns:
        解析后的配置字典，包含 ``credentials`` / ``settings`` / ``tasks`` / ``meta``。

    Raises:
        AuthenticationError: 加密文件密码错误。
        ValueError: 文件格式不完整或缺少必要字段。
        FileNotFoundError: 文件不存在。
    """
    input_path = Path(input_path)

    if is_encrypted(input_path):
        if password is None:
            raise AuthenticationError("该配置文件已加密，请提供密码")
        content = input_path.read_text(encoding="utf-8").strip()
        raw = base64.b64decode(content)
        plaintext_bytes = _decrypt_payload(raw, password)
        try:
            data = json.loads(plaintext_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"加密文件解密后不是有效的 JSON: {exc}") from exc
    else:
        # 明文文件
        try:
            content = input_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"文件不是有效的 JSON: {exc}") from exc

    _validate_imported_data(data)
    return data


def apply_imported_config(
    config_manager: ConfigManager,
    imported_data: dict[str, Any],
    merge: bool = True,
) -> None:
    """将导入的配置数据应用到 ConfigManager。

    Args:
        config_manager: 目标配置管理器。
        imported_data: 由 :func:`import_config` 返回的配置字典。
        merge: 合并模式。
            - ``True``：合并凭证（同名网盘新值覆盖旧值），合并设置；
            - ``False``：完全替换现有配置（清空后写入导入数据）。
    """
    _validate_imported_data(imported_data)

    credentials = imported_data.get("credentials", {})
    settings = imported_data.get("settings", {})
    tasks = imported_data.get("tasks", [])

    if merge:
        # 合并凭证
        existing_creds = config_manager._data.get("credentials", {})
        merged_creds = {**existing_creds, **credentials}
        config_manager._data["credentials"] = merged_creds

        # 合并设置
        for key, value in settings.items():
            config_manager._data[key] = value

        # 合并任务（去重：按 task id 或整体内容）
        existing_tasks = config_manager._data.get("tasks", [])
        if tasks:
            # 简单去重：如果任务有 id 字段则按 id 去重，否则按整体内容
            seen_ids: set[Any] = set()
            seen_contents: list[dict[str, Any]] = []
            combined: list[dict[str, Any]] = []

            for task in existing_tasks + tasks:
                task_id = task.get("id") if isinstance(task, dict) else None
                if task_id is not None:
                    if task_id in seen_ids:
                        continue
                    seen_ids.add(task_id)
                else:
                    if task in seen_contents:
                        continue
                    seen_contents.append(task)
                combined.append(task)

            config_manager._data["tasks"] = combined
    else:
        # 完全替换
        config_manager._data.clear()
        config_manager._data["credentials"] = dict(credentials)
        for key, value in settings.items():
            config_manager._data[key] = value
        if tasks:
            config_manager._data["tasks"] = list(tasks)

    config_manager.save()
