"""
配置管理：用户凭证使用 AES-GCM 加密存储。

加密流程：
1. 用户主密码通过 PBKDF2-HMAC-SHA256（100000 次迭代）派生 32 字节密钥。
2. 每条凭证使用独立的 12 字节随机 nonce 进行 AES-GCM 加密。
3. 密文格式：``base64(nonce + ciphertext + tag)``。

配置文件路径：``~/.yunx/config.enc``
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from .exceptions import AuthenticationError

# PBKDF2 迭代次数
_PBKDF2_ITERATIONS = 100_000
# AES-256 密钥长度
_KEY_LENGTH = 32
# GCM nonce 长度（96 bit，NIST 推荐）
_NONCE_LENGTH = 12
# 配置文件默认路径
_DEFAULT_CONFIG_PATH = Path.home() / ".yunx" / "config.enc"
# 盐值文件路径（与配置同目录，用于 PBKDF2）
_SALT_PATH = Path.home() / ".yunx" / "salt.bin"
# 盐值长度
_SALT_LENGTH = 16


def _derive_key(password: str, salt: bytes) -> bytes:
    """通过 PBKDF2-HMAC-SHA256 从用户密码派生加密密钥。

    Args:
        password: 用户主密码。
        salt: 盐值（16 字节）。

    Returns:
        32 字节 AES-256 密钥。
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def _load_or_create_salt(path: Path = _SALT_PATH) -> bytes:
    """加载盐值；不存在则生成并持久化。

    Args:
        path: 盐值文件路径。

    Returns:
        16 字节盐值。
    """
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(_SALT_LENGTH)
    path.write_bytes(salt)
    return salt


class ConfigManager:
    """加密配置管理器。

    支持各网盘独立凭证管理，所有敏感字段在落盘前均经 AES-GCM 加密。

    Example::

        cfg = ConfigManager("my_master_password")
        cfg.set_credential("quark", {"cookie": "__pus=...; __puus=..."})
        cookie = cfg.get_credential("quark")["cookie"]
    """

    def __init__(
        self,
        password: str,
        config_path: Path | str | None = None,
        salt_path: Path | str | None = None,
    ) -> None:
        """初始化配置管理器。

        Args:
            password: 用户主密码，用于派生加密密钥。
            config_path: 配置文件路径，默认 ``~/.yunx/config.enc``。
            salt_path: 盐值文件路径，默认 ``~/.yunx/salt.bin``。
        """
        self._config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self._salt = _load_or_create_salt(Path(salt_path) if salt_path else _SALT_PATH)
        self._key = _derive_key(password, self._salt)
        self._aesgcm = AESGCM(self._key)
        self._data: dict[str, Any] = {}
        self._load()

    # ---------- 加密 / 解密 ----------

    def _encrypt(self, plaintext: str) -> str:
        """加密字符串，返回 base64(nonce + ciphertext+tag)。"""
        nonce = os.urandom(_NONCE_LENGTH)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def _decrypt(self, encoded: str) -> str:
        """解密 base64(nonce + ciphertext+tag)。"""
        raw = base64.b64decode(encoded.encode("ascii"))
        nonce, ct = raw[:_NONCE_LENGTH], raw[_NONCE_LENGTH:]
        return self._aesgcm.decrypt(nonce, ct, None).decode("utf-8")

    # ---------- 持久化 ----------

    def _load(self) -> None:
        """从磁盘加载并解密配置；文件不存在则初始化为空。"""
        if not self._config_path.exists():
            self._data = {}
            return
        try:
            encoded = self._config_path.read_text(encoding="utf-8").strip()
            plaintext = self._decrypt(encoded)
            self._data = json.loads(plaintext)
        except Exception as exc:
            raise AuthenticationError(
                f"配置文件解密失败，可能是主密码错误或文件已损坏: {exc}"
            ) from exc

    def save(self) -> None:
        """将当前配置加密后写入磁盘。"""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(self._data, ensure_ascii=False, indent=2)
        encoded = self._encrypt(plaintext)
        # 写入临时文件再原子替换，避免中途损坏
        tmp = self._config_path.with_suffix(".tmp")
        tmp.write_text(encoded, encoding="utf-8")
        tmp.replace(self._config_path)

    # ---------- 凭证管理 ----------

    def set_credential(self, drive: str, credential: dict[str, Any]) -> None:
        """设置指定网盘的凭证。

        Args:
            drive: 网盘标识（如 ``"quark"``、``"pan123"``、``"xunlei"``）。
            credential: 凭证字典（如 ``{"cookie": "..."}`` 或 ``{"access_token": "..."}``）。
        """
        if "credentials" not in self._data:
            self._data["credentials"] = {}
        self._data["credentials"][drive] = credential
        self.save()

    def get_credential(self, drive: str) -> dict[str, Any] | None:
        """获取指定网盘的凭证。

        Args:
            drive: 网盘标识。

        Returns:
            凭证字典；不存在时返回 ``None``。
        """
        return self._data.get("credentials", {}).get(drive)

    def remove_credential(self, drive: str) -> None:
        """删除指定网盘的凭证。"""
        creds = self._data.get("credentials", {})
        if drive in creds:
            del creds[drive]
            self.save()

    def list_drives(self) -> list[str]:
        """列出已保存凭证的网盘标识。"""
        return list(self._data.get("credentials", {}).keys())

    # ---------- 通用配置 ----------

    def set(self, key: str, value: Any) -> None:
        """设置通用配置项。"""
        self._data[key] = value
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        """获取通用配置项。"""
        return self._data.get(key, default)
