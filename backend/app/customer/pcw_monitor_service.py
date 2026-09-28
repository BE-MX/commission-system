"""私海客户工作台（PCW）：PCW-05 客户官网与社媒监控服务。

设计依据 docs/requirements/private-customer-workbench-prototype/：
- development-spec.md PCW-05：调度开关 enabled 独立于采集状态 baseline/active/failed；
  首次成功只建立基线，不产生事件；失败显示失败而非"无变化"；快照引用不可变来源记录。
- api-contracts.md §3/§4.4：订阅创建/暂停恢复、事件决定的版本前置、幂等与稳定错误码。
- schema-migrations.md §1：MonitorSubscription / MonitorEvent / MonitorEventSource 语义；
  原始快照复用 CustomerSourceRecord（public_web/company_page 注册见 contracts.SOURCE_REGISTRY）。

SSRF 防护（validate_monitor_url）：仅 https、禁凭据、禁 IP 字面量、IDN 转 punycode、
host 必须含 "."、DNS 解析结果逐一用 ipaddress 判定，任一私网/回环/链路本地/保留/组播/
未指定地址即拒绝；真实采集器对每一跳重定向重新执行同一校验。

真实网络采集只在 settings.PCW_MONITOR_ENABLED=True 时发生；开关关闭且未注入 fetcher
时记录一次诚实的失败尝试（MONITOR_FETCH_DISABLED），绝不假装成功。已知限制：DNS 校验
与 TCP 连接之间存在 TOCTOU 窗口，未做解析结果钉死（connect-by-IP），上线前需评估。
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import get_live_user_authorization
from app.core.config import get_settings
from app.core.time import beijing_now, to_beijing_time
from app.customer import pcw_errors
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.fact_service import append_source_record
from app.customer.models import CustomerAssignment, CustomerSourceRecord
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.pcw_models import (
    MonitorEvent,
    MonitorEventSource,
    MonitorSubscription,
)
from app.customer.pcw_workitem_service import create_pcw_action, ensure_work_item

logger = logging.getLogger(__name__)

MONITOR_CHANNELS = frozenset({"website", "instagram", "facebook", "linkedin", "news"})
COLLECTION_STATUSES = frozenset({"baseline", "active", "failed", "restricted"})
EVENT_DECIDED_STATUSES = frozenset({"confirmed", "ignored"})
EVENT_STATUSES = frozenset({"pending", "confirmed", "ignored"})

INTERVAL_DAYS_MIN = 1
INTERVAL_DAYS_MAX = 90
MAX_URL_LENGTH = 1000
FETCH_TIMEOUT_SECONDS = 10
MAX_REDIRECT_HOPS = 5
ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
EVENT_EXCERPT_MAX_CHARS = 500
SNAPSHOT_EXCERPT_MAX_CHARS = 20_000

SNAPSHOT_PAYLOAD_SCHEMA_VERSION = "pcw_monitor_snapshot_v1"
SNAPSHOT_SOURCE_SYSTEM = "public_web"
SNAPSHOT_SOURCE_ENTITY_TYPE = "company_page"
SNAPSHOT_SOURCE_ACCOUNT_KEY = "global"  # 公开信源无账号隔离，固定 global（模型约定）
MONITOR_POLICY_VERSION = "pcw_monitor_v1"

# 采集失败稳定码：记录到 MonitorSubscription.last_error
FETCH_ERROR_CODES = frozenset({
    "FETCH_TIMEOUT",
    "FETCH_HTTP_ERROR",
    "FETCH_CONTENT_TYPE",
    "FETCH_TOO_LARGE",
    "FETCH_INVALID_REDIRECT",
    "FETCH_ERROR",
    "MONITOR_FETCH_DISABLED",
})

_READ_PERMISSIONS = {"customer:read", "customer:read_all", "customer:admin"}
_WRITE_PERMISSIONS = {"customer:write", "customer:read_all", "customer:admin"}
_MANAGE_PERMISSIONS = {"customer:read_all", "customer:admin"}

_HIGH_PRIORITY_EVENT_TYPES = frozenset({"procurement", "store_opening"})

_CHANNEL_LABELS = {
    "website": "官网",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "news": "新闻",
}

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


class _MonitorFetchError(Exception):
    """采集失败的内部稳定码载体；run_subscription 捕获后落入 last_error。"""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


# ─────────────────────────────────────────────────────────────────────────────
# A. URL 校验（SSRF 防护）
# ─────────────────────────────────────────────────────────────────────────────


def _reject_url(message: str) -> pcw_errors.PcwError:
    return pcw_errors.bad_request(message, error_code="URL_NOT_ALLOWED")


def _resolve_host_addresses(ascii_host: str, port: int) -> list:
    try:
        infos = socket.getaddrinfo(ascii_host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        raise _reject_url(f"订阅地址的域名无法解析：{ascii_host}") from exc
    if not infos:
        raise _reject_url(f"订阅地址的域名无法解析：{ascii_host}")
    return infos


def validate_monitor_url(url: str) -> str:
    """校验并规范化监控订阅 URL，返回规范化形式；不合法抛 400 URL_NOT_ALLOWED。

    规范化：scheme/host 小写、去默认端口 443、去 fragment、去路径末尾 "/"（保留
    有意义路径）、查询串原样保留；规范化结果长度 ≤1000。
    """
    raw = (url or "").strip()
    if not raw or len(raw) > 2048:
        raise _reject_url("订阅地址为空或超出长度限制")
    try:
        split = urlsplit(raw)
    except ValueError as exc:
        raise _reject_url("订阅地址不是合法 URL") from exc
    if (split.scheme or "").lower() != "https":
        raise _reject_url("订阅地址仅允许 https")
    if split.username is not None or split.password is not None:
        raise _reject_url("订阅地址不允许携带用户名或密码")
    try:
        port = split.port
    except ValueError as exc:
        raise _reject_url("订阅地址端口不合法") from exc
    host = split.hostname or ""
    if not host:
        raise _reject_url("订阅地址缺少主机名")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise _reject_url("订阅地址不允许直接使用 IP 地址")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError) as exc:
        raise _reject_url("订阅地址主机名不合法") from exc
    if "." not in ascii_host or len(ascii_host) > 253:
        raise _reject_url("订阅地址主机名不合法")
    for info in _resolve_host_addresses(ascii_host, port or 443):
        address = info[4][0]
        try:
            resolved = ipaddress.ip_address(address)
        except ValueError as exc:
            raise _reject_url("订阅地址解析结果不合法") from exc
        if (
            resolved.is_private
            or resolved.is_loopback
            or resolved.is_link_local
            or resolved.is_reserved
            or resolved.is_multicast
            or resolved.is_unspecified
        ):
            raise _reject_url("订阅地址解析到内网、回环或保留地址，不允许监控")
    netloc = ascii_host if port in (None, 443) else f"{ascii_host}:{port}"
    path = split.path or ""
    while len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    if path == "/":
        path = ""
    normalized = urlunsplit(("https", netloc, path, split.query, ""))
    if len(normalized) > MAX_URL_LENGTH:
        raise _reject_url("规范化后的订阅地址超出长度限制")
    return normalized


def normalize_url_hash(normalized_url: str) -> str:
    """规范化 URL 的 SHA-256，用于 unique(customer, channel, url_hash) 去重。"""
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# 公共：访问校验、序列化
# ─────────────────────────────────────────────────────────────────────────────


def _require_access(
    db: Session, *, customer_id: int, actor_user_id: int, write: bool
):
    """客户访问校验（access_service）：实时归属 ∩ 动作权限；失权/不存在统一 404。"""
    roles, permissions = get_live_user_authorization(db, int(actor_user_id))
    user = {
        "sub": str(int(actor_user_id)),
        "roles": roles,
        "permissions": permissions,
    }
    try:
        return require_customer_access(
            db,
            customer_id=int(customer_id),
            user=user,
            action_permissions=_WRITE_PERMISSIONS if write else _READ_PERMISSIONS,
            manage_permissions=_MANAGE_PERMISSIONS,
        )
    except CustomerAccessDenied:
        raise pcw_errors.customer_not_found() from None


def _iso_bj(value: datetime | None) -> str | None:
    if value is None:
        return None
    return to_beijing_time(value).isoformat(timespec="seconds")


def _subscription_dict(sub: MonitorSubscription) -> dict:
    return {
        "id": int(sub.id),
        "customer_id": int(sub.customer_id),
        "channel": sub.channel,
        "url": sub.url,
        "normalized_url_hash": sub.normalized_url_hash,
        "interval_days": int(sub.interval_days),
        "enabled": bool(sub.enabled),
        "collection_status": sub.collection_status,
        "baseline_source_record_id": (
            int(sub.baseline_source_record_id)
            if sub.baseline_source_record_id is not None
            else None
        ),
        "last_attempt_at": _iso_bj(sub.last_attempt_at),
        "last_success_at": _iso_bj(sub.last_success_at),
        "last_error": sub.last_error,
        "next_run_at": _iso_bj(sub.next_run_at),
        "row_version": int(sub.row_version),
        "created_by": int(sub.created_by),
        "created_at": _iso_bj(sub.created_at),
        "updated_at": _iso_bj(sub.updated_at),
    }


def _event_dict(db: Session, event: MonitorEvent) -> dict:
    sources = (
        db.query(MonitorEventSource)
        .filter(MonitorEventSource.event_id == event.id)
        .order_by(MonitorEventSource.id)
        .all()
    )
    return {
        "id": int(event.id),
        "customer_id": int(event.customer_id),
        "stable_event_key": event.stable_event_key,
        "event_type": event.event_type,
        "title": event.title,
        "summary": event.summary,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "occurred_at": _iso_bj(event.occurred_at),
        "discovered_at": _iso_bj(event.discovered_at),
        "collected_at": _iso_bj(event.collected_at),
        "status": event.status,
        "confidence": event.confidence,
        "row_version": int(event.row_version),
        "decided_by": int(event.decided_by) if event.decided_by is not None else None,
        "decided_at": _iso_bj(event.decided_at),
        "decision_reason": event.decision_reason,
        "action_id": int(event.action_id) if event.action_id is not None else None,
        "sources": [
            {
                "source_record_id": int(source.source_record_id),
                "evidence_locator": source.evidence_locator,
                "published_at": _iso_bj(source.published_at),
                "fetched_at": _iso_bj(source.fetched_at),
            }
            for source in sources
        ],
        "created_at": _iso_bj(event.created_at),
        "updated_at": _iso_bj(event.updated_at),
    }


def _validate_interval_days(interval_days) -> int:
    if type(interval_days) is bool or not isinstance(interval_days, int):
        raise pcw_errors.bad_request(
            "采集间隔必须为整数天数", error_code="MONITOR_INTERVAL_INVALID"
        )
    if not INTERVAL_DAYS_MIN <= interval_days <= INTERVAL_DAYS_MAX:
        raise pcw_errors.bad_request(
            f"采集间隔必须在 {INTERVAL_DAYS_MIN}~{INTERVAL_DAYS_MAX} 天之间",
            error_code="MONITOR_INTERVAL_INVALID",
        )
    return interval_days


def _locked_subscription(db: Session, subscription_id: int) -> MonitorSubscription:
    sub = (
        db.query(MonitorSubscription)
        .filter(MonitorSubscription.id == int(subscription_id))
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if sub is None:
        raise pcw_errors.customer_not_found()
    return sub


# ─────────────────────────────────────────────────────────────────────────────
# B. 订阅管理
# ─────────────────────────────────────────────────────────────────────────────


def create_subscription(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    channel: str,
    url: str,
    interval_days: int = 7,
    idempotency_key: str | None = None,
) -> dict:
    """创建监控订阅：渠道白名单 + URL 服务端校验 + 单客户上限 + 规范 URL 去重。

    初始 enabled=True、collection_status="baseline"、next_run_at=now+interval_days；
    不触发历史提醒（基线建立前不产生任何事件）。
    """
    if channel not in MONITOR_CHANNELS:
        raise pcw_errors.bad_request(
            "监控渠道不合法",
            error_code="MONITOR_CHANNEL_INVALID",
            details={"allowed": sorted(MONITOR_CHANNELS)},
        )
    interval = _validate_interval_days(interval_days)
    access = _require_access(db, customer_id=customer_id, actor_user_id=actor_user_id, write=True)
    normalized = validate_monitor_url(url)
    url_hash = normalize_url_hash(normalized)
    request_payload = {
        "customer_id": int(access.customer_id),
        "channel": channel,
        "url": normalized,
        "interval_days": interval,
    }

    def _execute() -> dict:
        from app.customer.workflow_service import _account_for_update

        # 锁客户行，串行化同客户订阅创建，保证上限判断不被并发绕过
        _account_for_update(db, int(access.customer_id))
        existing_count = (
            db.query(func.count(MonitorSubscription.id))
            .filter(MonitorSubscription.customer_id == int(access.customer_id))
            .scalar()
        )
        limit = int(get_settings().PCW_MONITOR_MAX_SUBSCRIPTIONS_PER_CUSTOMER)
        if int(existing_count or 0) >= limit:
            raise pcw_errors.bad_request(
                "该客户的监控订阅数量已达上限",
                error_code="SUBSCRIPTION_LIMIT_EXCEEDED",
                details={"limit": limit},
            )
        duplicate = (
            db.query(MonitorSubscription)
            .filter(
                MonitorSubscription.customer_id == int(access.customer_id),
                MonitorSubscription.channel == channel,
                MonitorSubscription.normalized_url_hash == url_hash,
            )
            .one_or_none()
        )
        if duplicate is not None:
            raise pcw_errors.conflict(
                "相同渠道与地址的监控订阅已存在",
                error_code="SUBSCRIPTION_EXISTS",
                details={"existing_id": int(duplicate.id)},
            )
        now = beijing_now()
        row = MonitorSubscription(
            customer_id=int(access.customer_id),
            channel=channel,
            url=normalized,
            normalized_url_hash=url_hash,
            interval_days=interval,
            enabled=True,
            collection_status="baseline",
            next_run_at=now + timedelta(days=interval),
            row_version=1,
            created_by=int(actor_user_id),
            created_at=now,
            updated_at=now,
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError as exc:
            winner = (
                db.query(MonitorSubscription)
                .filter(
                    MonitorSubscription.customer_id == int(access.customer_id),
                    MonitorSubscription.channel == channel,
                    MonitorSubscription.normalized_url_hash == url_hash,
                )
                .one_or_none()
            )
            if winner is not None:
                raise pcw_errors.conflict(
                    "相同渠道与地址的监控订阅已存在",
                    error_code="SUBSCRIPTION_EXISTS",
                    details={"existing_id": int(winner.id)},
                ) from exc
            raise pcw_errors.conflict(
                "并发写入冲突，请在新事务中重试", error_code="RETRY_NEW_TRANSACTION"
            ) from exc
        logger.info(
            "pcw monitor subscription created: id=%s customer=%s channel=%s",
            row.id, access.customer_id, channel,
        )
        return _subscription_dict(row)

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=int(actor_user_id),
            operation_scope=f"monitor_subscription_create:{int(access.customer_id)}",
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            execute=_execute,
        )
        return result
    return _execute()


def patch_subscription(
    db: Session,
    *,
    subscription_id: int,
    actor_user_id: int,
    expected_subscription_version: int,
    enabled: bool | None = None,
    interval_days: int | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """修改订阅：暂停/恢复只改 enabled，绝不动 collection_status/last_error/水位。

    interval_days 改变时重算 next_run_at；row_version 乐观锁不符返回 409
    SUBSCRIPTION_VERSION_CONFLICT（details 带当前版本）。
    """
    if expected_subscription_version is None:
        raise pcw_errors.bad_request(
            "必须携带 expected_subscription_version",
            error_code="SUBSCRIPTION_VERSION_REQUIRED",
        )
    if enabled is None and interval_days is None:
        raise pcw_errors.bad_request(
            "没有需要修改的字段", error_code="MONITOR_PATCH_EMPTY"
        )
    if enabled is not None and type(enabled) is not bool:
        raise pcw_errors.bad_request(
            "enabled 必须为布尔值", error_code="MONITOR_ENABLED_INVALID"
        )
    interval = (
        _validate_interval_days(interval_days) if interval_days is not None else None
    )
    request_payload = {
        "expected_subscription_version": int(expected_subscription_version),
        "enabled": enabled,
        "interval_days": interval,
    }

    def _execute() -> dict:
        sub = _locked_subscription(db, subscription_id)
        _require_access(
            db, customer_id=int(sub.customer_id), actor_user_id=actor_user_id, write=True
        )
        if int(sub.row_version) != int(expected_subscription_version):
            raise pcw_errors.conflict(
                "订阅版本已变化，请刷新后重新操作",
                error_code="SUBSCRIPTION_VERSION_CONFLICT",
                details={"current_subscription_version": int(sub.row_version)},
            )
        now = beijing_now()
        if enabled is not None:
            sub.enabled = enabled
        if interval is not None:
            sub.interval_days = interval
            sub.next_run_at = now + timedelta(days=interval)
        sub.row_version = int(sub.row_version) + 1
        sub.updated_at = now
        db.flush()
        return _subscription_dict(sub)

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=int(actor_user_id),
            operation_scope=f"monitor_subscription_patch:{int(subscription_id)}",
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            execute=_execute,
        )
        return result
    return _execute()


def list_subscriptions(
    db: Session, *, customer_id: int, actor_user_id: int
) -> dict:
    """客户维度订阅列表（含 enabled/collection_status/水位与失败原因）。只读。"""
    access = _require_access(db, customer_id=customer_id, actor_user_id=actor_user_id, write=False)
    rows = (
        db.query(MonitorSubscription)
        .filter(MonitorSubscription.customer_id == int(access.customer_id))
        .order_by(MonitorSubscription.id)
        .all()
    )
    return {"items": [_subscription_dict(row) for row in rows]}


# ─────────────────────────────────────────────────────────────────────────────
# C. 采集执行
# ─────────────────────────────────────────────────────────────────────────────


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁止 urllib 自动跟随重定向：3xx 以 HTTPError 形式上抛，由调用方逐跳校验。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_fetcher(url: str, *, max_bytes: int, timeout_sec: int) -> dict:
    """真实采集器：urllib 手工跟随重定向，每一跳重新执行 validate_monitor_url。

    只在 settings.PCW_MONITOR_ENABLED=True 时被 run_subscription 选用。
    """
    opener = urllib.request.build_opener(_NoRedirectHandler())
    current = url
    for _hop in range(MAX_REDIRECT_HOPS + 1):
        try:
            validate_monitor_url(current)
        except pcw_errors.PcwError as exc:
            raise _MonitorFetchError("FETCH_INVALID_REDIRECT") from exc
        request = urllib.request.Request(current, headers=dict(_FETCH_HEADERS))
        try:
            response = opener.open(request, timeout=timeout_sec)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location") if exc.headers else None
                if not location:
                    raise _MonitorFetchError("FETCH_INVALID_REDIRECT") from exc
                current = urljoin(current, location)
                continue
            raise _MonitorFetchError("FETCH_HTTP_ERROR") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise _MonitorFetchError("FETCH_TIMEOUT") from exc
            raise _MonitorFetchError("FETCH_HTTP_ERROR") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise _MonitorFetchError("FETCH_TIMEOUT") from exc
        except OSError as exc:
            raise _MonitorFetchError("FETCH_ERROR") from exc
        with response:
            content_type = (
                (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            )
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise _MonitorFetchError("FETCH_CONTENT_TYPE")
            body = response.read(int(max_bytes) + 1)
            if len(body) > int(max_bytes):
                raise _MonitorFetchError("FETCH_TOO_LARGE")
            return {
                "content": body,
                "content_type": content_type,
                "final_url": response.geturl() or current,
                "status": int(getattr(response, "status", 200) or 200),
            }
    raise _MonitorFetchError("FETCH_INVALID_REDIRECT")


def _validate_fetch_result(result, *, max_bytes: int, fallback_url: str) -> tuple[str, str, str, int]:
    """校验 fetcher 结果（对注入 fetcher 同样强制类型/体积/状态约束）。"""
    if not isinstance(result, dict):
        raise _MonitorFetchError("FETCH_ERROR")
    try:
        status = int(result.get("status"))
    except (TypeError, ValueError) as exc:
        raise _MonitorFetchError("FETCH_ERROR") from exc
    if not 200 <= status < 300:
        raise _MonitorFetchError("FETCH_HTTP_ERROR")
    content_type = str(result.get("content_type") or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise _MonitorFetchError("FETCH_CONTENT_TYPE")
    content = result.get("content")
    if isinstance(content, str):
        text = content
        raw_size = len(content.encode("utf-8"))
    elif isinstance(content, (bytes, bytearray)):
        raw = bytes(content)
        raw_size = len(raw)
        text = raw.decode("utf-8", errors="replace")
    else:
        raise _MonitorFetchError("FETCH_ERROR")
    if raw_size > int(max_bytes):
        raise _MonitorFetchError("FETCH_TOO_LARGE")
    final_url = str(result.get("final_url") or fallback_url)
    return text, content_type, final_url, status


def _extract_page_text(content: str) -> tuple[str | None, str]:
    """提取页面标题与去标签纯文本；页面内容按数据隔离处理，不执行其中任何指令。"""
    title = None
    match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if match:
        title = re.sub(r"\s+", " ", match.group(1)).strip() or None
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", content)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return title, text


def _registrable_domain(host: str) -> str:
    """publisher_key 规则 registrable_domain 的轻量实现：取 host 末两段。

    对 co.uk 等多级公共后缀不精确（无 PSL 依赖），仅用于快照的发布主体归组。
    """
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    return ".".join(labels[-2:])


def _snapshot_external_record_id(subscription_id: int) -> str:
    return f"pcw-monitor-subscription:{int(subscription_id)}"


def _latest_snapshot(db: Session, subscription_id: int) -> CustomerSourceRecord | None:
    return (
        db.query(CustomerSourceRecord)
        .filter(
            CustomerSourceRecord.source_system == SNAPSHOT_SOURCE_SYSTEM,
            CustomerSourceRecord.source_account_key == SNAPSHOT_SOURCE_ACCOUNT_KEY,
            CustomerSourceRecord.source_entity_type == SNAPSHOT_SOURCE_ENTITY_TYPE,
            CustomerSourceRecord.external_record_id
            == _snapshot_external_record_id(subscription_id),
        )
        .order_by(CustomerSourceRecord.id.desc())
        .first()
    )


def _store_snapshot(
    db: Session,
    *,
    sub: MonitorSubscription,
    final_url: str,
    status: int,
    page_title: str | None,
    content_hash: str,
    text_excerpt: str,
    now: datetime,
) -> CustomerSourceRecord:
    """快照写入不可变来源记录：payload 只存摘要/哈希/URL/状态码，不存整页 HTML。

    external_record_id 按订阅稳定，(key, content_hash) 由 SourceRecord 唯一约束
    保证相同内容重复采集不新增版本。
    """
    host = urlsplit(sub.url).hostname or sub.url
    return append_source_record(
        db,
        customer_id=int(sub.customer_id),
        source_system=SNAPSHOT_SOURCE_SYSTEM,
        source_account_key=SNAPSHOT_SOURCE_ACCOUNT_KEY,
        source_entity_type=SNAPSHOT_SOURCE_ENTITY_TYPE,
        external_record_id=_snapshot_external_record_id(int(sub.id)),
        payload_schema_version=SNAPSHOT_PAYLOAD_SCHEMA_VERSION,
        payload_json={
            "schema_version": SNAPSHOT_PAYLOAD_SCHEMA_VERSION,
            "subscription_id": int(sub.id),
            "channel": sub.channel,
            "url": sub.url,
            "final_url": final_url[:2048],
            "http_status": int(status),
            "title": (page_title or "")[:500] or None,
            "content_hash": content_hash,
            "text_excerpt": text_excerpt[:SNAPSHOT_EXCERPT_MAX_CHARS],
        },
        publisher_key=_registrable_domain(host),
        source_family_key=content_hash,
        source_url=final_url[:2048],
        occurred_at=None,  # 页面发布时间未知，不猜
        captured_at=now,
        processing_status="processed",
    )


def _ensure_monitor_event(
    db: Session,
    *,
    sub: MonitorSubscription,
    content_hash: str,
    snapshot: CustomerSourceRecord,
    previous_snapshot: CustomerSourceRecord | None,
    old_excerpt: str,
    new_excerpt: str,
    page_title: str | None,
    final_url: str,
    now: datetime,
) -> tuple[MonitorEvent, bool]:
    """按稳定键取或建监控候选事件；同内容重复发现归并到同一事件。"""
    stable_key = hashlib.sha256(
        f"{int(sub.id)}:{content_hash}".encode("utf-8")
    ).hexdigest()
    existing = (
        db.query(MonitorEvent)
        .filter(MonitorEvent.stable_event_key == stable_key)
        .one_or_none()
    )
    if existing is not None:
        return existing, False
    host = urlsplit(sub.url).hostname or sub.url
    channel_label = _CHANNEL_LABELS.get(sub.channel, sub.channel)
    event = MonitorEvent(
        customer_id=int(sub.customer_id),
        stable_event_key=stable_key,
        event_type="general",
        title=f"客户{channel_label}内容更新：{(page_title or host)[:200]}",
        summary=None,
        occurred_at=None,  # 页面未提供可核验的发布时间，不猜
        discovered_at=now,
        collected_at=now,
        old_value=old_excerpt[:EVENT_EXCERPT_MAX_CHARS] or None,
        new_value=new_excerpt[:EVENT_EXCERPT_MAX_CHARS] or None,
        status="pending",
        confidence="low",
        row_version=1,
        created_at=now,
        updated_at=now,
    )
    sources = [
        MonitorEventSource(
            source_record_id=int(snapshot.id),
            evidence_locator=final_url[:500],
            published_at=None,
            fetched_at=now,
            created_at=now,
        )
    ]
    if previous_snapshot is not None and int(previous_snapshot.id) != int(snapshot.id):
        previous_url = sub.url
        if isinstance(previous_snapshot.payload_json, dict):
            previous_url = (
                previous_snapshot.payload_json.get("final_url") or sub.url
            )
        sources.append(
            MonitorEventSource(
                source_record_id=int(previous_snapshot.id),
                evidence_locator=str(previous_url)[:500],
                published_at=None,
                fetched_at=now,
                created_at=now,
            )
        )
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
            for source in sources:
                source.event_id = int(event.id)
                db.add(source)
            db.flush()
        return event, True
    except IntegrityError as exc:
        winner = (
            db.query(MonitorEvent)
            .filter(MonitorEvent.stable_event_key == stable_key)
            .one_or_none()
        )
        if winner is not None:
            return winner, False
        raise pcw_errors.conflict(
            "并发写入冲突，请在新事务中重试", error_code="RETRY_NEW_TRANSACTION"
        ) from exc


def _record_run_failure(
    db: Session, *, sub: MonitorSubscription, error_code: str, now: datetime
) -> dict:
    """失败可见：状态 failed + 稳定错误码；保留 last_success_at 与基线。"""
    sub.collection_status = "failed"
    sub.last_error = error_code[:500]
    sub.last_attempt_at = now
    sub.next_run_at = now + timedelta(days=int(sub.interval_days))
    sub.updated_at = now
    db.flush()
    logger.info(
        "pcw monitor fetch failed: subscription=%s code=%s",
        sub.id, error_code,
    )
    return {
        "status": "failed",
        "subscription_id": int(sub.id),
        "error_code": error_code,
    }


def run_subscription(
    db: Session,
    *,
    subscription_id: int,
    actor_user_id: int | None = None,
    fetcher=None,
    force: bool = False,
) -> dict:
    """执行一次采集。不 commit，由调用方提交事务。

    - enabled=False 且非 force：返回 paused，不动任何字段；
    - 未注入 fetcher 且 PCW_MONITOR_ENABLED=False：记录一次诚实的失败尝试
      （last_error=MONITOR_FETCH_DISABLED，collection_status 不变），不假装成功；
    - 首次成功只建立基线；后续成功按内容哈希比对，变化生成一条 MonitorEvent
      （stable_event_key=sha256(subscription.id + 新内容hash)，重复发现归并）。
    """
    sub = _locked_subscription(db, subscription_id)
    if actor_user_id is not None:
        _require_access(
            db, customer_id=int(sub.customer_id), actor_user_id=actor_user_id, write=True
        )
    if not sub.enabled and not force:
        return {"status": "paused", "subscription_id": int(sub.id)}
    settings = get_settings()
    now = beijing_now()
    if fetcher is None and not getattr(settings, "PCW_MONITOR_ENABLED", False):
        sub.last_attempt_at = now
        sub.last_error = "MONITOR_FETCH_DISABLED"
        sub.next_run_at = now + timedelta(days=int(sub.interval_days))
        sub.updated_at = now
        db.flush()
        logger.info(
            "pcw monitor fetch disabled by switch: subscription=%s", sub.id
        )
        return {"status": "disabled", "subscription_id": int(sub.id)}
    fetch = fetcher if fetcher is not None else _default_fetcher
    max_bytes = int(getattr(settings, "PCW_MONITOR_FETCH_MAX_BYTES", 2_000_000))
    try:
        raw_result = fetch(
            sub.url, max_bytes=max_bytes, timeout_sec=FETCH_TIMEOUT_SECONDS
        )
        text, _content_type, final_url, status = _validate_fetch_result(
            raw_result, max_bytes=max_bytes, fallback_url=sub.url
        )
    except _MonitorFetchError as exc:
        return _record_run_failure(db, sub=sub, error_code=exc.error_code, now=now)
    except (TimeoutError, socket.timeout):
        return _record_run_failure(db, sub=sub, error_code="FETCH_TIMEOUT", now=now)
    except Exception as exc:
        logger.warning(
            "pcw monitor fetch raised unexpected error: subscription=%s",
            sub.id, exc_info=True,
        )
        return _record_run_failure(db, sub=sub, error_code="FETCH_ERROR", now=now)

    # 成功路径：内容规范化（去空白差异）后算哈希
    normalized_content = re.sub(r"\s+", " ", text).strip()
    content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    page_title, plain_text = _extract_page_text(text)
    previous = _latest_snapshot(db, int(sub.id))
    previous_hash = None
    old_excerpt = ""
    if previous is not None and isinstance(previous.payload_json, dict):
        previous_hash = previous.payload_json.get("content_hash")
        old_excerpt = str(previous.payload_json.get("text_excerpt") or "")
    snapshot = _store_snapshot(
        db,
        sub=sub,
        final_url=final_url,
        status=status,
        page_title=page_title,
        content_hash=content_hash,
        text_excerpt=plain_text,
        now=now,
    )
    sub.last_attempt_at = now
    sub.last_success_at = now
    sub.last_error = None
    sub.next_run_at = now + timedelta(days=int(sub.interval_days))
    sub.updated_at = now
    if sub.baseline_source_record_id is None:
        # 首次成功：只建立基线，不产生任何事件；collection_status 保持 baseline
        sub.baseline_source_record_id = int(snapshot.id)
        db.flush()
        logger.info(
            "pcw monitor baseline established: subscription=%s snapshot=%s",
            sub.id, snapshot.id,
        )
        return {
            "status": "baseline",
            "subscription_id": int(sub.id),
            "source_record_id": int(snapshot.id),
            "content_hash": content_hash,
        }
    sub.collection_status = "active"
    if previous_hash == content_hash:
        db.flush()
        return {
            "status": "unchanged",
            "subscription_id": int(sub.id),
            "content_hash": content_hash,
        }
    event, created = _ensure_monitor_event(
        db,
        sub=sub,
        content_hash=content_hash,
        snapshot=snapshot,
        previous_snapshot=previous,
        old_excerpt=old_excerpt,
        new_excerpt=plain_text,
        page_title=page_title,
        final_url=final_url,
        now=now,
    )
    db.flush()
    logger.info(
        "pcw monitor change detected: subscription=%s event=%s created=%s",
        sub.id, event.id, created,
    )
    return {
        "status": "changed",
        "subscription_id": int(sub.id),
        "content_hash": content_hash,
        "event_id": int(event.id),
        "event_reused": not created,
    }


# ─────────────────────────────────────────────────────────────────────────────
# D. 事件查询与决策
# ─────────────────────────────────────────────────────────────────────────────


def list_events(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """监控事件分页列表（含来源快照引用）。只读。"""
    if status is not None and status not in EVENT_STATUSES:
        raise pcw_errors.bad_request(
            "事件状态不合法",
            error_code="MONITOR_EVENT_STATUS_INVALID",
            details={"allowed": sorted(EVENT_STATUSES)},
        )
    access = _require_access(db, customer_id=customer_id, actor_user_id=actor_user_id, write=False)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 100)
    query = db.query(MonitorEvent).filter(
        MonitorEvent.customer_id == int(access.customer_id)
    )
    if status is not None:
        query = query.filter(MonitorEvent.status == status)
    total = query.count()
    rows = (
        query.order_by(MonitorEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_event_dict(db, row) for row in rows],
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


def _current_primary_user_id(db: Session, *, customer_id: int) -> int | None:
    row = (
        db.query(CustomerAssignment.user_id)
        .filter(
            CustomerAssignment.customer_id == int(customer_id),
            CustomerAssignment.assignment_role == "primary",
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        )
        .first()
    )
    return int(row.user_id) if row is not None else None


def decide_event(
    db: Session,
    *,
    event_id: int,
    actor_user_id: int,
    operation: str,
    expected_event_version: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """事件决定：confirm 生成恰好一个经营行动并回填 action_id；ignore 只改状态与审计。

    confirm 先校验联系限制（命中 409 CONTACT_RESTRICTED，事件保持 pending 无副作用）；
    行动创建成功后才在同一事务内把事件标记 confirmed。幂等 scope 按事件，
    重放返回同一 action_id。
    """
    if operation not in {"confirm", "ignore"}:
        raise pcw_errors.bad_request(
            "事件决定操作不合法",
            error_code="MONITOR_DECISION_INVALID",
            details={"allowed": ["confirm", "ignore"]},
        )
    if expected_event_version is None:
        raise pcw_errors.bad_request(
            "必须携带 expected_event_version",
            error_code="MONITOR_EVENT_VERSION_REQUIRED",
        )
    clean_reason = (reason or "").strip()
    if operation == "ignore" and not clean_reason:
        raise pcw_errors.bad_request(
            "忽略事件必须填写原因", error_code="DECISION_REASON_REQUIRED"
        )
    request_payload = {
        "operation": operation,
        "expected_event_version": int(expected_event_version),
        "reason": clean_reason or None,
    }

    def _execute() -> dict:
        event = (
            db.query(MonitorEvent)
            .filter(MonitorEvent.id == int(event_id))
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )
        if event is None:
            raise pcw_errors.customer_not_found()
        access = _require_access(
            db, customer_id=int(event.customer_id), actor_user_id=actor_user_id, write=True
        )
        if int(event.row_version) != int(expected_event_version):
            raise pcw_errors.conflict(
                "事件版本已变化，请刷新后重新确认",
                error_code="MONITOR_EVENT_VERSION_CONFLICT",
                details={"current_event_version": int(event.row_version)},
            )
        if event.status in EVENT_DECIDED_STATUSES:
            raise pcw_errors.conflict(
                "事件已完成决定，不能重复操作",
                error_code="EVENT_ALREADY_DECIDED",
                details={"status": event.status},
            )
        now = beijing_now()
        if operation == "ignore":
            event.status = "ignored"
        else:
            from app.sales_automation.public_pool_service import is_development_denied

            # 确认前校验联系限制：命中则事件保持 pending，不产生任何副作用
            if is_development_denied(db, int(access.customer_id), "global", None):
                raise pcw_errors.conflict(
                    "客户存在生效的联系限制，已阻止确认",
                    error_code="CONTACT_RESTRICTED",
                )
            item = ensure_work_item(
                db,
                customer_id=int(access.customer_id),
                business_key=f"monitor_event:{event.stable_event_key}",
                business_cycle="v1",
                work_type="monitor",
                title=f"客户动态：{event.title[:200]}",
                context={
                    "monitor_event_id": int(event.id),
                    "stable_event_key": event.stable_event_key,
                },
            )
            priority = (
                "high" if event.event_type in _HIGH_PRIORITY_EVENT_TYPES else "normal"
            )
            action = create_pcw_action(
                db,
                work_item=item,
                owner_user_id=_current_primary_user_id(
                    db, customer_id=int(access.customer_id)
                ),
                action_type="research",
                thread_group="key_account",
                priority=priority,
                reason=f"已确认的客户监控事件（{event.event_type}）：{event.title[:200]}。",
                next_action="查看事件证据，评估是否联系客户。",
                channel=None,
                business_due_at=now + timedelta(days=3),
                due_provenance="monitor_event",
                policy_version=MONITOR_POLICY_VERSION,
                source_type="rule",
            )
            event.status = "confirmed"
            event.action_id = int(action.id)
        event.decided_by = int(actor_user_id)
        event.decided_at = now
        event.decision_reason = clean_reason or None
        event.row_version = int(event.row_version) + 1
        event.updated_at = now
        db.flush()
        return {
            "event": {
                "id": int(event.id),
                "status": event.status,
                "version": int(event.row_version),
            },
            "action_id": int(event.action_id) if event.action_id is not None else None,
            "suggestion_id": None,  # 档案建议由 PCW-02 建议域产出，本服务不生成
        }

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=int(actor_user_id),
            operation_scope=f"monitor_event_decision:{int(event_id)}",
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            execute=_execute,
        )
        return result
    return _execute()


__all__ = [
    "MONITOR_CHANNELS",
    "FETCH_ERROR_CODES",
    "validate_monitor_url",
    "normalize_url_hash",
    "create_subscription",
    "patch_subscription",
    "list_subscriptions",
    "run_subscription",
    "list_events",
    "decide_event",
]
