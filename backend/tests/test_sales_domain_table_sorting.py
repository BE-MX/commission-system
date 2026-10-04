"""Header sorting covers the complete authorized result before pagination."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.time import beijing_now
from app.customer_image.models import CustomerImageGeneration, CustomerImageProduct
from app.customer_image.service import list_generations, list_invites
from app.expo import prompt_service, quota_service, service as expo_service, store_service
from app.expo.models import ExpoCustomer, ExpoStore
from app.sales_automation import service as sales_service
from tests.test_customer_image_permissions import _invite
from tests.test_pcw_conversation import (
    _bound_conversation, _customer_with_owner, _phone_point, _wa_account,
    _wa_conversation, _wa_message,
)
from tests.test_pcw_order_analytics import _actor, _order
from tests.test_customer_workflow import _account
from tests.test_sales_automation import _create_job
from tests.expo_prompt_support import seed_versions


@pytest.mark.parametrize("direction, expected", [("asc", [1, 2, 3]), ("desc", [3, 2, 1])])
def test_invite_and_generation_sort_cross_pages_preserves_owner(db, direction, expected):
    product = CustomerImageProduct(name="Sort", category="wig", fixed_prompt="x", output_prompt="y", created_by=1)
    db.add(product)
    db.flush()
    ids = {}
    for position, value in enumerate([3, 1, 2]):
        invite = _invite(db, owner=7, suffix=f"s{position:05}")
        invite.customer_name_snapshot = f"Customer {value}"
        generation = CustomerImageGeneration(
            invite_id=invite.id, product_id=product.id, logo_asset_id=1,
            request_id=f"sort-{position}", product_name_snapshot=f"Product {value}",
            config_version_snapshot=1, option_snapshot={}, prompt_snapshot="x",
            reference_asset_ids=[], preset_name="p",
        )
        db.add(generation)
        db.flush()
        ids[value] = (invite.id, generation.id)
    _invite(db, owner=8, suffix="other1")
    invite_ids, generation_ids = [], []
    for page in range(1, 4):
        rows, total = list_invites(db, 7, False, page, 1, "customer_name", direction)
        assert total == 3
        invite_ids.extend(row.id for row in rows)
        rows, total = list_generations(db, 7, False, page, 1, "product_name", direction)
        assert total == 3
        generation_ids.extend(row.id for row in rows)
    assert invite_ids == [ids[value][0] for value in expected]
    assert generation_ids == [ids[value][1] for value in expected]


def test_stores_computed_balance_sort_nulls_ties_clear_and_filter(db):
    rows = [ExpoStore(name=name, code=f"SORT-{index}", total_quota=quota, used_quota=used, status=status)
            for index, (name, quota, used, status) in enumerate([
                ("Z", 15, 5, 1), ("A", 15, 5, 1), ("B", 3, 1, 1), ("Hidden", 1, 0, 0),
            ])]
    db.add_all(rows)
    db.flush()
    asc = [store_service.list_stores(db, status=1, limit=1, offset=index, sort_field="remaining", sort_order="asc")[0][0].id for index in range(3)]
    assert asc == [rows[2].id, rows[0].id, rows[1].id]
    desc = store_service.list_stores(db, status=1, sort_field="remaining", sort_order="desc")[0]
    assert [row.id for row in desc] == [rows[0].id, rows[1].id, rows[2].id]
    clear = store_service.list_stores(db, status=1, sort_field="remaining", sort_order=None)[0]
    assert [row.id for row in clear] == [rows[2].id, rows[1].id, rows[0].id]
    assert [row.id for row in store_service.list_stores(db, status=1, sort_field="name; DROP TABLE", sort_order="asc")[0]] == [row.id for row in clear]


def test_quota_operator_join_sort_across_pages(db):
    from app.auth.models import ArkUser
    store = ExpoStore(name="Sort quota", code="SORT-Q")
    users = [ArkUser(username=name, password_hash="x", real_name=name) for name in ("Zulu", "Alpha")]
    db.add_all([store, *users])
    db.flush()
    for user in users:
        quota_service.recharge_quota(db, store_id=store.id, amount=10, operator_user_id=user.id)
    first, total = quota_service.list_quota_records(db, store.id, limit=1, sort_field="operator_name", sort_order="asc")
    second, _ = quota_service.list_quota_records(db, store.id, limit=1, offset=1, sort_field="operator_name", sort_order="asc")
    assert total == 2
    assert [first[0].operator_user_id, second[0].operator_user_id] == [users[1].id, users[0].id]


def test_expo_leads_memory_sort_before_slice_and_scope(db):
    store, other = ExpoStore(name="Sort", code="SORT-L"), ExpoStore(name="Other", code="SORT-L2")
    db.add_all([store, other])
    db.flush()
    db.add_all([ExpoCustomer(store_id=store.id, name=name, phone=f"100{index}") for index, name in enumerate(["Zulu", "Alpha", "Beta"])])
    db.add(ExpoCustomer(store_id=other.id, name="A hidden", phone="hidden"))
    db.flush()
    result, total = expo_service.list_leads(db, page=2, page_size=1, store_ids=[store.id], sort_field="name", sort_order="asc")
    assert total == 3 and result[0]["name"] == "Beta"


def test_search_jobs_http_sort_forwarding_and_status_filter(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.customer.router import router
    jobs = [_create_job(db, key=f"{index:064x}") for index in range(1, 4)]
    for job, name in zip(jobs, ["Zulu", "Alpha", "Beta"]):
        job.name = name
    db.flush()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "roles": [], "permissions": ["sales_automation:read"]}
    client = TestClient(app)
    response = client.get("/search-jobs", params={"page": 2, "page_size": 1, "status": "pending", "sort_field": "name", "sort_order": "asc"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 3 and data["items"][0]["name"] == "Beta"


def test_bound_and_pending_conversation_count_sort_before_page(db):
    from app.customer import pcw_conversation_service as svc
    customer, owner = _customer_with_owner(db, code="SORT-PCW", user_id=9510)
    for name, count in [("many", 4), ("few", 1), ("middle", 2)]:
        _bound_conversation(db, tag=f"sort-{name}", customer_id=customer.id, owner=owner, message_count=count)
    result = svc.list_conversations(db, customer_id=customer.id, actor_user_id=owner.id, page=2, page_size=1, sort_field="message_count", sort_order="asc")
    assert result["total"] == 3 and result["items"][0]["message_count"] == 2
    account = _wa_account(db, owner, "sort-pending")
    for name, count in [("many", 4), ("few", 1), ("middle", 2)]:
        conversation = _wa_conversation(db, account.account_uid, name, name=name)
        for index in range(count):
            _wa_message(db, account.account_uid, conversation.conversation_uid, index)
    result = svc.list_pending_bindings(db, actor_user_id=owner.id, actor_permissions=["customer:read"], page=2, page_size=1, sort_field="message_count", sort_order="desc")
    assert result["total"] == 3 and result["items"][0]["message_count"] == 2


def test_candidate_sort_uses_visible_evidence_before_pagination(db):
    from app.customer import pcw_conversation_service as svc
    customer, owner = _customer_with_owner(db, code="SORT-CANDIDATE", user_id=9511)
    _phone_point(db, customer.id, "+8613800138000")
    account = _wa_account(db, owner, "sort-candidate")
    _wa_conversation(db, account.account_uid, "unmatched", phone="+8613999999999")
    _wa_conversation(db, account.account_uid, "matched", phone="+8613800138000")
    result = svc.list_pending_bindings(db, actor_user_id=owner.id, actor_permissions=["customer:read"], page=1, page_size=1, sort_field="candidate_customer_id", sort_order="asc")
    assert result["total"] == 2
    assert result["items"][0]["source_conversation_id"] == "matched"
    result = svc.list_pending_bindings(db, actor_user_id=owner.id, actor_permissions=["customer:read"], page=2, page_size=1, sort_field="candidate_customer_id", sort_order="desc")
    assert result["items"][0]["source_conversation_id"] == "unmatched"


def test_customer_order_amount_numeric_sort_and_unknown_last_both_directions(db):
    from app.customer.pcw_order_service import list_customer_orders
    customer, _ = _account(db, code="SORT-ORDER")
    actor = _actor(db, customer, 9512)
    for seq, value in enumerate([Decimal("100"), Decimal("9"), None], start=991):
        _order(db, customer, seq=seq, order_date=date(2026, 9, 1), amount=value)
    for direction, expected in [("asc", ["9.0000", "100.0000", None]), ("desc", ["100.0000", "9.0000", None])]:
        items = [list_customer_orders(db, customer_id=customer.id, actor_user_id=actor.id, page=page, page_size=1, sort_field="amount", sort_order=direction)["items"][0]["amount"] for page in range(1, 4)]
        assert [Decimal(item) if item is not None else None for item in items] == [Decimal(item) if item is not None else None for item in expected]


def test_prompt_name_sort_cross_pages_restores_default(db):
    seed_versions(db)
    first, total = prompt_service.list_versions(db, page=1, page_size=1, sort_field="name", sort_order="asc")
    second, _ = prompt_service.list_versions(db, page=2, page_size=1, sort_field="name", sort_order="asc")
    all_rows, _ = prompt_service.list_versions(db, sort_field="name", sort_order="asc")
    assert total > 1 and [first[0].id, second[0].id] == [row.id for row in all_rows[:2]]
    restored, _ = prompt_service.list_versions(db, sort_field="name", sort_order=None)
    assert restored[0].default_slot == 1


def test_agent_title_json_and_usage_sort_before_page(db):
    from app.agent_runtime import models, seed
    from app.agent_runtime.service import list_runs
    from tests.test_customer_workflow import _user
    seed.seed_default_profiles(db)
    profile = db.query(models.AgentProfile).filter_by(status="active").first()
    owner = _user(db, 9513)
    session = models.AgentSession(owner_user_id=owner.id, profile_id=profile.id, title="Sort")
    db.add(session)
    db.flush()
    runs = [models.AgentRun(session_id=session.id, profile_id=profile.id, owner_user_id=owner.id,
                            idempotency_key=f"sort-agent-{index}", trigger_type="user", source_runtime="dsh", mode="interactive")
            for index in range(3)]
    db.add_all(runs)
    for row, title, steps in zip(runs, ["Zulu", "Alpha", "Beta"], [4, 1, 2]):
        row.input_json = {"question": title}
        row.steps_used = steps
    db.flush()
    for field in ["task_title", "steps_used"]:
        rows, total = list_runs(db, user_id=session.owner_user_id, can_read_all=True, status=None, runtime=None, page=2, page_size=1, sort_field=field, sort_order="asc")
        assert total == 3 and rows[0].id == runs[2].id


def test_mail_queue_sender_join_and_draft_language_http_sort(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.mail_outreach import job_service
    from app.mail_outreach.models import MailOutreachSendJob
    from app.mail_outreach.router import router
    from tests.mail_outreach_helpers import make_draft, make_mailbox, seed_graph
    graph = seed_graph(db)
    languages = ["zh", "en", "fr"]
    jobs = []
    for index, language in enumerate(languages):
        message, revision = make_draft(db, graph, language_tag=language)
        mailbox = make_mailbox(db, sender_email=f"{language}@sort.test", owner_user_id=graph.user.id)
        job = MailOutreachSendJob(
            idempotency_key=f"sort-mail-{index}", approval_id=index + 1,
            message_id=message.id, revision_id=revision.id, mailbox_binding_id=mailbox.id,
            to_contact_point_id=graph.point.id, to_email_snapshot=graph.point.normalized_value,
            due_at=beijing_now(), due_at_utc=beijing_now(),
        )
        db.add(job)
        db.flush()
        jobs.append(job)
    rows, total = job_service.list_jobs(db, page=2, page_size=1, sort_field="sender_email", sort_order="asc")
    assert total == 3 and rows[0]["id"] == jobs[2].id
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(graph.user.id), "roles": [], "permissions": ["mail_outreach:read", "customer:read_all"]}
    response = TestClient(app).get("/drafts", params={"page": 2, "page_size": 1, "sort_field": "language_tag", "sort_order": "asc"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 3 and data["items"][0]["language_tag"] == "fr"
    assert data["items"][0]["to_email"] == graph.point.normalized_value


@pytest.mark.parametrize("kind, fields", [
    ("customer", ["customer_name", "identity_status", "primary_industry", "relationship_stage", "is_public_pool", "profile_completeness", "updated_at"]),
    ("research", ["customer_name", "task_type", "tier", "task_status", "result_review_status", "data_classification", "updated_at"]),
    ("opportunity", ["title", "customer_name", "status", "priority_level", "owner_name", "due_at", "updated_at"]),
    ("action", ["action_type", "customer_name", "status", "priority", "due_at", "updated_at"]),
    ("qualification", ["customer_name", "scope_label", "match_score", "updated_at"]),
])
def test_customer_hub_all_whitelisted_display_expressions_execute(db, kind, fields):
    from app.customer import qualification_service, query_service
    functions = {
        "customer": query_service.list_customers,
        "research": query_service.list_research_tasks,
        "opportunity": query_service.list_opportunities,
        "action": query_service.list_actions,
        "qualification": qualification_service.list_queue,
    }
    user = {"sub": "1", "roles": ["super_admin"], "permissions": []}
    for field in fields:
        functions[kind](db, user, page=1, page_size=1, sort_field=field, sort_order="asc")
