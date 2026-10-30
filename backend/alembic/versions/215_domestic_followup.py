"""domestic customer follow-up: records, items, attachments, aliases, tasks, outbox, config

内贸客户跟进一期（docs/requirements/2026-10-30-domestic-customer-followup.md）。
只新建表 + 种三个 sys_dict 值域初值；不改既有表，滚动发布安全。
FK 类型与目标列一致：客户 INT、用户 INT UNSIGNED、发货批次 BIGINT。
downgrade 只删表；字典是用户可维护数据，不随 downgrade 删除。

Revision ID: 215_domestic_followup
Revises: 214_sales_return_ledger
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "215_domestic_followup"
down_revision = "214_sales_return_ledger"
branch_labels = None
depends_on = None

# 与 app/domestic_followup/constants.py 的 DICT_SEEDS 同一份；迁移不 import 业务代码（业务代码会演进）
DICT_SEEDS = {
    "domestic_followup_state_change": [
        "订单减少", "订单增长", "补货周期变长", "开始买低价款", "开始买高端款",
        "竞争品牌增加", "店里增加直播", "店里增加短视频", "老板换人", "客户定位改变",
        "稳定没变化", "已成交", "未成交", "链接未回复",
    ],
    "domestic_followup_category": ["质量", "发货物流", "色差", "尺寸", "价格", "售后退换", "服务", "产品需求", "其他"],
    "domestic_followup_channel": ["微信", "电话", "视频号", "到店", "展会", "其他"],
}

TABLES = (
    "ark_domestic_followup_config",
    "ark_domestic_followup_digests",
    "ark_domestic_followup_task_shipments",
    "ark_domestic_followup_tasks",
    "ark_domestic_customer_aliases",
    "ark_domestic_followup_attachments",
    "ark_domestic_followup_items",
    "ark_domestic_followups",
)


def _seed_dicts() -> None:
    bind = op.get_bind()
    for dict_type, labels in DICT_SEEDS.items():
        for idx, label in enumerate(labels):
            exists = bind.execute(
                sa.text("SELECT 1 FROM sys_dict WHERE type = :t AND code = :c LIMIT 1"),
                {"t": dict_type, "c": label},
            ).first()
            if exists:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO sys_dict (type, code, label, sort, is_active, created_at, updated_at) "
                    "VALUES (:t, :c, :l, :s, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"t": dict_type, "c": label, "l": label, "s": idx * 10},
            )


def _create_table(name, *columns, **kwargs) -> None:
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns, **kwargs)


def _create_index(name, table, columns, **kwargs) -> None:
    existing = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, **kwargs)


def upgrade():
    ident = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    big = sa.BigInteger()
    user_id = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
    customer_id = sa.Integer()

    _create_table(
        "ark_domestic_followups",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("customer_id", customer_id, sa.ForeignKey("ark_domestic_customers.id"), nullable=True, comment="客户ID；草稿可暂空，确认时必填"),
        sa.Column("author_user_id", user_id, sa.ForeignKey("ark_users.id"), nullable=False, comment="录入人，永久保留"),
        sa.Column("followup_date", sa.Date(), nullable=False, comment="跟进日期（北京日期）"),
        sa.Column("channel", sa.String(16), nullable=True, comment="沟通方式（sys_dict: domestic_followup_channel）"),
        sa.Column("raw_text", sa.Text(), nullable=True, comment="业务员原文，永不被 AI 覆盖"),
        sa.Column("summary", sa.String(500), nullable=True, comment="一句话摘要"),
        sa.Column("state_changes", sa.JSON(), nullable=True, comment="客户状态变化（sys_dict: domestic_followup_state_change）"),
        sa.Column("next_date", sa.Date(), nullable=True, comment="下次跟进日期"),
        sa.Column("next_plan", sa.String(500), nullable=True, comment="下次跟进内容"),
        sa.Column("next_method", sa.String(16), nullable=True, comment="下次跟进方式"),
        sa.Column("chat_title", sa.String(120), nullable=True, comment="截图聊天标题，确认后学习为客户别名"),
        sa.Column("source", sa.String(16), nullable=False, server_default="web", comment="web/mobile/mini/wechat_agent/import"),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft", comment="draft/confirmed/discarded"),
        sa.Column("ai_status", sa.String(12), nullable=False, server_default="none", comment="none/running/done/failed"),
        sa.Column("ai_result", sa.JSON(), nullable=True, comment="AI 归一化后的草稿"),
        sa.Column("ai_error", sa.String(255), nullable=True, comment="AI 失败原因（不含原文）"),
        sa.Column("ai_log_id", big, nullable=True, comment="AI 调用日志ID"),
        sa.Column("source_task_id", big, nullable=True, comment="从哪张待办发起的记录"),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True, comment="客户端幂等键"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="乐观锁：状态迁移时 +1"),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True, comment="确认时间（北京时间）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        comment="内贸客户跟进记录：一次触达一条",
    )
    _create_index("ix_dom_followup_customer_date", "ark_domestic_followups", ["customer_id", "followup_date"])
    _create_index("ix_dom_followup_author_status", "ark_domestic_followups", ["author_user_id", "status"])

    _create_table(
        "ark_domestic_followup_items",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("followup_id", big, sa.ForeignKey("ark_domestic_followups.id"), nullable=False, comment="所属跟进记录"),
        sa.Column("customer_id", customer_id, sa.ForeignKey("ark_domestic_customers.id"), nullable=False, comment="客户ID（冗余，供看板查询）"),
        sa.Column("seq", sa.SmallInteger(), nullable=False, comment="同类条目内的序号，从 1 开始"),
        sa.Column("kind", sa.String(12), nullable=False, comment="content/issue/suggestion"),
        sa.Column("text", sa.String(1000), nullable=False, comment="条目内容"),
        sa.Column("category", sa.String(32), nullable=True, comment="分类（sys_dict: domestic_followup_category）"),
        sa.Column("severity", sa.String(8), nullable=True, comment="一般/紧急"),
        sa.Column("origin", sa.String(16), nullable=False, server_default="user", comment="user/ai_inferred"),
        sa.Column("state", sa.String(20), nullable=True, comment="issue/suggestion：open/handling/resolved/closed_no_action"),
        sa.Column("handler_user_id", user_id, sa.ForeignKey("ark_users.id"), nullable=True, comment="当前处理人"),
        sa.Column("resolution", sa.String(500), nullable=True, comment="处理说明"),
        sa.Column("resolved_at", sa.DateTime(), nullable=True, comment="解决时间（北京时间）"),
        sa.Column("resolved_by_followup_id", big, nullable=True, comment="在哪条跟进里处理"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        comment="跟进条目：要点 / 异常 / 意见建议",
    )
    _create_index("ix_dom_followup_item_followup", "ark_domestic_followup_items", ["followup_id"])
    _create_index("ix_dom_followup_item_board", "ark_domestic_followup_items", ["kind", "state", "customer_id"])

    _create_table(
        "ark_domestic_followup_attachments",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("followup_id", big, sa.ForeignKey("ark_domestic_followups.id"), nullable=True, comment="所属跟进；上传后未绑定为空"),
        sa.Column("uploader_user_id", user_id, sa.ForeignKey("ark_users.id"), nullable=False, comment="上传人"),
        sa.Column("seq", sa.SmallInteger(), nullable=False, server_default="0", comment="在记录中的顺序"),
        sa.Column("file_path", sa.String(255), nullable=False, comment="domestic 存储相对路径"),
        sa.Column("file_name", sa.String(255), nullable=True, comment="原始文件名"),
        sa.Column("mime_type", sa.String(64), nullable=True, comment="MIME"),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0", comment="字节数"),
        sa.Column("ocr_status", sa.String(12), nullable=False, server_default="pending", comment="pending/done/failed"),
        sa.Column("ocr_text", sa.Text(), nullable=True, comment="OCR 文本"),
        sa.Column("unreadable_note", sa.String(500), nullable=True, comment="AI 读不到的内容说明（语音/视频等）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="上传时间（北京时间）"),
        comment="跟进截图附件，带 OCR 文本",
    )
    _create_index("ix_dom_followup_att_followup", "ark_domestic_followup_attachments", ["followup_id"])
    _create_index("ix_dom_followup_att_uploader", "ark_domestic_followup_attachments", ["uploader_user_id", "followup_id"])

    _create_table(
        "ark_domestic_customer_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("customer_id", customer_id, sa.ForeignKey("ark_domestic_customers.id", ondelete="CASCADE"), nullable=False, comment="客户ID"),
        sa.Column("alias", sa.String(120), nullable=False, comment="别名原文"),
        sa.Column("alias_norm", sa.String(120), nullable=False, comment="归一化别名（去空白、小写）"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="1", comment="确认命中次数"),
        sa.Column("created_by", user_id, sa.ForeignKey("ark_users.id"), nullable=False, comment="首次记录人"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        sa.UniqueConstraint("alias_norm", "customer_id", name="uq_dom_customer_alias"),
        comment="客户别名：聊天标题 / 微信备注名 → 客户",
    )

    _create_table(
        "ark_domestic_followup_tasks",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("task_type", sa.String(12), nullable=False, comment="plan/receipt/issue/suggestion"),
        sa.Column("customer_id", customer_id, sa.ForeignKey("ark_domestic_customers.id"), nullable=False, comment="客户ID"),
        sa.Column("assignee_user_id", user_id, sa.ForeignKey("ark_users.id"), nullable=False, comment="负责人"),
        sa.Column("source_key", sa.String(96), nullable=False, unique=True, comment="来源唯一键，一个来源只生一次任务"),
        sa.Column("title", sa.String(200), nullable=False, comment="标题"),
        sa.Column("due_date", sa.Date(), nullable=False, comment="到期日（北京日期）"),
        sa.Column("status", sa.String(12), nullable=False, server_default="todo", comment="todo/done/expired/cancelled"),
        sa.Column("snooze_count", sa.SmallInteger(), nullable=False, server_default="0", comment="顺延次数"),
        sa.Column("payload", sa.JSON(), nullable=True, comment="展示用快照：批次列表 / 计划内容 / 条目摘要"),
        sa.Column("source_followup_id", big, nullable=True, comment="来源跟进记录"),
        sa.Column("source_item_id", big, nullable=True, comment="来源条目"),
        sa.Column("closed_by_followup_id", big, nullable=True, comment="被哪条跟进关闭"),
        sa.Column("closed_reason", sa.String(16), nullable=True, comment="回访完成/有新跟进/条目已解决/超时过期/客户释放"),
        sa.Column("closed_by_user_id", user_id, sa.ForeignKey("ark_users.id"), nullable=True, comment="关闭操作人；系统关闭为空"),
        sa.Column("closed_at", sa.DateTime(), nullable=True, comment="关闭时间（北京时间）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        comment="跟进任务：约定跟进 / 收货回访 / 异常跟进 / 意见跟进",
    )
    _create_index("ix_dom_followup_task_assignee", "ark_domestic_followup_tasks", ["assignee_user_id", "status", "due_date"])
    _create_index("ix_dom_followup_task_customer", "ark_domestic_followup_tasks", ["customer_id", "status"])

    _create_table(
        "ark_domestic_followup_task_shipments",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("task_id", big, sa.ForeignKey("ark_domestic_followup_tasks.id"), nullable=False, comment="回访任务"),
        sa.Column("shipment_id", big, sa.ForeignKey("ark_domestic_shipments.id"), nullable=False, unique=True, comment="发货批次"),
        comment="收货回访任务覆盖的发货批次；shipment_id 唯一保证每批次只提醒一次",
    )
    _create_index("ix_ark_domestic_followup_task_shipments_task_id", "ark_domestic_followup_task_shipments", ["task_id"])

    _create_table(
        "ark_domestic_followup_digests",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("user_id", user_id, sa.ForeignKey("ark_users.id"), nullable=False, comment="接收人"),
        sa.Column("digest_date", sa.Date(), nullable=False, comment="推送业务日（北京日期）"),
        sa.Column("kind", sa.String(12), nullable=False, comment="daily=每日汇总，urgent=紧急异常"),
        sa.Column("ref_key", sa.String(64), nullable=False, server_default="", comment="daily 为空串；urgent 为 item:<id>"),
        sa.Column("title", sa.String(100), nullable=False, comment="通知标题"),
        sa.Column("markdown", sa.Text(), nullable=False, comment="通知正文"),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0", comment="发送失败次数"),
        sa.Column("last_error", sa.String(255), nullable=True, comment="最近一次失败原因"),
        sa.Column("pushed_at", sa.DateTime(), nullable=True, comment="推送成功时间（北京时间）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.UniqueConstraint("user_id", "digest_date", "kind", "ref_key", name="uq_dom_followup_digest"),
        comment="跟进推送发件箱：同人同日同类只推一次",
    )
    _create_index("ix_dom_followup_digest_pending", "ark_domestic_followup_digests", ["kind", "pushed_at"])

    _create_table(
        "ark_domestic_followup_config",
        sa.Column("key", sa.String(64), primary_key=True, comment="配置键"),
        sa.Column("value", sa.JSON(), nullable=True, comment="配置值"),
        sa.Column("updated_by", user_id, sa.ForeignKey("ark_users.id"), nullable=True, comment="最后维护人"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        comment="跟进模块配置：回访天数、上线日、紧急接收人、跟进频率",
    )

    _seed_dicts()


def downgrade():
    inspector = sa.inspect(op.get_bind())
    for table in TABLES:
        if inspector.has_table(table):
            op.drop_table(table)
