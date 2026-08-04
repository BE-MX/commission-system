"""采购节状态型事件测试：排名变化、里程碑、阵营超额与当日连击。"""

from app.festival import events_service
from app.festival.models import FestivalEvent, FestivalState  # noqa: F401


def _person(user_id: str, rank: int) -> dict:
    return {
        "user_id": user_id,
        "name": f"人员{user_id}",
        "new_points": 10 - rank,
        "new_amount": 1000 - rank,
        "first_count": 10 - rank,
        "re_amount": 1000 - rank,
    }


def _payload(sign_order=("A", "B", "C", "D"), *, new_total=14, camp_done=43,
             daily_orders=None):
    items = [_person(uid, idx) for idx, uid in enumerate(sign_order, start=1)]
    first_board = [dict(row) for row in items]
    amount_board = [dict(row) for row in items]
    teams = [
        {"name": name, "rank": idx, "total": 10 - idx, "avg": 10 - idx,
         "per_capita_re_amount": 1000 - idx}
        for idx, name in enumerate(("队一", "队二", "队三", "队四"), start=1)
    ]
    camps = [{
        "name": "阵营一", "done": camp_done, "req": 40,
        "members": [
            {**_person("A", 1), "is_top3": True, "is_first": False},
            {**_person("B", 2), "is_top3": False},
            {**_person("C", 3), "is_top3": False, "is_first": True},
            {**_person("D", 4), "is_top3": False, "is_first": False},
        ],
    }]
    return {
        "summary": {"new_total": new_total, "new_target": 149},
        "items": items,
        "camps": camps,
        "teams": teams,
        "first_board": first_board,
        "amount_board": amount_board,
        "daily_orders": daily_orders or {"A": [{"order_id": "O1", "amount": 100}]},
    }


def _detect(db, *, state_scope="okki", **payload):
    return events_service.detect_stateful_candidates(db, state_scope=state_scope, **payload)


def test_first_observation_only_builds_baseline(db):
    """首次部署不得补发已有排名、里程碑、超额档位或当天旧订单。"""
    candidates = _detect(db, **_payload())

    assert candidates == []
    assert db.query(FestivalState).count() > 0


def test_rank_rise_repeats_after_fall_and_reentry(db):
    """同一人跌落后再次上升仍应触发，dedup_key 必须与上一次不同。"""
    _detect(db, **_payload())

    first_rise = _detect(db, **_payload(sign_order=("B", "A", "C", "D")))
    assert [(c["event_type"], c["subject_id"]) for c in first_rise
            if c["event_type"] == "rank_up_sign"] == [("rank_up_sign", "B")]

    _detect(db, **_payload(sign_order=("A", "B", "C", "D")))
    second_rise = _detect(db, **_payload(sign_order=("B", "A", "C", "D")))
    b_events = [c for c in second_rise if c["event_type"] == "rank_up_sign"]

    assert len(b_events) == 1
    assert b_events[0]["dedup_key"] != next(
        c["dedup_key"] for c in first_rise if c["event_type"] == "rank_up_sign")
    assert "第2名 → 第1名" in b_events[0]["detail"]


def test_switching_data_source_builds_an_independent_baseline(db):
    _detect(db, **_payload())
    changed = _payload(sign_order=("B", "A", "C", "D"))
    assert any(c["event_type"] == "rank_up_sign" for c in _detect(db, **changed))

    assert _detect(db, state_scope="ark", **changed) == []


def test_each_leaderboard_emits_only_the_rising_subject(db):
    baseline = _payload()
    _detect(db, **baseline)

    changed = _payload()
    changed["first_board"] = [_person(uid, idx) for idx, uid in enumerate(("B", "A", "C", "D"), 1)]
    changed["amount_board"] = [_person(uid, idx) for idx, uid in enumerate(("C", "A", "B", "D"), 1)]
    changed["teams"] = [
        {"name": name, "rank": idx, "total": 10 - idx, "avg": 10 - idx,
         "per_capita_re_amount": 1000 - idx}
        for idx, name in enumerate(("队二", "队一", "队三", "队四"), 1)
    ]
    candidates = _detect(db, **changed)

    assert {(c["event_type"], c["subject_id"]) for c in candidates} >= {
        ("rank_up_first", "B"),
        ("rank_up_re", "C"),
        ("rank_up_team", "队二"),
    }


def test_camp_leader_change_emits_only_new_leader(db):
    _detect(db, **_payload())
    changed = _payload()
    for member in changed["camps"][0]["members"]:
        member["is_first"] = member["user_id"] == "D"

    candidates = _detect(db, **changed)
    camp_events = [c for c in candidates if c["event_type"] == "rank_up_camp"]

    assert len(camp_events) == 1
    assert camp_events[0]["subject_id"] == "D"
    assert "原第一 人员C" in camp_events[0]["detail"]


def test_company_milestone_camp_overage_and_combo_crossings(db):
    _detect(db, **_payload())

    changed = _payload(
        new_total=15,
        camp_done=44,
        daily_orders={"A": [
            {"order_id": "O1", "amount": 100},
            {"order_id": "O2", "amount": 200},
        ]},
    )
    candidates = _detect(db, **changed)
    by_type = {c["event_type"]: c for c in candidates}

    assert by_type["company_milestone"]["level"] == "L4"
    assert "10%" in by_type["company_milestone"]["detail"]
    assert by_type["camp_over_target"]["level"] == "L4"
    assert "110%" in by_type["camp_over_target"]["detail"]
    assert by_type["daily_combo"]["level"] == "L3"
    assert "×2" in by_type["daily_combo"]["detail"]

    assert _detect(db, **changed) == []


def test_combo_sequence_uses_observed_history_not_order_id_sort(db):
    _detect(db, **_payload(daily_orders={"A": [
        {"order_id": "O9", "amount": 100},
    ]}))

    candidates = _detect(db, **_payload(daily_orders={"A": [
        {"order_id": "O0", "amount": 200},
        {"order_id": "O9", "amount": 100},
    ]}))
    combo = next(c for c in candidates if c["event_type"] == "daily_combo")

    assert combo["dedup_key"].endswith(":O0")
    assert "×2" in combo["detail"]
