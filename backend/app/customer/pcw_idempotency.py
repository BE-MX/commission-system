"""私海客户工作台（PCW）写操作幂等回执服务。

对齐 docs/requirements/private-customer-workbench-prototype/schema-migrations.md：
相同 (actor, scope, key) 且请求哈希一致时重放首次结果；键相同但请求内容不同
返回 IDEMPOTENCY_CONFLICT；回执保留 7 天，覆盖客户端最大重试窗口。
并发插入冲突处理对齐 app.customer.workflow_service 的 begin_nested 模式。
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.pcw_models import OperationReceipt

RECEIPT_TTL_DAYS = 7


def validate_idempotency_key(key: str | None) -> str:
    """校验 Idempotency-Key：去首尾空白后须为 16-128 个字符。"""
    normalized = (key or "").strip()
    if not 16 <= len(normalized) <= 128:
        raise pcw_errors.bad_request(
            "Idempotency-Key 必须为 16-128 个字符",
            error_code="IDEMPOTENCY_KEY_INVALID",
        )
    return normalized


def canonical_request_hash(payload: Any) -> str:
    """请求体的规范哈希：排序键 + 紧凑分隔符，保证同一语义请求哈希稳定。"""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _find_receipt(
    db: Session, *, actor_user_id: int, operation_scope: str, key_hash: str
) -> OperationReceipt | None:
    return (
        db.query(OperationReceipt)
        .filter(
            OperationReceipt.actor_user_id == actor_user_id,
            OperationReceipt.operation_scope == operation_scope,
            OperationReceipt.key_hash == key_hash,
        )
        .one_or_none()
    )


def run_with_receipt(
    db: Session,
    *,
    actor_user_id: int,
    operation_scope: str,
    idempotency_key: str,
    request_payload: Any,
    execute: Callable[[], dict],
) -> tuple[dict, bool]:
    """以幂等回执执行写操作，返回 (业务结果, 是否重放)。

    并发防幻影：先以唯一键占位插入回执（同键插入会被数据库阻塞/拒绝），
    胜者执行业务并回填结果；败者在 execute 之前即拿到回执冲突，
    保证败者事务零业务副作用。占位与业务写入同处调用方事务，
    execute 抛错时整体回滚、不留回执。
    """
    key = validate_idempotency_key(idempotency_key)
    key_hash = _key_hash(key)
    request_hash = canonical_request_hash(request_payload)
    existing = _find_receipt(
        db, actor_user_id=actor_user_id, operation_scope=operation_scope, key_hash=key_hash
    )
    if existing is not None:
        if existing.request_hash == request_hash:
            return existing.result_json, True
        raise pcw_errors.conflict(
            "相同 Idempotency-Key 携带了不同的请求内容",
            error_code="IDEMPOTENCY_CONFLICT",
        )
    receipt = OperationReceipt(
        actor_user_id=actor_user_id,
        operation_scope=operation_scope,
        key_hash=key_hash,
        request_hash=request_hash,
        result_json={},
        status="pending",
        expires_at=beijing_now() + timedelta(days=RECEIPT_TTL_DAYS),
    )
    try:
        with db.begin_nested():
            db.add(receipt)
            db.flush()
    except IntegrityError as exc:
        # 占位失败：业务尚未执行，零副作用；同键同内容视为重放
        winner = _find_receipt(
            db, actor_user_id=actor_user_id, operation_scope=operation_scope, key_hash=key_hash
        )
        if winner is not None:
            if winner.request_hash == request_hash:
                return winner.result_json, True
            raise pcw_errors.conflict(
                "相同 Idempotency-Key 携带了不同的请求内容",
                error_code="IDEMPOTENCY_CONFLICT",
            ) from exc
        raise pcw_errors.conflict(
            "并发写入冲突，请在新事务中重试",
            error_code="RETRY_NEW_TRANSACTION",
        ) from exc
    result = execute()
    receipt.result_json = result
    receipt.status = "completed"
    db.flush()
    return result, False
