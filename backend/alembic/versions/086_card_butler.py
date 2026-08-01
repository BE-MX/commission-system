"""名片管家：业务员电子名片四表 + 种子业务员

Revision ID: 086_card_butler
Revises: 085_expo_prompt_variant
Create Date: 2026-08-01

业务员名片二维码（leshine.work/card/<slug>/）背后的动态层：
salespersons（档案，slug 与印刷二维码绑定）/ customers（口令=归一化邮箱/WhatsApp）/
entries（手工纪要）/ inquiries（公开表单询盘）。

种子 4 位业务员（ginny/janny/katy/sylvia）随迁移插入（WHERE NOT EXISTS 幂等）——
名片明早印刷，slug 必须当晚固化；档案细节后续在管理页维护。
纯新增表，无老表改动，天然满足「老代码 + 新 schema」过渡期。

留档：本迁移最初以 `note` 列名执行（2026-08-01 当晚），随后因命名宪法（note→remark）
在共享库人工 `RENAME COLUMN` 并同步改写本文件——文件与库现状一致，但与首次执行
历史不同；重建环境直接跑本文件即得正确 schema。
"""

import sqlalchemy as sa
from alembic import op

revision = "086_card_butler"
down_revision = "085_expo_prompt_variant"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_card_salespersons",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("slug", sa.String(32), nullable=False, comment="URL 标识（印刷二维码固化，禁改）"),
        sa.Column("name", sa.String(64), nullable=False, comment="英文名，如 Ginny"),
        sa.Column("title", sa.String(64), nullable=False, server_default="Sales Manager", comment="职位"),
        sa.Column("email", sa.String(128), nullable=False, comment="业务邮箱"),
        sa.Column("whatsapp", sa.String(32), nullable=True, comment="WhatsApp 号（可空，数据到齐后补）"),
        sa.Column("avatar_path", sa.String(512), nullable=True, comment="AI 头像相对路径"),
        sa.Column("intro", sa.Text(), nullable=True, comment="主页介绍文案"),
        sa.Column("links_json", sa.JSON(), nullable=True, comment="店铺/独立站链接 [{label,url}]"),
        sa.Column("is_active", sa.SmallInteger(), nullable=False, server_default="1", comment="1=启用,0=停用"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_ark_card_salespersons_slug"),
        comment="名片管家-业务员档案（slug 与印刷二维码绑定）",
    )
    op.create_index("idx_ark_card_salespersons_active", "ark_card_salespersons", ["is_active"])

    op.create_table(
        "ark_card_customers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("salesperson_id", sa.BigInteger(), nullable=False, comment="归属业务员 ark_card_salespersons.id"),
        sa.Column("display_name", sa.String(128), nullable=False, comment="客户称呼（解锁后问候语用）"),
        sa.Column("email_norm", sa.String(128), nullable=True, comment="口令-邮箱（小写归一）"),
        sa.Column("whatsapp_norm", sa.String(32), nullable=True, comment="口令-WhatsApp（纯数字归一）"),
        sa.Column("expo_code", sa.String(64), nullable=False, server_default="", comment="届次标记，如 2026-08"),
        sa.Column("remark", sa.Text(), nullable=True, comment="内部备注（不对客户展示）"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="录入人 ark_users.id（无 FK）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["salesperson_id"], ["ark_card_salespersons.id"], ondelete="CASCADE"),
        comment="名片管家-客户档案（归一化邮箱/WhatsApp 即客户口令）",
    )
    op.create_index("idx_ark_card_customers_sp", "ark_card_customers", ["salesperson_id"])
    op.create_index("idx_ark_card_customers_email", "ark_card_customers", ["email_norm"])
    op.create_index("idx_ark_card_customers_wa", "ark_card_customers", ["whatsapp_norm"])

    op.create_table(
        "ark_card_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="归属客户 ark_card_customers.id"),
        sa.Column("entry_type", sa.String(16), nullable=False, server_default="text", comment="text=文字 / image=图片"),
        sa.Column("title", sa.String(128), nullable=True, comment="条目标题（可空）"),
        sa.Column("content", sa.Text(), nullable=True, comment="文字内容"),
        sa.Column("attachment_path", sa.String(512), nullable=True, comment="附件相对路径 uploads/card/..."),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="录入人 ark_users.id（无 FK）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_card_customers.id"], ondelete="CASCADE"),
        comment="名片管家-沟通纪要（客户凭口令可见）",
    )
    op.create_index("idx_ark_card_entries_customer", "ark_card_entries", ["customer_id"])

    op.create_table(
        "ark_card_inquiries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("salesperson_id", sa.BigInteger(), nullable=False, comment="目标业务员 ark_card_salespersons.id"),
        sa.Column("customer_id", sa.BigInteger(), nullable=True, comment="联系方式命中客户档案时回填（可空）"),
        sa.Column("contact", sa.String(128), nullable=False, comment="客户留的联系方式原文"),
        sa.Column("message", sa.Text(), nullable=False, comment="需求/问题正文"),
        sa.Column("status", sa.String(16), nullable=False, server_default="new", comment="new=未处理 / handled=已处理"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["salesperson_id"], ["ark_card_salespersons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_card_customers.id"], ondelete="SET NULL"),
        comment="名片管家-客户询盘（公开表单，status 驱动跟进）",
    )
    op.create_index("idx_ark_card_inquiries_sp", "ark_card_inquiries", ["salesperson_id", "status"])

    # 种子 4 位业务员（slug 当晚随印刷固化；幂等，重跑不重复插）
    for slug, name, email in (
        ("ginny", "Ginny", "ginny@leshinehair.com"),
        ("janny", "Janny", "janny@leshinehair.com"),
        ("katy", "Katy", "katy@leshinehair.com"),
        ("sylvia", "Sylvia", "sylvia@leshinehair.com"),
    ):
        op.execute(sa.text(
            "INSERT INTO ark_card_salespersons (slug, name, email)"
            " SELECT :slug, :name, :email FROM DUAL"
            " WHERE NOT EXISTS (SELECT 1 FROM ark_card_salespersons WHERE slug = :slug)"
        ).bindparams(slug=slug, name=name, email=email))


def downgrade():
    op.drop_table("ark_card_inquiries")
    op.drop_table("ark_card_entries")
    op.drop_table("ark_card_customers")
    op.drop_table("ark_card_salespersons")
