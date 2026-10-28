"""色板库公库/私库与色差仪测量：归属隔离、唯一性、统计口径、幂等与晋升。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.color import swatch_library_service as svc
from app.color.models import ColorPalette
from app.color.swatch_library_models import ColorLibraryEvent, ColorLibraryMeasurement
from app.core.time import beijing_now
from app.customer.models import CustomerAccount, CustomerAssignment
from app.system.models import SysDict

NOW = beijing_now().replace(microsecond=0)


def _user(db, username, perms):
    role = ArkRole(name=f"role-{username}", label=username)
    db.add(role)
    db.flush()
    for code in perms:
        p = db.query(ArkPermission).filter_by(code=code).one_or_none()
        if p is None:
            module, action = code.split(":", 1)
            p = ArkPermission(code=code, module=module, action=action, label=code)
            db.add(p)
            db.flush()
        role.permissions.append(p)
    user = ArkUser(username=username, password_hash="x", real_name=username, is_active=True, roles=[role])
    db.add(user)
    db.flush()
    return user, {"sub": str(user.id), "roles": [role.name], "permissions": list(perms)}


def _customer(db, code, name="Acme Hair"):
    row = CustomerAccount(
        customer_code=code, display_name=name, entity_type="registered_company",
        identity_status="verified", relationship_stage="qualified", relationship_stage_changed_at=NOW,
        relationship_stage_reason="test", record_status="active", identity_confidence=1,
        profile_completeness=80, profile_input_seq=0, primary_country_code="US",
    )
    db.add(row)
    db.flush()
    return row


def _assign(db, customer, user, role="primary"):
    row = CustomerAssignment(
        customer_id=customer.id, user_id=user.id, assignment_role=role, assignment_status="active",
        assignment_source="manual", effective_from=NOW - timedelta(days=1), operated_by=user.id,
    )
    db.add(row)
    db.flush()
    return row


SALES = ("color_library:read", "color_library:write")
ADMIN = ("color_library:read", "color_library:write", "color_library:admin")


@pytest.fixture
def world(db):
    alice, alice_t = _user(db, "alice", SALES)
    bob, bob_t = _user(db, "bob", SALES)
    admin, admin_t = _user(db, "colormgr", ADMIN)
    c1 = _customer(db, "C-SW-1", "Bellamy Hair")
    c2 = _customer(db, "C-SW-2", "Glamour Ltd")
    _assign(db, c1, alice)
    _assign(db, c2, bob)
    for i, (code, label) in enumerate([("head", "样本头部"), ("middle", "样本中部"), ("tail", "样本尾部")]):
        db.add(SysDict(type=svc.TAG_DICT_TYPE, code=code, label=label, sort=i, is_active=True))
    db.commit()
    return {"alice": (alice, alice_t), "bob": (bob, bob_t), "admin": (admin, admin_t), "c1": c1, "c2": c2}


def _private(db, token, customer, code="#1C", size=18, **kw):
    return svc.create_swatch(db, token, {"library_scope": "private", "customer_id": customer.id,
                                         "color_code": code, "size_value": size, "size_unit": "inch", **kw})


def _m(request_id, lab, **kw):
    return {"client_request_id": request_id, "source": "simulation", "lab": lab, "position_tag": "middle", **kw}


# ── 隔离 ──────────────────────────────────────────────────


def test_private_swatch_requires_customer_and_live_assignment(db, world):
    _, alice = world["alice"]
    with pytest.raises(HTTPException) as caught:
        svc.create_swatch(db, alice, {"library_scope": "private", "color_code": "#1", "size_value": 18})
    assert caught.value.status_code == 422
    with pytest.raises(HTTPException) as caught:
        _private(db, alice, world["c2"])  # bob 的客户
    assert caught.value.status_code == 404
    created = _private(db, alice, world["c1"])
    assert created["customer_id"] == world["c1"].id and created["stats"]["count"] == 0


def test_other_sales_cannot_see_private_swatch_and_list_is_scoped(db, world):
    _, alice = world["alice"]
    _, bob = world["bob"]
    sw = _private(db, alice, world["c1"])
    with pytest.raises(HTTPException) as caught:
        svc.get_swatch(db, bob, sw["id"])
    assert caught.value.status_code == 404
    assert svc.list_swatches(db, bob, scope="private")["total"] == 0
    assert svc.list_swatches(db, alice, scope="private")["total"] == 1
    customers = svc.list_my_customers(db, alice)["items"]
    assert [(c["customer_id"], c["swatch_count"], c["assignment_role"]) for c in customers] == [
        (world["c1"].id, 1, "primary")]


def test_transfer_moves_visibility_without_touching_swatch(db, world):
    alice_user, alice = world["alice"]
    bob_user, bob = world["bob"]
    sw = _private(db, alice, world["c1"])
    row = db.query(CustomerAssignment).filter_by(customer_id=world["c1"].id, user_id=alice_user.id).one()
    row.assignment_status, row.effective_to = "ended", NOW
    db.flush()
    _assign(db, world["c1"], bob_user)
    db.commit()
    assert svc.get_swatch(db, bob, sw["id"])["id"] == sw["id"]
    with pytest.raises(HTTPException):
        svc.get_swatch(db, alice, sw["id"])


def test_collaborator_can_measure(db, world):
    alice_user, alice = world["alice"]
    _, bob = world["bob"]
    _assign(db, world["c2"], alice_user, role="collaborator")
    db.commit()
    sw = _private(db, bob, world["c2"])
    out = svc.add_measurements(db, alice, sw["id"], [_m("r1", [30, 5, 9])])
    assert out["stats"]["count"] == 1


def test_token_permission_not_in_db_is_ignored(db, world):
    user, _ = _user(db, "stale", ("color_library:read",))
    _assign(db, world["c1"], user)
    db.commit()
    stale_token = {"sub": str(user.id), "roles": ["role-stale"], "permissions": list(SALES)}
    with pytest.raises(HTTPException) as caught:
        _private(db, stale_token, world["c1"])
    assert caught.value.status_code == 404


def test_public_library_admin_only_for_write(db, world):
    _, alice = world["alice"]
    _, admin = world["admin"]
    with pytest.raises(HTTPException) as caught:
        svc.create_swatch(db, alice, {"library_scope": "public", "color_code": "#1B", "size_value": 18})
    assert caught.value.status_code == 403
    pub = svc.create_swatch(db, admin, {"library_scope": "public", "color_code": "#1B", "size_value": 18})
    assert svc.get_swatch(db, alice, pub["id"])["can_write"] is False
    with pytest.raises(HTTPException):
        svc.add_measurements(db, alice, pub["id"], [_m("p1", [20, 1, 2])])


# ── 唯一性 ────────────────────────────────────────────────


def test_code_plus_size_unique_per_customer_normalized(db, world):
    _, alice = world["alice"]
    _, bob = world["bob"]
    _private(db, alice, world["c1"], code="#1C", size=18)
    with pytest.raises(HTTPException) as caught:
        _private(db, alice, world["c1"], code=" #1c ", size=18.0)
    assert caught.value.status_code == 409
    assert _private(db, alice, world["c1"], code="#1C", size=22)["size_value"] == 22
    assert _private(db, alice, world["c1"], code="#1C", size=18, size_unit="cm")["size_unit"] == "cm"
    assert _private(db, bob, world["c2"], code="#1C", size=18)["customer_id"] == world["c2"].id


# ── 测量与统计 ────────────────────────────────────────────


def test_stats_follow_cie2000_and_exclusion_recomputes(db, world):
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    labs = [[20.5, 1.6, 2.4], [20.9, 1.5, 2.2], [20.2, 1.9, 2.6]]
    out = svc.add_measurements(db, alice, sw["id"], [_m(f"r{i}", lab) for i, lab in enumerate(labs)])
    expected = svc.compute_stats(labs)
    assert out["stats"]["count"] == 3
    assert out["stats"]["avg_lab"] == pytest.approx([round(v, 2) for v in expected["avg"]], abs=0.006)
    assert out["stats"]["mean_de"] == pytest.approx(expected["mean_de"], abs=0.006)
    assert out["stats"]["max_de"] == pytest.approx(expected["max_de"], abs=0.006)
    assert [m["seq_no"] for m in out["measurements"]] == [1, 2, 3]

    worst = out["measurements"][2]["id"]
    out = svc.set_inclusion(db, alice, sw["id"], worst, False, "位置偏移")
    assert out["stats"]["count"] == 2
    assert out["stats"]["mean_de"] == pytest.approx(svc.compute_stats(labs[:2])["mean_de"], abs=0.006)
    assert worst not in [m["id"] for m in out["measurements"]]
    stored = db.get(ColorLibraryMeasurement, worst)
    assert float(stored.lab_l) == 20.2 and stored.exclude_reason == "位置偏移"
    assert db.query(ColorLibraryEvent).filter_by(swatch_id=sw["id"], event_type="excluded").count() == 1


def test_exclusion_reason_is_optional(db, world):
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    out = svc.add_measurements(db, alice, sw["id"], [_m("a", [30, 1, 2]), _m("b", [31, 1, 2])])
    target = out["measurements"][0]["id"]
    out = svc.set_inclusion(db, alice, sw["id"], target, False, "  ")
    assert out["stats"]["count"] == 1 and len(out["measurements"]) == 1
    assert db.get(ColorLibraryMeasurement, target).exclude_reason is None


def test_batch_records_do_not_change_standard_stats(db, world):
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    svc.add_measurements(db, alice, sw["id"], [_m("s1", [40, 2, 10]), _m("s2", [40.4, 2.2, 10.2])])
    out = svc.add_measurements(db, alice, sw["id"], [
        _m("b1", [38, 4, 9], record_type="batch", position_tag="head"),
        _m("b2", [40.3, 2.1, 10.1], record_type="batch"),
    ])
    assert out["stats"]["count"] == 2
    assert out["stats"]["avg_lab"] == pytest.approx([40.2, 2.1, 10.1], abs=0.006)
    b1, b2 = [m for m in out["measurements"] if m["record_type"] == "batch"]
    assert b1["position_tag"] == "head" and b1["position_label"] == "样本头部"
    assert b1["shift"] == ["偏黑缺白", "偏红缺绿", "偏蓝缺黄"]
    assert b1["de_ab"] == pytest.approx(svc.de76([38, 4, 9], [40.2, 2.1, 10.1]), abs=1e-6)
    assert b1["passed"] is False and b2["passed"] is True
    assert b2["shift"] == [None, None, None]
    bs = out["batch_stats"]
    assert bs["count"] == 2
    assert bs["std_avg_lab"] == out["stats"]["avg_lab"]
    assert bs["avg_de_ab"] == pytest.approx(svc.de76(bs["avg_lab"], bs["std_avg_lab"]), abs=1e-6)
    assert bs["mean_de_diff"] == pytest.approx(bs["mean_de"] - out["stats"]["mean_de"], abs=1e-6)


@pytest.mark.parametrize("tag", ["nowhere", None, "  "])
def test_position_tag_is_required_and_must_exist(db, world, tag):
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    with pytest.raises(HTTPException) as caught:
        svc.add_measurements(db, alice, sw["id"], [_m("x", [30, 1, 2], position_tag=tag)])
    assert caught.value.status_code == 422
    assert db.query(ColorLibraryMeasurement).filter_by(swatch_id=sw["id"]).count() == 0


def test_promotion_copies_only_standard_records(db, world):
    _, alice = world["alice"]
    _, admin = world["admin"]
    sw = _private(db, alice, world["c1"], code="#9Z")
    svc.add_measurements(db, alice, sw["id"], [_m("s", [41, 3, 8]), _m("b", [30, 3, 8], record_type="batch")])
    svc.request_promotion(db, alice, sw["id"])
    pub_id = svc.review_promotion(db, admin, sw["id"], True)["public_swatch_id"]
    assert [m["record_type"] for m in svc.get_swatch(db, admin, pub_id)["measurements"]] == ["standard"]


def test_single_measurement_has_no_spread(db, world):
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    out = svc.add_measurements(db, alice, sw["id"], [_m("only", [40, 5, 12])])
    assert out["stats"]["mean_de"] is None and out["stats"]["max_de"] is None
    assert out["verdict"] == "ok"


def test_compute_stats_matches_reference_de00():
    # Sharma 2005 reference pair #1: ΔE00 = 2.0425
    assert svc.de00([50.0, 2.6772, -79.7751], [50.0, 0.0, -82.7485]) == pytest.approx(2.0425, abs=1e-4)


def test_measurement_batch_is_idempotent_and_keeps_all_spaces(db, world):
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    item = _m("dup-1", [63.21, -12.78, 23.14], luv=[63.21, -15.1, 24.3], lch=[63.21, 26.4, 118.9],
              yxy=[31.4, 0.3012, 0.3554], cmyk=[22, 0, 40, 30], rgb=[180, 120, 90], raw_hex="AB44", device_sn="2410803317")
    first = svc.add_measurements(db, alice, sw["id"], [item])
    again = svc.add_measurements(db, alice, sw["id"], [item])
    assert first["created_count"] == 1 and again["created_count"] == 0
    m = again["measurements"][0]
    assert m["lab"] == [63.21, -12.78, 23.14]
    assert m["yxy"] == [31.4, 0.3012, 0.3554]
    assert m["cmyk"] == [22, 0, 40, 30] and m["rgb"] == [180, 120, 90]
    assert m["device_sn"] == "2410803317"


def test_measurement_rejects_out_of_range_bytes(db, world):
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    with pytest.raises(HTTPException) as caught:
        svc.add_measurements(db, alice, sw["id"], [_m("bad", [1, 2, 3], rgb=[0, 0, 300])])
    assert caught.value.status_code == 422


def test_measurement_timestamps_convert_to_beijing(db, world):
    """服务器非东八区时也以北京时间入库；UTC 23:30 是北京次日 07:30（跨日）。"""
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    utc = datetime(2026, 10, 27, 23, 30, tzinfo=timezone.utc)
    svc.add_measurements(db, alice, sw["id"], [_m("tz", [30, 1, 1], requested_at=utc, received_at=utc)])
    row = db.query(ColorLibraryMeasurement).filter_by(client_request_id="tz").one()
    assert row.requested_at == datetime(2026, 10, 28, 7, 30)
    assert row.received_at.tzinfo is None


def test_base_delta_uses_public_swatch_mean_then_palette(db, world):
    _, alice = world["alice"]
    _, admin = world["admin"]
    palette = ColorPalette(industry_code="#1B", display_name="Natural Black", hex_code="#2B2522",
                           rgb_r=43, rgb_g=37, rgb_b=34, lab_l=19.8, lab_a=1.4, lab_b_val=1.9, color_family="black")
    db.add(palette)
    db.commit()
    by_palette = _private(db, alice, world["c1"], code="#1C", base_palette_id=palette.id)
    out = svc.add_measurements(db, alice, by_palette["id"], [_m("a", [20.6, 1.6, 2.4])])
    assert out["stats"]["base_de"] == pytest.approx(svc.de00([20.6, 1.6, 2.4], [19.8, 1.4, 1.9]), abs=0.006)

    pub = svc.create_swatch(db, admin, {"library_scope": "public", "color_code": "#1B", "size_value": 18})
    svc.add_measurements(db, admin, pub["id"], [_m("p", [20.0, 1.5, 2.0])])
    by_swatch = _private(db, alice, world["c1"], code="#1C", size=22, base_swatch_id=pub["id"])
    out = svc.add_measurements(db, alice, by_swatch["id"], [_m("b", [21.0, 1.9, 2.8])])
    assert out["stats"]["base_de"] == pytest.approx(svc.de00([21.0, 1.9, 2.8], [20.0, 1.5, 2.0]), abs=0.006)
    tol_breach = svc.update_swatch(db, alice, by_swatch["id"], {"tolerance_de": 0.1})
    assert tol_breach["verdict"] == "warn"

    # 公库实测变化后，依赖它的私库对基准 ΔE 同步更新
    svc.add_measurements(db, admin, pub["id"], [_m("p2", [22.0, 1.9, 3.0])])
    refreshed = svc.get_swatch(db, alice, by_swatch["id"])
    assert refreshed["stats"]["base_de"] == pytest.approx(svc.de00([21.0, 1.9, 2.8], [21.0, 1.7, 2.5]), abs=0.006)


def test_private_base_must_be_public(db, world):
    _, alice = world["alice"]
    other = _private(db, alice, world["c1"], code="#2")
    with pytest.raises(HTTPException) as caught:
        _private(db, alice, world["c1"], code="#4", base_swatch_id=other["id"])
    assert caught.value.status_code == 422


# ── 晋升 ──────────────────────────────────────────────────


def test_promotion_copies_measurements_to_public_and_keeps_private(db, world):
    _, alice = world["alice"]
    _, admin = world["admin"]
    sw = _private(db, alice, world["c1"], code="BH-ASH-02")
    with pytest.raises(HTTPException):
        svc.request_promotion(db, alice, sw["id"])  # 未测量
    svc.add_measurements(db, alice, sw["id"], [_m("x1", [41, 3, 8]), _m("x2", [41.4, 3.2, 8.3])])
    assert svc.request_promotion(db, alice, sw["id"])["promotion_status"] == "pending"
    with pytest.raises(HTTPException):
        svc.review_promotion(db, alice, sw["id"], True)
    assert [i["id"] for i in svc.list_promotions(db, admin)["items"]] == [sw["id"]]
    result = svc.review_promotion(db, admin, sw["id"], True)
    pub = svc.get_swatch(db, alice, result["public_swatch_id"])
    assert pub["library_scope"] == "public" and pub["customer_id"] is None
    assert pub["stats"]["count"] == 2
    assert svc.get_swatch(db, alice, sw["id"])["stats"]["count"] == 2
    with pytest.raises(HTTPException):
        svc.review_promotion(db, admin, sw["id"], True)


def test_archived_swatch_rejects_new_measurements(db, world):
    _, alice = world["alice"]
    sw = _private(db, alice, world["c1"])
    svc.archive_swatch(db, alice, sw["id"])
    assert svc.list_swatches(db, alice, scope="private")["total"] == 0
    with pytest.raises(HTTPException) as caught:
        svc.add_measurements(db, alice, sw["id"], [_m("late", [1, 1, 1])])
    assert caught.value.status_code == 409
