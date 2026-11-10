"""Isolated HTTP contracts for current human scope and manual feed dependencies."""
from copy import deepcopy
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.alibaba_feed.business_router import router
from app.alibaba_feed import business_service as service
from app.alibaba_feed.models import AlibabaFeedSource, AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedLink, AlibabaFeedMessage
from app.alibaba_feed.source_service import SourcePatch, update_source
from app.alibaba_feed.source_router import router as admin_router
from app.auth.models import ArkPermission, ArkRolePermission, ArkUser, ArkUserExternalBinding
from app.auth.utils import create_access_token
from app.core.config import get_settings
from app.core.database import get_db
from tests.test_alibaba_feed_auth import feed
from tests.test_alibaba_feed_core import payload, NOW


@pytest.fixture
def business(feed, monkeypatch):
    db, issued, source, role = feed
    db.autoflush = False
    ArkUserExternalBinding.__table__.create(db.get_bind())
    for model in (AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedLink, AlibabaFeedMessage):
        model.__table__.create(db.get_bind())
    for action in ("read", "write"):
        role.permissions.append(ArkPermission(code=f"client_desk:{action}", module="client_desk", action=action, label=action))
    db.commit()
    row = db.query(AlibabaFeedSource).one()
    row.consent_state = "authorized"
    row.crm_shared = row.ai_egress_allowed = row.private_feed_enabled = True
    row.owner_aliases = {"Seller A": 1}
    record = deepcopy(payload()["records"][0])
    record["assignee_name"] = "Seller A"
    record["messages"].append(deepcopy(record["messages"][0]))
    db.add(AlibabaFeedBatch(id="batch", source_account_uid="shop-a", run_id="run", collection_generation=1, body_hash="a"*64,
        raw_hash="b"*64, raw_body=b"{}", body_bytes=2, source_status="ok", status="completed", observed_at=NOW,
        received_records=1, received_messages=2))
    db.flush()
    db.add(AlibabaFeedItem(id=1, batch_id="batch", record_index=0, source_account_uid="shop-a", collection_generation=1,
        record_type="inquiry", inquiry_id="item-a", observed_at=NOW, snapshot_hash="c"*64, snapshot=record,
        outcome="current_updated", is_current=True, window_result="uncertain", issues=["WINDOW_PRECISION_INSUFFICIENT"]))
    db.commit()
    monkeypatch.setattr(get_settings(), "ALIBABA_FEED_BUSINESS_ENABLED", True)
    monkeypatch.setattr(get_settings(), "ALIBABA_FEED_BUSINESS_PILOT_USER_IDS", [1, 2])
    scope = {1: {101, 102}, 2: {202}}
    def check(db, user, company_id, **kwargs):
        if int(company_id) not in scope.get(int(user["sub"]), set()):
            raise HTTPException(404, "not visible")
    monkeypatch.setattr(service.private_scope, "assert_company_access", check)
    monkeypatch.setattr(service.private_scope, "list_private_companies", lambda db, user: [{"company_id": str(i), "name": f"Customer {i}", "country": "US"} for i in sorted(scope[int(user["sub"])])])
    app = FastAPI()
    app.include_router(router, prefix="/business")
    app.include_router(admin_router, prefix="/admin")
    app.dependency_overrides[get_db] = lambda: db
    def headers(uid=1):
        token = create_access_token({"sub":str(uid), "roles":["super_admin"] if uid==2 else [], "permissions":["client_desk:read", "client_desk:write", "alibaba_feed:admin"]})
        return {"Authorization": "Bearer " + token}
    yield TestClient(app), db, headers, scope, issued


def link(client, headers, **changes):
    body = {"item_id": 1, "company_id": 101, "expected_mapping_version": 1, "client_request_id": "req-1", **changes}
    return client.post("/business/links", json=body, headers=headers())


def test_visible_unlinked_then_link_and_explicit_evidence(business):
    client, db, headers, _, _ = business
    response = client.get("/business/records", headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["data"]["total"] == 1
    assert response.headers["cache-control"] == "no-store"
    assert link(client, headers).status_code == 200
    selected = service.select_for_analysis(db, {"sub":"1"}, 101, [1])
    assert list(selected["refs"]) == ["AF-1-1", "AF-1-2"]
    assert len(selected["messages"]) == 2  # Repeated text is not deduplicated.
    assert selected["dependencies"]["policy"] == "manual_only_v1"
    assert service.dependencies_valid(db, {"sub":"1"}, 101, selected["dependencies"])
    assert any("精度" in gap for gap in selected["coverage_gaps"])
    assert client.get("/business/customers/101/records", headers=headers()).json()["data"]["total"] == 1
    customers = client.get("/business/customers?page_size=1&page=2", headers=headers()).json()["data"]
    assert customers["total"] == 2 and len(customers["items"]) == 1


def test_machine_and_admin_cannot_read_other_owner_body(business):
    client, db, headers, _, issued = business
    assert client.get("/business/records/1", headers={"Authorization":"Bearer "+issued["token"]}).status_code == 401
    assert client.get("/business/records/1", headers=headers(2)).status_code == 404
    assert client.get("/business/records", headers=headers(2)).json()["data"]["total"] == 0
    assert client.get("/admin/sources", headers=headers(2)).status_code == 200
    assert "Synthetic secret" not in client.get("/admin/sources", headers=headers(2)).text
    assert link(client, headers, company_id=202).status_code == 404


def test_business_access_requires_explicit_feed_pilot_enrollment(business, monkeypatch):
    client, db, headers, _, _ = business
    settings = get_settings()
    monkeypatch.setattr(settings, "ALIBABA_FEED_BUSINESS_PILOT_USER_IDS", [1])
    source = db.query(AlibabaFeedSource).one()
    # Make the other account the current exact owner. Ownership and its
    # administrator role must not grant access outside the pilot.
    source.owner_aliases = {"Seller A": 2}
    db.commit()

    assert client.get("/business/records/1", headers=headers(2)).status_code == 403
    assert client.get("/business/customers", headers=headers(2)).status_code == 403
    assert client.get("/admin/sources", headers=headers(2)).status_code == 200

    monkeypatch.setattr(settings, "ALIBABA_FEED_BUSINESS_PILOT_USER_IDS", [2])
    assert client.get("/business/records/1", headers=headers(2)).status_code == 200
    monkeypatch.setattr(settings, "ALIBABA_FEED_BUSINESS_PILOT_USER_IDS", [])
    assert client.get("/business/records/1", headers=headers(2)).status_code == 403



def test_link_idempotency_and_versions(business):
    client, db, headers, _, _ = business
    first = link(client, headers).json()["data"]
    replay = link(client, headers).json()["data"]
    assert replay["id"] == first["id"] and replay["replayed"]
    assert link(client, headers, company_id=102).status_code == 409
    assert link(client, headers, client_request_id="req-2").status_code == 409
    assert db.query(AlibabaFeedLink).count() == 1
    assert client.delete(f"/business/links/{first['id']}?expected_version=2", headers=headers()).status_code == 409
    assert client.delete(f"/business/links/{first['id']}?expected_version=1", headers=headers()).status_code == 200
    assert link(client, headers).status_code == 409
    assert link(client, headers, client_request_id="req-2").status_code == 200
    assert db.query(AlibabaFeedLink).count() == 2


@pytest.mark.parametrize("change", ["transfer", "crm", "ai", "private", "owner", "mapping", "generation", "current", "inactive", "permission", "delete", "legacy"])
def test_dependency_closure_invalidates_immediately(business, change):
    client, db, headers, scope, _ = business
    created = link(client, headers).json()["data"]
    dependencies = service.select_for_analysis(db, {"sub":"1"}, 101, [1])["dependencies"]
    source = db.query(AlibabaFeedSource).one()
    if change == "transfer": scope[1].remove(101)
    elif change == "crm": source.crm_shared = False
    elif change == "ai": source.ai_egress_allowed = False
    elif change == "private": source.private_feed_enabled = False
    elif change == "owner": source.owner_aliases = {"Seller A": 2}
    elif change == "mapping": source.mapping_version += 1
    elif change == "generation": source.collection_generation += 1
    elif change == "current": db.get(AlibabaFeedItem,1).is_current = False
    elif change == "inactive": db.get(ArkUser,1).is_active = False
    elif change == "permission":
        permission = db.query(ArkPermission).filter_by(code="client_desk:read").one()
        db.query(ArkRolePermission).filter_by(permission_id=permission.id).delete()
    elif change == "delete": client.delete(f"/business/links/{created['id']}?expected_version=1", headers=headers())
    elif change == "legacy": source.legacy_identity_blocked = True
    db.commit()
    assert not service.dependencies_valid(db, {"sub":"1"}, 101, dependencies)
    if change not in ("ai", "private"):
        response = client.get("/business/records/1", headers=headers())
        assert response.status_code in (403,404), response.text
        assert "Synthetic secret" not in response.text


def test_selection_all_or_nothing_rejects_bad_quality_or_stale(business):
    client, db, headers, _, _ = business
    link(client, headers)
    for ids in ([1,999], [1,1], []):
        with pytest.raises(HTTPException): service.select_for_analysis(db, {"sub":"1"}, 101, ids)
    item = db.get(AlibabaFeedItem,1)
    item.window_result = "out_of_window"
    db.commit()
    with pytest.raises(HTTPException): service.select_for_analysis(db, {"sub":"1"}, 101, [1])


def test_source_admin_exact_mapping_and_consent_version(business):
    client, db, headers, _, _ = business
    row = db.query(AlibabaFeedSource).one()
    before = row.version
    updated = update_source(db,"shop-a",SourcePatch(expected_version=before, owner_aliases={" Seller A ":1},crm_shared=False),actor_id=2)
    assert updated["owner_aliases"] == {" Seller A ":1}
    assert updated["mapping_version"] == 2 and updated["consent_version"] == 2
    assert row.mapping_updated_by == 2
    with pytest.raises(HTTPException): update_source(db,"shop-a",SourcePatch(expected_version=updated["version"],owner_aliases={"Seller A":4}))
    assert client.get("/business/records",headers=headers()).json()["data"]["total"] == 0
    assert client.patch("/admin/sources/shop-a",json={"expected_version":updated["version"],"verified_capabilities":{"reliable_order":True}},headers=headers(2)).status_code == 422
    valid = client.patch("/admin/sources/shop-a",json={"expected_version":updated["version"],"verified_capabilities":{"reliable_order":True,"evidence_note":"isolated fixture"}},headers=headers(2))
    assert valid.status_code == 200, valid.text
    assert valid.json()["data"]["capability_version"] == 2


def test_feature_disabled_and_cross_source_mapping(business, monkeypatch):
    client, db, headers, _, _ = business
    row = db.query(AlibabaFeedSource).one()
    row.owner_aliases={"seller a":1}
    db.commit()
    assert client.get("/business/records/1", headers=headers()).status_code == 404
    monkeypatch.setattr(get_settings(),"ALIBABA_FEED_BUSINESS_ENABLED",False)
    assert client.get("/business/records", headers=headers()).status_code == 503

def test_link_mapping_race_requires_new_confirmation(business):
    client, db, headers, _, _ = business
    first = link(client, headers).json()["data"]
    source = db.query(AlibabaFeedSource).one()
    updated = update_source(db, "shop-a", SourcePatch(expected_version=source.version, owner_aliases={"Seller A":1,"Seller B":2}), actor_id=2)
    assert link(client, headers, client_request_id="req-2").status_code == 409
    assert client.get("/business/records/1",headers=headers()).status_code == 404
    redacted = client.get("/business/records",headers=headers()).json()["data"]["items"][0]
    assert redacted["link"] is None and redacted["visibility_state"] == "mapping_changed"
    assert redacted["buyer"]["name"] == "资料待重新确认"
    assert "snapshot" not in redacted and "messages" not in redacted
    result = link(client, headers, client_request_id="req-2", expected_mapping_version=updated["mapping_version"])
    assert result.status_code == 200, result.text
    assert result.json()["data"]["id"] != first["id"]
    assert db.get(AlibabaFeedLink,first["id"]).deleted_at is not None
    assert db.query(AlibabaFeedLink).filter_by(deleted_at=None).count() == 1
    assert "Synthetic secret text" in client.get("/business/records/1",headers=headers()).text


def test_same_record_identity_cannot_cross_source(business):
    client, db, headers, _, _ = business
    db.add(AlibabaFeedSource(source_account_uid="shop-b",integration_app_id=998,name="Other source",consent_state="authorized",crm_shared=True,owner_aliases={"Seller A":2}))
    item=db.get(AlibabaFeedItem,1)
    db.add(AlibabaFeedItem(id=2,batch_id="batch",record_index=1,source_account_uid="shop-b",collection_generation=1,record_type="inquiry",inquiry_id=item.inquiry_id,observed_at=NOW,snapshot_hash="d"*64,snapshot=deepcopy(item.snapshot),outcome="current_updated",is_current=True,window_result="in_window",issues=[]))
    db.commit()
    assert client.get("/business/records/2",headers=headers()).status_code==404
    assert client.get("/business/records",headers=headers()).json()["data"]["total"]==1
    assert client.get("/business/records/1",headers=headers(2)).status_code==404
    assert link(client,headers,item_id=2).status_code==404


def test_link_audit_time_uses_beijing_midnight(business, monkeypatch):
    from datetime import datetime
    client,db,headers,_,_=business
    monkeypatch.setenv("TZ","America/Los_Angeles")
    monkeypatch.setattr(service,"beijing_now",lambda:datetime(2026,11,6,0,0,1,123456))
    created=link(client,headers).json()["data"]
    response=client.delete(f"/business/links/{created['id']}?expected_version=1",headers=headers())
    assert response.status_code==200
    assert db.get(AlibabaFeedLink,created["id"]).deleted_at==datetime(2026,11,6,0,0,1,123456)

def test_stable_owner_binding_overrides_display_name_and_has_no_fallback(business):
    client,db,headers,_,_=business
    item=db.get(AlibabaFeedItem,1)
    item.snapshot={**item.snapshot,"assignee_external_user_id":"Employee-A"}
    db.commit()
    # An explicit stable identity without a binding cannot fall back to alias.
    assert client.get("/business/records/1",headers=headers()).status_code==404
    db.add(ArkUserExternalBinding(id=1,ark_user_id=2,provider="alibaba_icbu",external_account_id="Employee-A",binding_status="active"))
    db.commit()
    assert client.get("/business/records/1",headers=headers()).status_code==404
    assert client.get("/business/records/1",headers=headers(2)).status_code==200
    binding=db.get(ArkUserExternalBinding,1)
    binding.ark_user_id=1
    db.commit()
    assert client.get("/business/records/1",headers=headers()).status_code==200
    db.add(ArkUserExternalBinding(id=2,ark_user_id=1,provider="alibaba_icbu",external_account_id="Employee-A",binding_status="active"))
    db.commit()
    assert client.get("/business/records/1",headers=headers()).status_code==404


def test_stable_owner_dependency_revoked(business):
    client,db,headers,_,_=business
    item=db.get(AlibabaFeedItem,1)
    item.snapshot={**item.snapshot,"assignee_external_user_id":"Employee-A"}
    db.add(ArkUserExternalBinding(id=1,ark_user_id=1,provider="alibaba_icbu",external_account_id="Employee-A",binding_status="active"))
    db.commit()
    assert link(client,headers).status_code==200
    dependencies=service.select_for_analysis(db,{"sub":"1"},101,[1])["dependencies"]
    db.get(ArkUserExternalBinding,1).binding_status="inactive"
    db.commit()
    assert not service.dependencies_valid(db,{"sub":"1"},101,dependencies)
    assert client.get("/business/records/1",headers=headers()).status_code==404

def _paired_analysis_items(business, *, second_source="shop-a", second_message="stable-message", schema="ark_alibaba_feed_v1.1"):
    from app.alibaba_feed.normalization import message_hash
    client,db,headers,_,_=business
    first=db.get(AlibabaFeedItem,1)
    if second_source != "shop-a":
        db.add(AlibabaFeedSource(source_account_uid=second_source,integration_app_id=998,name="Other authorized source",
            consent_state="authorized",crm_shared=True,ai_egress_allowed=True,private_feed_enabled=True,owner_aliases={"Seller A":1}))
    second=AlibabaFeedItem(id=2,batch_id="batch",record_index=1,source_account_uid=second_source,
        collection_generation=1,record_type="tm",inquiry_id="tm-item",observed_at=NOW,snapshot_hash="d"*64,
        snapshot=deepcopy(first.snapshot),outcome="current_updated",is_current=True,window_result="in_window",issues=[])
    db.add(second)
    known=set()
    for item,message_id in ((first,"stable-message"),(second,second_message)):
        item.schema_version=schema
        item.snapshot={**deepcopy(first.snapshot),"type":item.record_type,"inquiry_id":item.inquiry_id}
        if schema == "ark_alibaba_feed_v1.1":
            item.conversation_id="conversation-a"
            item.conversation_revision=1
            item.snapshot_revision=1
            message={**item.snapshot["messages"][0],"message_id":message_id,"message_revision":1,"source_order":1,"actor_type":"human"}
            item.snapshot={**item.snapshot,"messages":[message],"conversation_id":item.conversation_id}
            identity=(item.source_account_uid,message_id)
            if identity not in known:
                db.add(AlibabaFeedMessage(source_account_uid=item.source_account_uid,collection_generation=1,
                    conversation_id=item.conversation_id,message_id=message_id,source_order=1,message_revision=1,
                    latest_conversation_revision=1,observed_at=NOW,snapshot_hash=message_hash(message),content=deepcopy(message),
                    actor_type="human",first_item_id=item.id))
                known.add(identity)
    db.commit()
    assert link(client,headers).status_code==200
    linked=link(client,headers,item_id=2,client_request_id="req-2")
    assert linked.status_code==200,linked.text
    return linked.json()["data"]


def test_v11_shared_inquiry_tm_message_selected_once_but_both_dependencies_retained(business):
    client,db,headers,_,_=business
    second_link=_paired_analysis_items(business)
    result=service.select_for_analysis(db,{"sub":"1"},101,[2,1])
    assert [m["key"] for m in result["messages"]]==["AF-1-1"]
    assert list(result["refs"])==["AF-1-1"]
    assert [item["item_id"] for item in result["dependencies"]["items"]]==[1,2]
    assert service.dependencies_valid(db,{"sub":"1"},101,result["dependencies"])
    assert client.delete(f"/business/links/{second_link['id']}?expected_version=1",headers=headers()).status_code==200
    assert not service.dependencies_valid(db,{"sub":"1"},101,result["dependencies"])


@pytest.mark.parametrize("second_source,second_message",[("shop-b","stable-message"),("shop-a","different-message")])
def test_v11_different_source_or_message_identity_never_merged(business,second_source,second_message):
    _,db,_,_,_=business
    _paired_analysis_items(business,second_source=second_source,second_message=second_message)
    result=service.select_for_analysis(db,{"sub":"1"},101,[1,2])
    assert [m["key"] for m in result["messages"]]==["AF-1-1","AF-2-1"]
    assert len(result["refs"])==2
    assert len(result["dependencies"]["items"])==2


def test_v1_identical_text_and_refs_across_records_remain_distinct(business):
    _,db,_,_,_=business
    _paired_analysis_items(business,schema="ark_alibaba_feed_v1")
    result=service.select_for_analysis(db,{"sub":"1"},101,[1,2])
    assert list(result["refs"])==["AF-1-1","AF-1-2","AF-2-1","AF-2-2"]
    assert len(result["messages"])==4

def test_revoked_link_hides_body_but_supports_explicit_reconfirmation(business):
    client,db,headers,_,_=business
    created=link(client,headers).json()["data"]
    assert client.delete(f"/business/links/{created['id']}?expected_version=1",headers=headers()).status_code==200
    detail=client.get("/business/records/1",headers=headers())
    assert detail.status_code==404 and "Synthetic secret" not in detail.text
    listing=client.get("/business/records",headers=headers())
    row=listing.json()["data"]["items"][0]
    assert row["visibility_state"]=="link_revoked" and row["ai_eligible"] is False and row["link"] is None
    assert "Synthetic" not in listing.text and "snapshot" not in row and "messages" not in row
    assert link(client,headers,client_request_id="reconfirm").status_code==200
    restored=client.get("/business/records/1",headers=headers())
    assert restored.status_code==200 and "Synthetic secret text" in restored.text


@pytest.mark.parametrize("invalidity",["revoked","mapping"])
def test_invalid_link_cannot_downgrade_to_unlinked_after_customer_transfer(business,invalidity):
    client,db,headers,scope,_=business
    created=link(client,headers).json()["data"]
    if invalidity=="revoked":
        assert client.delete(f"/business/links/{created['id']}?expected_version=1",headers=headers()).status_code==200
    else:
        source=db.query(AlibabaFeedSource).one()
        source.mapping_version+=1
        db.commit()
    scope[1].remove(101)
    listing=client.get("/business/records",headers=headers())
    assert listing.json()["data"]["items"]==[] and "Synthetic secret" not in listing.text
    assert client.get("/business/records/1",headers=headers()).status_code==404
