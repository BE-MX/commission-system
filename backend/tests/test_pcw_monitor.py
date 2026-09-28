"""PCW-05 客户官网与社媒监控服务契约测试。"""

from __future__ import annotations

import socket
from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAction,
    CustomerAnnotation,
    CustomerAssignment,
    CustomerSourceRecord,
)
from app.customer.pcw_models import (
    CustomerWorkItem,
    MonitorEvent,
    MonitorEventSource,
    MonitorSubscription,
)
from app.customer.pcw_monitor_service import (
    create_subscription,
    decide_event,
    list_events,
    list_subscriptions,
    normalize_url_hash,
    patch_subscription,
    run_subscription,
    validate_monitor_url,
)
from tests.test_customer_workflow import _account, _grant_permission, _user

NOW = beijing_now().replace(microsecond=0)

PUBLIC_ADDR = ("93.184.216.34", 443)
PRIVATE_ADDR = ("192.168.1.10", 443)
LOOPBACK_ADDR = ("127.0.0.1", 443)


def _fake_getaddrinfo(addr):
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", addr)]

    return fake


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(PUBLIC_ADDR))


def _customer(db, *, code: str, user_id: int):
    account, _version = _account(db, code=code)
    owner = _user(db, user_id)
    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=owner.id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=owner.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    return account, owner


def _fetcher(content, *, status=200, content_type="text/html; charset=utf-8", final_url=None):
    def fetch(url, *, max_bytes, timeout_sec):
        return {
            "content": content,
            "content_type": content_type,
            "final_url": final_url or url,
            "status": status,
        }

    return fetch


def _failing_fetcher(exc):
    def fetch(url, *, max_bytes, timeout_sec):
        raise exc

    return fetch


def _create(db, account, owner, *, url="https://acme.example/news", channel="website", interval_days=7):
    return create_subscription(
        db,
        customer_id=account.id,
        actor_user_id=owner.id,
        channel=channel,
        url=url,
        interval_days=interval_days,
    )


def _subscription(db, subscription_id: int) -> MonitorSubscription:
    return db.get(MonitorSubscription, subscription_id)


# ─────────────────────────────────────────────────────────────────────────────
# A. URL 校验
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_monitor_url_rejects_non_https():
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        validate_monitor_url("http://acme.example/news")
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "URL_NOT_ALLOWED"


def test_validate_monitor_url_rejects_ip_literal():
    for url in ("https://192.168.1.1/", "https://8.8.8.8/news", "https://[::1]/"):
        with pytest.raises(pcw_errors.PcwError) as excinfo:
            validate_monitor_url(url)
        assert excinfo.value.error_code == "URL_NOT_ALLOWED"


def test_validate_monitor_url_rejects_credentials():
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        validate_monitor_url("https://user:pass@acme.example/news")
    assert excinfo.value.error_code == "URL_NOT_ALLOWED"


def test_validate_monitor_url_rejects_single_label_host():
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        validate_monitor_url("https://localhost/")
    assert excinfo.value.error_code == "URL_NOT_ALLOWED"


def test_validate_monitor_url_rejects_private_resolution(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(PRIVATE_ADDR))
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        validate_monitor_url("https://intranet.acme.example/")
    assert excinfo.value.error_code == "URL_NOT_ALLOWED"

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(LOOPBACK_ADDR))
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        validate_monitor_url("https://intranet.acme.example/")
    assert excinfo.value.error_code == "URL_NOT_ALLOWED"


def test_validate_monitor_url_rejects_when_any_resolution_is_private(monkeypatch):
    def mixed(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", PUBLIC_ADDR),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", PRIVATE_ADDR),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        validate_monitor_url("https://acme.example/")
    assert excinfo.value.error_code == "URL_NOT_ALLOWED"


def test_validate_monitor_url_dns_failure(monkeypatch):
    def broken(host, port, *args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", broken)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        validate_monitor_url("https://no-such-host.acme.example/")
    assert excinfo.value.error_code == "URL_NOT_ALLOWED"
    assert "解析" in excinfo.value.message


def test_validate_monitor_url_normalizes(public_dns):
    assert (
        validate_monitor_url("HTTPS://Acme.Example:443/news/#frag")
        == "https://acme.example/news"
    )
    assert validate_monitor_url("https://acme.example/") == "https://acme.example"
    assert validate_monitor_url("https://acme.example/news/") == "https://acme.example/news"
    assert (
        validate_monitor_url("https://acme.example:8443/n?a=1&b=2")
        == "https://acme.example:8443/n?a=1&b=2"
    )
    # IDN 转 punycode
    assert (
        validate_monitor_url("https://münchen.example/")
        == "https://xn--mnchen-3ya.example"
    )
    digest = normalize_url_hash("https://acme.example/news")
    assert digest == normalize_url_hash("https://acme.example/news")
    assert len(digest) == 64


# ─────────────────────────────────────────────────────────────────────────────
# B. 订阅管理
# ─────────────────────────────────────────────────────────────────────────────


def test_create_subscription_success(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-01", user_id=9301)
    result = _create(db, account, owner)
    assert result["enabled"] is True
    assert result["collection_status"] == "baseline"
    assert result["interval_days"] == 7
    assert result["row_version"] == 1
    assert result["url"] == "https://acme.example/news"
    assert result["next_run_at"] is not None
    row = _subscription(db, result["id"])
    assert row.enabled is True
    assert row.baseline_source_record_id is None


def test_create_subscription_duplicate_returns_409_with_existing_id(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-02", user_id=9302)
    first = _create(db, account, owner, url="https://acme.example/news")
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _create(db, account, owner, url="HTTPS://Acme.Example:443/news/#top")
    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "SUBSCRIPTION_EXISTS"
    assert excinfo.value.details["existing_id"] == first["id"]


def test_create_subscription_limit_exceeded(db, public_dns, monkeypatch):
    account, owner = _customer(db, code="C-PCW-MON-03", user_id=9303)
    monkeypatch.setattr(get_settings(), "PCW_MONITOR_MAX_SUBSCRIPTIONS_PER_CUSTOMER", 1)
    _create(db, account, owner, url="https://acme.example/news")
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _create(db, account, owner, url="https://acme.example/blog")
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "SUBSCRIPTION_LIMIT_EXCEEDED"


def test_create_subscription_invalid_channel_and_interval(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-04", user_id=9304)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _create(db, account, owner, channel="twitter")
    assert excinfo.value.error_code == "MONITOR_CHANNEL_INVALID"
    for bad_interval in (0, 91):
        with pytest.raises(pcw_errors.PcwError) as excinfo:
            _create(db, account, owner, interval_days=bad_interval)
        assert excinfo.value.error_code == "MONITOR_INTERVAL_INVALID"


def test_create_subscription_denied_for_outsider_and_unknown_customer(db, public_dns):
    account, _owner = _customer(db, code="C-PCW-MON-05", user_id=9305)
    outsider = _user(db, 9306)  # 有 customer:write 但不在客户归属范围
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_subscription(
            db,
            customer_id=account.id,
            actor_user_id=outsider.id,
            channel="website",
            url="https://acme.example/news",
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.error_code == "CUSTOMER_NOT_FOUND_OR_FORBIDDEN"
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_subscription(
            db,
            customer_id=999999,
            actor_user_id=outsider.id,
            channel="website",
            url="https://acme.example/news",
        )
    assert excinfo.value.error_code == "CUSTOMER_NOT_FOUND_OR_FORBIDDEN"


def test_patch_pause_resume_only_toggles_enabled(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-06", user_id=9307)
    created = _create(db, account, owner)
    sub_id = created["id"]
    # 先跑出一次成功（基线）再制造一次失败，让 last_success_at / last_error 都有值
    run_subscription(
        db, subscription_id=sub_id,
        fetcher=_fetcher("<html><body><h1>Hello World</h1></body></html>"),
    )
    run_subscription(
        db, subscription_id=sub_id,
        fetcher=_failing_fetcher(TimeoutError("timed out")),
    )
    row = _subscription(db, sub_id)
    assert row.collection_status == "failed"
    assert row.last_error == "FETCH_TIMEOUT"
    success_at = row.last_success_at
    assert success_at is not None
    next_run_at = row.next_run_at

    # 暂停：只改 enabled + row_version
    paused = patch_subscription(
        db, subscription_id=sub_id, actor_user_id=owner.id,
        expected_subscription_version=1, enabled=False,
    )
    assert paused["enabled"] is False
    assert paused["row_version"] == 2
    row = _subscription(db, sub_id)
    assert row.collection_status == "failed"  # 不被暂停重置
    assert row.last_error == "FETCH_TIMEOUT"
    assert row.last_success_at == success_at
    assert row.next_run_at == next_run_at  # 未改频率不重算
    assert row.baseline_source_record_id is not None

    # 恢复：同样只动 enabled；同时验证改频率会重算 next_run_at
    resumed = patch_subscription(
        db, subscription_id=sub_id, actor_user_id=owner.id,
        expected_subscription_version=2, enabled=True, interval_days=3,
    )
    assert resumed["enabled"] is True
    assert resumed["row_version"] == 3
    row = _subscription(db, sub_id)
    assert row.last_error == "FETCH_TIMEOUT"
    assert row.last_success_at == success_at
    expected_next = row.updated_at + timedelta(days=3)
    assert abs((row.next_run_at - expected_next).total_seconds()) < 2


def test_patch_subscription_version_conflict(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-07", user_id=9308)
    created = _create(db, account, owner)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        patch_subscription(
            db, subscription_id=created["id"], actor_user_id=owner.id,
            expected_subscription_version=99, enabled=False,
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "SUBSCRIPTION_VERSION_CONFLICT"
    assert excinfo.value.details["current_subscription_version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# C. 采集执行
# ─────────────────────────────────────────────────────────────────────────────


def test_run_disabled_switch_records_honest_failure(db, public_dns, monkeypatch):
    account, owner = _customer(db, code="C-PCW-MON-08", user_id=9309)
    monkeypatch.setattr(get_settings(), "PCW_MONITOR_ENABLED", False)
    created = _create(db, account, owner)
    result = run_subscription(db, subscription_id=created["id"])  # 未注入 fetcher
    assert result["status"] == "disabled"
    row = _subscription(db, created["id"])
    assert row.last_attempt_at is not None
    assert row.last_error == "MONITOR_FETCH_DISABLED"
    assert row.collection_status == "baseline"  # 不被失败尝试改变
    assert row.last_success_at is None
    assert row.baseline_source_record_id is None
    # 绝不假装成功：不产生任何快照
    assert db.query(CustomerSourceRecord).count() == 0


def test_run_paused_subscription_untouched_and_force_collects(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-09", user_id=9310)
    created = _create(db, account, owner)
    patch_subscription(
        db, subscription_id=created["id"], actor_user_id=owner.id,
        expected_subscription_version=1, enabled=False,
    )
    result = run_subscription(
        db, subscription_id=created["id"],
        fetcher=_fetcher("<html><body>Hello World</body></html>"),
    )
    assert result["status"] == "paused"
    row = _subscription(db, created["id"])
    assert row.last_attempt_at is None  # 暂停不动任何字段
    assert row.last_error is None

    forced = run_subscription(
        db, subscription_id=created["id"], force=True,
        fetcher=_fetcher("<html><body>Hello World</body></html>"),
    )
    assert forced["status"] == "baseline"
    row = _subscription(db, created["id"])
    assert row.enabled is False  # force 采集不改变调度开关
    assert row.baseline_source_record_id is not None


CONTENT_A = "<html><body><h1>Hello  World</h1></body></html>"
CONTENT_A_WHITESPACE_VARIANT = "<html><body><h1>Hello World</h1></body></html>"
CONTENT_B = "<html><body><h1>Big Sale</h1><p>New fall collection</p></body></html>"


def test_run_baseline_change_and_stable_key_dedup(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-10", user_id=9311)
    created = _create(db, account, owner)
    sub_id = created["id"]

    # 首次成功：只建基线，无事件
    r1 = run_subscription(db, subscription_id=sub_id, fetcher=_fetcher(CONTENT_A))
    assert r1["status"] == "baseline"
    row = _subscription(db, sub_id)
    assert row.baseline_source_record_id is not None
    assert row.collection_status == "baseline"
    assert row.last_success_at is not None
    assert db.query(MonitorEvent).count() == 0

    # 第二次同内容（仅空白差异）：无事件，状态转 active
    r2 = run_subscription(
        db, subscription_id=sub_id, fetcher=_fetcher(CONTENT_A_WHITESPACE_VARIANT)
    )
    assert r2["status"] == "unchanged"
    row = _subscription(db, sub_id)
    assert row.collection_status == "active"
    assert db.query(MonitorEvent).count() == 0

    # 第三次内容变化：恰好一条事件，挂源快照
    r3 = run_subscription(db, subscription_id=sub_id, fetcher=_fetcher(CONTENT_B))
    assert r3["status"] == "changed"
    assert r3["event_reused"] is False
    events = db.query(MonitorEvent).all()
    assert len(events) == 1
    event = events[0]
    assert event.status == "pending"
    assert event.event_type == "general"
    assert event.confidence == "low"
    assert event.occurred_at is None  # 发布时间未知不猜
    assert event.discovered_at is not None and event.collected_at is not None
    assert event.old_value and "Hello World" in event.old_value
    assert event.new_value and "Big Sale" in event.new_value
    sources = db.query(MonitorEventSource).filter_by(event_id=event.id).all()
    assert len(sources) == 2  # 新快照 + 旧快照
    # 快照 payload 只存摘要/哈希/URL/状态码，不存整页 HTML
    for source in sources:
        snapshot = db.get(CustomerSourceRecord, source.source_record_id)
        assert snapshot.source_system == "public_web"
        assert snapshot.source_entity_type == "company_page"
        assert "<h1>" not in str(snapshot.payload_json)

    # 第四次同内容：无事件
    r4 = run_subscription(db, subscription_id=sub_id, fetcher=_fetcher(CONTENT_B))
    assert r4["status"] == "unchanged"
    assert db.query(MonitorEvent).count() == 1

    # 内容摆回 A：与最近快照（B）不同 → 变化；A 此前无事件 → 新建
    r5 = run_subscription(db, subscription_id=sub_id, fetcher=_fetcher(CONTENT_A))
    assert r5["status"] == "changed"
    assert db.query(MonitorEvent).count() == 2

    # 继续 A：stable_event_key 去重，同内容重复发现不重复事件
    r6 = run_subscription(db, subscription_id=sub_id, fetcher=_fetcher(CONTENT_A))
    assert r6["status"] == "changed"
    assert r6["event_reused"] is True
    assert r6["event_id"] == r5["event_id"]
    assert db.query(MonitorEvent).count() == 2

    # 快照层同样按内容去重：6 次采集只有 2 条版本记录
    assert db.query(CustomerSourceRecord).count() == 2


def test_run_failure_preserves_success_watermark(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-11", user_id=9312)
    created = _create(db, account, owner)
    sub_id = created["id"]
    run_subscription(db, subscription_id=sub_id, fetcher=_fetcher(CONTENT_A))
    row = _subscription(db, sub_id)
    success_at = row.last_success_at
    baseline_id = row.baseline_source_record_id

    failed = run_subscription(
        db, subscription_id=sub_id, fetcher=_failing_fetcher(TimeoutError("timed out"))
    )
    assert failed["status"] == "failed"
    assert failed["error_code"] == "FETCH_TIMEOUT"
    row = _subscription(db, sub_id)
    assert row.collection_status == "failed"
    assert row.last_error == "FETCH_TIMEOUT"
    assert row.last_success_at == success_at  # 失败保留旧成功时间
    assert row.baseline_source_record_id == baseline_id  # 基线保留
    assert row.last_attempt_at >= success_at


def test_run_fetch_result_constraints_enforced_for_injected_fetcher(db, public_dns, monkeypatch):
    account, owner = _customer(db, code="C-PCW-MON-12", user_id=9313)
    created = _create(db, account, owner)
    sub_id = created["id"]

    # Content-Type 不在白名单
    result = run_subscription(
        db, subscription_id=sub_id,
        fetcher=_fetcher('{"ok": true}', content_type="application/json"),
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "FETCH_CONTENT_TYPE"

    # 响应体超过上限
    monkeypatch.setattr(get_settings(), "PCW_MONITOR_FETCH_MAX_BYTES", 16)
    result = run_subscription(
        db, subscription_id=sub_id,
        fetcher=_fetcher("<html><body>this body is definitely too large</body></html>"),
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "FETCH_TOO_LARGE"

    # HTTP 错误状态
    result = run_subscription(
        db, subscription_id=sub_id, fetcher=_fetcher("x", status=500),
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "FETCH_HTTP_ERROR"

    # 全部失败：不建基线、不产生事件
    assert db.query(MonitorEvent).count() == 0
    row = _subscription(db, sub_id)
    assert row.baseline_source_record_id is None
    assert row.collection_status == "failed"


def test_run_unknown_subscription_404(db):
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        run_subscription(db, subscription_id=999999, fetcher=_fetcher("x"))
    assert excinfo.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# D. 事件查询与决策
# ─────────────────────────────────────────────────────────────────────────────


def _produce_event(db, account, owner, *, code_url="https://acme.example/news"):
    created = _create(db, account, owner, url=code_url)
    run_subscription(db, subscription_id=created["id"], fetcher=_fetcher(CONTENT_A))
    run_subscription(db, subscription_id=created["id"], fetcher=_fetcher(CONTENT_B))
    return db.query(MonitorEvent).one()


def test_list_events_with_sources_and_status_filter(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-13", user_id=9314)
    _grant_permission(db, owner.id, "customer:read")
    event = _produce_event(db, account, owner)

    result = list_events(db, customer_id=account.id, actor_user_id=owner.id)
    assert result["total"] == 1
    assert result["page"] == 1
    item = result["items"][0]
    assert item["id"] == event.id
    assert item["status"] == "pending"
    assert len(item["sources"]) == 2

    pending = list_events(
        db, customer_id=account.id, actor_user_id=owner.id, status="pending"
    )
    assert pending["total"] == 1
    ignored = list_events(
        db, customer_id=account.id, actor_user_id=owner.id, status="ignored"
    )
    assert ignored["total"] == 0

    subscriptions = list_subscriptions(
        db, customer_id=account.id, actor_user_id=owner.id
    )
    assert len(subscriptions["items"]) == 1
    assert subscriptions["items"][0]["collection_status"] == "active"


def test_decide_confirm_creates_exactly_one_action_and_replays(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-14", user_id=9315)
    event = _produce_event(db, account, owner)
    before = beijing_now()

    result = decide_event(
        db, event_id=event.id, actor_user_id=owner.id,
        operation="confirm", expected_event_version=1,
        reason="已核验官网公告",
        idempotency_key="monitor-confirm-0001-aaaa",
    )
    assert result["event"]["status"] == "confirmed"
    assert result["event"]["version"] == 2
    action_id = result["action_id"]
    assert action_id is not None

    db.refresh(event)
    assert event.status == "confirmed"
    assert event.action_id == action_id
    assert event.decided_by == owner.id
    assert event.decision_reason == "已核验官网公告"
    assert event.row_version == 2

    action = db.get(CustomerAction, action_id)
    assert action.thread_group == "key_account"
    assert action.action_type == "research"
    assert action.priority == "normal"  # general 事件
    assert action.owner_user_id == owner.id  # 当前 primary
    assert action.channel is None
    assert action.due_provenance == "monitor_event"
    assert before + timedelta(days=3) - timedelta(seconds=2) <= action.business_due_at
    work_item = db.get(CustomerWorkItem, action.work_item_id)
    assert work_item.business_key == f"monitor_event:{event.stable_event_key}"
    assert work_item.business_cycle == "v1"
    assert work_item.work_type == "monitor"

    # 同键重放：返回同一 action，不产生第二个
    replay = decide_event(
        db, event_id=event.id, actor_user_id=owner.id,
        operation="confirm", expected_event_version=1,
        reason="已核验官网公告",
        idempotency_key="monitor-confirm-0001-aaaa",
    )
    assert replay["action_id"] == action_id
    work_item_id = work_item.id
    assert db.query(CustomerAction).filter_by(work_item_id=work_item_id).count() == 1
    db.commit()

    # 不同键重复决定：已 decided → 409
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_event(
            db, event_id=event.id, actor_user_id=owner.id,
            operation="confirm", expected_event_version=2,
            reason="再次确认",
            idempotency_key="monitor-confirm-0001-bbbb",
        )
    assert excinfo.value.error_code == "EVENT_ALREADY_DECIDED"
    db.rollback()
    assert db.query(CustomerAction).filter_by(work_item_id=work_item_id).count() == 1


def test_decide_confirm_high_priority_event_types(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-15", user_id=9316)
    event = MonitorEvent(
        customer_id=account.id,
        stable_event_key="procurement:acme.example:2026-09-24",
        event_type="procurement",
        title="官网发布采购招募",
        status="pending",
        confidence="low",
        row_version=1,
    )
    db.add(event)
    db.flush()
    result = decide_event(
        db, event_id=event.id, actor_user_id=owner.id,
        operation="confirm", expected_event_version=1,
    )
    action = db.get(CustomerAction, result["action_id"])
    assert action.priority == "high"


def test_decide_event_version_conflict_returns_current(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-16", user_id=9317)
    event = _produce_event(db, account, owner)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_event(
            db, event_id=event.id, actor_user_id=owner.id,
            operation="confirm", expected_event_version=99,
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "MONITOR_EVENT_VERSION_CONFLICT"
    assert excinfo.value.details["current_event_version"] == 1


def test_decide_confirm_dnc_blocks_and_keeps_pending(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-17", user_id=9318)
    event = _produce_event(db, account, owner)
    db.add(CustomerAnnotation(
        customer_id=account.id,
        annotation_type="do_not_contact",
        content_schema_version="v1",
        content_json={"text": "客户要求停止联系"},
        policy_scope_type="global",
        policy_effective_at=NOW - timedelta(days=1),
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=owner.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.commit()  # 先提交前置数据，使预期失败的 decide 回滚后现场仍可校验

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_event(
            db, event_id=event.id, actor_user_id=owner.id,
            operation="confirm", expected_event_version=1,
            idempotency_key="monitor-confirm-dnc-0001",
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "CONTACT_RESTRICTED"
    db.rollback()
    db.refresh(event)
    assert event.status == "pending"  # 事件保持 pending，无副作用
    assert event.action_id is None
    assert db.query(CustomerAction).count() == 0
    assert db.query(CustomerWorkItem).count() == 0


def test_decide_ignore_requires_reason(db, public_dns):
    account, owner = _customer(db, code="C-PCW-MON-18", user_id=9319)
    event = _produce_event(db, account, owner)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_event(
            db, event_id=event.id, actor_user_id=owner.id,
            operation="ignore", expected_event_version=1, reason="  ",
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "DECISION_REASON_REQUIRED"

    result = decide_event(
        db, event_id=event.id, actor_user_id=owner.id,
        operation="ignore", expected_event_version=1,
        reason="误报，与客户业务无关",
        idempotency_key="monitor-ignore-0001-aaaa",
    )
    assert result["event"]["status"] == "ignored"
    assert result["action_id"] is None
    db.refresh(event)
    assert event.status == "ignored"
    assert event.decision_reason == "误报，与客户业务无关"
    assert event.decided_by == owner.id
    assert event.row_version == 2
    assert db.query(CustomerAction).count() == 0  # 忽略不产生任务

    replay = decide_event(
        db, event_id=event.id, actor_user_id=owner.id,
        operation="ignore", expected_event_version=1,
        reason="误报，与客户业务无关",
        idempotency_key="monitor-ignore-0001-aaaa",
    )
    assert replay["event"]["status"] == "ignored"

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_event(
            db, event_id=event.id, actor_user_id=owner.id,
            operation="ignore", expected_event_version=2,
            reason="重复忽略",
            idempotency_key="monitor-ignore-0001-bbbb",
        )
    assert excinfo.value.error_code == "EVENT_ALREADY_DECIDED"
    db.rollback()
