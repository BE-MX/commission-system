"""Provider calls use real SQLite task/lease records and simulated provider HTTP."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.agent_runtime.seed import seed_default_profiles
from app.core.time import beijing_now
from app.customer.models import CustomerFact, CustomerResearchTask
from app.sales_automation import public_pool_service, research_tools_providers as providers
from app.sales_automation import research_tools_service as gateway, research_tools_worker as worker, service
from app.sales_automation.private_research_policy import PRIVATE_RESEARCH_POLICY
from app.sales_automation.research_tools_models import ResearchToolCall
from tests.test_public_pool_research import _task


@pytest.fixture
def controls(engine, monkeypatch, request):
    settings = SimpleNamespace(
        PRIVATE_RESEARCH_TOOLS_WORKER_ENABLED=True,
        PRIVATE_RESEARCH_MAIGRET_ENABLED=True, PRIVATE_RESEARCH_MAIGRET_TOKEN="a" * 24,
        PRIVATE_RESEARCH_MONID_ENABLED=True, PRIVATE_RESEARCH_MONID_API_KEY="local-test-placeholder",
        PRIVATE_RESEARCH_EGRESS_PROXY="http://user:pass@127.0.0.1:9",
        PRIVATE_RESEARCH_MONID_BUDGET_MICROUSD=20_000,
    )
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        baseline = _task(db)
        seed_default_profiles(db)
        task, _ = public_pool_service.ensure_research_task(
            db, customer_id=baseline.customer_id, task_type="full_research", source_ref_type="manual",
            source_ref_id="v2-test", research_policy_version=PRIVATE_RESEARCH_POLICY,
            input_snapshot={"lead_track": getattr(request, "param", "weak")},
            selection_reason=[{"reason": "test"}], tier=None, created_by=1,
        )
        db.commit()
        task, lease_token = public_pool_service.claim_task(
            db, task.id, 1, "test-agent", external_run=True, supports_private_v2=True,
        )
        task.gate_status = "passed"
        db.commit()
        yield db, sessions, settings, (task.id, 1, "test-agent", lease_token, task.agent_run_id)


def _scan(db, args, key="scan"):
    return gateway.submit_call(
        db, *args, tool="username_scan", operation="username_scan", target="sample-shop",
        idempotency_key=key, free_search={"queries": ["sample-shop public contacts"], "outcome": "insufficient"},
    )


def _paid(db, args, scan_id, operation="instagram_profile", target="sample-shop", key="paid"):
    return gateway.submit_call(
        db, *args, tool="monid", operation=operation, target=target, idempotency_key=key,
        gap="social_activity", maigret_call_id=scan_id,
    )


def test_scan_candidate_is_persisted_but_no_fact_until_bind(controls, monkeypatch):
    db, sessions, settings, args = controls
    queued = _scan(db, args)
    assert queued["status"] == "queued"
    assert _scan(db, args)["call_id"] == queued["call_id"]
    with pytest.raises(service.SalesAutomationError):
        gateway.submit_call(
            db, *args, tool="username_scan", operation="username_scan", target="another",
            idempotency_key="scan", free_search={"queries": ["another contacts"], "outcome": "insufficient"},
        )
    db.rollback()
    monkeypatch.setattr(providers, "scan", lambda *_: {
        "checked": 10, "connection_failures": 0, "unknown": 0,
        "hits": [{"site": "Instagram", "url": "https://www.instagram.com/sample-shop"}],
    })
    worker.process_once(settings, sessions)
    candidate = gateway.get_call(db, *args, tool="username_scan", call_id=queued["call_id"])
    assert candidate["result"]["candidates"][0]["fact_type"] == "social_profile_candidate"
    assert db.query(CustomerFact).count() == 0
    with pytest.raises(service.SalesAutomationError):
        gateway.bind_call(db, *args, tool="username_scan", call_id=queued["call_id"], candidate_ids=[2])
    db.rollback()
    receipt = gateway.bind_call(db, *args, tool="username_scan", call_id=queued["call_id"], candidate_ids=[1])
    assert receipt["evidence_refs"][0]["data_classification"] == "personal_contact"
    again = gateway.bind_call(db, *args, tool="username_scan", call_id=queued["call_id"], candidate_ids=[1])
    assert receipt == again and db.query(CustomerFact).count() == 1


def test_a7_budget_and_ambiguous_post_never_replays(controls, monkeypatch):
    db, sessions, settings, args = controls
    scan = _scan(db, args)
    with pytest.raises(service.ConflictError):
        _paid(db, args, scan["call_id"])
    db.rollback()
    monkeypatch.setattr(providers, "scan", lambda *_: {
        "checked": 10, "connection_failures": 5, "unknown": 5, "hits": [],
    })
    worker.process_once(settings, sessions)
    state = gateway.get_call(db, *args, tool="username_scan", call_id=scan["call_id"])
    assert state["status"] == "unavailable" and state["result"]["outcome"] == "unavailable"
    with pytest.raises(service.ConflictError):
        _paid(db, args, scan["call_id"], target="wrong-subject")
    db.rollback()
    queued = _paid(db, args, scan["call_id"])
    assert _paid(db, args, scan["call_id"])["call_id"] == queued["call_id"]
    count = 0
    def lost_response(*_args, **_kwargs):
        nonlocal count
        count += 1
        raise TimeoutError
    monkeypatch.setattr(providers, "request_json", lost_response)
    monkeypatch.setattr(providers, "monid_prepare", lambda *_args: {"validated": True})
    for _ in range(2):
        worker.process_once(settings, sessions)
    assert count == 1
    status = gateway.get_call(db, *args, tool="monid", call_id=queued["call_id"])
    assert status["status"] == "uncertain" and status["error_code"] == "dispatch_outcome_unknown"
    day = beijing_now().date()
    spend = gateway.list_spend(db, day, day)["by_day"][0]
    assert spend["reserved_usd"] == "0.010000"
    settings.PRIVATE_RESEARCH_MONID_BUDGET_MICROUSD = 19_999
    with pytest.raises(service.ConflictError, match="预算"):
        _paid(db, args, scan["call_id"], operation="tiktok_profile", key="paid2")
    db.rollback()
    with pytest.raises(service.ConflictError):
        _paid(db, args, scan["call_id"], key="duplicate-paid")


def test_queued_payment_is_cancelled_if_lease_expires(controls, monkeypatch):
    db, sessions, settings, args = controls
    scan = _scan(db, args)
    monkeypatch.setattr(providers, "scan", lambda *_: {
        "checked": 8, "connection_failures": 0, "unknown": 0, "hits": [],
    })
    worker.process_once(settings, sessions)
    task = db.get(CustomerResearchTask, args[0])
    payment = _paid(db, args, scan["call_id"])
    task.lease_expires_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    monkeypatch.setattr(providers, "request_json", lambda *_a, **_kw: pytest.fail("expired task sent outbound"))
    worker.process_once(settings, sessions)
    db.expire_all()
    row = db.get(ResearchToolCall, payment["call_id"])
    assert row.status == "cancelled" and row.charged_microusd == 0


@pytest.mark.parametrize("controls", ["company"], indirect=True)
def test_company_can_scan_but_cannot_buy_provider_data(controls, monkeypatch):
    db, sessions, settings, args = controls
    scan = _scan(db, args)
    monkeypatch.setattr(providers, "scan", lambda *_: {
        "checked": 10, "connection_failures": 0, "unknown": 0, "hits": [],
    })
    worker.process_once(settings, sessions)
    with pytest.raises(service.ConflictError, match="弱线索"):
        _paid(db, args, scan["call_id"])
    assert db.query(ResearchToolCall).filter_by(tool="monid").count() == 0


def test_paid_async_pointer_is_persisted_then_settled_once(controls, monkeypatch):
    db, sessions, settings, args = controls
    scan = _scan(db, args)
    monkeypatch.setattr(providers, "scan", lambda *_: {
        "checked": 10, "connection_failures": 0, "unknown": 0, "hits": [],
    })
    worker.process_once(settings, sessions)
    paid = _paid(db, args, scan["call_id"])
    target = "https://www.instagram.com/sample-shop"
    runid = "01J9GKAJ3R84P3BVDDDTQG2XCZ"
    op = providers.OPERATIONS["instagram_profile"]
    meta = {"provider": op.provider, "endpoint": op.endpoint, "runId": runid}
    monkeypatch.setattr(providers, "monid_prepare", lambda *_: {})
    methods = []
    def upstream(_client, method, url, **_kwargs):
        methods.append(method)
        if method == "POST":
            return {**meta, "status": "RUNNING"}
        assert url.endswith(runid)
        return {**meta, "status": "COMPLETED", "cost": {"currency": "USD", "value": 0.002},
                "providerResponse": {"httpStatus": 200}, "output": [{"username": "sample-shop", "url": target,
                                                                     "fullName": "Sample Shop", "followersCount": 87}]}
    monkeypatch.setattr(providers, "request_json", upstream)
    worker.process_once(settings, sessions)
    row = db.get(ResearchToolCall, paid["call_id"])
    assert row.status == "polling" and row.provider_run_id == runid
    worker.process_once(settings, sessions)
    worker.process_once(settings, sessions)
    db.expire_all()
    assert methods == ["POST", "GET"]
    done = gateway.get_call(db, *args, tool="monid", call_id=paid["call_id"])
    assert done["status"] == "succeeded"
    assert done["result"]["candidates"][0]["value"]["followersCount"] == 87
    assert db.query(CustomerFact).count() == 0
    receipt = gateway.bind_call(db, *args, tool="monid", call_id=paid["call_id"], candidate_ids=[1])
    assert len(receipt["evidence_refs"]) == 1
    assert db.query(CustomerFact).one().fact_key == "social_profile"
    day = beijing_now().date()
    by_customer = gateway.list_spend(db, day, day)["by_customer"][0]
    assert by_customer["charged_usd"] == "0.002000" and by_customer["reserved_usd"] == "0.000000"


def test_upstream_charge_drift_stops_already_queued_paid_calls(controls, monkeypatch):
    db, sessions, settings, args = controls
    scan = _scan(db, args)
    monkeypatch.setattr(providers, "scan", lambda *_: {
        "checked": 10, "connection_failures": 0, "unknown": 0, "hits": [],
    })
    worker.process_once(settings, sessions)
    first = _paid(db, args, scan["call_id"])
    second = _paid(db, args, scan["call_id"], operation="tiktok_profile", key="paid2")
    methods = []
    op = providers.OPERATIONS["instagram_profile"]
    def upstream(_client, method, _url, **_kwargs):
        methods.append(method)
        return {"provider": op.provider, "endpoint": op.endpoint, "status": "COMPLETED",
                "providerResponse": {"httpStatus": 404}, "cost": {"currency": "USD", "value": 0.02}}
    monkeypatch.setattr(providers, "request_json", upstream)
    monkeypatch.setattr(providers, "monid_prepare", lambda *_: {})
    worker.process_once(settings, sessions)
    worker.process_once(settings, sessions)
    assert methods == ["POST"]
    assert gateway.get_call(db, *args, tool="monid", call_id=first["call_id"])["error_code"] == "charge_over_cap"
    assert gateway.get_call(db, *args, tool="monid", call_id=second["call_id"])["error_code"] == "budget_unavailable"


def test_invalid_found_urls_never_become_no_matches():
    result = providers.scan_result({"checked": 10, "unknown": 0, "connection_failures": 0,
                                   "hits": [{"site": "Facebook", "url": "https://facebook.com/profile.php?id=1"}]})
    assert result["outcome"] == "unavailable"


@pytest.mark.parametrize("target", ["https://www.linkedin.com/company/name", "https://linkedin.com@evil.com/in/name",
                                   "https://www.linkedin.com/in/name?redirect=http://127.0.0.1"])
def test_linkedin_only_exact_person_path(target):
    with pytest.raises(service.SalesAutomationError):
        providers.normalize_target("monid", "linkedin_profile", target)


def test_price_inspection_bounds_fixed_request_and_real_cost_shape(monkeypatch):
    operation = providers.OPERATIONS["hunter_domain_email"]
    body = {"provider": operation.provider, "endpoint": operation.endpoint,
            "price": {"currency": "USD", "type": "PER_RESULT", "amount": 0.02, "flatFee": 0.001}}
    monkeypatch.setattr(providers, "request_json", lambda *_a, **_kw: body)
    assert providers.monid_prepare(None, "hunter_domain_email", "vendor.com", 20_000) is None
    payload = providers.monid_prepare(None, "hunter_domain_email", "vendor.com", 30_000)
    assert payload["input"] == {"body": {"domain": "vendor.com", "limit": 1}}
    assert providers.reported_charge({"cost": {"value": 0.021, "currency": "USD"}}) == 21_000


@pytest.mark.parametrize(("operation_name", "target", "price_type", "amount", "microusd"), [
    ("instagram_profile", "sample", "PER_RESULT", 0.00081, 810),
    ("tiktok_profile", "sample", "PER_CALL", 0.001, 1000),
    ("facebook_profile", "https://www.facebook.com/sample", "PER_RESULT", 0.006, 6000),
    ("linkedin_profile", "https://www.linkedin.com/in/sample", "PER_CALL", 0.01, 10000),
    ("hunter_domain_email", "example.com", "PER_RESULT", 0.0245, 24500),
])
def test_monid_inspect_accepts_live_quotes_within_the_reserved_budget(
    monkeypatch, operation_name, target, price_type, amount, microusd,
):
    operation = providers.OPERATIONS[operation_name]
    reply = {
        "provider": operation.provider,
        "endpoint": operation.endpoint,
        "price": {"type": price_type, "amount": {"value": amount, "currency": "USD"}},
    }

    def request_inspect(_client, method, url, *, json):
        assert method == "POST" and url == f"{providers.MONID_BASE}/inspect"
        assert json == {"provider": operation.provider, "endpoint": operation.endpoint}
        return reply

    monkeypatch.setattr(providers, "request_json", request_inspect)
    assert providers.monid_prepare(None, operation_name, target, microusd) is not None
    assert providers.monid_prepare(None, operation_name, target, microusd - 1) is None


def test_monid_price_rejects_foreign_currency_and_counts_nested_usd_fees():
    price = {
        "type": "PER_RESULT",
        "amount": {"value": 0.006, "currency": "USD"},
        "flatFee": {"value": 0.001, "currency": "USD"},
    }
    assert providers._expected_max_price(price) == 7000
    assert providers._expected_max_price({**price, "currency": "EUR"}) is None
    assert providers._expected_max_price({**price, "flatFee": {"value": 0.001, "currency": "EUR"}}) is None
    assert providers._expected_max_price({**price, "amount": {"value": "NaN", "currency": "USD"}}) is None
    assert providers._expected_max_price({**price, "flatFee": {"value": "1e-34", "currency": "USD"}}) > 6000
    assert providers._expected_max_price({**price, "amount": {"value": "1e999999", "currency": "USD"}}) is None
    assert providers._expected_max_price({**price, "type": []}) is None


def test_facebook_profile_supplies_required_minimum_max_posts(monkeypatch):
    operation = providers.OPERATIONS["facebook_profile"]
    target = "https://www.facebook.com/sample-shop"
    reply = {
        "provider": operation.provider,
        "endpoint": operation.endpoint,
        "price": {"currency": "USD", "type": "PER_RESULT", "amount": 0.006},
    }
    monkeypatch.setattr(providers, "request_json", lambda *_args, **_kwargs: reply)

    payload = providers.monid_prepare(None, "facebook_profile", target, operation.cap)

    assert payload["input"] == {
        "body": {"endpoint": "details_by_url", "urls_text": target, "max_posts": 1},
    }


@pytest.mark.parametrize(("result", "matches"), [
    ({"fullName": "Unidentified Person"}, False),
    ({"fullName": "Another Person", "linkedinUrl": "https://www.linkedin.com/in/other"}, False),
    ({"fullName": "Conflicting Person", "publicIdentifier": "sample", "linkedinUrl": "https://example.com"}, False),
    ({"fullName": "Matching Person", "publicIdentifier": "sample"}, True),
    ({"fullName": "Matching Person", "linkedinUrl": "https://linkedin.com/in/sample/"}, True),
])
def test_monid_candidate_requires_provider_owned_target_match(result, matches):
    raw = {"status": "COMPLETED", "providerResponse": {"httpStatus": 200}, "output": result}
    outcome = providers.monid_result("linkedin_profile", "https://www.linkedin.com/in/sample", raw)
    assert bool(outcome["candidates"]) is matches
