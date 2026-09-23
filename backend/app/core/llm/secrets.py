"""API Key 的加密存储与掩码回显（B2-1）。

约定：
    * 落库一律 `encrypt_secret()` → `enc:v1:<fernet-token>`；
    * 读取用 `decrypt_secret()`，**兼容历史明文**（ai_configs.api_key_encrypted 就是明文），
      所以无需数据迁移；
    * 对外接口只回 `mask_secret()`（`sk-***1234`），永不回明文。

密钥派生：`settings.jwt_secret_key` 的 SHA256 → urlsafe base64（Fernet 要求 32 字节 key）。
换 jwt_secret_key 会导致已存密文解不开 —— 此时 `decrypt_secret()` 返回空串并告警，
调用方应重新保存一次 api_key（不会崩，只是该供应商暂时不可用）。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from app.config import get_settings

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    key = hashlib.sha256(get_settings().jwt_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(_PREFIX)


def encrypt_secret(plain: str) -> str:
    """明文 → 密文（幂等保护：已是密文则原样返回，避免二次加密）。"""
    if not plain:
        return ""
    if is_encrypted(plain):
        return plain
    return _PREFIX + _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(stored: str | None) -> str:
    """密文 → 明文；历史明文原样返回；密钥不匹配时返回空串并告警。"""
    if not stored:
        return ""
    if not is_encrypted(stored):
        return stored
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("API Key 解密失败（jwt_secret_key 是否换过？），请重新保存该供应商密钥")
        return ""


def mask_secret(plain: str | None) -> str:
    """掩码回显：`sk-***1234`（短密钥只保留末 4 位）。"""
    if not plain:
        return ""
    if len(plain) <= 8:
        return "***" + plain[-4:]
    return f"{plain[:3]}***{plain[-4:]}"


__all__ = ["decrypt_secret", "encrypt_secret", "is_encrypted", "mask_secret"]
