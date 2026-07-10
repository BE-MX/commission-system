"""外部账号绑定服务 — 归属解析 + 绑定 CRUD + 候选管理"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkUserExternalBinding, ArkExternalBindingCandidate

logger = logging.getLogger("insight.binding")


# ── 归属解析 ────────────────────────────────────────────

class OwnerResult:
    """resolve_owner 的返回值"""
    __slots__ = ("user_id", "binding_id", "status")

    def __init__(self, user_id=None, binding_id=None, status="unassigned"):
        self.user_id = user_id
        self.binding_id = binding_id
        self.status = status


def resolve_owner(
    db: Session,
    provider: str,
    external_account_id: str,
    external_display_name: str | None = None,
    raw_payload: dict | None = None,
) -> OwnerResult:
    """
    核心归属解析：根据外部账号 ID 查找绑定的方舟用户。

    返回 OwnerResult(user_id, binding_id, status):
    - resolved: 找到活跃绑定 + 活跃用户
    - inactive_user: 绑定存在但用户已禁用/离职
    - unassigned: 无绑定
    - conflict: 多个活跃绑定（脏数据）
    """
    bindings = (
        db.query(ArkUserExternalBinding)
        .filter(
            ArkUserExternalBinding.provider == provider,
            ArkUserExternalBinding.external_account_id == external_account_id,
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        )
        .all()
    )

    if not bindings:
        # 未绑定 → 写/更新候选
        ensure_candidate(db, provider, external_account_id, external_display_name, raw_payload)
        return OwnerResult(status="unassigned")

    if len(bindings) > 1:
        # 多个匹配（脏数据）
        logger.error(f"Binding conflict: {provider}/{external_account_id} matches {len(bindings)} bindings")
        return OwnerResult(status="conflict")

    binding = bindings[0]

    # 检查用户是否活跃
    user = (
        db.query(ArkUser)
        .filter(
            ArkUser.id == binding.ark_user_id,
            ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None),
        )
        .first()
    )
    if not user:
        return OwnerResult(binding_id=binding.id, status="inactive_user")

    return OwnerResult(user_id=user.id, binding_id=binding.id, status="resolved")


# ── 候选管理 ────────────────────────────────────────────

def ensure_candidate(
    db: Session,
    provider: str,
    external_account_id: str,
    external_display_name: str | None = None,
    raw_payload: dict | None = None,
    source: str = "accio_work",
) -> ArkExternalBindingCandidate:
    """创建或更新未绑定候选记录。已 ignored 的不覆盖。"""
    candidate = (
        db.query(ArkExternalBindingCandidate)
        .filter(
            ArkExternalBindingCandidate.provider == provider,
            ArkExternalBindingCandidate.external_account_id == external_account_id,
        )
        .first()
    )
    if candidate:
        if candidate.candidate_status == "ignored":
            return candidate
        candidate.last_seen_at = datetime.utcnow()
        candidate.seen_count = (candidate.seen_count or 0) + 1
        if external_display_name:
            candidate.external_display_name = external_display_name
        if raw_payload:
            candidate.raw_payload = raw_payload
        db.flush()
        return candidate

    # 尝试按显示名推测用户
    suggested_user_id = None
    suggestion_reason = None
    if external_display_name:
        match = (
            db.query(ArkUser)
            .filter(
                ArkUser.real_name == external_display_name,
                ArkUser.is_active.is_(True),
                ArkUser.deleted_at.is_(None),
            )
            .first()
        )
        if match:
            suggested_user_id = match.id
            suggestion_reason = "subaccount_name equals real_name"

    candidate = ArkExternalBindingCandidate(
        provider=provider,
        external_account_id=external_account_id,
        external_display_name=external_display_name,
        raw_payload=raw_payload,
        source=source,
        suggested_user_id=suggested_user_id,
        suggestion_reason=suggestion_reason,
    )
    db.add(candidate)
    db.flush()
    return candidate


def sync_okki_candidates(db: Session) -> dict:
    """从业务库 user_basic（OKKI 用户镜像）生成 provider='okki' 的绑定候选。

    已有活跃 okki 绑定的账号跳过；其余走 ensure_candidate（幂等 upsert，
    姓名与 real_name 相同的自动带出建议用户）。返回统计供前端 toast。
    """
    from sqlalchemy import text

    from app.core.config import get_settings

    schema = get_settings().BUSINESS_DB_NAME
    rows = db.execute(text(
        f"SELECT user_id, full_name, nickname, user_mobile FROM `{schema}`.user_basic"
    )).mappings().all()

    bound_ids = {
        acc_id for (acc_id,) in db.query(ArkUserExternalBinding.external_account_id).filter(
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        ).all()
    }
    existing_ids = {
        acc_id for (acc_id,) in db.query(ArkExternalBindingCandidate.external_account_id).filter(
            ArkExternalBindingCandidate.provider == "okki",
        ).all()
    }

    # 绑定被解除后候选还停在 bound 状态会卡死重绑路径，复位为 pending
    reactivated = 0
    stale_bound = db.query(ArkExternalBindingCandidate).filter(
        ArkExternalBindingCandidate.provider == "okki",
        ArkExternalBindingCandidate.candidate_status == "bound",
    ).all()
    for cand in stale_bound:
        if cand.external_account_id not in bound_ids:
            cand.candidate_status = "pending"
            reactivated += 1

    created = updated = skipped_bound = skipped_ignored = 0
    for row in rows:
        account_id = str(row["user_id"] or "").strip()
        if not account_id:
            continue
        if account_id in bound_ids:
            skipped_bound += 1
            continue
        display_name = (row["full_name"] or "").strip() or (row["nickname"] or "").strip() or None
        candidate = ensure_candidate(
            db,
            provider="okki",
            external_account_id=account_id,
            external_display_name=display_name,
            raw_payload={
                "full_name": row["full_name"],
                "nickname": row["nickname"],
                "user_mobile": row["user_mobile"],
            },
            source="okki_user_basic",
        )
        if candidate.candidate_status == "ignored":
            skipped_ignored += 1
        elif account_id in existing_ids:
            updated += 1
        else:
            created += 1
    db.commit()
    return {
        "total": len(rows),
        "created": created,
        "updated": updated,
        "skipped_bound": skipped_bound,
        "skipped_ignored": skipped_ignored,
        "reactivated": reactivated,
    }


def list_candidates(db: Session, status: str | None = None) -> list[ArkExternalBindingCandidate]:
    q = db.query(ArkExternalBindingCandidate)
    if status:
        q = q.filter(ArkExternalBindingCandidate.candidate_status == status)
    return q.order_by(ArkExternalBindingCandidate.last_seen_at.desc()).all()


def bind_candidate(db: Session, candidate_id: int, user_id: int, admin_user_id: int) -> ArkExternalBindingCandidate:
    """将候选绑定到指定方舟用户。同时创建正式绑定记录。"""
    candidate = db.query(ArkExternalBindingCandidate).get(candidate_id)
    if not candidate:
        raise ValueError(f"Candidate {candidate_id} not found")
    if candidate.candidate_status != "pending":
        raise ValueError(f"Candidate {candidate_id} is {candidate.candidate_status}, not pending")

    # 创建正式绑定
    binding = ArkUserExternalBinding(
        ark_user_id=user_id,
        provider=candidate.provider,
        external_account_id=candidate.external_account_id,
        external_display_name=candidate.external_display_name,
        external_meta=candidate.raw_payload,
        binding_status="active",
        created_by=admin_user_id,
    )
    db.add(binding)

    # 更新候选状态
    candidate.candidate_status = "bound"
    db.flush()
    return candidate


def ignore_candidate(db: Session, candidate_id: int) -> ArkExternalBindingCandidate:
    candidate = db.query(ArkExternalBindingCandidate).get(candidate_id)
    if not candidate:
        raise ValueError(f"Candidate {candidate_id} not found")
    candidate.candidate_status = "ignored"
    db.flush()
    return candidate


# ── 绑定 CRUD ──────────────────────────────────────────

def get_user_bindings(db: Session, user_id: int) -> list[ArkUserExternalBinding]:
    return (
        db.query(ArkUserExternalBinding)
        .filter(
            ArkUserExternalBinding.ark_user_id == user_id,
            ArkUserExternalBinding.deleted_at.is_(None),
        )
        .order_by(ArkUserExternalBinding.created_at.desc())
        .all()
    )


def create_binding(db: Session, user_id: int, provider: str, external_account_id: str,
                   external_display_name: str | None = None, is_primary: bool = False,
                   created_by: int | None = None) -> ArkUserExternalBinding:
    # 检查唯一性
    existing = (
        db.query(ArkUserExternalBinding)
        .filter(
            ArkUserExternalBinding.provider == provider,
            ArkUserExternalBinding.external_account_id == external_account_id,
            ArkUserExternalBinding.deleted_at.is_(None),
        )
        .first()
    )
    if existing:
        raise ValueError(f"Binding already exists: {provider}/{external_account_id}")

    binding = ArkUserExternalBinding(
        ark_user_id=user_id,
        provider=provider,
        external_account_id=external_account_id,
        external_display_name=external_display_name,
        binding_status="active",
        is_primary=is_primary,
        created_by=created_by,
    )
    db.add(binding)
    db.flush()
    return binding


def delete_binding(db: Session, binding_id: int) -> None:
    """软删除绑定"""
    binding = db.query(ArkUserExternalBinding).get(binding_id)
    if not binding:
        raise ValueError(f"Binding {binding_id} not found")
    binding.deleted_at = datetime.utcnow()
    binding.binding_status = "inactive"
    db.flush()
