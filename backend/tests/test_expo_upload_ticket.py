"""展会扫码上传：令牌签发/校验 + 待取文件（2026-08-01）。

令牌不落库，customer_id 与过期时间明文随令牌传输，靠 HMAC 防篡改。
"""

import time

import pytest

from app.core.config import Settings, get_settings
from app.expo import ai_pipeline, upload_service

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


class TestPendingFiles:
    @pytest.fixture(autouse=True)
    def _isolate_pending_dir(self, tmp_path, monkeypatch):
        """待取目录指向 tmp，避免测试污染真实 uploads/expo/pending。"""
        monkeypatch.setattr(upload_service, "PENDING_DIR", tmp_path / "pending")

    @staticmethod
    def _jpeg_bytes(size=(80, 120)):
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", size, (120, 90, 70)).save(buf, "JPEG")
        return buf.getvalue()

    def test_save_pending_writes_file_named_for_customer(self):
        name = upload_service.save_pending(42, self._jpeg_bytes(), "my photo.JPG")
        assert name.startswith("c42_")
        assert name.endswith(".jpg")
        assert (upload_service.PENDING_DIR / name).exists()

    def test_save_pending_rejects_non_image(self):
        with pytest.raises(ValueError, match="不是有效的图片"):
            upload_service.save_pending(42, b"definitely-not-an-image", "x.jpg")

    def test_save_pending_rejects_oversize(self):
        oversize = b"\xff" * (upload_service.MAX_UPLOAD_BYTES + 1)
        with pytest.raises(ValueError, match="过大"):
            upload_service.save_pending(42, oversize, "big.jpg")

    def test_save_pending_downscales_large_image(self):
        from PIL import Image

        name = upload_service.save_pending(42, self._jpeg_bytes((4000, 3000)), "p.jpg")
        with Image.open(upload_service.PENDING_DIR / name) as im:
            assert max(im.size) <= ai_pipeline.UPLOAD_MAX_EDGE

    def test_latest_pending_returns_newest_of_many(self):
        import os

        first = upload_service.save_pending(42, self._jpeg_bytes(), "a.jpg")
        second = upload_service.save_pending(42, self._jpeg_bytes(), "b.jpg")
        # mtime 分辨率在部分文件系统上不足以区分同秒写入，显式拉开
        os.utime(upload_service.PENDING_DIR / first, (time.time() - 60,) * 2)
        assert upload_service.latest_pending(42).name == second

    def test_latest_pending_ignores_other_customers(self):
        upload_service.save_pending(99, self._jpeg_bytes(), "other.jpg")
        assert upload_service.latest_pending(42) is None

    def test_latest_pending_none_when_empty(self):
        assert upload_service.latest_pending(42) is None

    def test_resolve_pending_blocks_path_traversal(self):
        with pytest.raises(ValueError, match="非法"):
            upload_service.resolve_pending(42, "../../etc/passwd")

    def test_resolve_pending_blocks_other_customers_file(self):
        name = upload_service.save_pending(99, self._jpeg_bytes(), "x.jpg")
        with pytest.raises(ValueError, match="不属于该客户"):
            upload_service.resolve_pending(42, name)

    def test_resolve_pending_missing_file(self):
        with pytest.raises(ValueError, match="不存在"):
            upload_service.resolve_pending(42, "c42_deadbeef.jpg")

    def test_sweep_stale_removes_only_expired(self):
        import os

        fresh = upload_service.save_pending(42, self._jpeg_bytes(), "fresh.jpg")
        stale = upload_service.save_pending(42, self._jpeg_bytes(), "stale.jpg")
        old = time.time() - upload_service.STALE_AFTER_SECONDS - 60
        os.utime(upload_service.PENDING_DIR / stale, (old, old))

        assert upload_service.sweep_stale() == 1
        assert (upload_service.PENDING_DIR / fresh).exists()
        assert not (upload_service.PENDING_DIR / stale).exists()

    def test_sweep_stale_survives_missing_dir(self):
        """目录尚未创建时清理不得抛异常——它挂在发码路径上，抛了就发不出码。"""
        assert upload_service.sweep_stale() == 0
