"""Persist and activate validated public-pool settings with optimistic updates."""

from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.time import beijing_now
from app.sales_automation.models import PublicPoolRuleConfig
from app.sales_automation.pool_rule_schema import PoolRules, PoolQuotas, PoolRuleSave, PoolRuleInput
from app.sales_automation.service import ConflictError


def get_config(db):
    row = db.query(PublicPoolRuleConfig).filter_by(id=1).populate_existing().one_or_none()
    return {
        "version": row.version if row else 0, "active": row is not None,
        "rules": row.rules_json if row else PoolRules().model_dump(mode="json"),
        "quotas": row.quotas_json if row else PoolQuotas().model_dump(mode="json"),
        "updated_at": row.updated_at.isoformat() if row else None,
    }


def save_config(db, payload, actor_id):
    try:
        return _save_config(db, payload, actor_id)
    except OperationalError as exc:
        db.rollback()
        if getattr(exc.orig, "args", (None,))[0] not in {1205, 1213}:
            raise
        raise ConflictError("规则正在被修改，请重试") from exc


def _save_config(db, payload, actor_id):
    payload = PoolRuleSave.model_validate(payload)
    row = db.query(PublicPoolRuleConfig).filter_by(id=1).populate_existing().with_for_update().one_or_none()
    if (row.version if row else 0) != payload.expected_version:
        raise ConflictError("规则已被其他人修改，请重新加载后再保存")
    if row is None:
        row = PublicPoolRuleConfig(id=1, version=0)
        db.add(row)
    row.version += 1
    row.rules_json = payload.rules.model_dump(mode="json")
    row.quotas_json = payload.quotas.model_dump(mode="json")
    row.updated_by, row.updated_at = actor_id, beijing_now()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("规则保存冲突，请重新加载后再保存") from exc
    return get_config(db)


def preview(db, payload):
    from app.sales_automation.pool_selection import evaluate
    payload = PoolRuleInput.model_validate(payload)
    return evaluate(db, payload.rules, payload.quotas)[1]


def batch_payload(db, *, expected_version=None):
    config = get_config(db)
    if not config["active"] or (expected_version is not None and config["version"] != expected_version):
        raise ConflictError("请先保存规则；规则更新后须重新加载再创建批次")
    return {"policy_version": f"pool-v{config['version']}", "profile_conditions": config["rules"], "quotas_json": config["quotas"]}


def create_configured_batch(db, payload, actor_id):
    from app.sales_automation.public_pool_service import generate_batch
    return generate_batch(db, batch_payload(db, expected_version=payload.expected_version), actor_id)
