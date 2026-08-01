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
        """这条测的是端到端结果（干净 ValueError，不是 500），但要老实交代它实际
        走的是哪条防线：'é'*16 不满足 _SIGNATURE_RE 的 [0-9a-f]{16}，在形状校验
        这一步就被拒了，从未真正走到 hmac.compare_digest。这不是巧合而是结构性
        必然——凡是能通过 [0-9a-f]{16} 形状校验的字符串，本身就只含 ASCII 十六
        进制字符，compare_digest 不可能在这条路径上收到非 ASCII 输入。换句话说，
        形状校验一旦存在，就已经把"compare_digest 遇到非 ASCII 抛 TypeError"这类
        输入结构性地挡在门外，不需要再单独证明——没有办法在保留形状校验的前提下，
        构造一个"形状合法但非 ASCII"的签名段去真正触达 compare_digest。"""
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


class TestCanonicalToken:
    """I3：int() 对输入的宽容（前后空白含裸换行/"+"前缀/下划线分组/全角数字）
    意味着签名校验通过的合法令牌，原始字符串未必是能安全塞进 JS 单引号字面量的
    规范 ASCII。canonical_token 用解析出的 int 值重建，天生只含数字/连字符/
    十六进制字符——这里逐一验证"permissive int() 接受、但字面量不规范"的输入，
    canonical_token 都能重建回与 make_token 输出完全一致的规范形式。"""

    def test_accepts_and_normalizes_leading_newline(self):
        token = upload_service.make_token(42)
        cid, exp, sig = token.split("-")
        noisy = f"\n{cid}-{exp}-{sig}"
        assert upload_service.parse_token(noisy) == 42  # int() 的宽容让它照样校验通过
        assert upload_service.canonical_token(noisy) == token  # 重建回规范形式

    def test_accepts_and_normalizes_trailing_whitespace(self):
        token = upload_service.make_token(42)
        cid, exp, sig = token.split("-")
        noisy = f"{cid} \t-{exp}-{sig}"
        assert upload_service.parse_token(noisy) == 42
        assert upload_service.canonical_token(noisy) == token

    def test_accepts_and_normalizes_fullwidth_digits(self):
        token = upload_service.make_token(42)
        cid, exp, sig = token.split("-")
        fullwidth = cid.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
        noisy = f"{fullwidth}-{exp}-{sig}"
        assert upload_service.parse_token(noisy) == 42
        assert upload_service.canonical_token(noisy) == token

    def test_accepts_and_normalizes_underscore_digit_grouping(self):
        token = upload_service.make_token(1000)
        cid, exp, sig = token.split("-")
        noisy = f"1_000-{exp}-{sig}"
        assert upload_service.parse_token(noisy) == 1000
        assert upload_service.canonical_token(noisy) == token

    def test_rejects_expired_token_same_as_parse_token(self):
        token = upload_service.make_token(42, ttl_seconds=-1)
        with pytest.raises(ValueError, match="已过期"):
            upload_service.canonical_token(token)

    def test_rejects_invalid_token_same_as_parse_token(self):
        with pytest.raises(ValueError, match="无效"):
            upload_service.canonical_token("not-a-real-token")


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

    def test_save_pending_prunes_to_newest_k(self):
        """C1：一个有效令牌在 10 分钟窗口内可反复上传，二维码又贴在共享展位屏——
        "有人拿着有效令牌"是每个路过的人都成立的设计常态，不是攻击。若不裁剪，
        一个善意的客户端重试循环或恶意脚本都能在窗口内把云端展会实例（方舟全量
        部署）的磁盘写满。latest_pending 只读最新一张，keep 之外的纯属浪费——
        上传 keep+2 张后应只剩 keep 张，且最新一张必须还在。"""
        import os

        keep = upload_service.PENDING_KEEP_PER_CUSTOMER
        base = time.time() - 1000
        names = []
        for i in range(keep + 2):
            name = upload_service.save_pending(42, self._jpeg_bytes(), f"{i}.jpg")
            names.append(name)
            # 显式拉开 mtime：同一测试进程里连续调用可能落在同一时间片分辨率内，
            # 靠系统真实写入时间区分"谁最新"不够可靠
            stamp = base + i * 10
            os.utime(upload_service.PENDING_DIR / name, (stamp, stamp))

        remaining = {p.name for p in upload_service.PENDING_DIR.glob("c42_*")}
        assert len(remaining) == keep
        assert names[-1] in remaining  # 最新一张必须还在

    def test_save_pending_prune_ignores_other_customers(self):
        """裁剪按客户隔离：客户 A 传满 keep 张不该动客户 B 的待取照片。"""
        keep = upload_service.PENDING_KEEP_PER_CUSTOMER
        for i in range(keep + 2):
            upload_service.save_pending(42, self._jpeg_bytes(), f"{i}.jpg")
        other = upload_service.save_pending(99, self._jpeg_bytes(), "other.jpg")
        assert (upload_service.PENDING_DIR / other).exists()

    def test_save_pending_write_failure_is_clean_valueerror_and_leaves_no_partial_file(self, monkeypatch):
        """I2：写盘中途失败（磁盘满——见 C1、AV 锁库）不能在最终文件名上留下半截
        文件——那个文件名会被 latest_pending 认作"最新待取照片"、被 resolve_pending
        三道校验全部放行，kiosk 顾问会看到一张损坏图。原子写（tmp + os.replace）
        把这类失败收敛成客户可读的 ValueError，且不留任何同名残留（含临时文件）。"""
        def _boom(src, dst):
            raise OSError("simulated disk full during atomic replace")

        monkeypatch.setattr(upload_service.os, "replace", _boom)
        with pytest.raises(ValueError):
            upload_service.save_pending(42, self._jpeg_bytes(), "p.jpg")
        assert list(upload_service.PENDING_DIR.glob("c42_*")) == []
        assert list(upload_service.PENDING_DIR.glob(".tmp_*")) == []  # finally 清掉了临时文件

    def test_pending_tmp_file_not_picked_up_by_latest_pending(self):
        """I2 相关的命名陷阱：临时文件若叫 "c42_xxx.jpg.tmp"（最终名加后缀），会同时
        命中 latest_pending 的 "c{cid}_*" 与 sweep_stale 的 "c*" 两个 glob——孤儿 .tmp
        文件可能被误当正式待取照片提供给 kiosk。当前命名（.tmp_ 前缀，第一个字符
        就不是 "c"）结构性地避开这两处 glob，这里直接摆一个孤儿 .tmp 文件验证。"""
        upload_service.PENDING_DIR.mkdir(parents=True, exist_ok=True)
        (upload_service.PENDING_DIR / ".tmp_c42_deadbeef12.jpg").write_bytes(self._jpeg_bytes())
        assert upload_service.latest_pending(42) is None

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
        """粗粒度冒烟：basename 都对不上任何客户前缀，靠归属校验就能挡下来——
        真正戳穿"路径穿越守卫是否起作用"的是下面那条 sibling-directory 用例。"""
        with pytest.raises(ValueError, match="非法"):
            upload_service.resolve_pending(42, "../../etc/passwd")

    def test_resolve_pending_blocks_sibling_directory_traversal(self):
        """真实攻击面：展会永久试戴照片目录（app/expo/service.py 里的
        PHOTO_DIR）与待取目录（PENDING_DIR）是 UPLOAD_ROOT 下的平级目录，
        且两边用的是同一套 c{customer_id}_{uuid4().hex[:10]}{suffix} 命名。

        这意味着 "../photos/c42_<真实uuid>.jpg" 这个 payload 能直接通过归属
        校验（前缀对得上）和存在性校验（文件真实存在）——只有路径穿越校验
        （candidate.parent != root）能挡住它。上面那条 ../../etc/passwd 用例
        basename 连前缀都凑不上，归属校验单独就能拦下来，测不出这道最关键的
        守卫是否还在——这条才是。"""
        sibling = upload_service.PENDING_DIR.parent / "photos"
        sibling.mkdir(parents=True)
        (sibling / "c42_abcdef1234.jpg").write_bytes(self._jpeg_bytes())

        with pytest.raises(ValueError, match="非法"):
            upload_service.resolve_pending(42, "../photos/c42_abcdef1234.jpg")

    def test_resolve_pending_blocks_other_customers_file(self):
        name = upload_service.save_pending(99, self._jpeg_bytes(), "x.jpg")
        with pytest.raises(ValueError, match="不属于该客户"):
            upload_service.resolve_pending(42, name)

    def test_resolve_pending_missing_file(self):
        with pytest.raises(ValueError, match="不存在"):
            upload_service.resolve_pending(42, "c42_deadbeef.jpg")

    def test_resolve_pending_does_not_create_pending_dir(self):
        """纯查找不应有副作用：待取目录还不存在时，一次失败的 resolve 不该
        顺手把它建出来（同一目录树下 save_pending 才该建目录）。"""
        with pytest.raises(ValueError, match="不存在"):
            upload_service.resolve_pending(42, "c42_deadbeef.jpg")
        assert not upload_service.PENDING_DIR.exists()

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
        """目录尚未创建时清理不得抛异常——它挂在发码路径上，抛了就发不出码。

        注：当前 Python 的 Path.glob() 对不存在的目录直接返回空迭代器，
        所以这条测试对"提前 return"那行代码本身不是判定性的（删掉那行、
        全靠下面的 glob 也一样能让本用例通过）；它锁定的是函数级契约
        ——"目录不在＝返回 0、不抛异常"——这份契约现在由显式 return 与
        外层 try/except OSError 共同兜底，删掉任一个都不会让这条测试变红。"""
        assert upload_service.sweep_stale() == 0

    def test_sweep_stale_survives_listing_failure(self, monkeypatch):
        """glob() 本身抛出的 OSError 不能穿透函数边界——外层 try 必须把
        "迭代目录"这一步也纳入保护，不能只护住循环体内部的 unlink/stat。"""

        class _ExplodingDir:
            def exists(self):
                return True

            def glob(self, pattern):
                raise PermissionError("simulated AV lock contention")

        monkeypatch.setattr(upload_service, "PENDING_DIR", _ExplodingDir())
        assert upload_service.sweep_stale() == 0
