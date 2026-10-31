"""Color swatch library: public/private (customer-bound) swatches with colorimeter measurements.

Additive tables only; downgrade keeps data (production is forward-only).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "210_color_swatch_library"
down_revision = "209_invoice_item_groups"
branch_labels = None
depends_on = None


def upgrade():
    ident = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    user_id = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
    palette_id = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
    big = sa.BigInteger()

    op.create_table(
        "ark_color_library_swatches",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("library_scope", sa.String(16), nullable=False, comment="库范围：public=公库，private=私库"),
        sa.Column("customer_id", big, sa.ForeignKey("ark_customer_accounts.id"), nullable=True,
                  comment="私库绑定的统一客户ID；公库为空"),
        sa.Column("customer_scope_key", big, nullable=False, server_default="0",
                  comment="唯一约束用客户键：私库=customer_id，公库=0（避免 NULL 不参与唯一）"),
        sa.Column("owner_user_id", user_id, sa.ForeignKey("ark_users.id"), nullable=False, comment="创建人；不参与授权"),
        sa.Column("color_code", sa.String(30), nullable=False, comment="色号原文，如 #1C、#8/60、客户自定义编码"),
        sa.Column("color_code_key", sa.String(30), nullable=False, comment="色号规范化键（去空格、大写），用于唯一判定"),
        sa.Column("size_value", sa.Numeric(5, 1), nullable=False, comment="尺寸数值，如 18.0"),
        sa.Column("size_unit", sa.String(8), nullable=False, server_default="inch", comment="尺寸单位：inch / cm"),
        sa.Column("display_name", sa.String(100), nullable=True, comment="展示名称"),
        sa.Column("base_swatch_id", big, sa.ForeignKey("ark_color_library_swatches.id"), nullable=True,
                  comment="对比基准：公库色板ID（优先用其实测平均Lab）"),
        sa.Column("base_palette_id", palette_id, sa.ForeignKey("ark_color_palette.id"), nullable=True,
                  comment="对比基准：公库基础色号ID（无实测色板时使用其Lab）"),
        sa.Column("tolerance_de", sa.Numeric(4, 2), nullable=False, server_default="1.50", comment="允许色差阈值（ΔE00）"),
        sa.Column("stat_count", sa.SmallInteger(), nullable=False, server_default="0", comment="参与平均的测量组数（由测量记录重算）"),
        sa.Column("stat_lab_l", sa.Numeric(6, 2), nullable=True, comment="平均 L*（重算冗余）"),
        sa.Column("stat_lab_a", sa.Numeric(6, 2), nullable=True, comment="平均 a*（重算冗余）"),
        sa.Column("stat_lab_b", sa.Numeric(6, 2), nullable=True, comment="平均 b*（重算冗余）"),
        sa.Column("stat_mean_de", sa.Numeric(5, 2), nullable=True, comment="组内平均ΔE00：各组到平均Lab的ΔE均值，至少2组"),
        sa.Column("stat_max_de", sa.Numeric(5, 2), nullable=True, comment="组内最大ΔE00，至少2组"),
        sa.Column("stat_base_de", sa.Numeric(5, 2), nullable=True, comment="平均Lab与基准Lab的ΔE00"),
        sa.Column("record_status", sa.String(16), nullable=False, server_default="active", comment="active=有效，archived=已归档"),
        sa.Column("promoted_from_id", big, sa.ForeignKey("ark_color_library_swatches.id"), nullable=True,
                  comment="公库色板由哪条私库色板晋升而来"),
        sa.Column("promotion_status", sa.String(16), nullable=True,
                  comment="私库晋升申请状态：pending=待审核，approved=已纳入，rejected=已驳回"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        sa.CheckConstraint(
            "(library_scope = 'public' AND customer_id IS NULL AND customer_scope_key = 0) "
            "OR (library_scope = 'private' AND customer_id IS NOT NULL AND customer_scope_key = customer_id)",
            name="ck_color_library_swatch_scope"),
        sa.CheckConstraint("size_value > 0", name="ck_color_library_swatch_size"),
        sa.UniqueConstraint("library_scope", "customer_scope_key", "color_code_key", "size_value", "size_unit",
                            name="uq_color_library_swatch_identity"),
        sa.Index("ix_color_library_swatch_customer", "customer_id", "record_status"),
        sa.Index("ix_color_library_swatch_scope", "library_scope", "record_status"),
        comment="色板库：公库标准色板与业务员私库客户色板；私库必须绑定客户，同库同客户下色号+尺寸唯一",
    )

    op.create_table(
        "ark_color_library_measurements",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("swatch_id", big, sa.ForeignKey("ark_color_library_swatches.id"), nullable=False, comment="所属色板"),
        sa.Column("seq_no", sa.Integer(), nullable=False, comment="色板内测量序号，从1递增"),
        sa.Column("lab_l", sa.Numeric(6, 2), nullable=False, comment="Lab L*（帧字节8-9 int16LE/100）"),
        sa.Column("lab_a", sa.Numeric(6, 2), nullable=False, comment="Lab a*（帧字节10-11 int16LE/100）"),
        sa.Column("lab_b", sa.Numeric(6, 2), nullable=False, comment="Lab b*（帧字节12-13 int16LE/100）"),
        sa.Column("luv_l", sa.Numeric(6, 2), nullable=True, comment="Luv L*"),
        sa.Column("luv_u", sa.Numeric(6, 2), nullable=True, comment="Luv u*"),
        sa.Column("luv_v", sa.Numeric(6, 2), nullable=True, comment="Luv v*"),
        sa.Column("lch_l", sa.Numeric(6, 2), nullable=True, comment="LCh L*"),
        sa.Column("lch_c", sa.Numeric(6, 2), nullable=True, comment="LCh C*"),
        sa.Column("lch_h", sa.Numeric(6, 2), nullable=True, comment="LCh h（保留原厂App有/无符号规则）"),
        sa.Column("yxy_y", sa.Numeric(7, 2), nullable=True, comment="Yxy Y（/100）"),
        sa.Column("yxy_x", sa.Numeric(6, 4), nullable=True, comment="Yxy x（/10000）"),
        sa.Column("yxy_yy", sa.Numeric(6, 4), nullable=True, comment="Yxy y（/10000）"),
        sa.Column("cmyk_c", sa.SmallInteger(), nullable=True, comment="设备返回 CMYK C（uint8 原值）"),
        sa.Column("cmyk_m", sa.SmallInteger(), nullable=True, comment="设备返回 CMYK M"),
        sa.Column("cmyk_y", sa.SmallInteger(), nullable=True, comment="设备返回 CMYK Y"),
        sa.Column("cmyk_k", sa.SmallInteger(), nullable=True, comment="设备返回 CMYK K"),
        sa.Column("rgb_r", sa.SmallInteger(), nullable=True, comment="设备返回 RGB R，仅作预览"),
        sa.Column("rgb_g", sa.SmallInteger(), nullable=True, comment="设备返回 RGB G"),
        sa.Column("rgb_b", sa.SmallInteger(), nullable=True, comment="设备返回 RGB B"),
        sa.Column("raw_hex", sa.Text(), nullable=True, comment="完整 CRC 有效帧 HEX，可离线重解析；手工录入为空"),
        sa.Column("source", sa.String(16), nullable=False, comment="device=色差仪，simulation=模拟设备，manual=手工录入"),
        sa.Column("receipt_status", sa.String(16), nullable=False, server_default="matched",
                  comment="matched=请求窗口内匹配，late=超时后到达经人工确认，manual=手工录入"),
        sa.Column("device_name", sa.String(64), nullable=True, comment="广播设备名"),
        sa.Column("device_sn", sa.String(32), nullable=True, comment="设备信息帧解析的 SN；不是 MAC 或浏览器设备ID"),
        sa.Column("device_fw", sa.String(16), nullable=True, comment="设备版本显示值"),
        sa.Column("session_id", sa.String(64), nullable=True, comment="前端一次蓝牙连接会话ID"),
        sa.Column("client_request_id", sa.String(64), nullable=False, comment="前端幂等键，防止重试重复入库"),
        sa.Column("requested_at", sa.DateTime(), nullable=True, comment="发送测量指令的北京时间"),
        sa.Column("received_at", sa.DateTime(), nullable=True, comment="收到测量帧的北京时间"),
        sa.Column("is_included", sa.SmallInteger(), nullable=False, server_default="1", comment="1=参与平均，0=已剔除"),
        sa.Column("exclude_reason", sa.String(255), nullable=True, comment="剔除原因"),
        sa.Column("measured_by", user_id, sa.ForeignKey("ark_users.id"), nullable=False, comment="操作人"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="入库时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        sa.UniqueConstraint("swatch_id", "seq_no", name="uq_color_library_measurement_seq"),
        sa.UniqueConstraint("swatch_id", "client_request_id", name="uq_color_library_measurement_request"),
        sa.Index("ix_color_library_measurement_swatch", "swatch_id", "is_included"),
        comment="色板测量组：一行对应色差仪一次 CRC 有效的 44 类测量返回；原始值不可修改，只能剔除",
    )

    op.create_table(
        "ark_color_library_events",
        sa.Column("id", ident, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("swatch_id", big, sa.ForeignKey("ark_color_library_swatches.id"), nullable=False, comment="色板ID"),
        sa.Column("event_type", sa.String(32), nullable=False,
                  comment="created/updated/measured/excluded/restored/promotion_requested/promotion_approved/promotion_rejected/archived"),
        sa.Column("detail_json", sa.Text(), nullable=True, comment="事件详情 JSON 文本（变更前后值、原因）"),
        sa.Column("operated_by", user_id, sa.ForeignKey("ark_users.id"), nullable=False, comment="操作人"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="事件时间（北京时间）"),
        sa.Index("ix_color_library_event_swatch", "swatch_id", "id"),
        comment="色板库审计事件：新建、修改属性、剔除/恢复测量、晋升申请与审核",
    )


def downgrade():
    # Forward-only in production; keep measurement history.
    pass
