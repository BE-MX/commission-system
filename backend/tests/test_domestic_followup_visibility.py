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
