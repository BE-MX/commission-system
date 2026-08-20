"""Artifact validation, idempotency and human decisions."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agent_runtime.errors import ConflictError, NotFoundError
from app.agent_runtime.event_service import append_event, content_hash
from app.agent_runtime.models import AgentArtifact, AgentProfile, AgentRun


_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def validate_output(content: dict[str, Any], evidence: list[dict], profile: AgentProfile) -> list[str]:
    errors: list[str] = []
    schema = profile.output_schema or {}
    if schema.get("type") == "object" and not isinstance(content, dict):
        return ["成果必须是对象"]
    for key in schema.get("required") or []:
        if key not in content:
            errors.append(f"缺少必填字段: {key}")
    for key, definition in (schema.get("properties") or {}).items():
        if key not in content:
            continue
        expected = _JSON_TYPES.get(definition.get("type"))
        if expected and not isinstance(content[key], expected):
            errors.append(f"字段 {key} 类型必须是 {definition['type']}")
    if schema.get("additionalProperties") is False:
        unknown = set(content) - set((schema.get("properties") or {}))
        if unknown:
            errors.append(f"存在未声明字段: {', '.join(sorted(unknown))}")
    policy = profile.policy_json or {}
    if policy.get("evidence_required") and not evidence:
        errors.append("该 Profile 要求至少一条证据")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"第 {index + 1} 条证据必须是对象")
            continue
        if not item.get("source") and not item.get("tool_call_id") and not item.get("source_url"):
            errors.append(f"第 {index + 1} 条证据缺少 source/tool_call_id/source_url")
    return errors


def create_artifact(
    db: Session,
    run: AgentRun,
    profile: AgentProfile,
    *,
    artifact_type: str,
    schema_version: int,
    title: str | None,
    content: dict,
    evidence: list[dict],
) -> AgentArtifact:
    errors = validate_output(content, evidence, profile)
    if errors:
        raise ConflictError("成果校验失败: " + "; ".join(errors))
    digest = content_hash({"content": content, "evidence": evidence})
    existing = db.query(AgentArtifact).filter(
        AgentArtifact.run_id == run.id,
        AgentArtifact.artifact_type == artifact_type,
        AgentArtifact.content_sha256 == digest,
    ).one_or_none()
    if existing is not None:
        return existing
    artifact = AgentArtifact(
        run_id=run.id,
        artifact_type=artifact_type,
        schema_version=schema_version,
        title=title,
        content_json=content,
        evidence_json=evidence,
        content_sha256=digest,
        validation_status="valid",
        validation_errors=[],
        decision_status="draft",
    )
    db.add(artifact)
    db.flush()
    append_event(
        db, run,
        event_id=f"artifact-{artifact.id}-created",
        event_type="artifact.created",
        actor_type="control_plane",
        payload={"artifact_id": artifact.id, "artifact_type": artifact_type, "content_sha256": digest},
    )
    append_event(
        db, run,
        event_id=f"artifact-{artifact.id}-validated",
        event_type="artifact.validated",
        actor_type="control_plane",
        payload={"artifact_id": artifact.id, "validation_status": "valid"},
    )
    return artifact


def decide_artifact(
    db: Session,
    artifact_id: int,
    *,
    user_id: int,
    decision: str,
    note: str | None,
    can_read_all: bool,
) -> AgentArtifact:
    artifact = db.query(AgentArtifact).filter(AgentArtifact.id == artifact_id).with_for_update().one_or_none()
    if artifact is None:
        raise NotFoundError("Agent 成果不存在")
    run = db.query(AgentRun).filter(AgentRun.id == artifact.run_id).one()
    if run.owner_user_id != user_id and not can_read_all:
        raise NotFoundError("Agent 成果不存在")
    if artifact.validation_status != "valid":
        raise ConflictError("只有校验通过的成果才能接受或拒绝")
    if artifact.decision_status != "draft" and artifact.decision_status != decision:
        raise ConflictError("Agent 成果已经做出不同决策")
    artifact.decision_status = decision
    artifact.decided_by = user_id
    artifact.decided_at = datetime.utcnow()
    artifact.feedback_note = note
    append_event(
        db, run,
        event_id=f"artifact-{artifact.id}-{decision}",
        event_type="user.feedback",
        actor_type="user",
        payload={"artifact_id": artifact.id, "decision": decision, "note": note},
    )
    db.commit()
    db.refresh(artifact)
    return artifact

