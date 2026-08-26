"""Artifact validation, idempotency and human decisions."""

from datetime import datetime
from app.core.time import beijing_now
import re
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from app.agent_runtime.errors import ConflictError, NotFoundError
from app.agent_runtime.event_service import append_event, content_hash
from app.agent_runtime.models import AgentArtifact, AgentEvent, AgentProfile, AgentRun


_ARABIC_QUANTITY_RE = re.compile(r"[0-9０-９]|[%％$￥¥€]")


def _raw_tool_name(value: str) -> str:
    if value.startswith("mcp__") and "__" in value[5:]:
        return value.split("__", 2)[-1]
    return value


def _successful_tool_calls(db: Session, run_id: int) -> dict[str, str]:
    rows = db.query(AgentEvent).filter(
        AgentEvent.run_id == run_id,
        AgentEvent.event_type.in_(["tool.requested", "tool.succeeded"]),
    ).order_by(AgentEvent.sequence_no).all()
    requested: dict[str, str] = {}
    succeeded: set[str] = set()
    for row in rows:
        payload = row.payload_json or {}
        call_id = str(payload.get("call_id") or "")
        if not call_id:
            continue
        if row.event_type == "tool.requested":
            requested[call_id] = _raw_tool_name(str(payload.get("tool_name") or ""))
        else:
            succeeded.add(call_id)
    return {call_id: requested[call_id] for call_id in succeeded if call_id in requested}


def validate_output(
    content: dict[str, Any], evidence: list[dict], profile: AgentProfile,
    *, successful_tool_calls: dict[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    schema = profile.output_schema or {}
    for error in Draft202012Validator(schema).iter_errors(content):
        path = ".".join(str(item) for item in error.absolute_path) or "成果"
        errors.append(f"{path}: {error.message}")
    policy = profile.policy_json or {}
    if policy.get("evidence_required") and not evidence:
        errors.append("该 Profile 要求至少一条证据")
    embedded = content.get("evidence")
    if not isinstance(embedded, list):
        embedded = content.get("candidates") if isinstance(content.get("candidates"), list) else []
    evidence_sets = [("证据", evidence)]
    if embedded != evidence:
        evidence_sets.append(("成果内证据", embedded))
    for label, items in evidence_sets:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{label}第 {index + 1} 条必须是对象")
                continue
            call_id = str(item.get("tool_call_id") or "")
            if not call_id:
                errors.append(f"{label}第 {index + 1} 条缺少 tool_call_id")
                continue
            if successful_tool_calls is not None and call_id not in successful_tool_calls:
                errors.append(f"{label}第 {index + 1} 条未关联本任务成功的工具调用")
                continue
            source = str(item.get("source") or "")
            expected_source = (successful_tool_calls or {}).get(call_id)
            if source and expected_source and _raw_tool_name(source) != expected_source:
                errors.append(f"{label}第 {index + 1} 条来源与工具调用不匹配")
    if policy.get("claim_evidence_required"):
        evidence_ids = {
            str(item.get("tool_call_id"))
            for item in evidence
            if isinstance(item, dict) and item.get("tool_call_id")
        }
        if _ARABIC_QUANTITY_RE.search(str(content.get("summary") or "")):
            errors.append("summary 只能做不含数字的定性概括；定量结论必须放入带证据的结构化条目")
        for field in ("key_findings", "risks", "recommended_actions"):
            for index, item in enumerate(content.get(field) or []):
                if not isinstance(item, dict):
                    continue
                for call_id in item.get("evidence_call_ids") or []:
                    if call_id not in evidence_ids:
                        errors.append(f"{field}第 {index + 1} 条引用了未列入 evidence 的工具调用")
                    elif successful_tool_calls is not None and call_id not in successful_tool_calls:
                        errors.append(f"{field}第 {index + 1} 条未关联本任务成功的工具调用")
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
    errors = validate_output(
        content, evidence, profile,
        successful_tool_calls=_successful_tool_calls(db, run.id),
    )
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
        business_ref_type=run.business_ref_type,
        business_ref_id=run.business_ref_id,
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
    artifact_ref = db.query(AgentArtifact).filter(AgentArtifact.id == artifact_id).one_or_none()
    if artifact_ref is None:
        raise NotFoundError("Agent 成果不存在")
    # Serialize every decision/event append for the Run before locking the
    # individual Artifact. Multiple artifacts can otherwise allocate the same
    # next event sequence concurrently.
    run = db.query(AgentRun).filter(AgentRun.id == artifact_ref.run_id).with_for_update().one()
    artifact = db.query(AgentArtifact).filter(AgentArtifact.id == artifact_id).with_for_update().one()
    if run.owner_user_id != user_id and not can_read_all:
        raise NotFoundError("Agent 成果不存在")
    if artifact.validation_status != "valid":
        raise ConflictError("只有校验通过的成果才能接受或拒绝")
    if artifact.decision_status != "draft" and artifact.decision_status != decision:
        raise ConflictError("Agent 成果已经做出不同决策")
    artifact.decision_status = decision
    artifact.decided_by = user_id
    artifact.decided_at = beijing_now()
    artifact.feedback_note = note
    if decision == "accepted":
        from app.agent_runtime.projection_service import project_accepted_artifact
        project_accepted_artifact(db, artifact, run)
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
