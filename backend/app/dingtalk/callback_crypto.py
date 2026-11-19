"""钉钉 HTTP 事件回调加解密 — 签名校验、AES-CBC 解密与加密应答

协议（钉钉开放平台「HTTP 推送」）：
- 请求 query 带 signature（旧版为 msg_signature）、timestamp（毫秒）、nonce，body 为 {"encrypt": "..."}
- 签名 = sha1(sorted([token, timestamp, nonce, encrypt]) 依次拼接).hexdigest()
- 密钥 = base64decode(aes_key + "=")，32 字节；IV 取密钥前 16 字节；PKCS#7 按 32 字节补位
- 明文 = 16 字节随机串 + 4 字节大端消息长度 + 消息 JSON + 接收方 ID（企业内部应用为 AppKey）
- 应答必须是同样加密的 "success"，否则钉钉判定推送失败
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_BLOCK_SIZE = 32
# 签名覆盖 timestamp，超出窗口的请求即使签名正确也拒绝，限制重放
MAX_TIMESTAMP_SKEW_MS = 10 * 60 * 1000


class CallbackCryptoError(ValueError):
    """回调验签或解密失败；message 只含原因代码，不含密文或密钥"""


def _signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    return hashlib.sha1("".join(sorted([token, timestamp, nonce, encrypt])).encode("utf-8")).hexdigest()


class DingTalkCallbackCrypto:
    def __init__(self, token: str, aes_key: str, receiver_id: str):
        if not token or not aes_key or not receiver_id:
            raise CallbackCryptoError("not_configured")
        try:
            key = base64.b64decode(aes_key + "=")
        except (ValueError, TypeError) as exc:
            raise CallbackCryptoError("invalid_aes_key") from exc
        if len(aes_key) != 43 or len(key) != 32:
            raise CallbackCryptoError("invalid_aes_key")
        self._token = token
        self._key = key
        self._receiver_id = receiver_id

    def decrypt(self, signature: str, timestamp: str, nonce: str, encrypt: str, *, now_ms: int | None = None) -> dict:
        """验签 + 时间窗 + 解密 + 接收方校验，返回事件 JSON"""
        if not signature or not timestamp or not nonce or not encrypt:
            raise CallbackCryptoError("missing_params")
        # compare_digest 遇非 ASCII str 会抛 TypeError，统一比较 bytes
        expected = _signature(self._token, timestamp, nonce, encrypt).encode("utf-8")
        if not hmac.compare_digest(expected, signature.encode("utf-8")):
            raise CallbackCryptoError("bad_signature")
        try:
            sent_ms = int(timestamp)
        except ValueError as exc:
            raise CallbackCryptoError("bad_timestamp") from exc
        current = now_ms if now_ms is not None else int(time.time() * 1000)
        if abs(current - sent_ms) > MAX_TIMESTAMP_SKEW_MS:
            raise CallbackCryptoError("stale_timestamp")

        # 签名已覆盖原始串；官方 SDK 用 encodebytes 可能带换行，这里宽松解码
        try:
            data = base64.b64decode(encrypt)
        except (ValueError, TypeError) as exc:
            raise CallbackCryptoError("bad_ciphertext") from exc
        if not data or len(data) % 16:
            raise CallbackCryptoError("bad_ciphertext")
        decryptor = Cipher(algorithms.AES(self._key), modes.CBC(self._key[:16])).decryptor()
        plain = decryptor.update(data) + decryptor.finalize()
        pad = plain[-1]
        if pad < 1 or pad > _BLOCK_SIZE or plain[-pad:] != bytes([pad]) * pad:
            raise CallbackCryptoError("bad_padding")
        plain = plain[:-pad]
        if len(plain) < 20:
            raise CallbackCryptoError("bad_payload")
        (msg_len,) = struct.unpack(">I", plain[16:20])
        msg = plain[20 : 20 + msg_len]
        receiver = plain[20 + msg_len :]
        if len(msg) != msg_len or not hmac.compare_digest(receiver, self._receiver_id.encode("utf-8")):
            raise CallbackCryptoError("receiver_mismatch")
        try:
            event = json.loads(msg.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CallbackCryptoError("bad_payload") from exc
        if not isinstance(event, dict):
            raise CallbackCryptoError("bad_payload")
        return event

    def encrypt(self, message: str, *, timestamp: str | None = None, nonce: str | None = None) -> dict:
        """生成钉钉要求的加密应答体"""
        msg = message.encode("utf-8")
        plain = os.urandom(16) + struct.pack(">I", len(msg)) + msg + self._receiver_id.encode("utf-8")
        pad = _BLOCK_SIZE - len(plain) % _BLOCK_SIZE
        plain += bytes([pad]) * pad
        encryptor = Cipher(algorithms.AES(self._key), modes.CBC(self._key[:16])).encryptor()
        encrypt = base64.b64encode(encryptor.update(plain) + encryptor.finalize()).decode("ascii")
        ts = timestamp or str(int(time.time() * 1000))
        nc = nonce or secrets.token_hex(8)
        return {
            "msg_signature": _signature(self._token, ts, nc, encrypt),
            "timeStamp": ts,
            "nonce": nc,
            "encrypt": encrypt,
        }
