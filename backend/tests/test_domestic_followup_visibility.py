from app.domestic_followup import config_service, dict_service
from app.domestic_followup.constants import DICT_CATEGORY, DICT_CHANNEL, DICT_STATE_CHANGE
from tests.domestic_followup_helpers import grant, make_user, seed_dicts


def test_followup_permissions_seeded_with_correct_kind_and_admin_grants(db):
    from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
    from app.auth.service import seed_role_permissions

    admin_role = ArkRole(name="admin", label="管理员")
    db.add(admin_role)
    db.flush()
    seed_role_permissions(db)
    seed_role_permissions(db)  # 幂等：跟 test_domestic_operation_permissions.py 同一惯例，跑两次确认不重复授予

    read_all_perm = db.query(ArkPermission).filter_by(code="domestic_followup:read_all").one()
    assert read_all_perm.kind == "data"

    def _admin_granted(code: str) -> bool:
        perm = db.query(ArkPermission).filter_by(code=code).one()
        return db.query(ArkRolePermission).filter_by(
            role_id=admin_role.id, permission_id=perm.id,
        ).count() > 0

    assert _admin_granted("domestic_followup:read")
    assert _admin_granted("domestic_followup:write")
    assert not _admin_granted("domestic_followup:read_all")
    assert not _admin_granted("domestic_followup:admin")
    assert not _admin_granted("domestic_followup:coordinate")


def test_config_defaults_and_update(db):
    admin = make_user(db, "fu_cfg_admin")
    grant(db, admin, "domestic_followup:read_all")
    config = config_service.get_config(db)
    assert config["receipt_delay_days"] == 3
    assert config["frequency_days"] == {"S级": 7, "A级": 14, "B级": 30, "C级": 30}  # 2026-11-13 Q3：1 个月未跟进即入公海

    config_service.update_config(db, {"receipt_delay_days": 4, "urgent_receiver_user_ids": [admin.id]}, admin.id)
    config = config_service.get_config(db)
    assert config["receipt_delay_days"] == 4
    assert config["urgent_receiver_user_ids"] == [admin.id]


def test_urgent_receivers_must_hold_read_all(db):
    import pytest

    boss = make_user(db, "fu_cfg_boss")
    grant(db, boss, "domestic_followup:read_all")
    root = make_user(db, "fu_cfg_root")
    grant(db, root, role_name="super_admin")
    clerk = make_user(db, "fu_cfg_clerk")
    clerk.real_name = "小王"
    grant(db, clerk, "domestic_followup:read", "domestic_followup:write")
    with pytest.raises(ValueError, match="小王 没有『全部客户跟进范围』权限，点开推送会看不到客户"):
        config_service.update_config(db, {"urgent_receiver_user_ids": [boss.id, clerk.id]}, None, commit=False)
    assert config_service.get_config(db)["urgent_receiver_user_ids"] == []
    config_service.update_config(db, {"urgent_receiver_user_ids": [boss.id, root.id]}, None, commit=False)
    assert config_service.get_config(db)["urgent_receiver_user_ids"] == [boss.id, root.id]


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


from datetime import date

import pytest

from app.domestic_followup import visibility
from app.domestic_followup.models import DomesticCustomerAlias, DomesticFollowup, DomesticFollowupTask
from tests.domestic_followup_helpers import make_customer


def _user_ctx(user, perms=("domestic_followup:read", "domestic_followup:write")):
    return {"sub": str(user.id), "roles": [], "permissions": list(perms)}


def test_customer_scope_owner_commission_and_read_all(db):
    owner, partner, other, boss = (make_user(db, f"fu_vis_{n}") for n in ("o", "p", "x", "b"))
    customer = make_customer(db, owner, "可见测试店", commission_users=[partner])
    assert visibility.can_write_customer(db, _user_ctx(owner), customer)
    assert visibility.can_write_customer(db, _user_ctx(partner), customer)
    assert not visibility.can_write_customer(db, _user_ctx(other), customer)
    boss_ctx = _user_ctx(boss, ("domestic_followup:read", "domestic_followup:write", "domestic_followup:read_all"))
    assert visibility.in_customer_scope(db, boss_ctx, customer.id)
    assert not visibility.can_write_customer(db, boss_ctx, customer)


def test_legacy_public_customer_can_be_recorded_but_task_assignment_is_not_a_general_grant(db):
    owner, creator, stranger = (make_user(db, f"fu_vis2_{n}") for n in ("o", "c", "s"))
    public = make_customer(db, None, "公海店", creator=owner)
    assert visibility.can_write_customer(db, _user_ctx(stranger), public)

    owned = make_customer(db, owner, "有主店")
    db.add(DomesticFollowupTask(task_type="receipt", customer_id=owned.id, assignee_user_id=creator.id,
                                source_key="receipt:t", title="t", due_date=__import__("datetime").date(2026, 11, 2)))
    db.flush()
    assert not visibility.can_write_customer(db, _user_ctx(creator), owned)


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
    with pytest.raises(ValueError, match="可能已有档案，请联系管理员核实"):
        visibility.create_prospect(db, _user_ctx(other), "新潜在店")


def test_ensure_writable_rejects_inactive_customer(db):
    owner = make_user(db, "fu_vis6_owner")
    customer = make_customer(db, owner, "停用跟进店")
    customer.status = 0
    db.flush()
    with pytest.raises(PermissionError, match="已停用"):
        visibility.ensure_customer_writable(db, _user_ctx(owner), customer.id)


def test_followup_filter_four_quadrants(db):
    author, scoped_owner, outsider = (make_user(db, f"fu_filt_{n}") for n in ("a", "s", "o"))
    customer = make_customer(db, scoped_owner, "过滤测试店")

    draft = DomesticFollowup(author_user_id=author.id, customer_id=customer.id,
                              followup_date=date(2026, 10, 30), status="draft", request_id="r-filt-draft")
    confirmed = DomesticFollowup(author_user_id=author.id, customer_id=customer.id,
                                  followup_date=date(2026, 10, 30), status="confirmed", request_id="r-filt-confirmed")
    discarded = DomesticFollowup(author_user_id=author.id, customer_id=customer.id,
                                  followup_date=date(2026, 10, 30), status="discarded", request_id="r-filt-discarded")
    db.add_all([draft, confirmed, discarded])
    db.flush()

    def visible_ids(user):
        return {row.id for row in db.query(DomesticFollowup).filter(visibility.followup_filter(_user_ctx(user))).all()}

    author_ids = visible_ids(author)
    assert draft.id in author_ids  # 作者看自己的草稿：可见
    assert confirmed.id in author_ids
    assert discarded.id in author_ids  # 作者对自己的记录（含作废）全部可见

    outsider_ids = visible_ids(outsider)
    assert draft.id not in outsider_ids  # 他人看草稿：不可见
    assert confirmed.id not in outsider_ids
    assert discarded.id not in outsider_ids

    scoped_ids = visible_ids(scoped_owner)
    assert confirmed.id in scoped_ids  # 同客户范围内的他人看已确认记录：可见
    assert discarded.id not in scoped_ids  # 同客户范围内的他人看作废记录：不可见
    assert draft.id not in scoped_ids


def test_task_filter_matches_assignee_or_customer_scope(db):
    assignee, scoped_owner, outsider = (make_user(db, f"fu_taskfilt_{n}") for n in ("a", "o", "x"))
    other_customer = make_customer(db, None, "任务过滤店A", creator=assignee)
    scoped_customer = make_customer(db, scoped_owner, "任务过滤店B")
    task_by_assignee = DomesticFollowupTask(task_type="plan", customer_id=other_customer.id,
                                             assignee_user_id=assignee.id, source_key="plan:filt-a",
                                             title="t", due_date=date(2026, 11, 2))
    task_by_scope = DomesticFollowupTask(task_type="plan", customer_id=scoped_customer.id,
                                          assignee_user_id=assignee.id, source_key="plan:filt-b",
                                          title="t2", due_date=date(2026, 11, 2))
    db.add_all([task_by_assignee, task_by_scope])
    db.flush()

    def visible_ids(user):
        return {row.id for row in db.query(DomesticFollowupTask).filter(visibility.task_filter(_user_ctx(user))).all()}

    assignee_ids = visible_ids(assignee)
    assert task_by_assignee.id in assignee_ids and task_by_scope.id in assignee_ids  # 负责人两条都看得到

    scoped_ids = visible_ids(scoped_owner)
    assert task_by_scope.id in scoped_ids  # 客户在自己范围内：可见
    assert task_by_assignee.id not in scoped_ids  # 客户不在范围、自己也不是负责人：不可见

    assert not visible_ids(outsider)  # 既不是负责人也不在客户范围：都看不到


def test_search_excludes_out_of_scope_and_inactive_customers(db):
    owner, other = (make_user(db, f"fu_search_{n}") for n in ("o", "x"))
    in_scope = make_customer(db, owner, "范围内蜡烫店")
    out_of_scope = make_customer(db, other, "范围外蜡烫店")
    inactive = make_customer(db, owner, "停用蜡烫店")
    inactive.status = 0
    db.flush()

    results = {row["id"] for row in visibility.search_customers(db, _user_ctx(owner), "蜡烫店")}
    assert in_scope.id in results
    assert out_of_scope.id not in results  # 范围外客户搜不到
    assert inactive.id not in results  # status=0 被排除


def test_search_keyword_with_percent_and_underscore_matches_literally(db):
    owner = make_user(db, "fu_search_lit")
    literal = make_customer(db, owner, "100%纯手工店")
    decoy = make_customer(db, owner, "100X纯手工店")
    db.flush()
    results = {row["id"] for row in visibility.search_customers(db, _user_ctx(owner), "100%纯")}
    assert literal.id in results
    assert decoy.id not in results


def test_search_super_admin_role_sees_others_customers(db):
    boss = make_user(db, "fu_search_boss")
    other_owner = make_user(db, "fu_search_other")
    customer = make_customer(db, other_owner, "总管可见店")
    db.flush()
    boss_ctx = _user_ctx(boss, ("domestic_followup:read",))
    boss_ctx["roles"] = ["super_admin"]
    results = {row["id"] for row in visibility.search_customers(db, boss_ctx, "总管可见店")}
    assert customer.id in results


def test_match_alias_scope_excludes_higher_hit_outside_customer(db):
    owner, other_owner = (make_user(db, f"fu_alias_{n}") for n in ("o", "x"))
    in_scope = make_customer(db, owner, "范围内别名店")
    out_of_scope = make_customer(db, other_owner, "范围外别名店")
    db.add(DomesticCustomerAlias(customer_id=out_of_scope.id, alias="别名冲突", alias_norm="别名冲突",
                                 hit_count=50, created_by=other_owner.id))
    db.add(DomesticCustomerAlias(customer_id=in_scope.id, alias="别名冲突", alias_norm="别名冲突",
                                 hit_count=1, created_by=owner.id))
    db.flush()
    matched = visibility.match_alias(db, _user_ctx(owner), "别名冲突")
    assert matched is not None and matched["id"] == in_scope.id


def test_learn_alias_concurrent_insert_bumps_hit_count_instead_of_failing(db, monkeypatch):
    owner = make_user(db, "fu_vis_alias")
    customer = make_customer(db, owner, "别名并发店")
    db.add(DomesticCustomerAlias(customer_id=customer.id, alias="均哥", alias_norm="均哥", created_by=owner.id))
    db.flush()
    # 预查没看到（另一事务刚插入），插入撞 uq_dom_customer_alias
    monkeypatch.setattr(visibility, "_find_alias", lambda *a: None)
    visibility.learn_alias(db, customer.id, " 均哥 ", owner.id)
    db.flush()
    row = db.query(DomesticCustomerAlias).filter_by(customer_id=customer.id).one()
    db.refresh(row)
    assert row.hit_count == 2
