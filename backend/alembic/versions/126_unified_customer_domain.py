"""Rebuild the unified customer domain behind a fail-closed cutover fence.

Revision ID: 126
Revises: 125_invoice_integration

This revision intentionally has no downgrade.  It clears the approved legacy
customer business scope and rebuilds it; the maintenance evidence and exact
Agent closure are therefore part of the migration contract, not operator notes.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any, Mapping

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app.core.time import beijing_now_aware
from app.customer.cutover_service import (
    AGENT_ID_QUERY_CHUNK_SIZE,
    CUTOVER_EVIDENCE_ROOT,
    AgentHistoryClosure,
    CutoverGuardError,
    _model_physical_schema_signature,
    bootstrap_migration_fence,
    canonical_json_bytes,
    load_bound_customer_physical_schema_contract,
    migration_preflight,
    resolve_agent_history_closure,
    validate_customer_physical_schema_contract,
    verify_agent_history_removed,
    verify_expected_customer_table_state,
)
from app.customer.models import CORE_TABLES as APPROVED_CORE_TABLES


revision = "126"
down_revision = "125_invoice_integration"
branch_labels = None
depends_on = None


CORE_TABLE_NAMES = (
    "ark_customer_accounts",
    "ark_customer_names",
    "ark_customer_external_identities",
    "ark_customer_relationships",
    "ark_customer_assignments",
    "ark_customer_contacts",
    "ark_customer_contact_points",
    "ark_customer_contact_relationships",
    "ark_customer_source_records",
    "ark_customer_facts",
    "ark_customer_events",
    "ark_customer_annotations",
    "ark_customer_qualification_reviews",
    "ark_customer_profile_versions",
    "ark_customer_agent_contexts",
    "ark_customer_conversations",
    "ark_customer_messages",
    "ark_customer_conversation_analyses",
    "ark_customer_orders",
    "ark_customer_order_items",
    "ark_customer_research_tasks",
    "ark_customer_sync_cursors",
    "ark_customer_fact_evidence_links",
    "ark_customer_fact_conflicts",
    "ark_customer_list_projections",
    "ark_customer_change_proposals",
    "ark_customer_agent_run_scopes",
    "ark_customer_suppression_registry",
    "ark_customer_resolution_keys",
    "ark_customer_target_matches",
    "ark_customer_acquisition_attributions",
)
WORKFLOW_TABLE_NAMES = (
    "ark_sales_search_jobs",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_sales_public_pool_batches",
    "ark_customer_opportunities",
    "ark_customer_opportunity_events",
    "ark_customer_actions",
)
TARGET_TABLE_NAMES = CORE_TABLE_NAMES + WORKFLOW_TABLE_NAMES

RETIRED_OR_REBUILT_TABLES = (
    "ark_sales_search_jobs",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_sales_companies",
    "ark_sales_contacts",
    "ark_sales_research_subjects",
    "ark_sales_public_pool_batches",
    "ark_sales_public_pool_tasks",
    "ark_sales_deal_assessments",
    "ark_sales_research_runs",
    "ark_sales_research_facts",
    "ark_inquiry_import_batches",
    "ark_customer_opportunities",
    "ark_customer_opportunity_events",
    "ark_customer_profiles",
    "ark_customer_profile_events",
    "ark_customer_actions",
)
OPTIONAL_RETIRED_TABLES = frozenset({"ark_sales_search_result_sources"})
DROP_ORDER = (
    "ark_customer_actions",
    "ark_customer_profile_events",
    "ark_customer_opportunity_events",
    "ark_sales_deal_assessments",
    "ark_sales_public_pool_tasks",
    "ark_sales_search_result_sources",
    "ark_sales_search_results",
    "ark_sales_contacts",
    "ark_sales_research_facts",
    "ark_sales_research_runs",
    "ark_sales_public_pool_batches",
    "ark_sales_research_subjects",
    "ark_sales_companies",
    "ark_sales_search_jobs",
    "ark_customer_opportunities",
    "ark_customer_profiles",
    "ark_inquiry_import_batches",
)
AGENT_DELETE_ORDER = (
    ("ark_agent_artifacts", "artifact_ids"),
    ("ark_agent_events", "event_ids"),
    ("ark_agent_runs", "run_ids"),
    ("ark_agent_sessions", "session_ids"),
)
TARGET_PROFILE_COLUMNS = {
    "policy_version": "策略版本",
    "policy_json": "target_profile_policy_v1阈值、权重、研究与领取规则",
    "policy_snapshot_hash": "规范快照SHA-256",
    "last_improvement_artifact_id": "最近人工批准改进Artifact",
    "policy_applied_at": "策略生效北京时间",
}

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
CHAR64 = sa.String(64).with_variant(mysql.CHAR(64), "mysql")
TINYINT = sa.SmallInteger().with_variant(mysql.TINYINT(), "mysql")

# This literal pins the complete 38-table physical signature.  The migration
# may reuse the approved core SQLAlchemy declarations only while their full
# normalized MySQL schema still hashes to this value; any future model edit
# makes revision 126 fail closed instead of silently changing historical DDL.
FROZEN_TARGET_SCHEMA_SHA256 = (
    "92eafb4a280014e92d64860c964bde2e3627ab4fdfc290a2f89a5a4a4c8a9195"
)

GENERATED_EXPRESSIONS = {
    ("ark_customer_external_identities", "primary_identity_slot"): (
        "CASE WHEN is_primary=1 AND status='active' THEN "
        "SHA2(CONCAT_WS(CHAR(31), IF(customer_id IS NULL, 'contact', 'customer'), "
        "COALESCE(customer_id, contact_id), identifier_type), 256) ELSE NULL END"
    ),
    ("ark_customer_external_identities", "verified_strong_key"): (
        "CASE WHEN identity_strength='strong' AND cardinality='one_to_one' "
        "AND verification_status='verified' AND status='active' THEN "
        "SHA2(CONCAT_WS(CHAR(31), source_system, source_account_key, identifier_type, "
        "normalized_value), 256) ELSE NULL END"
    ),
    ("ark_customer_relationships", "active_relation_key"): (
        "CASE WHEN effective_to IS NULL AND verification_status IN "
        "('candidate','verified') THEN SHA2(CONCAT_WS(CHAR(31), from_customer_id, "
        "to_customer_id, relationship_type), 256) ELSE NULL END"
    ),
    ("ark_customer_assignments", "active_assignment_key"): (
        "CASE WHEN assignment_status='active' THEN SHA2(CONCAT_WS(CHAR(31), "
        "customer_id, user_id, assignment_role), 256) ELSE NULL END"
    ),
    ("ark_customer_assignments", "active_primary_slot"): (
        "CASE WHEN assignment_role='primary' AND assignment_status='active' "
        "THEN 1 ELSE NULL END"
    ),
    ("ark_customer_contact_points", "primary_point_slot"): (
        "CASE WHEN is_primary=1 THEN SHA2(CONCAT_WS(CHAR(31), "
        "IF(customer_id IS NULL, 'contact', 'customer'), COALESCE(customer_id, contact_id), "
        "point_type, COALESCE(platform, '')), 256) ELSE NULL END"
    ),
    ("ark_customer_contact_relationships", "active_relation_key"): (
        "CASE WHEN effective_to IS NULL AND verification_status IN "
        "('identified','verified') THEN SHA2(CONCAT_WS(CHAR(31), customer_id, contact_id, "
        "relationship_type), 256) ELSE NULL END"
    ),
    ("ark_customer_annotations", "active_dnc_key"): (
        "CASE WHEN annotation_type='do_not_contact' AND status='active' THEN "
        "SHA2(CONCAT_WS(CHAR(31), customer_id, policy_scope_type, "
        "COALESCE(policy_scope_ref_id, '')), 256) ELSE NULL END"
    ),
    ("ark_customer_qualification_reviews", "current_scope_slot"): (
        "CASE WHEN is_current=1 THEN SHA2(CONCAT_WS(CHAR(31), customer_id, scope_type, "
        "COALESCE(scope_ref_id, '')), 256) ELSE NULL END"
    ),
    ("ark_customer_suppression_registry", "active_suppression_key"): (
        "CASE WHEN status='active' THEN SHA2(CONCAT_WS(CHAR(31), identifier_type, "
        "source_system, source_account_key, normalized_value_hmac, scope_type, "
        "COALESCE(scope_ref_id, '')), 256) ELSE NULL END"
    ),
    ("ark_customer_target_matches", "current_match_slot"): (
        "CASE WHEN is_current=1 THEN SHA2(CONCAT_WS(CHAR(31), customer_id, "
        "target_profile_id), 256) ELSE NULL END"
    ),
}


def _fk(
    local: str | tuple[str, ...],
    remote: str | tuple[str, ...],
    name: str,
    *,
    ondelete: str = "RESTRICT",
    onupdate: str | None = None,
) -> sa.ForeignKeyConstraint:
    local_columns = (local,) if isinstance(local, str) else local
    remote_columns = (remote,) if isinstance(remote, str) else remote
    return sa.ForeignKeyConstraint(
        local_columns,
        remote_columns,
        name=name,
        ondelete=ondelete,
        onupdate=onupdate,
    )


def _workflow_tables(metadata: MetaData) -> None:
    sa.Table(
        "ark_sales_search_jobs",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True, comment="搜索任务ID"),
        sa.Column("job_run_id", sa.BigInteger, nullable=True, comment="本次搜索任务对应的全平台任务运行ID；仅手工草稿未执行时为空"),
        sa.Column("profile_id", sa.BigInteger, nullable=False, comment="创建任务时使用的获客目标模型ID"),
        sa.Column("name", sa.String(255), nullable=False, comment="面向用户的搜索任务名称"),
        sa.Column("status", sa.String(16), nullable=False, index=True, comment="状态：pending、running、completed、failed、cancelled"),
        sa.Column("adapter", sa.String(64), nullable=False, index=True, comment="搜索执行器：agent、apollo、import或登记值"),
        sa.Column("target_count", sa.Integer, nullable=False, comment="目标候选客户数量，必须大于0"),
        sa.Column("criteria_json", sa.JSON, nullable=False, comment="search_criteria_v1：国家、行业、渠道、产品、规模和排除条件"),
        sa.Column("profile_snapshot", sa.JSON, nullable=False, comment="target_profile_snapshot_v1：模型版本、规则、阈值和创建时字段快照"),
        sa.Column("policy_version", sa.String(32), nullable=False, comment="搜索、去重、评分和背调触发策略版本"),
        sa.Column("profile_snapshot_hash", CHAR64, nullable=False, comment="目标模型快照规范JSON的SHA-256"),
        sa.Column("idempotency_key", CHAR64, nullable=False, unique=True, comment="创建任务请求和目标模型快照生成的幂等键"),
        sa.Column("ingestion_receipts", sa.JSON, nullable=False, comment="Schema v1已接受批次request_key到计数和内容哈希的映射"),
        sa.Column("result_count", sa.Integer, nullable=False, comment="成功关联到任务的搜索结果数"),
        sa.Column("created_customer_count", sa.Integer, nullable=False, comment="本任务新建provisional客户数"),
        sa.Column("deduplicated_count", sa.Integer, nullable=False, comment="命中已有统一客户的结果数"),
        sa.Column("researched_count", sa.Integer, nullable=False, comment="已创建或复用背调任务的结果数"),
        sa.Column("qualified_count", sa.Integer, nullable=False, comment="在本任务作用范围内审核通过的客户数"),
        sa.Column("provider_usage_json", sa.JSON, nullable=False, comment="search_provider_usage_v1：供应商、请求数、记录数、计费单位、Agent Run ID和费用分项；无使用量为空数组"),
        sa.Column("cost_status", sa.String(16), nullable=False, index=True, comment="成本核验状态：pending、confirmed、not_applicable；pending时金额字段必须为空"),
        sa.Column("cost_original", sa.Numeric(15, 6), nullable=True, comment="本任务已确认外部搜索与Agent执行原币成本；not_applicable为0，pending为空"),
        sa.Column("cost_currency", sa.String(8), nullable=True, comment="cost_original的ISO币种代码；pending或not_applicable允许为空"),
        sa.Column("cost_usd", sa.Numeric(15, 6), nullable=True, comment="按入账日版本化汇率折算的美元成本；confirmed必填，not_applicable为0，pending为空且不得进入成本指标"),
        sa.Column("claimed_by", sa.String(128), nullable=True, comment="当前执行Agent或Worker稳定标识"),
        sa.Column("lease_token_hash", CHAR64, nullable=True, comment="执行租约令牌SHA-256"),
        sa.Column("lease_expires_at", sa.DateTime, nullable=True, index=True, comment="执行租约到期的北京时间"),
        sa.Column("attempt_count", sa.Integer, nullable=False, comment="执行尝试次数"),
        sa.Column("error_code", sa.String(64), nullable=True, comment="最近失败的稳定错误码"),
        sa.Column("error_message", sa.String(1000), nullable=True, comment="最近失败的可行动脱敏说明"),
        sa.Column("started_at", sa.DateTime, nullable=True, comment="最近一次开始执行的北京时间"),
        sa.Column("finished_at", sa.DateTime, nullable=True, comment="到达当前终态的北京时间"),
        sa.Column("created_by", USER_ID, nullable=False, comment="创建任务的方舟用户ID"),
        sa.Column("created_at", sa.DateTime, nullable=False, comment="搜索任务创建的北京时间"),
        sa.Column("updated_at", sa.DateTime, nullable=False, comment="搜索任务最后更新的北京时间"),
        _fk("job_run_id", "ark_job_runs.id", "fk_customer_search_job_run"),
        _fk("profile_id", "ark_sales_target_profiles.id", "fk_customer_search_profile"),
        _fk("created_by", "ark_users.id", "fk_customer_search_created_by"),
        sa.CheckConstraint("target_count > 0", name="ck_customer_search_target_count"),
        sa.CheckConstraint("result_count >= 0 AND created_customer_count >= 0 AND deduplicated_count >= 0 AND researched_count >= 0 AND qualified_count >= 0 AND attempt_count >= 0", name="ck_customer_search_nonnegative_counts"),
        sa.CheckConstraint("(cost_status = 'pending' AND cost_original IS NULL AND cost_currency IS NULL AND cost_usd IS NULL) OR (cost_status = 'confirmed' AND cost_original IS NOT NULL AND cost_currency IS NOT NULL AND cost_usd IS NOT NULL) OR (cost_status = 'not_applicable' AND cost_original = 0 AND cost_usd = 0)", name="ck_customer_search_cost_state"),
        comment="智能获客搜索任务、冻结目标画像、执行租约、幂等回执和结果统计表；不保存客户档案副本。",
    )

    sa.Table(
        "ark_sales_search_results",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True, comment="搜索结果ID"),
        sa.Column("job_id", sa.BigInteger, nullable=False, index=True, comment="所属搜索任务ID"),
        sa.Column("customer_id", sa.BigInteger, nullable=False, index=True, comment="解析或创建的统一客户ID"),
        sa.Column("best_rank", sa.Integer, nullable=True, index=True, comment="此客户在本任务全部来源中的最佳排名；供应商均未提供时为空"),
        sa.Column("best_score", sa.Numeric(5, 2), nullable=False, index=True, comment="此客户相对本任务冻结目标画像的当前最佳匹配分0至100"),
        sa.Column("aggregated_score_reasons", sa.JSON, nullable=False, comment="search_score_aggregate_v1：维度、权重、聚合分值、理由、证据事实ID和result_source_id"),
        sa.Column("result_status", sa.String(16), nullable=False, index=True, comment="状态：active、ignored、qualified、rejected"),
        sa.Column("qualification_review_id", sa.BigInteger, nullable=True, comment="最近一次与本搜索结果直接相关的资格审核ID"),
        sa.Column("created_at", sa.DateTime, nullable=False, comment="搜索结果创建的北京时间"),
        sa.Column("updated_at", sa.DateTime, nullable=False, comment="搜索结果状态最后更新的北京时间"),
        _fk("job_id", "ark_sales_search_jobs.id", "fk_customer_search_result_job", ondelete="CASCADE"),
        _fk("customer_id", "ark_customer_accounts.id", "fk_customer_search_result_customer"),
        _fk(("qualification_review_id", "customer_id"), ("ark_customer_qualification_reviews.id", "ark_customer_qualification_reviews.customer_id"), "fk_customer_search_result_qualification"),
        sa.UniqueConstraint("job_id", "customer_id", name="uq_customer_search_result_job_customer"),
        sa.CheckConstraint("best_rank IS NULL OR best_rank > 0", name="ck_customer_search_result_rank"),
        sa.CheckConstraint("best_score >= 0 AND best_score <= 100", name="ck_customer_search_result_score"),
        comment="搜索任务发现统一客户的候选成员、聚合排名、匹配评分、处理状态和资格审核引用表；每个任务与客户唯一，不保存独立候选客户主档。",
    )

    sa.Table(
        "ark_sales_search_result_sources",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True, comment="搜索候选来源ID"),
        sa.Column("result_id", sa.BigInteger, nullable=False, index=True, comment="所属唯一搜索候选ID"),
        sa.Column("request_key", sa.String(64), nullable=False, index=True, comment="Agent或适配器提交本批结果的幂等键"),
        sa.Column("source_record_id", sa.BigInteger, nullable=False, index=True, comment="发现该候选的不可变原始信源版本ID"),
        sa.Column("source_provider", sa.String(64), nullable=False, index=True, comment="搜索适配器、外部供应商或受控Agent名称"),
        sa.Column("source_url", sa.String(2048), nullable=True, comment="发现候选的公开证据URL；无URL的结构化供应商记录为空"),
        sa.Column("captured_at", sa.DateTime, nullable=False, index=True, comment="采集此候选信源的北京时间"),
        sa.Column("rank", sa.Integer, nullable=True, index=True, comment="候选在本次请求或供应商结果中的原始排名；未提供时为空"),
        sa.Column("score", sa.Numeric(5, 2), nullable=False, index=True, comment="此来源相对任务冻结画像的匹配分0至100"),
        sa.Column("score_reasons", sa.JSON, nullable=False, comment="search_source_score_v1：维度、分值、理由和证据事实ID"),
        sa.Column("allocated_cost_usd", sa.Numeric(15, 6), nullable=False, comment="按任务费用和供应商用量分摊到本来源的美元成本；无费用为0"),
        sa.Column("source_fingerprint", CHAR64, nullable=False, unique=True, comment="result_id、request_key、source_provider、source_record内容哈希和评分规则版本生成的SHA-256"),
        sa.Column("created_at", sa.DateTime, nullable=False, comment="候选来源写入方舟的北京时间"),
        _fk("result_id", "ark_sales_search_results.id", "fk_customer_search_source_result", ondelete="CASCADE"),
        _fk("source_record_id", "ark_customer_source_records.id", "fk_customer_search_source_record"),
        sa.CheckConstraint("rank IS NULL OR rank > 0", name="ck_customer_search_source_rank"),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_customer_search_source_score"),
        sa.CheckConstraint("allocated_cost_usd >= 0", name="ck_customer_search_source_cost"),
        comment="搜索候选在不同批次、适配器和公开信源中的逐次发现证据、原始排名、评分和分摊成本表；多条来源汇总到唯一搜索候选。",
    )

    sa.Table(
        "ark_sales_public_pool_batches",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True, comment="公海研究批次ID"),
        sa.Column("batch_date", sa.Date, nullable=False, index=True, comment="批次业务日期"),
        sa.Column("policy_version", sa.String(32), nullable=False, comment="T1/T2/T3、配额、冷却和选取规则版本"),
        sa.Column("status", sa.String(16), nullable=False, index=True, comment="状态：pending、running、completed、failed、cancelled"),
        sa.Column("quotas_json", sa.JSON, nullable=False, comment="public_pool_quotas_v1：各档目标数、团队范围和总上限"),
        sa.Column("selection_snapshot", sa.JSON, nullable=False, comment="public_pool_selection_v1：候选计数、过滤原因、输入水位和策略哈希"),
        sa.Column("result_counts", sa.JSON, nullable=False, comment="public_pool_counts_v1：selected、created、reused、skipped、failed按档统计"),
        sa.Column("idempotency_key", CHAR64, nullable=False, unique=True, comment="批次日期、策略版本、团队范围和输入水位生成的幂等键"),
        sa.Column("started_at", sa.DateTime, nullable=True, comment="批次开始生成的北京时间"),
        sa.Column("finished_at", sa.DateTime, nullable=True, comment="批次到达当前终态的北京时间"),
        sa.Column("error_code", sa.String(64), nullable=True, comment="批次失败稳定错误码"),
        sa.Column("error_message", sa.String(1000), nullable=True, comment="批次失败可行动脱敏说明"),
        sa.Column("created_by", USER_ID, nullable=True, comment="手工创建批次的方舟用户ID；系统批次允许为空但必须有service principal运行记录"),
        sa.Column("created_at", sa.DateTime, nullable=False, comment="公海批次创建的北京时间"),
        sa.Column("updated_at", sa.DateTime, nullable=False, comment="公海批次最后更新的北京时间"),
        _fk("created_by", "ark_users.id", "fk_customer_pool_batch_created_by"),
        comment="公海客户分档抽样批次和冻结策略表；批次只选择统一customer_id并创建research_tasks，不拥有客户副本。",
    )

    sa.Table(
        "ark_customer_opportunities",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True, comment="客户销售机会ID"),
        sa.Column("customer_id", sa.BigInteger, nullable=False, index=True, comment="机会所属统一客户ID"),
        sa.Column("opportunity_type", sa.String(32), nullable=False, index=True, comment="类型：ali_inquiry、public_pool、customer_reactivation、new_product、manual"),
        sa.Column("source", sa.String(32), nullable=False, index=True, comment="来源：alibaba、public_pool、customer_hub、manual"),
        sa.Column("source_system", sa.String(32), nullable=False, index=True, comment="机会幂等来源系统：alibaba、search、public_pool、internal或登记值"),
        sa.Column("source_account_key", sa.String(128), nullable=False, index=True, comment="外部来源账号或租户命名空间；内部和跨账号业务键使用global"),
        sa.Column("source_key", sa.String(255), nullable=False, comment="来源系统账号命名空间内的稳定业务对象键，不含凭证"),
        sa.Column("source_ref_type", sa.String(32), nullable=True, comment="引用类型：source_record、conversation、message、research_task、customer_event"),
        sa.Column("source_ref_id", sa.BigInteger, nullable=True, index=True, comment="对应方舟来源对象ID；由source_ref_type解释"),
        sa.Column("owner_user_id", USER_ID, nullable=True, index=True, comment="当前机会负责人；空表示待分配，不替代客户主负责人"),
        sa.Column("primary_contact_id", sa.BigInteger, nullable=True, comment="本机会主要联系人ID"),
        sa.Column("expected_amount", sa.Numeric(15, 2), nullable=True, comment="机会预计原币种金额"),
        sa.Column("currency", sa.String(8), nullable=True, comment="预计金额ISO币种代码"),
        sa.Column("expected_close_date", sa.Date, nullable=True, index=True, comment="预计成交业务日期"),
        sa.Column("stage_probability", sa.SmallInteger, nullable=True, comment="阶段概率0至100；未知为空"),
        sa.Column("forecast_category", sa.String(16), nullable=True, index=True, comment="预测分类：pipeline、best_case、commit、closed"),
        sa.Column("priority_level", sa.String(4), nullable=False, index=True, comment="机会优先级：A、B、C、D"),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False, comment="机会判断置信度0至100"),
        sa.Column("urgency", sa.String(16), nullable=False, index=True, comment="紧迫度：urgent、high、normal、low"),
        sa.Column("title", sa.String(255), nullable=False, comment="机会标题"),
        sa.Column("summary", sa.Text, nullable=True, comment="机会当前摘要；不复制客户档案"),
        sa.Column("product_requirement_json", sa.JSON, nullable=False, comment="opportunity_requirement_v1：产品、规格、数量、价格、交期及未知项"),
        sa.Column("quote_ref", sa.String(128), nullable=True, comment="方舟报价业务引用；首期不建立报价域外键"),
        sa.Column("competitor_json", sa.JSON, nullable=False, comment="opportunity_competitor_v1：名称、信号、证据事实ID；未知为空数组"),
        sa.Column("recommended_strategy", sa.Text, nullable=True, comment="基于当前证据的机会策略建议"),
        sa.Column("opening_message_en", sa.Text, nullable=True, comment="供人工确认的英文开场草稿，不自动外发"),
        sa.Column("follow_up_message_en", sa.Text, nullable=True, comment="供人工确认的英文跟进草稿，不自动外发"),
        sa.Column("evidence_fact_ids", sa.JSON, nullable=False, comment="Schema v1支撑机会判断的客户事实ID数组"),
        sa.Column("status", sa.String(16), nullable=False, index=True, comment="状态：pending、contacted、replied、quoted、won、lost、dismissed"),
        sa.Column("stage_entered_at", sa.DateTime, nullable=False, index=True, comment="进入当前机会状态的北京时间"),
        sa.Column("due_at", sa.DateTime, nullable=True, index=True, comment="当前机会处理截止时间"),
        sa.Column("latest_message_at", sa.DateTime, nullable=True, index=True, comment="本机会相关最近消息时间"),
        sa.Column("next_step", sa.String(1000), nullable=True, comment="业务员确认的下一步"),
        sa.Column("next_step_due_at", sa.DateTime, nullable=True, index=True, comment="下一步计划完成时间"),
        sa.Column("close_reason_code", sa.String(32), nullable=True, index=True, comment="关闭原因标准码；开放机会为空"),
        sa.Column("close_reason_text", sa.String(1000), nullable=True, comment="关闭原因补充说明"),
        sa.Column("linked_order_id", sa.BigInteger, nullable=True, comment="won机会对应的方舟有效订单ID"),
        sa.Column("handled_at", sa.DateTime, nullable=True, comment="首次被人工处理的北京时间"),
        sa.Column("created_by", USER_ID, nullable=True, comment="手工创建机会的方舟用户ID；同步创建允许为空"),
        sa.Column("created_at", sa.DateTime, nullable=False, comment="机会创建的北京时间"),
        sa.Column("updated_at", sa.DateTime, nullable=False, comment="机会当前态最后更新的北京时间"),
        _fk("customer_id", "ark_customer_accounts.id", "fk_customer_opportunity_customer"),
        _fk("owner_user_id", "ark_users.id", "fk_customer_opportunity_owner"),
        _fk("primary_contact_id", "ark_customer_contacts.id", "fk_customer_opportunity_contact"),
        _fk(("linked_order_id", "customer_id"), ("ark_customer_orders.id", "ark_customer_orders.customer_id"), "fk_customer_opportunity_order"),
        _fk("created_by", "ark_users.id", "fk_customer_opportunity_created_by"),
        sa.UniqueConstraint("id", "customer_id", name="uq_customer_opportunity_id_customer"),
        sa.UniqueConstraint("source_system", "source_account_key", "source_key", name="uq_customer_opportunity_source_key"),
        sa.CheckConstraint("stage_probability IS NULL OR (stage_probability >= 0 AND stage_probability <= 100)", name="ck_customer_opportunity_probability"),
        sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_customer_opportunity_confidence"),
        comment="统一客户的单次销售机会当前态表；保存销售过程、预测、下一步和关闭结果，不复制客户完整档案。",
    )

    sa.Table(
        "ark_customer_opportunity_events",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True, comment="机会事件ID"),
        sa.Column("opportunity_id", sa.BigInteger, nullable=False, index=True, comment="所属客户机会ID"),
        sa.Column("customer_id", sa.BigInteger, nullable=False, index=True, comment="冗余校验的统一客户ID，必须与机会一致"),
        sa.Column("event_type", sa.String(32), nullable=False, index=True, comment="事件：created、assigned、stage_changed、contact_changed、amount_changed、next_step_changed、closed、reopened"),
        sa.Column("from_status", sa.String(16), nullable=True, comment="状态变化前值；非阶段事件为空"),
        sa.Column("to_status", sa.String(16), nullable=True, comment="状态变化后值；非阶段事件为空"),
        sa.Column("event_payload", sa.JSON, nullable=False, comment="opportunity_event_v1：变更前后字段、原因和业务引用"),
        sa.Column("evidence_fact_ids", sa.JSON, nullable=False, comment="Schema v1支撑本次机会变化的事实ID数组"),
        sa.Column("actor_user_id", USER_ID, nullable=True, comment="人工操作方舟用户ID；确定性同步允许为空"),
        sa.Column("occurred_at", sa.DateTime, nullable=False, index=True, comment="机会业务变化发生的北京时间"),
        sa.Column("event_fingerprint", CHAR64, nullable=False, unique=True, comment="机会、事件类型、变更内容、业务时间和来源生成的SHA-256"),
        sa.Column("created_at", sa.DateTime, nullable=False, comment="机会事件写入方舟的北京时间"),
        _fk(("opportunity_id", "customer_id"), ("ark_customer_opportunities.id", "ark_customer_opportunities.customer_id"), "fk_customer_opp_event_opportunity", ondelete="CASCADE"),
        _fk("actor_user_id", "ark_users.id", "fk_customer_opp_event_actor"),
        comment="客户机会分配、阶段、联系人、金额、下一步和关闭变化的追加式事件表。",
    )

    sa.Table(
        "ark_customer_actions",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True, comment="客户经营行动ID"),
        sa.Column("customer_id", sa.BigInteger, nullable=False, index=True, comment="行动所属统一客户ID"),
        sa.Column("owner_user_id", USER_ID, nullable=False, index=True, comment="行动执行人方舟用户ID"),
        sa.Column("opportunity_id", sa.BigInteger, nullable=True, index=True, comment="可选关联机会ID，必须与customer_id一致"),
        sa.Column("contact_id", sa.BigInteger, nullable=True, comment="可选目标联系人ID"),
        sa.Column("action_type", sa.String(24), nullable=False, index=True, comment="行动类型：call、email、message、meeting、research、review"),
        sa.Column("thread_group", sa.String(24), nullable=False, index=True, comment="分组：new_inquiry、sample、key_account、reorder、reactivation、public_pool"),
        sa.Column("channel", sa.String(16), nullable=True, comment="渠道：alibaba、email、whatsapp、phone、linkedin、offline、internal"),
        sa.Column("priority", sa.String(16), nullable=False, index=True, comment="优先级：urgent、high、normal、low"),
        sa.Column("reason", sa.String(1000), nullable=False, comment="有证据的行动推荐原因"),
        sa.Column("next_action", sa.String(1000), nullable=False, comment="建议执行的明确下一步"),
        sa.Column("suggested_message", sa.Text, nullable=True, comment="供人工确认的话术草稿，不自动外发"),
        sa.Column("planned_at", sa.DateTime, nullable=True, index=True, comment="计划开始执行时间"),
        sa.Column("due_at", sa.DateTime, nullable=True, index=True, comment="计划完成截止时间"),
        sa.Column("action_date", sa.Date, nullable=False, index=True, comment="雷达列表业务日期"),
        sa.Column("status", sa.String(16), nullable=False, index=True, comment="状态：pending、done、dismissed、snoozed、cancelled"),
        sa.Column("snoozed_until", sa.DateTime, nullable=True, index=True, comment="延后到期时间"),
        sa.Column("completed_at", sa.DateTime, nullable=True, comment="行动完成的北京时间"),
        sa.Column("completed_by", USER_ID, nullable=True, comment="标记行动完成的方舟用户ID"),
        sa.Column("outcome_code", sa.String(32), nullable=True, index=True, comment="结果：contacted、replied、no_response、meeting_booked、wrong_contact、other"),
        sa.Column("dismissal_reason", sa.String(32), nullable=True, comment="忽略原因稳定码"),
        sa.Column("feedback_json", sa.JSON, nullable=False, comment="action_feedback_v1：评价、备注、结果证据和下一步"),
        sa.Column("source_event_ids", sa.JSON, nullable=False, comment="Schema v1触发行动的客户事件ID数组"),
        sa.Column("evidence_fact_ids", sa.JSON, nullable=False, comment="Schema v1支撑行动原因和建议的事实ID数组"),
        sa.Column("profile_version_id", sa.BigInteger, nullable=False, comment="生成行动时使用的客户档案版本ID"),
        sa.Column("source_type", sa.String(16), nullable=False, index=True, comment="生成来源：rule、agent、manual"),
        sa.Column("agent_run_id", sa.BigInteger, nullable=True, comment="Agent生成行动时的受控Run ID"),
        sa.Column("policy_version", sa.String(32), nullable=False, comment="行动生成与抑制策略版本"),
        sa.Column("action_fingerprint", CHAR64, nullable=False, unique=True, comment="客户、行动日期、策略、触发事实和目标对象生成的SHA-256"),
        sa.Column("evidence_status", sa.String(16), nullable=False, index=True, comment="证据状态：valid、stale、invalid"),
        sa.Column("generated_at", sa.DateTime, nullable=False, comment="行动建议完成生成的北京时间"),
        sa.Column("created_at", sa.DateTime, nullable=False, comment="行动创建的北京时间"),
        sa.Column("updated_at", sa.DateTime, nullable=False, comment="行动当前态最后更新的北京时间"),
        _fk("customer_id", "ark_customer_accounts.id", "fk_customer_action_customer"),
        _fk("owner_user_id", "ark_users.id", "fk_customer_action_owner"),
        _fk(("opportunity_id", "customer_id"), ("ark_customer_opportunities.id", "ark_customer_opportunities.customer_id"), "fk_customer_action_opportunity"),
        _fk("contact_id", "ark_customer_contacts.id", "fk_customer_action_contact"),
        _fk(("profile_version_id", "customer_id"), ("ark_customer_profile_versions.id", "ark_customer_profile_versions.customer_id"), "fk_customer_action_profile"),
        _fk("agent_run_id", "ark_agent_runs.id", "fk_customer_action_agent_run"),
        _fk("completed_by", "ark_users.id", "fk_customer_action_completed_by"),
        comment="客户经营雷达给业务员的待执行、完成、忽略和延后行动表；建议与真实销售活动严格分开。",
    )


def _build_target_metadata() -> MetaData:
    metadata = MetaData()
    external_stubs = (
        sa.Table("ark_users", metadata, sa.Column("id", USER_ID, primary_key=True)),
        sa.Table("ark_agent_runs", metadata, sa.Column("id", sa.BigInteger, primary_key=True)),
        sa.Table("ark_job_runs", metadata, sa.Column("id", sa.BigInteger, primary_key=True)),
        sa.Table("ark_sales_target_profiles", metadata, sa.Column("id", sa.BigInteger, primary_key=True)),
    )
    for table_name in CORE_TABLE_NAMES:
        APPROVED_CORE_TABLES[table_name].to_metadata(metadata)
    _workflow_tables(metadata)

    attribution = metadata.tables["ark_customer_acquisition_attributions"]
    attribution.append_constraint(
        _fk("search_job_id", "ark_sales_search_jobs.id", "fk_customer_attribution_search_job")
    )
    attribution.append_constraint(
        _fk("opportunity_id", "ark_customer_opportunities.id", "fk_customer_attribution_opportunity")
    )
    for (table_name, column_name), expression in GENERATED_EXPRESSIONS.items():
        column = metadata.tables[table_name].c[column_name]
        column.type = TINYINT if column_name == "active_primary_slot" else CHAR64
        column.computed = sa.Computed(expression, persisted=True)
        column.server_default = column.computed
        column.server_onupdate = column.computed

    # Resolve external FK targets now, then hide infrastructure stubs from the
    # exact 38-table domain contract.  ForeignKey objects retain resolved columns.
    for table_name in TARGET_TABLE_NAMES:
        for foreign_key in metadata.tables[table_name].foreign_keys:
            foreign_key.column
    for stub in external_stubs:
        metadata.remove(stub)
    _name_physical_constraints(metadata)
    _ensure_fk_supporting_indexes(metadata)
    frozen_payload = _physical_schema_payload(metadata)
    frozen_sha256 = hashlib.sha256(canonical_json_bytes(frozen_payload)).hexdigest()
    if FROZEN_TARGET_SCHEMA_SHA256 and frozen_sha256 != FROZEN_TARGET_SCHEMA_SHA256:
        raise CutoverGuardError(
            "revision 126 frozen target schema no longer matches its runtime declarations"
        )
    return metadata


def _stable_constraint_name(
    kind: str, table_name: str, column_names: tuple[str, ...]
) -> str:
    raw = f"{kind}_{table_name}_{'_'.join(column_names)}"
    if len(raw) <= 64:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{raw[:51]}_{digest}"


def _name_physical_constraints(metadata: MetaData) -> None:
    for table_name in TARGET_TABLE_NAMES:
        table = metadata.tables[table_name]
        for constraint in tuple(table.constraints):
            if isinstance(constraint, sa.PrimaryKeyConstraint):
                continue
            if constraint.name is None:
                kind = (
                    "fk"
                    if isinstance(constraint, sa.ForeignKeyConstraint)
                    else "uq"
                    if isinstance(constraint, sa.UniqueConstraint)
                    else "ck"
                )
                constraint.name = _stable_constraint_name(
                    kind,
                    table_name,
                    tuple(column.name for column in constraint.columns),
                )
            if len(constraint.name) > 64:
                raise CutoverGuardError(
                    f"revision 126 constraint name exceeds MySQL limit: {constraint.name}"
                )


def _ensure_fk_supporting_indexes(metadata: MetaData) -> None:
    """Name indexes InnoDB would otherwise create implicitly for foreign keys."""
    for table_name in TARGET_TABLE_NAMES:
        table = metadata.tables[table_name]
        covered = [tuple(column.name for column in index.columns) for index in table.indexes]
        covered.extend(
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(
                constraint,
                (sa.PrimaryKeyConstraint, sa.UniqueConstraint),
            )
        )
        for foreign_key in sorted(
            (
                constraint
                for constraint in table.constraints
                if isinstance(constraint, sa.ForeignKeyConstraint)
            ),
            key=lambda constraint: constraint.name,
        ):
            local_columns = tuple(
                element.parent.name for element in foreign_key.elements
            )
            if any(
                columns[: len(local_columns)] == local_columns for columns in covered
            ):
                continue
            index_name = _stable_constraint_name("ix", table_name, local_columns)
            sa.Index(index_name, *(table.c[name] for name in local_columns))
            covered.append(local_columns)


def _physical_schema_payload(metadata: MetaData) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "migration_revision": revision,
        "tables": {
            table_name: _model_physical_schema_signature(
                metadata.tables[table_name]
            )
            for table_name in TARGET_TABLE_NAMES
        },
    }


TARGET_METADATA = _build_target_metadata()


def _build_physical_schema_contract() -> dict[str, Any]:
    payload = _physical_schema_payload(TARGET_METADATA)
    return {
        **payload,
        "contract_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


PHYSICAL_SCHEMA_CONTRACT = _build_physical_schema_contract()


def _load_cutover_contract() -> Mapping[str, Any]:
    values = context.get_x_argument(as_dictionary=True)
    if set(values) != {"customer_cutover_contract"}:
        raise CutoverGuardError(
            "revision 126 requires only -x customer_cutover_contract=<fixed path>"
        )
    raw_path = values["customer_cutover_contract"]
    if not isinstance(raw_path, str):
        raise CutoverGuardError("customer cutover contract path is required")
    lexical = Path(raw_path)
    root = CUTOVER_EVIDENCE_ROOT.resolve()
    current = lexical
    while current != root and current.is_relative_to(root):
        if current.exists() and current.is_symlink():
            raise CutoverGuardError("customer cutover contract path uses a symlink")
        current = current.parent
    path = lexical.resolve()
    if path.parent != root or not path.name.startswith("migration-contract-"):
        raise CutoverGuardError("customer cutover contract is outside the fixed evidence root")
    try:
        raw = path.read_bytes()
        contract = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoverGuardError("cannot read customer cutover contract") from exc
    if not isinstance(contract, Mapping) or raw != canonical_json_bytes(contract) + b"\n":
        raise CutoverGuardError("customer cutover contract is not canonical JSON")
    if Path(str(contract.get("contract_path"))).resolve() != path:
        raise CutoverGuardError("customer cutover contract path binding is invalid")
    return contract


def _delete_agent_history_closure(
    db: Session, closure: AgentHistoryClosure
) -> None:
    metadata = MetaData()
    for table_name, id_attribute in AGENT_DELETE_ORDER:
        ids = tuple(sorted(getattr(closure, id_attribute)))
        if not ids:
            continue
        table = Table(table_name, metadata, autoload_with=db.connection())
        iterator = iter(ids)
        while chunk := tuple(islice(iterator, AGENT_ID_QUERY_CHUNK_SIZE)):
            result = db.execute(sa.delete(table).where(table.c.id.in_(chunk)))
            if result.rowcount != len(chunk):
                raise CutoverGuardError(
                    f"exact Agent closure delete mismatch for {table_name}"
                )
    verify_agent_history_removed(db, closure)


def _drop_foreign_keys_into_retired() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    retired = set(RETIRED_OR_REBUILT_TABLES)
    for table_name in sorted(inspector.get_table_names()):
        for foreign_key in inspector.get_foreign_keys(table_name):
            if foreign_key.get("referred_table") not in retired:
                continue
            constraint_name = foreign_key.get("name")
            if not constraint_name:
                raise CutoverGuardError(
                    f"unnamed foreign key into retired customer table from {table_name}"
                )
            op.drop_constraint(constraint_name, table_name, type_="foreignkey")


def _drop_retired_tables() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table_name in DROP_ORDER:
        if table_name not in existing:
            if table_name in OPTIONAL_RETIRED_TABLES:
                continue
            raise CutoverGuardError(f"required retired table is missing: {table_name}")
        op.drop_table(table_name)


def _alter_target_profiles() -> None:
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("policy_version", sa.String(32), nullable=True, comment=TARGET_PROFILE_COLUMNS["policy_version"]),
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("policy_json", sa.JSON, nullable=True, comment=TARGET_PROFILE_COLUMNS["policy_json"]),
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("policy_snapshot_hash", CHAR64, nullable=True, comment=TARGET_PROFILE_COLUMNS["policy_snapshot_hash"]),
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("last_improvement_artifact_id", sa.BigInteger, nullable=True, comment=TARGET_PROFILE_COLUMNS["last_improvement_artifact_id"]),
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("policy_applied_at", sa.DateTime, nullable=True, comment=TARGET_PROFILE_COLUMNS["policy_applied_at"]),
    )
    policy_json_sql = (
        "JSON_OBJECT('schema_version','target_profile_policy_v1',"
        "'migration_state','legacy_unconfigured')"
    )
    op.execute(
        sa.text(
            "UPDATE ark_sales_target_profiles SET "
            "policy_version='legacy-1', "
            f"policy_json={policy_json_sql}, "
            f"policy_snapshot_hash=SHA2(CAST({policy_json_sql} AS CHAR), 256), "
            "policy_applied_at=updated_at"
        )
    )
    op.alter_column("ark_sales_target_profiles", "policy_version", existing_type=sa.String(32), nullable=False, comment=TARGET_PROFILE_COLUMNS["policy_version"], existing_comment=TARGET_PROFILE_COLUMNS["policy_version"])
    op.alter_column("ark_sales_target_profiles", "policy_json", existing_type=sa.JSON(), nullable=False, comment=TARGET_PROFILE_COLUMNS["policy_json"], existing_comment=TARGET_PROFILE_COLUMNS["policy_json"])
    op.alter_column("ark_sales_target_profiles", "policy_snapshot_hash", existing_type=CHAR64, nullable=False, comment=TARGET_PROFILE_COLUMNS["policy_snapshot_hash"], existing_comment=TARGET_PROFILE_COLUMNS["policy_snapshot_hash"])
    op.alter_column("ark_sales_target_profiles", "policy_applied_at", existing_type=sa.DateTime(), nullable=False, comment=TARGET_PROFILE_COLUMNS["policy_applied_at"], existing_comment=TARGET_PROFILE_COLUMNS["policy_applied_at"])
    op.create_index(
        "ix_sales_target_profile_last_improvement_artifact",
        "ark_sales_target_profiles",
        ["last_improvement_artifact_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_sales_target_profile_improvement_artifact",
        "ark_sales_target_profiles",
        "ark_agent_artifacts",
        ["last_improvement_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def _ddl_column(column: sa.Column[Any]) -> sa.Column[Any]:
    positional: list[Any] = []
    if column.computed is not None:
        positional.append(
            sa.Computed(
                str(column.computed.sqltext),
                persisted=column.computed.persisted,
            )
        )
    return sa.Column(
        column.name,
        column.type.copy(),
        *positional,
        nullable=column.nullable,
        autoincrement=column.autoincrement,
        comment=column.comment,
    )


def _non_fk_ddl_constraints(table: sa.Table) -> list[sa.Constraint]:
    constraints: list[sa.Constraint] = [
        sa.PrimaryKeyConstraint(
            *(column.name for column in table.primary_key.columns),
            name=table.primary_key.name,
        )
    ]
    for constraint in tuple(table.constraints):
        if isinstance(constraint, sa.UniqueConstraint):
            constraints.append(
                sa.UniqueConstraint(
                    *(column.name for column in constraint.columns),
                    name=constraint.name,
                )
            )
        elif isinstance(constraint, sa.CheckConstraint):
            constraints.append(
                sa.CheckConstraint(str(constraint.sqltext), name=constraint.name)
            )
    return constraints


def _create_target_tables() -> None:
    for table_name in TARGET_TABLE_NAMES:
        table = TARGET_METADATA.tables[table_name]
        op.create_table(
            table_name,
            *(_ddl_column(column) for column in table.c),
            *_non_fk_ddl_constraints(table),
            comment=table.comment,
        )
    for table_name in TARGET_TABLE_NAMES:
        table = TARGET_METADATA.tables[table_name]
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            op.create_index(
                index.name,
                table_name,
                [column.name for column in index.columns],
                unique=index.unique,
            )
    for table_name in TARGET_TABLE_NAMES:
        table = TARGET_METADATA.tables[table_name]
        foreign_keys = sorted(
            (
                constraint
                for constraint in table.constraints
                if isinstance(constraint, sa.ForeignKeyConstraint)
            ),
            key=lambda item: item.name or "",
        )
        for foreign_key in foreign_keys:
            elements = tuple(foreign_key.elements)
            op.create_foreign_key(
                foreign_key.name,
                table_name,
                elements[0].column.table.name,
                [element.parent.name for element in elements],
                [element.column.name for element in elements],
                ondelete=foreign_key.ondelete,
                onupdate=foreign_key.onupdate,
            )


def _write_success_receipt(contract: Mapping[str, Any], started_at: datetime) -> None:
    root = CUTOVER_EVIDENCE_ROOT.resolve()
    receipt_path = (root / str(contract["receipt_path"])).resolve()
    expected_name = f"migration-receipt-{contract['nonce']}.json"
    if receipt_path.parent != root or receipt_path.name != expected_name:
        raise CutoverGuardError("migration receipt path is not fixed")
    completed_at = beijing_now_aware()
    receipt = {
        field: contract[field]
        for field in (
            "inventory_sha256",
            "preflight_report_sha256",
            "suppression_manifest_sha256",
            "writer_manifest_sha256",
            "approved_marker_sha256",
            "maintenance_fence_artifact_sha256",
            "instance_inventory_artifact_sha256",
            "physical_schema_contract_sha256",
            "nonce",
            "contract_sha256",
            "contract_path",
            "receipt_path",
        )
    }
    receipt.update(
        {
            "migration_revision": revision,
            "schema_signature_sha256": contract["physical_schema_contract_sha256"],
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "status": "succeeded",
        }
    )
    receipt["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(receipt)
    ).hexdigest()
    try:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            receipt_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(receipt) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise CutoverGuardError(
            f"migration DDL succeeded but receipt write failed: {receipt_path}; "
            "keep all writers stopped"
        ) from exc


def upgrade() -> None:
    started_at = beijing_now_aware()
    contract = _load_cutover_contract()
    validate_customer_physical_schema_contract(PHYSICAL_SCHEMA_CONTRACT)
    bound_physical_contract = load_bound_customer_physical_schema_contract(contract)
    if canonical_json_bytes(bound_physical_contract) != canonical_json_bytes(
        PHYSICAL_SCHEMA_CONTRACT
    ):
        raise CutoverGuardError(
            "bound physical schema contract does not match revision 126 frozen DDL"
        )
    bind = op.get_bind()
    db = Session(bind=bind)
    bootstrap_migration_fence(db, contract)
    inventory = migration_preflight(db, contract)
    closure = resolve_agent_history_closure(db, inventory)
    _delete_agent_history_closure(db, closure)
    _drop_foreign_keys_into_retired()
    _drop_retired_tables()
    _alter_target_profiles()
    _create_target_tables()
    verify_expected_customer_table_state(db, bound_physical_contract)
    _write_success_receipt(contract, started_at)


def downgrade() -> None:
    raise RuntimeError("destructive customer-domain restoration is unsupported")
