"""展会扫码上传：令牌签发/校验 + 待取文件（2026-08-01）。

令牌不落库，customer_id 与过期时间明文随令牌传输，靠 HMAC 防篡改。
"""

import time

import pytest

from app.expo import upload_service


class TestToken:
    def test_roundtrip_returns_customer_id(self):
        token = upload_service.make_token(42)
        assert upload_service.parse_token(token) == 42

    def test_expired_token_rejected(self):
        token = upload_service.make_token(42, ttl_seconds=-1)
        with pytest.raises(ValueError, match="已过期"):
            upload_service.parse_token(token)

    def test_tampered_customer_id_rejected(self):
        _, exp, sig = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="校验失败"):
            upload_service.parse_token(f"99-{exp}-{sig}")

    def test_tampered_expiry_rejected(self):
        cid, exp, sig = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="校验失败"):
            upload_service.parse_token(f"{cid}-{int(exp) + 600}-{sig}")

    def test_tampered_signature_rejected(self):
        cid, exp, _ = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="校验失败"):
            upload_service.parse_token(f"{cid}-{exp}-0000000000000000")

    @pytest.mark.parametrize("bad", ["", "abc", "1-2", "1-2-3-4", "x-y-z"])
    def test_malformed_token_rejected(self, bad):
        with pytest.raises(ValueError, match="格式不正确"):
            upload_service.parse_token(bad)

    def test_expiry_checked_before_signature(self):
        """过期先于签名校验：过期令牌即使签名合法也不该泄露「签名对不对」的信息。"""
        token = upload_service.make_token(42, ttl_seconds=-1)
        with pytest.raises(ValueError, match="已过期"):
            upload_service.parse_token(token)

    def test_default_ttl_is_ten_minutes(self):
        before = int(time.time())
        _, exp, _ = upload_service.make_token(7).split("-")
        assert 595 <= int(exp) - before <= 605
