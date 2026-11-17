from datetime import date

import pytest

from app.core.time import beijing_today
from app.domestic.public_sea import compute_clocks
from app.domestic_followup import jobs
from app.domestic_followup.collaboration_models import FollowupResponsibility, FollowupScope
from app.domestic_followup.models import DomesticCustomerAlias, DomesticFollowup, DomesticFollowupTask
from tests.domestic_followup_helpers import ALL_PERMS, followup_client, grant, make_customer, make_user, seed_dicts

API = "/api/domestic-followup"


@pytest.mark.parametrize("managed", [False, True])
def test_non_owner_can_record_lost_customer_without_gaining_customer_access(db, monkeypatch, managed):
    seed_dicts(db)
    monkeypatch.setattr(jobs, "submit", lambda *args: None)
    owner, actor = (make_user(db, name) for name in ("lost_owner", "lost_actor"))
    grant(db, actor, *ALL_PERMS)
    customer = make_customer(db, owner, "回访测试流失门店")
    customer.lifecycle_status = "流失"
    customer.contact = "非绑定不可搜索联系人"
    customer.custom_code = "ls-lost-002"
    db.add(DomesticCustomerAlias(customer_id=customer.id, alias="私有微信备注", alias_norm="私有微信备注",
                                 created_by=owner.id))
    db.add(DomesticFollowup(customer_id=customer.id, author_user_id=owner.id, followup_date=date(2026, 10, 1),
                            request_id="lost-private-owner", raw_text="原业务员的记录", status="confirmed"))
    if managed:
        db.add(FollowupResponsibility(customer_id=customer.id, owner_user_id=owner.id, status="following"))
    db.commit()
    fields = {"customer_id": customer.id, "result_code": "有效沟通"}

    with followup_client(db, actor) as client:
        search = client.get(f"{API}/customers/search", params={"q": customer.custom_code}).json()["data"]
        assert [(row["id"], row["writable"], row["contact"]) for row in search] == [(customer.id, True, None)]
        assert not client.get(f"{API}/customers/search", params={"q": customer.contact}).json()["data"]
        assert not client.get(f"{API}/customers/search", params={"q": "私有微信备注"}).json()["data"]
        timeline = client.get(f"{API}/customers/{customer.id}/timeline").json()["data"]
        assert timeline["customer"]["record_only"] and not timeline["customer"]["readable"]
        assert timeline["events"] == []

        denied = client.post(f"{API}/followups", json={
            **fields, "request_id": "lost-no-plan", "raw_text": "未经安排的待办",
            "next_date": date(2099, 1, 1).isoformat(), "next_plan": "改下次跟进",
        })
        assert denied.status_code == 403
        saved = client.post(f"{API}/followups", json={
            **fields, "request_id": "lost-direct-save", "raw_text": "重新联系过客户",
            "items": [{"kind": "issue", "text": "客户反馈", "record_only": True}],
        })
        assert saved.status_code == 200, saved.text
        recorded = saved.json()["data"]
        assert recorded["author_user_id"] == actor.id
        assert recorded["items"][0]["status"] == "closed_no_action"
        assert client.get(f"{API}/followups", params={"keyword": customer.contact}).json()["data"]["total"] == 0
        assert client.get(f"{API}/followups", params={"keyword": customer.custom_code}).json()["data"]["total"] == 1

        draft = client.post(f"{API}/drafts", json={
            **fields, "request_id": "lost-ai-draft", "raw_text": "客户愿意再了解",
        })
        assert draft.status_code == 200, draft.text
        content = draft.json()["data"]
        url = f"{API}/drafts/{content['id']}/confirm"
        customer.lifecycle_status = "活跃"
        db.commit()
        payload = {**fields, "version": content["version"]}
        assert client.post(url, json=payload).status_code == 403
        assert client.post(f"{API}/followups", json={
            **fields, "request_id": "lost-no-history-bypass", "raw_text": "越权历史补录",
            "historical_only": True, "followup_date": "2026-10-01",
        }).status_code == 403
        edit_url = f"{API}/followups/{recorded['id']}"
        note = recorded["items"][0]
        edit = {"request_id": "lost-edit-note", "reason": "补正", "raw_text": "更正沟通内容",
                "version": recorded["version"], "followup_date": recorded["followup_date"],
                "items": [{"id": note["id"], "kind": note["kind"], "text": note["text"], "record_only": True}]}
        assert client.put(edit_url, json={**edit, "next_date": "2099-01-01"}).status_code == 403
        assert client.put(edit_url, json={**edit, "items": [{**edit["items"][0], "record_only": False}]}).status_code == 403
        corrected = client.put(edit_url, json=edit)
        assert corrected.status_code == 200, corrected.text
        customer.lifecycle_status = "流失"
        db.commit()
        confirmed = client.post(url, json=payload)
        assert confirmed.status_code == 200, confirmed.text

        timeline = client.get(f"{API}/customers/{customer.id}/timeline").json()["data"]
        assert {event["data"]["author_user_id"] for event in timeline["events"]} == {actor.id}
    assert db.query(DomesticFollowupTask).filter_by(customer_id=customer.id).count() == 0
    assert compute_clocks(db, [customer], beijing_today())[customer.id].last_followup_date == date(2026, 10, 1)
    assert customer.owner_user_id == owner.id
    if managed:
        responsibility = db.get(FollowupResponsibility, customer.id)
        assert (responsibility.owner_user_id, responsibility.version) == (owner.id, 1)


def test_lost_customer_requires_live_write_and_enabled_customer(db):
    seed_dicts(db)
    owner, actor = (make_user(db, name) for name in ("lost_guard_owner", "lost_guard_actor"))
    customer = make_customer(db, owner, "流失权限验证门店")
    customer.lifecycle_status = "流失"
    db.commit()
    params = {"q": customer.shop_name}
    payload = {"customer_id": customer.id, "result_code": "有效沟通", "request_id": "lost-guard",
               "raw_text": "跟进记录"}
    for permissions in (("domestic_followup:read",), ALL_PERMS):
        with followup_client(db, actor, permissions) as client:
            assert client.get(f"{API}/customers/search", params=params).json()["data"] == []
            assert client.post(f"{API}/followups", json=payload).status_code == 403

    grant(db, actor, *ALL_PERMS)
    customer.status = 0
    db.commit()
    with followup_client(db, actor) as client:
        assert client.get(f"{API}/customers/search", params=params).json()["data"] == []
        assert client.post(f"{API}/followups", json=payload).status_code == 403


def test_overview_offers_recording_without_preparation_or_contact_permissions(db):
    owner, actor = (make_user(db, name) for name in ("lost_overview_owner", "lost_overview_actor"))
    grant(db, actor, *ALL_PERMS)
    customer = make_customer(db, owner, "流失总览门店")
    customer.lifecycle_status = "流失"
    customer.contact = "受限联系人"
    db.add(FollowupScope(customer_id=customer.id, user_id=actor.id, added_by_user_id=owner.id,
                         scope_key=f"c:{customer.id}"))
    db.commit()
    with followup_client(db, actor) as client:
        resp = client.get(f"{API}/customer-overview", params={"scope": "authorized"})
        assert resp.status_code == 200, resp.text
        row = resp.json()["data"]["items"][0]
        assert row["id"] == customer.id and row["record_only"]
        assert not row["can_record"] and not row["can_edit_contact"] and not row["can_view_timeline"]
        assert row["contact"] is None
