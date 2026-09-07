"""Separate domestic production orders and seed the four bounded process routes.

Existing orders and their progress snapshots are preserved. Route plans are
validated before schema DDL; sites without either source route only get schema.
"""

import copy
import json

from alembic import op
import sqlalchemy as sa


revision = "140_domestic_order_kinds"
down_revision = "139_expo_prompt_versions"
branch_labels = None
depends_on = None

ORDERS = "ark_domestic_orders"
ITEMS = "ark_domestic_order_items"
SOURCES = ("头套网帽（递针）", "发片网底（递针）")
KIND_FIELDS = (
    "(order_kind = 'business' AND customer_id IS NOT NULL AND order_category IS NOT NULL AND order_category IN ('normal', 'special')) OR "
    "(order_kind = 'production' AND customer_id IS NULL AND order_category IS NULL AND "
    "order_type IS NULL AND order_channel IS NULL AND required_ship_date IS NULL AND total_amount = 0 AND charged_amount = 0)"
)
PRICE_RULES = "'base_price', 'member_fixed', 'member_fixed_capped', 'member_reduction', 'manual_override', 'legacy_manual'"
ZERO_PRICE = (
    "pricing_rule <> 'production' OR (unit_price = 0 AND original_price = 0 AND "
    "discount_amount = 0 AND labor_fee = 0 AND membership_level_snapshot IS NULL AND base_price_version_snapshot = 0)"
)


def route_plans(conn):
    plans = []
    for name in SOURCES:
        source = conn.execute(sa.text(
            "SELECT id, status FROM process_route WHERE name = :name"
        ), {"name": name}).mappings().first()
        if source is None:
            continue  # Empty installations may not have configured domestic routes.
        if source["status"] != 1:
            raise RuntimeError(f"Source route is disabled: {name}")
        steps = conn.execute(sa.text(
            "SELECT s.process_id, p.name FROM process_route_step s "
            "JOIN process p ON p.id = s.process_id "
            "WHERE s.route_id = :id ORDER BY s.step_order"
        ), {"id": source["id"]}).mappings().all()
        names = [step["name"] for step in steps]
        boundaries = ("确认下单", "入库", "毛坯出库", "发货完成")
        if any(names.count(boundary) != 1 for boundary in boundaries):
            raise RuntimeError(f"Source route is missing a unique boundary: {name}")
        start, store, outbound, end = [names.index(boundary) for boundary in boundaries]
        if not start <= store < outbound <= end:
            raise RuntimeError(f"Source route boundaries are out of order: {name}")
        rules = conn.execute(sa.text(
            "SELECT process_id, rule_type, config_json FROM ark_domestic_route_rules WHERE route_id = :id"
        ), {"id": source["id"]}).mappings().all()
        for prefix, first, last in (("生产订单", start, store), ("业务普单", outbound, end)):
            target_name = f"{prefix} · {name}"
            if conn.execute(sa.text("SELECT id FROM process_route WHERE name = :name"), {"name": target_name}).first():
                raise RuntimeError(f"Target route already exists; reconcile it before migration: {target_name}")
            process_ids = [step["process_id"] for step in steps[first:last + 1]]
            kept = set(process_ids)
            cloned_rules = []
            for rule in rules:
                config = rule["config_json"]
                config = json.loads(config) if isinstance(config, str) else copy.deepcopy(config)
                targets = {
                    target for option in (config or {}).get("options", [])
                    for target in option["skip_process_ids"]
                }
                if rule["process_id"] not in kept:
                    if targets & kept:
                        raise RuntimeError(f"A decision outside the slice controls steps inside: {target_name}")
                    continue
                if config:
                    for option in config["options"]:
                        option["skip_process_ids"] = [pid for pid in option["skip_process_ids"] if pid in kept]
                cloned_rules.append({**dict(rule), "config_json": config})
            plans.append({"name": target_name, "process_ids": process_ids, "rules": cloned_rules})
    return plans


def seed_routes(conn, plans):
    routes = sa.table("process_route", sa.column("id", sa.Integer), sa.column("name", sa.String),
                      sa.column("description", sa.String), sa.column("status", sa.SmallInteger),
                      sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime))
    steps = sa.table("process_route_step", sa.column("route_id", sa.Integer),
                     sa.column("process_id", sa.Integer), sa.column("step_order", sa.SmallInteger),
                     sa.column("created_at", sa.DateTime))
    rules = sa.table("ark_domestic_route_rules", sa.column("route_id", sa.Integer),
                     sa.column("process_id", sa.Integer), sa.column("rule_type", sa.String),
                     sa.column("config_json", sa.JSON),
                     sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime))
    for plan in plans:
        conn.execute(routes.insert().values(name=plan["name"], status=1,
                                            created_at=sa.func.current_timestamp(), updated_at=sa.func.current_timestamp(),
                                            description="内贸订单大类分段路线（140 迁移），独立维护"))
        rid = conn.execute(sa.select(routes.c.id).where(routes.c.name == plan["name"])).scalar_one()
        conn.execute(steps.insert().values(created_at=sa.func.current_timestamp()), [
            {"route_id": rid, "process_id": pid, "step_order": idx}
            for idx, pid in enumerate(plan["process_ids"], start=1)
        ])
        if plan["rules"]:
            conn.execute(rules.insert().values(created_at=sa.func.current_timestamp(), updated_at=sa.func.current_timestamp()),
                         [{**rule, "route_id": rid} for rule in plan["rules"]])


def upgrade():
    conn = op.get_bind()
    plans = route_plans(conn)
    op.add_column(ORDERS, sa.Column("order_kind", sa.String(16), nullable=False, server_default="business",
                                    comment="business=业务订单,production=生产订单"))
    op.alter_column(ORDERS, "customer_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column(ORDERS, "order_category", existing_type=sa.String(16), nullable=True)
    op.create_index("idx_dom_order_kind", ORDERS, ["order_kind", "deleted_flag"])
    op.create_check_constraint("ck_dom_order_kind", ORDERS, "order_kind IN ('business', 'production')")
    op.create_check_constraint("ck_dom_order_kind_fields", ORDERS, KIND_FIELDS)
    op.drop_constraint("ck_dom_item_original_price_valid", ITEMS, type_="check")
    op.create_check_constraint("ck_dom_item_original_price_valid", ITEMS,
                               "original_price > 0 OR pricing_rule IN ('legacy_manual', 'production')")
    op.drop_constraint("ck_dom_item_pricing_rule", ITEMS, type_="check")
    op.create_check_constraint("ck_dom_item_pricing_rule", ITEMS, f"pricing_rule IN ({PRICE_RULES}, 'production')")
    op.create_check_constraint("ck_dom_item_production_price", ITEMS, ZERO_PRICE)
    seed_routes(conn, plans)


def downgrade():
    conn = op.get_bind()
    if conn.execute(sa.text(f"SELECT id FROM {ORDERS} WHERE order_kind = 'production' LIMIT 1")).first():
        raise RuntimeError("Production orders exist; preserve data and migrate forward instead")
    names = [f"{prefix} · {name}" for name in SOURCES for prefix in ("生产订单", "业务普单")]
    routes = sa.table("process_route", sa.column("id", sa.Integer), sa.column("name", sa.String))
    ids = list(conn.execute(sa.select(routes.c.id).where(routes.c.name.in_(names))).scalars())
    for table in (ITEMS, "ark_domestic_products", "product_process_route"):
        refs = sa.table(table, sa.column("route_id", sa.Integer))
        if ids and conn.execute(sa.select(refs.c.route_id).where(refs.c.route_id.in_(ids)).limit(1)).first():
            raise RuntimeError("Split routes are in use; preserve their snapshots and migrate forward")
    for table in ("ark_domestic_route_rules", "process_route_step"):
        rows = sa.table(table, sa.column("route_id", sa.Integer))
        conn.execute(rows.delete().where(rows.c.route_id.in_(ids)))
    conn.execute(routes.delete().where(routes.c.id.in_(ids)))
    op.drop_constraint("ck_dom_item_production_price", ITEMS, type_="check")
    op.drop_constraint("ck_dom_item_pricing_rule", ITEMS, type_="check")
    op.create_check_constraint("ck_dom_item_pricing_rule", ITEMS, f"pricing_rule IN ({PRICE_RULES})")
    op.drop_constraint("ck_dom_item_original_price_valid", ITEMS, type_="check")
    op.create_check_constraint("ck_dom_item_original_price_valid", ITEMS, "original_price > 0 OR pricing_rule = 'legacy_manual'")
    op.drop_constraint("ck_dom_order_kind_fields", ORDERS, type_="check")
    op.drop_constraint("ck_dom_order_kind", ORDERS, type_="check")
    op.drop_index("idx_dom_order_kind", table_name=ORDERS)
    op.alter_column(ORDERS, "customer_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column(ORDERS, "order_category", existing_type=sa.String(16), nullable=False)
    op.drop_column(ORDERS, "order_kind")
