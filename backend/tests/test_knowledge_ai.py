from types import SimpleNamespace
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.auth.models import ArkUser
from app.core.database import Base
from app.knowledge import (
    ai_job_service,
    ai_profile_service,
    ai_prompt_service,
    ai_worker,
    service,
)
from app.knowledge.models import (
    KnowledgeAiJob,
    KnowledgeAiJobSource,
    KnowledgeAiProfile,
    KnowledgeAiProfileLog,
    KnowledgeAiProfileSource,
    KnowledgeAiProfileTarget,
    KnowledgeApprovalRequest,
    KnowledgeAsset,
    KnowledgeAuditLog,
    KnowledgeDocument,
    KnowledgeLibrary,
    KnowledgeLibraryMember,
    KnowledgeRevision,
    KnowledgeRevisionAsset,
    bj_now,
)


TABLES = [
    ArkUser.__table__, AiProvider.__table__, AiPreset.__table__, AiCallLog.__table__,
    KnowledgeLibrary.__table__, KnowledgeLibraryMember.__table__,
    KnowledgeDocument.__table__, KnowledgeRevision.__table__,
    KnowledgeApprovalRequest.__table__, KnowledgeAuditLog.__table__,
    KnowledgeAsset.__table__, KnowledgeRevisionAsset.__table__,
    KnowledgeAiProfile.__table__, KnowledgeAiProfileLog.__table__,
    KnowledgeAiProfileSource.__table__, KnowledgeAiProfileTarget.__table__,
    KnowledgeAiJob.__table__, KnowledgeAiJobSource.__table__,
]


def identity(user_id, permissions):
    return {
        "sub": str(user_id), "username": f"user-{user_id}",
        "roles": [], "permissions": permissions,
    }


def doc_json(*paragraphs):
    return {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        for text in paragraphs
    ]}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TABLES)
    session = sessionmaker(bind=engine)()
    session.add_all([
        ArkUser(
            id=user_id, username=f"user-{user_id}", real_name=f"用户{user_id}",
            password_hash="test", is_active=True,
        )
        for user_id in range(1, 6)
    ])
    provider = AiProvider(
        id=1, name="测试直连", provider_type="direct", api_base="https://ai.test/v1",
        api_type="openai", is_enabled=True, timeout_sec=60,
    )
    preset = AiPreset(
        id=1, preset_name="knowledge_test", provider_id=1, model="test-model",
        is_enabled=True,
    )
    session.add_all([provider, preset])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def profile_data(source_ids, target_ids, **overrides):
    data = {
        "name": "企业知识增强",
        "description": "仅使用授权知识",
        "preset_id": 1,
        "format_prompt": "统一标题层级",
        "enhance_prompt": "补充可核验内容",
        "source_library_ids": source_ids,
        "target_library_ids": target_ids,
        "retrieval_limit": 5,
        "context_char_limit": 30000,
        "allow_cross_library": True,
        "require_citations": True,
        "max_document_chars": 30000,
        "daily_limit": 20,
        "max_concurrent_per_user": 2,
        "is_enabled": True,
    }
    data.update(overrides)
    return data


def seed_libraries(db):
    admin = identity(1, [
        "knowledge:admin", "knowledge:write", "knowledge:review", "knowledge:read",
        "knowledge_ai:admin",
    ])
    editor = identity(2, ["knowledge:write", "knowledge:read", "knowledge_ai:write"])
    reviewer = identity(3, ["knowledge:review", "knowledge:read"])
    source = service.create_library(db, admin, name="制度库", category="company")
    target = service.create_library(db, admin, name="作业库", category="department")
    service.replace_members(db, admin, source.id, [
        {"user_id": 2, "role": "viewer"}, {"user_id": 3, "role": "reviewer"},
    ])
    service.replace_members(db, admin, target.id, [
        {"user_id": 2, "role": "editor"}, {"user_id": 3, "role": "reviewer"},
    ])
    return admin, editor, reviewer, source, target


def test_profile_crud_audits_versions_and_masks_prompts_for_writers(db):
    admin, editor, _reviewer, source, target = seed_libraries(db)
    created = ai_profile_service.create_profile(
        db, admin, profile_data([source.id], [target.id])
    )

    assert created["config_version"] == 1
    assert created["source_library_ids"] == [source.id]
    updated = ai_profile_service.update_profile(
        db, admin, created["id"],
        profile_data([source.id], [target.id], name="新版知识增强"),
    )
    assert updated["config_version"] == 2
    assert [row["action"] for row in ai_profile_service.list_profile_logs(
        db, admin, created["id"]
    )] == ["update", "create"]

    visible = ai_profile_service.list_profiles(
        db, editor, target_library_id=target.id
    )[0]
    assert set(visible) == {"id", "name", "description", "config_version", "is_enabled"}
    assert "enhance_prompt" not in visible
    with pytest.raises(service.NotFoundError):
        ai_profile_service.list_profiles(db, editor, target_library_id=source.id + target.id + 100)


def test_enhance_job_freezes_only_authorized_published_sources_and_is_idempotent(db):
    admin, editor, _reviewer, source, target = seed_libraries(db)
    profile = ai_profile_service.create_profile(
        db, admin, profile_data([source.id], [target.id])
    )
    published = service.create_document(
        db, admin, source.id, title="安全帽规定", content=doc_json("安全帽规定必须系紧下颌带")
    )
    service.approve_request(db, admin, service.submit_document(db, admin, published.id).id)
    service.create_document(
        db, admin, source.id, title="未发布规定", content=doc_json("安全帽规定草案不可引用")
    )
    target_doc = service.create_document(
        db, editor, target.id, title="班前检查", content=doc_json("安全帽规定需要执行")
    )

    job = ai_job_service.create_job(
        db, editor, target_doc.id, mode="enhance", profile_id=profile["id"],
        base_revision_id=target_doc.draft_revision_id,
        idempotency_key="same_request_001",
    )
    repeated = ai_job_service.create_job(
        db, editor, target_doc.id, mode="enhance", profile_id=profile["id"],
        base_revision_id=target_doc.draft_revision_id,
        idempotency_key="same_request_001",
    )

    assert repeated.id == job.id
    sources = db.query(KnowledgeAiJobSource).filter_by(job_id=job.id).all()
    assert [row.revision_id for row in sources] == [published.published_revision_id]
    assert job.config_snapshot["preset_name"] == "knowledge_test"
    assert job.config_snapshot["preset_model"] == "test-model"
    assert len(job.config_snapshot["preset_fingerprint"]) == 64
    assert len(job.config_snapshot["provider_fingerprint"]) == 64


def test_format_job_apply_is_idempotent_and_rejects_newer_draft(db):
    admin, editor, _reviewer, source, target = seed_libraries(db)
    profile = ai_profile_service.create_profile(
        db, admin, profile_data([source.id], [target.id], require_citations=False)
    )
    document = service.create_document(
        db, editor, target.id, title="作业步骤", content=doc_json("第一步", "第二步")
    )
    first = ai_job_service.create_job(
        db, editor, document.id, mode="format", profile_id=profile["id"],
        base_revision_id=document.draft_revision_id, idempotency_key="format_job_001",
    )
    base = db.query(KnowledgeRevision).filter_by(id=document.draft_revision_id).one()
    first.status = "completed"
    first.result_json = {"title": base.title, "content_json": base.content_json}
    db.commit()

    applied = ai_job_service.apply_job(db, editor, first.id)
    repeated = ai_job_service.apply_job(db, editor, first.id)
    assert repeated["revision_id"] == applied["revision_id"]

    db.refresh(document)
    second = ai_job_service.create_job(
        db, editor, document.id, mode="format", profile_id=profile["id"],
        base_revision_id=document.draft_revision_id, idempotency_key="format_job_002",
    )
    second.status = "completed"
    second.result_json = {"title": "作业步骤", "content_json": doc_json("第一步", "第二步")}
    db.commit()
    service.save_document(
        db, editor, document.id, title="作业步骤", content=doc_json("后来修改")
    )
    with pytest.raises(service.ConflictError, match="cannot overwrite"):
        ai_job_service.apply_job(db, editor, second.id)


def test_prompt_validation_enforces_format_invariance_and_grounded_enhancement():
    base = KnowledgeRevision(
        id=7, document_id=1, version_no=1, title="原题",
        content_json=doc_json("观点一", "观点二"), content_text="观点一\n观点二", created_by=1,
    )
    format_job = KnowledgeAiJob(mode="format", config_snapshot={})
    formatted = {"title": "原题", "content_json": {
        "type": "doc", "content": [{
            "type": "heading", "attrs": {"level": 2},
            "content": [{"type": "text", "text": "观点一观点二"}],
        }],
    }}
    assert ai_prompt_service.validate_result(format_job, base, formatted, {})[
        "after_block_count"
    ] == 1
    with pytest.raises(service.ValidationError, match="changed document characters"):
        ai_prompt_service.validate_result(
            format_job, base, {"title": "原题", "content_json": doc_json("被改写")}, {}
        )
    protected_base = KnowledgeRevision(
        id=8, document_id=1, version_no=2, title="代码",
        content_json={"type": "doc", "content": [{
            "type": "codeBlock", "attrs": {"language": "python"},
            "content": [{"type": "text", "text": "print(1)"}],
        }]},
        content_text="print(1)", created_by=1,
    )
    protected_changed = {"title": "代码", "content_json": {
        "type": "doc", "content": [{
            "type": "codeBlock", "attrs": {"language": "javascript"},
            "content": [{"type": "text", "text": "print(1)"}],
        }],
    }}
    with pytest.raises(service.ValidationError, match="protected structures"):
        ai_prompt_service.validate_result(format_job, protected_base, protected_changed, {})

    enhance_job = KnowledgeAiJob(
        mode="enhance", config_snapshot={"require_citations": True}
    )
    result = {
        "title": "优化题",
        "content_json": doc_json("观点一", "观点二", "补充安全要求"),
        "core_points": [
            {"block_id": ai_prompt_service._authored_blocks(base)[0]["block_id"], "point": "一", "preserved": True, "original_quote": "观点一", "optimized_quote": "观点一"},
            {"block_id": ai_prompt_service._authored_blocks(base)[1]["block_id"], "point": "二", "preserved": True, "original_quote": "观点二", "optimized_quote": "观点二"},
        ],
        "citations": [{
            "source_revision_id": 11, "claim": "安全要求",
            "source_quote": "必须佩戴安全帽",
        }],
        "application_advice": {
            "knowledge": ["归档"], "skill": ["检查 Skill"],
            "agent": ["巡检 Agent"], "workflow": ["审批工作流"],
        },
    }
    comparison = ai_prompt_service.validate_result(
        enhance_job, base, result, {11: "制度明确：必须佩戴安全帽。"}
    )
    assert comparison["core_point_count"] == 2
    assert any(
        block.get("type") == "heading"
        and block.get("content", [{}])[0].get("text") == "应用建议"
        for block in result["content_json"]["content"]
    )

    bad_citation = {**result, "content_json": doc_json("观点一", "观点二")}
    bad_citation["citations"] = [{
        "source_revision_id": 11, "claim": "伪造", "source_quote": "来源中不存在",
    }]
    with pytest.raises(service.ValidationError, match="source evidence"):
        ai_prompt_service.validate_result(
            enhance_job, base, bad_citation, {11: "必须佩戴安全帽"}
        )

    reversed_point = {**result, "content_json": doc_json(
        "观点一得到保留是错误的，应当否定观点一", "观点二得到保留"
    )}
    reversed_point["core_points"] = [
        {**result["core_points"][0], "optimized_quote": "观点一得到保留是错误的，应当否定观点一"},
        result["core_points"][1],
    ]
    with pytest.raises(service.ValidationError, match="optimized core point"):
        ai_prompt_service.validate_result(enhance_job, base, reversed_point, {})


def test_semantic_verification_fails_closed_for_contradictions_and_uncited_facts():
    base = KnowledgeRevision(
        id=7, document_id=1, version_no=1, title="安全",
        content_json=doc_json("必须佩戴安全帽"), content_text="必须佩戴安全帽", created_by=1,
    )
    job = KnowledgeAiJob(mode="enhance", config_snapshot={"require_citations": True})
    result = {
        "title": "安全", "content_json": doc_json("必须佩戴安全帽", "每日检查"),
        "core_points": [{
            "block_id": ai_prompt_service._authored_blocks(base)[0]["block_id"],
            "point": "安全帽要求", "preserved": True,
            "original_quote": "必须佩戴安全帽", "optimized_quote": "必须佩戴安全帽",
        }],
        "citations": [{"source_revision_id": 11, "claim": "每日检查", "source_quote": "每日检查"}],
    }
    block_id = ai_prompt_service._authored_blocks(base)[0]["block_id"]
    valid = {
        "verdict": "pass",
        "core_verdicts": [{"block_id": block_id, "verdict": "entailed", "reason": "保留"}],
        "citation_verdicts": [{"citation_index": 0, "verdict": "supported", "reason": "来源支持"}],
        "unmapped_new_facts": [], "contradictions": [],
    }
    ai_prompt_service.validate_verification(job, base, result, valid)

    contradicted = {**valid, "verdict": "fail", "contradictions": ["否定安全帽要求"]}
    with pytest.raises(service.ValidationError, match="contradiction"):
        ai_prompt_service.validate_verification(job, base, result, contradicted)

    uncited = {**valid, "verdict": "fail", "unmapped_new_facts": ["现场禁止佩戴"]}
    with pytest.raises(service.ValidationError, match="uncited new fact"):
        ai_prompt_service.validate_verification(job, base, result, uncited)

    messages = ai_prompt_service.build_verification_messages(
        job, base, result["content_json"], result["citations"]
    )
    assert "semantic_integrity_and_grounding_verification" in messages[0]["content"]
    final_with_advice = {**result, "application_advice": {
        "knowledge": ["现场禁止佩戴安全帽"], "skill": [], "agent": [], "workflow": [],
    }}
    ai_prompt_service.validate_result(
        job,
        base,
        final_with_advice,
        {11: "每日检查"},
    )
    verification_payload = ai_prompt_service.build_verification_messages(
        job, base, final_with_advice["content_json"], final_with_advice["citations"]
    )[0]["content"]
    assert "现场禁止佩戴安全帽" in verification_payload


def test_revoked_platform_write_permission_blocks_existing_ai_jobs(db):
    admin, editor, _reviewer, source, target = seed_libraries(db)
    profile = ai_profile_service.create_profile(
        db, admin, profile_data([source.id], [target.id], require_citations=False)
    )
    document = service.create_document(
        db, editor, target.id, title="权限", content=doc_json("原文")
    )
    job = ai_job_service.create_job(
        db, editor, document.id, mode="format", profile_id=profile["id"],
        base_revision_id=document.draft_revision_id, idempotency_key="revoked_write_001",
    )
    revoked = identity(2, ["knowledge:read", "knowledge_ai:write"])
    for operation in (
        lambda: ai_job_service.get_job(db, revoked, job.id),
        lambda: ai_job_service.list_document_jobs(db, revoked, document.id),
        lambda: ai_job_service.cancel_job(db, revoked, job.id),
        lambda: ai_job_service.apply_job(db, revoked, job.id),
    ):
        with pytest.raises(service.ForbiddenError, match="knowledge:write"):
            operation()


def test_cross_library_ai_revision_requires_reviewer_confirmation(db):
    admin, editor, reviewer, source, target = seed_libraries(db)
    profile = ai_profile_service.create_profile(
        db, admin, profile_data([source.id], [target.id])
    )
    source_doc = service.create_document(
        db, admin, source.id, title="来源", content=doc_json("来源证据")
    )
    service.approve_request(db, admin, service.submit_document(db, admin, source_doc.id).id)
    target_doc = service.create_document(
        db, editor, target.id, title="目标", content=doc_json("原文")
    )
    applied_revision = service.save_document(
        db, editor, target_doc.id, title="目标", content=doc_json("AI 优化草稿")
    )
    job = KnowledgeAiJob(
        document_id=target_doc.id, base_revision_id=target_doc.draft_revision_id,
        owner_user_id=2, profile_id=profile["id"], mode="enhance", status="applied",
        idempotency_key="applied_job_001", config_snapshot={},
        applied_revision_id=applied_revision.id,
    )
    db.add(job)
    db.flush()
    db.add(KnowledgeAiJobSource(
        job_id=job.id, library_id=source.id, document_id=source_doc.id,
        revision_id=source_doc.published_revision_id, title_snapshot="来源", score=1, position=0,
    ))
    db.commit()
    approval = service.submit_document(db, editor, target_doc.id)

    detail = service.get_approval_detail(db, reviewer, approval.id)
    assert detail["requires_cross_library_confirmation"] is True
    with pytest.raises(service.ConflictError, match="explicit reviewer confirmation"):
        service.approve_request(db, reviewer, approval.id)
    service.approve_request(
        db, reviewer, approval.id, confirm_cross_library_sources=True
    )


def test_job_and_approval_hide_results_after_source_document_is_deleted(db):
    admin, editor, reviewer, source, target = seed_libraries(db)
    profile = ai_profile_service.create_profile(
        db, admin, profile_data([source.id], [target.id])
    )
    source_doc = service.create_document(
        db, admin, source.id, title="来源", content=doc_json("目标原文来源证据")
    )
    service.approve_request(db, admin, service.submit_document(db, admin, source_doc.id).id)
    target_doc = service.create_document(
        db, editor, target.id, title="目标", content=doc_json("目标原文")
    )
    job = ai_job_service.create_job(
        db, editor, target_doc.id, mode="enhance", profile_id=profile["id"],
        base_revision_id=target_doc.draft_revision_id,
        idempotency_key="deleted_source_001",
    )
    job.status = "completed"
    job.result_json = {"title": "目标", "content_json": doc_json("目标原文来源证据")}
    db.commit()
    applied = ai_job_service.apply_job(db, editor, job.id)
    approval = service.submit_document(db, editor, target_doc.id)
    assert applied["revision_id"] == approval.revision_id

    service.delete_node(db, admin, source_doc.id)
    with pytest.raises(service.ForbiddenError, match="source access"):
        ai_job_service.get_job(db, editor, job.id)
    with pytest.raises(service.ForbiddenError, match="source"):
        service.get_approval_detail(db, reviewer, approval.id)


def test_approval_rejects_soft_deleted_source_library(db):
    admin, editor, reviewer, source, target = seed_libraries(db)
    profile = ai_profile_service.create_profile(
        db, admin, profile_data([source.id], [target.id])
    )
    source_doc = service.create_document(
        db, admin, source.id, title="来源", content=doc_json("目标原文来源证据")
    )
    service.approve_request(db, admin, service.submit_document(db, admin, source_doc.id).id)
    target_doc = service.create_document(
        db, editor, target.id, title="目标", content=doc_json("目标原文")
    )
    job = ai_job_service.create_job(
        db, editor, target_doc.id, mode="enhance", profile_id=profile["id"],
        base_revision_id=target_doc.draft_revision_id, idempotency_key="deleted_library_001",
    )
    job.status = "completed"
    job.result_json = {"title": "目标", "content_json": doc_json("目标原文来源证据")}
    db.commit()
    ai_job_service.apply_job(db, editor, job.id)
    approval = service.submit_document(db, editor, target_doc.id)
    service.delete_library(db, admin, source.id)

    with pytest.raises(service.ForbiddenError, match="source"):
        service.get_approval_detail(db, reviewer, approval.id)
    with pytest.raises(service.ForbiddenError, match="source"):
        service.approve_request(
            db, reviewer, approval.id, confirm_cross_library_sources=True
        )


def test_long_provider_timeout_extends_worker_lease(monkeypatch):
    monkeypatch.setattr(
        ai_worker, "get_settings", lambda: SimpleNamespace(KNOWLEDGE_AI_LEASE_SECONDS=180)
    )
    assert ai_worker.lease_seconds_for_provider(SimpleNamespace(timeout_sec=600)) == 660
    assert ai_worker.lease_seconds_for_provider(SimpleNamespace(timeout_sec=30)) == 180


def test_stale_jobs_requeue_then_fail_after_bounded_claims(db):
    admin, editor, _reviewer, source, target = seed_libraries(db)
    profile = ai_profile_service.create_profile(
        db, admin, profile_data([source.id], [target.id], require_citations=False)
    )
    document = service.create_document(
        db, editor, target.id, title="租约", content=doc_json("原文")
    )
    job = ai_job_service.create_job(
        db, editor, document.id, mode="format", profile_id=profile["id"],
        base_revision_id=document.draft_revision_id, idempotency_key="stale_job_001",
    )
    job.status = "running"
    job.claim_count = 2
    job.lease_token = "expired"
    job.lease_expires_at = bj_now() - timedelta(seconds=1)
    db.commit()

    assert ai_worker.recover_stale_jobs(db) == 1
    db.refresh(job)
    assert job.status == "queued"
    job.status = "running"
    job.claim_count = 3
    job.lease_token = "expired-again"
    job.lease_expires_at = bj_now() - timedelta(seconds=1)
    db.commit()

    assert ai_worker.recover_stale_jobs(db) == 1
    db.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "stale_exhausted"


def test_runtime_fingerprint_detects_configuration_changes(db):
    preset = db.query(AiPreset).filter_by(id=1).one()
    provider = db.query(AiProvider).filter_by(id=1).one()
    before = ai_job_service.ai_runtime_fingerprints(preset, provider)
    preset.parameters = {"temperature": 0.2}
    provider.api_base = "https://changed.test/v1"
    after = ai_job_service.ai_runtime_fingerprints(preset, provider)

    assert before[0] != after[0]
    assert before[1] != after[1]
