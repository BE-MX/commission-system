"""展会扫码上传：令牌签发/校验 + 待取文件（2026-08-01）。

令牌不落库，customer_id 与过期时间明文随令牌传输，靠 HMAC 防篡改。
"""

import time

import pytest

from app.core.config import Settings, get_settings
from app.expo import upload_service

_DEFAULT_SECRET = Settings.model_fields["EXPO_UPLOAD_SIGN_SECRET"].default


@pytest.fixture(autouse=True)
def _non_default_secret(monkeypatch):
    """功能测试统一钉死成一个非默认密钥，不依赖 backend/.env 里配没配这个变量——
    默认值本身的行为单独在 TestSecretIsDefault 里测，且显式 monkeypatch 回默认值
    （同 tests/test_domestic_wxacode.py 的 _non_default_secret 套路）。"""
    monkeypatch.setattr(get_settings(), "EXPO_UPLOAD_SIGN_SECRET", "unit-test-secret-not-default")


class TestToken:
    def test_roundtrip_returns_customer_id(self):
        token = upload_service.make_token(42)
        assert upload_service.parse_token(token) == 42

    def test_negative_customer_id_round_trips(self):
        """customer_id 本身可能带负号，令牌里就有两个"-"歧义来源；
        parse_token 必须从右只切两刀（rsplit(-, 2)）才能正确还原。"""
        token = upload_service.make_token(-5)
        assert upload_service.parse_token(token) == -5

    def test_expired_token_rejected(self):
        token = upload_service.make_token(42, ttl_seconds=-1)
        with pytest.raises(ValueError, match="已过期"):
            upload_service.parse_token(token)

    def test_tampered_customer_id_rejected(self):
        _, exp, sig = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="无效"):
            upload_service.parse_token(f"99-{exp}-{sig}")

    def test_tampered_expiry_rejected(self):
        cid, exp, sig = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="无效"):
            upload_service.parse_token(f"{cid}-{int(exp) + 600}-{sig}")

    def test_tampered_signature_rejected(self):
        cid, exp, _ = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="无效"):
            upload_service.parse_token(f"{cid}-{exp}-0000000000000000")

    def test_non_ascii_signature_rejected_as_value_error(self):
        """hmac.compare_digest 遇到非 ASCII 字符会抛 TypeError 而不是 ValueError；
        这个端点完全免登录，一条乱码 URL 不该把 500 甩给顾客。签名段必须先过
        形状校验（16 位十六进制）再进 compare_digest。"""
        cid, exp, _ = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="无效"):
            upload_service.parse_token(f"{cid}-{exp}-{'é' * 16}")

    @pytest.mark.parametrize("bad", ["", "abc", "1-2", "1-2-3-4", "x-y-z"])
    def test_malformed_token_rejected(self, bad):
        with pytest.raises(ValueError, match="无效"):
            upload_service.parse_token(bad)

    def test_expiry_checked_before_signature(self):
        """过期先于签名校验：即便签名也被篡改成合法形状但错误的值，过期令牌
        仍必须报「已过期」而不是「无效」。这不是防泄密——exp 本就是攻击者自己
        拼出来的明文，顺序换了也不会多泄露什么；纯粹是体验取舍：一个确实
        过期的码，值得那句"回展位重新获取"的可操作提示，而不是笼统的「无效」。"""
        token = upload_service.make_token(42, ttl_seconds=-1)
        cid, exp, _ = token.split("-")
        tampered = f"{cid}-{exp}-{'0' * 16}"
        with pytest.raises(ValueError, match="已过期"):
            upload_service.parse_token(tampered)

    def test_default_ttl_is_ten_minutes(self):
        before = int(time.time())
        _, exp, _ = upload_service.make_token(7).split("-")
        assert int(exp) - before in (600, 601)

    def test_changing_secret_invalidates_existing_token(self, monkeypatch):
        """签名必须真的用密钥算——把 _sign 换成不带密钥的哈希，全部前面的用例
        照样全绿；只有换密钥后重新校验旧令牌才能戳穿这种"假签名"实现。"""
        token = upload_service.make_token(42)
        monkeypatch.setattr(get_settings(), "EXPO_UPLOAD_SIGN_SECRET", "a-different-deployment-secret")
        with pytest.raises(ValueError, match="无效"):
            upload_service.parse_token(token)


class TestSecretIsDefault:
    """密钥兜底判定：免登录端点的整个授权模型压在这个密钥上，默认值等于没锁。"""

    def test_true_on_repo_default_secret(self, monkeypatch):
        """显式钉回默认值再断言——不能靠"没人配过这个变量"这种环境侥幸，
        那条侥幸恰恰会在 C1 修复生效、真的配好 .env 的那台机器上碎。"""
        monkeypatch.setattr(get_settings(), "EXPO_UPLOAD_SIGN_SECRET", _DEFAULT_SECRET)
        assert upload_service.secret_is_default() is True

    def test_false_once_overridden(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "EXPO_UPLOAD_SIGN_SECRET", "a-real-deployment-secret")
        assert upload_service.secret_is_default() is False
