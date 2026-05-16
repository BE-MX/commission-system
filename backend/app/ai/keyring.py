"""AI Provider API Key 加密/解密 (AES-256-GCM, base64 占位 fallback)

设计原则:
- production 模式下 Settings 强制要求 ARK_AI_ENCRYPTION_KEY 显式配置 (见 core/config.py 校验)
- dev 模式无环境变量时 fallback 到一个默认占位串,加密会退化为 base64
- 解密保留双轨能力,以兼容历史用 base64 占位写入的数据
"""

import base64
import os
from typing import Optional

_ARK_AI_ENCRYPTION_KEY: Optional[str] = None


def _get_encryption_key() -> str:
    """获取加密密钥。模块级缓存,首次调用读环境变量。"""
    global _ARK_AI_ENCRYPTION_KEY
    if _ARK_AI_ENCRYPTION_KEY is None:
        key = os.environ.get("ARK_AI_ENCRYPTION_KEY", "")
        if not key:
            # dev 环境占位,AES 会因 key 长度不足退化到 base64 fallback
            _ARK_AI_ENCRYPTION_KEY = base64.b64encode(b"ark_ai_default_key_32_bytes_").decode()
        else:
            _ARK_AI_ENCRYPTION_KEY = key
    return _ARK_AI_ENCRYPTION_KEY


def encrypt_key(plaintext: Optional[str]) -> Optional[str]:
    """加密 api_key。优先 AES-256-GCM,cryptography 缺失或异常时回退到 base64。"""
    if not plaintext:
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key_b64 = _get_encryption_key()
        key = base64.b64decode(key_b64)
        iv = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
        raw = iv + ciphertext
        return base64.b64encode(raw).decode("ascii")
    except ImportError:
        return base64.b64encode(plaintext.encode()).decode()
    except Exception:
        return base64.b64encode(plaintext.encode()).decode()


def decrypt_key(encrypted: Optional[str]) -> Optional[str]:
    """解密 api_key。支持 AES-256-GCM 与历史 base64 占位双轨。"""
    if not encrypted:
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key_b64 = _get_encryption_key()
        key = base64.b64decode(key_b64)
        raw = base64.b64decode(encrypted)
        iv = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        return plaintext.decode("utf-8")
    except ImportError:
        return base64.b64decode(encrypted).decode()
    except Exception:
        # 解密失败可能是 base64 占位格式
        try:
            return base64.b64decode(encrypted).decode()
        except Exception:
            return encrypted
