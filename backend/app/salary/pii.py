"""薪资敏感字段（身份证 / 银行卡）的加密、哈希与脱敏。

三个函数各管一件事，不要混用：
- `encrypt_pii` / `decrypt_pii`：AES-256-GCM，随机 IV，**只用于存储与展示**
- `hash_pii`：HMAC-SHA256，确定性输出，**唯一约束与导入匹配只能走这个**
- `mask_pii`：界面与导出默认形态

为什么必须两列并存：AES-GCM 每次加密的 IV 随机，同一张银行卡两次入库密文不同，
既做不了 UNIQUE 索引也没法跟社保表的明文身份证 JOIN。哈希列补上这个能力，
密文列负责「需要时能还原明文」（银行代发盘）。对应设计文档 §4 与 §2.5 错误 2/3/4。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Optional


class SalaryKeyNotConfigured(RuntimeError):
    """薪资 PII 密钥未配置。写入路径必须硬失败，不许回落占位密钥。"""


def _keys() -> tuple[bytes, bytes]:
    """取加密密钥与哈希密钥。**未配置就抛错，不回落占位串。**

    为什么不给 dev 兜底（2026-08-06 自查发现并修正）：开发机与生产共用同一套 RDS
    （见 CLAUDE.md 技术栈节）。若 dev 用仓库里写死的占位密钥写入真实身份证/银行卡：
    1. 密文等同明文——密钥躺在 git 里，加密形同虚设；
    2. 生产后来配上真钥，占位密钥写的行既解不开、哈希也全变——唯一约束失效、
       M2 社保导入按哈希匹配全部落空，且是静默的。
    宁可建档时报错让人去配 .env，也不能悄悄写一批毒数据进共享库。

    共享库的推论：dev 与生产的 .env 必须配**完全相同**的两把钥匙，否则同一张身份证
    在两边算出不同哈希，唯一约束与导入匹配都会错。
    """
    from app.core.config import get_settings

    settings = get_settings()
    raw_enc = settings.ARK_SALARY_ENCRYPTION_KEY
    raw_hash = settings.ARK_SALARY_HASH_KEY
    if not raw_enc or not raw_hash:
        missing = [
            name
            for name, val in (
                ("ARK_SALARY_ENCRYPTION_KEY", raw_enc),
                ("ARK_SALARY_HASH_KEY", raw_hash),
            )
            if not val
        ]
        raise SalaryKeyNotConfigured(
            f"薪资 PII 密钥未配置：{', '.join(missing)}。请在 backend/.env 补齐"
            "（开发机与生产共用同一套库，两边必须配相同的值，否则哈希对不上）。"
            "生成：python -c \"import os,base64;print(base64.b64encode(os.urandom(32)).decode())\""
        )
    try:
        enc_key = base64.b64decode(raw_enc)
    except Exception:
        enc_key = raw_enc.encode("utf-8")
    if len(enc_key) not in (16, 24, 32):
        # 长度不合规时派生稳定的 32 字节；此时密钥是"人配错了"而非"没配"，
        # 派生保证同一份配置永远得到同一把钥匙，不会导致数据前后不一致。
        enc_key = hashlib.sha256(enc_key).digest()
    return enc_key, raw_hash.encode("utf-8")


def normalize_id_card(value: Optional[str]) -> str:
    """身份证归一化：去空格、末位 x 统一大写。哈希前必须过这一层。"""
    if not value:
        return ""
    return str(value).strip().replace(" ", "").upper()


def normalize_bank_card(value: Optional[str]) -> str:
    """银行卡归一化：只留数字（HR 表里常带空格或撇号前缀）。"""
    if not value:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def hash_pii(value: Optional[str]) -> Optional[str]:
    """HMAC-SHA256 十六进制摘要。唯一约束、查重、跨表匹配都用它。"""
    if not value:
        return None
    _, hash_key = _keys()
    return hmac.new(hash_key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_pii(plaintext: Optional[str]) -> Optional[str]:
    """AES-256-GCM 加密，输出 base64(iv + ciphertext)。cryptography 缺失时抛错。

    不做 base64 降级：薪资 PII 静默存成明文是合规事故，宁可启动即失败。
    """
    if not plaintext:
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    enc_key, _ = _keys()
    iv = os.urandom(12)
    ciphertext = AESGCM(enc_key).encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(iv + ciphertext).decode("ascii")


def decrypt_pii(encrypted: Optional[str]) -> Optional[str]:
    """解密。失败返回 None 而非抛错——单行密文损坏不应让整张表打不开。"""
    if not encrypted:
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        enc_key, _ = _keys()
        raw = base64.b64decode(encrypted)
        return AESGCM(enc_key).decrypt(raw[:12], raw[12:], None).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 — 记录后降级，不阻断列表查询
        import logging

        logging.getLogger(__name__).warning("薪资 PII 解密失败: %s", exc)
        print(f"[salary.pii] decrypt failed: {exc}", flush=True)
        return None


def mask_pii(value: Optional[str], keep_head: int = 3, keep_tail: int = 4) -> str:
    """脱敏：保留头尾，中间打星。界面与导出默认形态。"""
    if not value:
        return ""
    s = str(value)
    if len(s) <= keep_head + keep_tail:
        return "*" * len(s)
    return f"{s[:keep_head]}{'*' * (len(s) - keep_head - keep_tail)}{s[-keep_tail:]}"
