"""domestic: 内贸订单管理与生产跟踪（7 张表 + 属性值域字典初值）

与外贸生产订单/报工完全平行的一套表：外贸报工是整行 0/1 流转，
内贸要按数量拆批流转，进度表结构不同（累计完成数 + 报工流水），
故不复用 order_product_process_progress，避免动老表带来的回归面。

复用的全局资产（不新建）：process / process_route / process_route_step /
user_process_binding —— 工序、路线、工人分工内外贸共用一套。

Revision ID: 081_domestic_orders
Revises: 080_dashboard_preference
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "081_domestic_orders"
down_revision = "080_dashboard_preference"
branch_labels = None
depends_on = None

# ark_users.id 实际是 INT UNSIGNED，FK 类型必须完全一致（cerebrum 2026-06-10）
_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")

TABLES = [
    "ark_domestic_report_logs",
    "ark_domestic_item_progress",
    "ark_domestic_order_items",
    "ark_domestic_orders",
    "ark_domestic_craft_routes",
    "ark_domestic_products",
    "ark_domestic_customers",
]

# 属性值域初值：code 直接用中文（业务值本身就是这个名字，主管加选项不用编 slug）
DICT_SEEDS = {
    "domestic_cap_craft": ["递针旋全头套", "递针旋九分头", "递针顶", "递针中分界", "递针左分界"],
    "domestic_net_color": ["呼吸红", "经典紫", "闷青"],
    "domestic_piece_craft": ["递针旋", "递针中分界", "递针左分界", "U型递针", "全递针"],
    "domestic_cap_size": ["ss", "s", "m", "L", "xl", "51", "53", "55", "57", "59", "取模定制"],
    "domestic_piece_size": ["9*14", "12*14", "13*15", "14*16", "15*17", "16*18", "18*20", "取模定制"],
    "domestic_length": ["15厘米", "20厘米", "25厘米", "30厘米", "35厘米", "40厘米"],
    "domestic_density": ["65%", "80%", "90%"],
}


def _existing_tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    # MySQL DDL 自动提交不可回滚，逐表幂等检查防半执行状态
    existing = _existing_tables()

    if "ark_domestic_customers" not in existing:
        op.create_table(
            "ark_domestic_customers",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column("shop_name", sa.String(120), nullable=False, unique=True, comment="客户店名（业务主标识）"),
            sa.Column("contact", sa.String(60), comment="联系人"),
            sa.Column("phone", sa.String(40), comment="联系电话"),
            sa.Column("address", sa.String(255), comment="收货地址"),
            sa.Column("remark", sa.String(500), comment="备注"),
            sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1", comment="0=停用,1=启用"),
            sa.Column("created_by", _UINT, sa.ForeignKey("ark_users.id"), nullable=False, comment="创建人"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            comment="内贸客户（店名维度）",
        )

    if "ark_domestic_products" not in existing:
        op.create_table(
            "ark_domestic_products",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column("attrs_key", sa.String(255), nullable=False, unique=True,
                      comment="属性组合唯一键 type|craft|net_color|size|length|density，find-or-create 依据"),
            sa.Column("name", sa.String(255), nullable=False, comment="展示名（属性拼接，创建时快照）"),
            sa.Column("product_type", sa.String(16), nullable=False, comment="cap=头套,piece=发片"),
            sa.Column("craft", sa.String(64), nullable=False, comment="工艺（头套工艺或发片工艺）"),
            sa.Column("net_color", sa.String(64), comment="网底颜色（仅头套）"),
            sa.Column("size", sa.String(64), nullable=False, comment="尺寸（含「取模定制」）"),
            sa.Column("length", sa.String(32), nullable=False, comment="长度"),
            sa.Column("density", sa.String(32), nullable=False, comment="发量"),
            sa.Column("route_id", sa.Integer(), sa.ForeignKey("process_route.id", ondelete="RESTRICT"),
                      comment="工艺路线，按 craft 映射自动绑定，可人工改绑；NULL=未匹配到路线"),
            sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1", comment="0=停用,1=启用"),
            sa.Column("use_count", sa.Integer(), nullable=False, server_default="0", comment="被下单次数"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            comment="内贸产品（下单选属性自动沉淀）",
        )
        op.create_index("idx_dom_product_type", "ark_domestic_products", ["product_type", "status"])
        op.create_index("idx_dom_product_route", "ark_domestic_products", ["route_id"])

    if "ark_domestic_craft_routes" not in existing:
        op.create_table(
            "ark_domestic_craft_routes",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column("product_type", sa.String(16), nullable=False, comment="cap=头套,piece=发片"),
            sa.Column("craft", sa.String(64), nullable=False, comment="工艺值（对应字典 code）"),
            sa.Column("route_id", sa.Integer(), sa.ForeignKey("process_route.id", ondelete="RESTRICT"),
                      nullable=False, comment="该工艺默认走的工艺路线"),
            sa.Column("updated_by", _UINT, sa.ForeignKey("ark_users.id"), comment="最后维护人"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.UniqueConstraint("product_type", "craft", name="uk_dom_craft_route"),
            comment="内贸工艺→工艺路线映射（新产品自动配路线的依据）",
        )

    if "ark_domestic_orders" not in existing:
        op.create_table(
            "ark_domestic_orders",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column("domestic_no", sa.String(32), nullable=False, unique=True, comment="系统单号 DO{YYYYMMDD}-{NNN}"),
            sa.Column("order_no", sa.String(64), nullable=False, comment="客户订单号（原样文本，格式不统一不做约束）"),
            sa.Column("order_date", sa.Date(), nullable=False, comment="下单日期"),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("ark_domestic_customers.id", ondelete="RESTRICT"),
                      nullable=False, comment="客户"),
            sa.Column("order_type", sa.String(16), nullable=False, server_default="normal", comment="normal=普货,special=特单"),
            sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1",
                      comment="1=生产中,2=已完工,3=已发货,4=已终止"),
            sa.Column("remark", sa.String(1000), comment="订单备注"),
            sa.Column("created_by", _UINT, sa.ForeignKey("ark_users.id"), nullable=False, comment="下单人"),
            sa.Column("deleted_flag", sa.SmallInteger(), nullable=False, server_default="0", comment="0=正常,1=已删除"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            comment="内贸订单主表",
        )
        op.create_index("idx_dom_order_status", "ark_domestic_orders", ["status", "deleted_flag"])
        op.create_index("idx_dom_order_customer", "ark_domestic_orders", ["customer_id"])
        op.create_index("idx_dom_order_date", "ark_domestic_orders", ["order_date"])
        op.create_index("idx_dom_order_no", "ark_domestic_orders", ["order_no"])

    if "ark_domestic_order_items" not in existing:
        op.create_table(
            "ark_domestic_order_items",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("ark_domestic_orders.id", ondelete="CASCADE"),
                      nullable=False, comment="所属订单"),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("ark_domestic_products.id", ondelete="RESTRICT"),
                      nullable=False, comment="内贸产品"),
            sa.Column("product_name", sa.String(255), nullable=False, comment="产品名快照"),
            sa.Column("attrs_snapshot", sa.JSON(), comment="属性快照 {product_type,craft,net_color,size,length,density}"),
            sa.Column("route_id", sa.Integer(), sa.ForeignKey("process_route.id", ondelete="RESTRICT"),
                      comment="下单时锁定的工艺路线快照，后改映射不影响在制单"),
            sa.Column("order_qty", sa.Integer(), nullable=False, comment="下单数量"),
            sa.Column("hairstyle", sa.String(1000), comment="发型（文字）"),
            sa.Column("hairstyle_images", sa.JSON(), comment="发型参考图 [相对路径]"),
            sa.Column("color", sa.String(1000), comment="颜色（文字）"),
            sa.Column("color_images", sa.JSON(), comment="颜色参考图 [相对路径]"),
            sa.Column("style_requirement", sa.String(2000), comment="发型要求（文字）"),
            sa.Column("style_images", sa.JSON(), comment="发型要求图 [相对路径]"),
            sa.Column("remark", sa.String(2000), comment="明细备注（文字）"),
            sa.Column("remark_images", sa.JSON(), comment="备注图 [相对路径]"),
            sa.Column("status", sa.SmallInteger(), nullable=False, server_default="0",
                      comment="0=生产中,1=已完工,2=已发货"),
            sa.Column("ship_time", sa.DateTime(), comment="发货时间（发货前必填）"),
            sa.Column("ship_weight", sa.Numeric(10, 2), comment="发货克重 g（发货前必填，单件属性）"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            comment="内贸订单明细（一单多品，每行独立走工艺路线）",
        )
        op.create_index("idx_dom_item_order", "ark_domestic_order_items", ["order_id"])
        op.create_index("idx_dom_item_status", "ark_domestic_order_items", ["status"])
        op.create_index("idx_dom_item_product", "ark_domestic_order_items", ["product_id"])

    if "ark_domestic_item_progress" not in existing:
        op.create_table(
            "ark_domestic_item_progress",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("ark_domestic_order_items.id", ondelete="CASCADE"),
                      nullable=False, comment="所属明细"),
            sa.Column("route_id", sa.Integer(), sa.ForeignKey("process_route.id", ondelete="RESTRICT"),
                      nullable=False, comment="冗余路线ID"),
            sa.Column("process_id", sa.Integer(), sa.ForeignKey("process.id", ondelete="RESTRICT"),
                      nullable=False, comment="工序"),
            sa.Column("step_order", sa.SmallInteger(), nullable=False, comment="工序顺序，从1开始"),
            sa.Column("completed_qty", sa.Integer(), nullable=False, server_default="0",
                      comment="本道累计完成数量；可报数量=上道累计-本道累计，首道上游=order_qty"),
            sa.Column("status", sa.SmallInteger(), nullable=False, server_default="0", comment="0=进行中,1=本道已做完"),
            sa.Column("first_reported_at", sa.DateTime(), comment="首次报工时间"),
            sa.Column("last_reported_at", sa.DateTime(), comment="最后一次报工时间"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.UniqueConstraint("item_id", "step_order", name="uk_dom_progress_item_step"),
            comment="内贸明细工序进度（按数量累计，非 0/1 流转）",
        )
        op.create_index("idx_dom_progress_item", "ark_domestic_item_progress", ["item_id"])
        op.create_index("idx_dom_progress_process", "ark_domestic_item_progress", ["process_id", "status"])

    if "ark_domestic_report_logs" not in existing:
        op.create_table(
            "ark_domestic_report_logs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True, comment="主键"),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("ark_domestic_order_items.id", ondelete="CASCADE"),
                      nullable=False, comment="所属明细"),
            sa.Column("progress_id", sa.Integer(), sa.ForeignKey("ark_domestic_item_progress.id", ondelete="CASCADE"),
                      nullable=False, comment="所属进度行"),
            sa.Column("process_id", sa.Integer(), sa.ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, comment="工序"),
            sa.Column("step_order", sa.SmallInteger(), nullable=False, comment="工序顺序"),
            sa.Column("report_qty", sa.Integer(), nullable=False, comment="本次报工数量"),
            sa.Column("reported_by_user_id", _UINT, sa.ForeignKey("ark_users.id"), nullable=False, comment="报工人"),
            sa.Column("reported_by_name", sa.String(60), comment="报工人姓名快照"),
            sa.Column("source", sa.String(16), nullable=False, server_default="mini", comment="mini=小程序,web=主站"),
            sa.Column("reported_at", sa.DateTime(), nullable=False, comment="报工时间（北京时）"),
            sa.Column("revoked", sa.SmallInteger(), nullable=False, server_default="0", comment="0=有效,1=已撤销"),
            sa.Column("revoked_at", sa.DateTime(), comment="撤销时间"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            comment="内贸报工流水（支持撤销回减与计件统计，外贸侧没有这张表）",
        )
        op.create_index("idx_dom_log_item", "ark_domestic_report_logs", ["item_id", "step_order"])
        op.create_index("idx_dom_log_user_time", "ark_domestic_report_logs", ["reported_by_user_id", "reported_at"])
        op.create_index("idx_dom_log_progress", "ark_domestic_report_logs", ["progress_id", "revoked"])

    _seed_dicts()


def _seed_dicts():
    """种属性值域初值。一次性种下，之后归用户在「数据字典」页管理。

    刻意不做 bootstrap upsert——字典是用户可删数据，每次启动 upsert 会让
    删掉的选项复活。已存在同 (type,code) 则跳过。
    """
    bind = op.get_bind()
    if "sys_dict" not in _existing_tables():
        print("[081] sys_dict 不存在，跳过字典初值", flush=True)
        return
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


def downgrade():
    existing = _existing_tables()
    for table in TABLES:  # 按 FK 依赖逆序删
        if table in existing:
            op.drop_table(table)
    bind = op.get_bind()
    if "sys_dict" in existing:
        for dict_type in DICT_SEEDS:
            bind.execute(sa.text("DELETE FROM sys_dict WHERE type = :t"), {"t": dict_type})
