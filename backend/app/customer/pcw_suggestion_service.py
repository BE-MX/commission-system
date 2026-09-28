"""PCW AI 档案建议审核元数据服务。

CustomerFactReview 只保存审核状态与事实/修订引用（schema-migrations 第 1 节）：
- 建议由分析/监控等流程登记（register_suggestion），一候选事实只登记一次；
- 绑定变化、来源失权或人工修订同字段时，旧 pending/deferred 建议标记 stale
  （mark_suggestions_stale），不允许重置回 pending；
- 决定（accept/edit_accept/reject/defer）见 pcw_profile_service.decide_suggestion。
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.models import CustomerFact
from app.customer.pcw_models import CustomerFactReview

logger = logging.getLogger(__name__)

SUGGESTION_OPEN_STATUSES = frozenset({"pending", "deferred"})
SUGGESTION_TERMINAL_STATUSES = frozenset({"accepted", "rejected"})


def register_suggestion(
    db: Session,
    *,
    customer_id: int,
    candidate_fact_id: int,
) -> tuple[CustomerFactReview, bool]:
    """为候选事实登记待审核建议；重复登记返回既有记录（created=False）。"""
    fact = db.query(CustomerFact).filter(
        CustomerFact.id == candidate_fact_id,
        CustomerFact.customer_id == customer_id,
    ).one_or_none()
    if fact is None:
        raise pcw_errors.not_found(
            "候选事实不存在或不属于该客户", error_code="CANDIDATE_FACT_NOT_FOUND"
        )
    existing = db.query(CustomerFactReview).filter(
        CustomerFactReview.candidate_fact_id == candidate_fact_id,
    ).one_or_none()
    if existing is not None:
        return existing, False
    row = CustomerFactReview(
        candidate_fact_id=candidate_fact_id,
        customer_id=customer_id,
        status="pending",
        suggestion_version=1,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row, True
    except IntegrityError:
        winner = db.query(CustomerFactReview).filter(
            CustomerFactReview.candidate_fact_id == candidate_fact_id,
        ).one_or_none()
        if winner is not None:
            return winner, False
        raise


def mark_suggestions_stale(
    db: Session,
    *,
    customer_id: int,
    reason: str,
) -> int:
    """把客户所有待处理建议标记为 stale（绑定更正、来源失权、人工修订同字段）。

    返回受影响行数；已终态（accepted/rejected）的建议不受影响。
    """
    rows = db.query(CustomerFactReview).filter(
        CustomerFactReview.customer_id == customer_id,
        CustomerFactReview.status.in_(sorted(SUGGESTION_OPEN_STATUSES)),
    ).all()
    now = beijing_now()
    for row in rows:
        row.status = "stale"
        row.decision_reason = (row.decision_reason or "") + f"[stale] {reason}"[:500]
        row.suggestion_version = int(row.suggestion_version) + 1
        row.updated_at = now
    if rows:
        db.flush()
        logger.info(
            "pcw suggestions marked stale: customer=%s count=%s reason=%s",
            customer_id, len(rows), reason,
        )
    return len(rows)
