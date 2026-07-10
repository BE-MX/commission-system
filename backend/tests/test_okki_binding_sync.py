"""OKKI 用户候选同步（user_basic → ark_external_binding_candidates）测试"""

from sqlalchemy import text

from app.auth.models import ArkExternalBindingCandidate, ArkUser, ArkUserExternalBinding
from app.insight.external_binding_service import sync_okki_candidates


def _seed(db):
    db.execute(text(
        "INSERT INTO lsordertest.user_basic (user_id, full_name, nickname, user_mobile) VALUES "
        "('11858712', 'Diana', 'D', '13800000001'), "
        "('11858713', '', 'OnlyNick', '13800000002'), "
        "('11858714', 'AlreadyBound', NULL, NULL)"
    ))
    user = ArkUser(username="diana", password_hash="x", real_name="Diana", is_active=True)
    db.add(user)
    db.flush()
    db.add(ArkUserExternalBinding(
        ark_user_id=user.id, provider="okki",
        external_account_id="11858714", binding_status="active",
    ))
    db.commit()
    return user


def test_sync_okki_candidates(db):
    user = _seed(db)

    stats = sync_okki_candidates(db)
    assert stats == {
        "total": 3, "created": 2, "updated": 0,
        "skipped_bound": 1, "skipped_ignored": 0, "reactivated": 0,
    }

    cands = {
        c.external_account_id: c
        for c in db.query(ArkExternalBindingCandidate).filter_by(provider="okki").all()
    }
    assert set(cands) == {"11858712", "11858713"}
    # 姓名与 real_name 相同 → 自动带出建议用户
    assert cands["11858712"].suggested_user_id == user.id
    assert cands["11858712"].external_display_name == "Diana"
    # full_name 为空回退 nickname
    assert cands["11858713"].external_display_name == "OnlyNick"
    assert cands["11858713"].suggested_user_id is None
    assert cands["11858712"].source == "okki_user_basic"

    # 重跑幂等：全部走更新，不重复建行
    stats2 = sync_okki_candidates(db)
    assert stats2["created"] == 0 and stats2["updated"] == 2 and stats2["skipped_bound"] == 1
    assert db.query(ArkExternalBindingCandidate).filter_by(provider="okki").count() == 2

    # 已忽略的候选：不复活、单独计数不算"更新"
    cands["11858713"].candidate_status = "ignored"
    db.commit()
    stats3 = sync_okki_candidates(db)
    assert stats3["skipped_ignored"] == 1 and stats3["updated"] == 1
    assert cands["11858713"].candidate_status == "ignored"


def test_sync_reopens_candidate_after_unbind(db):
    from app.insight.external_binding_service import bind_candidate, delete_binding

    user = _seed(db)
    sync_okki_candidates(db)

    cand = db.query(ArkExternalBindingCandidate).filter_by(
        provider="okki", external_account_id="11858712"
    ).first()
    bind_candidate(db, cand.id, user.id, admin_user_id=1)
    db.commit()
    assert cand.candidate_status == "bound"

    # 解绑后重新同步 → 候选复位 pending，可走候选台重绑
    binding = db.query(ArkUserExternalBinding).filter_by(
        provider="okki", external_account_id="11858712"
    ).first()
    delete_binding(db, binding.id)
    db.commit()

    stats = sync_okki_candidates(db)
    assert stats["reactivated"] == 1
    assert cand.candidate_status == "pending"
