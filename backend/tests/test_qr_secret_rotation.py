"""QR_SIGN_SECRET 轮换过渡：旧密钥兜底的边界

2026-07-30 生产为进度码上线换了签名密钥，车间已打印的外贸/内贸报工卡
全部失效。兜底规则：登录后的报工扫码接受旧密钥（QR_SIGN_SECRET_LEGACY），
免登录的进度码永远只认当前密钥——这条边界破了，换钥就白换了。
"""

import pytest

from app.core.config import get_settings
from app.domestic import report_service as domestic_rs
from app.production import report_service as production_rs

NEW_SECRET = "rotated-new-secret-for-tests"
OLD_SECRET = "legacy-old-secret-for-tests"


@pytest.fixture(autouse=True)
def _rotated_secrets(monkeypatch):
    """模拟换钥后的生产：当前密钥是新值，旧密钥进了 LEGACY"""
    monkeypatch.setattr(get_settings(), "QR_SIGN_SECRET", NEW_SECRET)
    monkeypatch.setattr(get_settings(), "QR_SIGN_SECRET_LEGACY", OLD_SECRET)


# ── 外贸 ARK-P ────────────────────────────────────────


def test_production_old_card_still_verifies():
    old_code = f"ARK-P:7:{production_rs.generate_qr_sign(7, OLD_SECRET)}"
    assert production_rs.verify_qr_data(old_code) == (True, 7)


def test_production_new_card_verifies():
    assert production_rs.verify_qr_data(production_rs.generate_qr_data(7)) == (True, 7)


def test_production_forged_sign_still_rejected():
    assert production_rs.verify_qr_data("ARK-P:7:00000000")[0] is False


def test_production_fallback_off_when_legacy_unset(monkeypatch):
    monkeypatch.setattr(get_settings(), "QR_SIGN_SECRET_LEGACY", "")
    old_code = f"ARK-P:7:{production_rs.generate_qr_sign(7, OLD_SECRET)}"
    assert production_rs.verify_qr_data(old_code)[0] is False


# ── 内贸 ARK-D ────────────────────────────────────────


def test_domestic_old_card_still_verifies():
    old_code = f"ARK-D:9:{domestic_rs.generate_qr_sign(9, OLD_SECRET)}"
    assert domestic_rs.verify_qr_data(old_code) == (True, 9)


def test_domestic_new_card_verifies():
    assert domestic_rs.verify_qr_data(domestic_rs.generate_qr_data(9)) == (True, 9)


def test_domestic_fallback_off_when_legacy_unset(monkeypatch):
    monkeypatch.setattr(get_settings(), "QR_SIGN_SECRET_LEGACY", "")
    old_code = f"ARK-D:9:{domestic_rs.generate_qr_sign(9, OLD_SECRET)}"
    assert domestic_rs.verify_qr_data(old_code)[0] is False


# ── 免登录进度码：绝不吃旧密钥兜底 ────────────────────


def test_track_scene_never_accepts_legacy_secret():
    """进度码是免登录口子——旧密钥（很可能是进了 git 的默认值）签出的
    scene 必须被拒，否则换钥等于没换"""
    legacy_scene = f"i:9:{domestic_rs.generate_track_scene_sign(9, OLD_SECRET)}"
    assert domestic_rs.verify_track_scene(legacy_scene)[0] is False
    # 当前密钥签的照常通过
    assert domestic_rs.verify_track_scene(domestic_rs.generate_track_scene(9)) == (True, 9)
