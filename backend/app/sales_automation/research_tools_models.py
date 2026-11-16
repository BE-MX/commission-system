"""Durable, lease-scoped external research calls and spend reservations."""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint

from app.core.database import Base
from app.core.time import beijing_now


class ResearchToolCall(Base):
    __tablename__ = "ark_customer_research_tool_calls"
    __table_args__ = (
        UniqueConstraint("task_id", "run_id", "idempotency_key", name="uq_research_tool_idempotency"),
        Index("ix_research_tool_dispatch", "status", "id"),
        Index("ix_research_tool_spend", "tool", "requested_at"),
    )

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True, comment="工具调用编号")
    task_id = Column(BigInteger, ForeignKey("ark_customer_research_tasks.id"), nullable=False, comment="所属研究任务")
    run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id"), nullable=False, comment="所属研究运行")
    lease_generation = Column(Integer, nullable=False, comment="领取该运行时的租约代次")
    tool = Column(String(20), nullable=False, comment="工具：用户名扫描或付费查询")
    operation = Column(String(32), nullable=False, comment="工具注册的只读操作")
    idempotency_key = Column(String(96), nullable=False, comment="任务运行内的调用幂等键")
    request_hash = Column(String(64), nullable=False, comment="规范化请求摘要")
    target = Column(String(512), nullable=False, comment="经校验的用户名、主页或域名")
    gap = Column(String(32), comment="触发付费查询的关键缺口")
    free_search = Column(JSON, comment="用户名扫描前声明的免费查询与结果")
    scan_call_id = Column(BigInteger, ForeignKey("ark_customer_research_tool_calls.id"), comment="付费查询对应的扫描调用")
    status = Column(String(24), nullable=False, comment="调用阶段；不确定状态不重发")
    reserved_microusd = Column(Integer, nullable=False, default=0, comment="调用前预算预占，单位百万分之一美元")
    charged_microusd = Column(Integer, comment="已确认的实际花费，空值表示未结算")
    provider_run_id = Column(String(64), comment="用于只读轮询的供应商运行编号")
    response_json = Column(JSON, comment="原始响应与后端提取的待绑定候选")
    evidence_refs = Column(JSON, comment="已确认的候选编号和事实写入回执")
    error_code = Column(String(64), comment="不含凭据或原始请求的错误代码")
    requested_at = Column(DateTime, nullable=False, default=beijing_now, comment="提交请求的北京时间")
    started_at = Column(DateTime, comment="开始处理的北京时间")
    finished_at = Column(DateTime, comment="完成调用的北京时间")
