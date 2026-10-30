from app.domestic_followup import config_service, dict_service
from app.domestic_followup.constants import DICT_CATEGORY, DICT_CHANNEL, DICT_STATE_CHANGE
from tests.domestic_followup_helpers import make_user, seed_dicts


def test_followup_permissions_seeded_and_read_all_is_data_kind():
    from app.auth.service import _DATA_KIND_CODES, seed_role_permissions

    assert "domestic_followup:read_all" in _DATA_KIND_CODES
    consts = " ".join(str(v) for v in seed_role_permissions.__code__.co_consts)
    for code in ("domestic_followup:read", "domestic_followup:write", "domestic_followup:admin"):
        assert code in consts


def test_config_defaults_and_update(db):
    admin = make_user(db, "fu_cfg_admin")
    config = config_service.get_config(db)
    assert config["receipt_delay_days"] == 3
    assert config["frequency_days"] == {"S级": 7, "A级": 14, "B级": 30, "C级": 60}

    config_service.update_config(db, {"receipt_delay_days": 4, "urgent_receiver_user_ids": [admin.id]}, admin.id)
    config = config_service.get_config(db)
    assert config["receipt_delay_days"] == 4
    assert config["urgent_receiver_user_ids"] == [admin.id]


def test_update_config_rejects_unknown_key(db):
    import pytest

    admin = make_user(db, "fu_cfg_admin2")
    with pytest.raises(ValueError):
        config_service.update_config(db, {"bogus": 1}, admin.id)


def test_dict_values_come_from_sys_dict(db):
    seed_dicts(db)
    values = dict_service.load_values(db)
    assert "竞争品牌增加" in values[DICT_STATE_CHANGE]
    assert values[DICT_CATEGORY][-1] == "其他"
    assert "电话" in values[DICT_CHANNEL]


import pytest

from app.domestic_followup import visibility
from app.domestic_followup.models import DomesticCustomerAlias, DomesticFollowupTask
from tests.domestic_followup_helpers import make_customer


def _user_ctx(user, perms=("domestic_followup:read", "domestic_followup:write")):
    return {"sub": str(user.id), "roles": [], "permissions": list(perms)}


def test_customer_scope_owner_commission_and_read_all(db):
    owner, partner, other, boss = (make_user(db, f"fu_vis_{n}") for n in ("o", "p", "x", "b"))
    customer = make_customer(db, owner, "可见测试店", commission_users=[partner])
    assert visibility.can_write_customer(db, _user_ctx(owner), customer)
    assert visibility.can_write_customer(db, _user_ctx(partner), customer)
    assert not visibility.can_write_customer(db, _user_ctx(other), customer)
    boss_ctx = _user_ctx(boss, ("domestic_followup:read", "domestic_followup:read_all"))
    assert visibility.can_write_customer(db, boss_ctx, customer)


def test_public_sea_and_task_assignee_can_write(db):
    owner, creator, stranger = (make_user(db, f"fu_vis2_{n}") for n in ("o", "c", "s"))
    public = make_customer(db, None, "公海店", creator=owner)
    assert visibility.can_write_customer(db, _user_ctx(stranger), public)

    owned = make_customer(db, owner, "有主店")
    db.add(DomesticFollowupTask(task_type="receipt", customer_id=owned.id, assignee_user_id=creator.id,
                                source_key="receipt:t", title="t", due_date=__import__("datetime").date(2026, 11, 2)))
    db.flush()
    assert visibility.can_write_customer(db, _user_ctx(creator), owned)


def test_ensure_writable_reports_owner_name(db):
    owner = make_user(db, "fu_vis3_owner")
    other = make_user(db, "fu_vis3_other")
    customer = make_customer(db, owner, "归属提示店")
    with pytest.raises(PermissionError, match="fu_vis3_owner"):
        visibility.ensure_customer_writable(db, _user_ctx(other), customer.id)


def test_search_matches_name_code_and_alias(db):
    owner = make_user(db, "fu_vis4")
    customer = make_customer(db, owner, "发丝特均哥")
    db.add(DomesticCustomerAlias(customer_id=customer.id, alias="均哥 三家店", alias_norm="均哥三家店",
                                 created_by=owner.id))
    db.flush()
    by_name = visibility.search_customers(db, _user_ctx(owner), "均哥")
    by_alias = visibility.search_customers(db, _user_ctx(owner), "三家店")
    assert by_name[0]["id"] == customer.id and by_name[0]["writable"] is True
    assert by_alias[0]["id"] == customer.id and by_alias[0]["matched_alias"] == "均哥 三家店"


def test_create_prospect_and_conflicts(db):
    seed_dicts(db)
    owner = make_user(db, "fu_vis5_owner")
    other = make_user(db, "fu_vis5_other")
    created = visibility.create_prospect(db, _user_ctx(owner), "  新潜在店 ")
    assert created["shop_name"] == "新潜在店"
    assert created["lifecycle_status"] == "潜在"
    assert created["owner_user_id"] == owner.id
    with pytest.raises(ValueError, match="已存在（归属：fu_vis5_owner）"):
        visibility.create_prospect(db, _user_ctx(other), "新潜在店")
