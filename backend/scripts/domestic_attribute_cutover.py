"""Guarded replacement of domestic standard attributes and craft routes.

The command is read-only unless ``--apply`` is passed. Historical products,
orders, and order-item snapshots are reported but never updated or deleted.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.domestic import constants as C
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticOrder,
    DomesticOrderItem,
    DomesticProduct,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep
from app.system.models import SysDict


logger = logging.getLogger("commission")

STANDARD_DICTIONARIES = {
    C.DICT_CAP_CRAFT: ["递旋", "中分界", "左分界", "大U型", "递顶"],
    C.DICT_CAP_NET_COLOR: [
        "紫网全头套",
        "绿网全头套",
        "红网全头套",
        "绿网九分头",
        "黑网九分头",
        "特单网帽",
    ],
    C.DICT_CAP_SIZE: ["SS", "S", "M", "L", "XL", "51", "53", "57", "59", "取模定制"],
    C.DICT_CAP_LENGTH: [f"{length}厘米" for length in range(15, 61, 5)],
    C.DICT_CAP_DENSITY: ["65%", "80%", "90%"],
    C.DICT_CAP_HAIR_STYLE_SERIES: [
        "直发",
        "纹理",
        "卷发",
        "毛坯",
        "来图直发",
        "来图纹理",
        "来图卷发",
    ],
    C.DICT_PIECE_CRAFT_SIZE: [
        "U型13*15",
        "U型14*16",
        "U型16*18",
        "全递针9*14",
        "全递针12*14",
        "全递针13*15",
        "全递针14*16",
        "全递针15*17",
        "特单发片",
    ],
    C.DICT_PIECE_LENGTH: [f"{length}厘米" for length in range(20, 41, 5)],
    C.ORDER_TYPE_DICT: [
        ("first_order", "首单"),
        ("repurchase", "复购"),
        ("return_order", "返单"),
        ("supplementary", "补单"),
        ("after_sales_remake", "售后重做"),
    ],
    C.ORDER_CHANNEL_DICT: [
        ("wechat", "微信"),
        ("phone", "电话"),
        ("exhibition", "展会"),
        ("offline_visit", "线下拜访"),
        ("other", "其他"),
    ],
}

OBSOLETE_DICT_TYPES = (
    "domestic_net_color",
    "domestic_piece_craft",
    "domestic_piece_size",
    "domestic_length",
    "domestic_density",
)

ROUTE_BY_PRODUCT_TYPE = {
    "cap": "头套网帽（递针）",
    "piece": "发片网底（递针）",
}

CRAFT_DICT_BY_PRODUCT_TYPE = {
    "cap": C.DICT_CAP_CRAFT,
    "piece": C.DICT_PIECE_CRAFT_SIZE,
}

SPECIAL_CRAFT_DICTS = {
    "cap": (f"{C.DICT_CAP_CRAFT}_special",),
    "piece": (
        f"{C.DICT_PIECE_CRAFT_SIZE}_special",
        f"{OBSOLETE_DICT_TYPES[1]}_special",
    ),
}


class CutoverError(ValueError):
    """The domestic attribute cutover preconditions were not satisfied."""


def _standard_rows() -> list[dict]:
    rows = []
    for dict_type, values in STANDARD_DICTIONARIES.items():
        for sort, value in enumerate(values, start=1):
            code, label = value if isinstance(value, tuple) else (value, value)
            rows.append({
                "type": dict_type,
                "code": code,
                "label": label,
                "sort": sort,
                "is_active": True,
            })
    return rows


def _load_route(db: Session, name: str, *, lock: bool) -> dict:
    query = db.query(ProcessRoute).filter(ProcessRoute.name == name)
    if lock:
        query = query.with_for_update()
    route = query.one_or_none()
    if route is None:
        raise CutoverError(f"目标路线“{name}”不存在，请先创建并配置启用工序")
    if route.status != 1:
        raise CutoverError(f"目标路线“{name}”已停用，请先启用")

    steps_query = (
        db.query(ProcessRouteStep)
        .join(Process, Process.id == ProcessRouteStep.process_id)
        .filter(
            ProcessRouteStep.route_id == route.id,
            Process.status == 1,
        )
    )
    if lock:
        steps_query = steps_query.with_for_update()
    enabled_step_count = len(steps_query.all())
    if enabled_step_count == 0:
        raise CutoverError(f"目标路线“{name}”没有启用工序，请先配置并启用至少一道工序")
    return {
        "id": route.id,
        "name": route.name,
        "enabled_step_count": enabled_step_count,
    }


def _dictionary_changes(db: Session, *, lock: bool) -> dict:
    managed_types = tuple(STANDARD_DICTIONARIES)
    query = db.query(SysDict).filter(
        SysDict.type.in_((*managed_types, *OBSOLETE_DICT_TYPES))
    )
    if lock:
        query = query.with_for_update()
    existing = query.order_by(SysDict.type.asc(), SysDict.sort.asc(), SysDict.id.asc()).all()
    expected_rows = _standard_rows()
    expected_by_key = {
        (row["type"], row["code"]): row
        for row in expected_rows
    }
    exact_keys = set()
    deletions = []
    for row in existing:
        expected = expected_by_key.get((row.type, row.code))
        is_exact = expected is not None and (
            row.label == expected["label"]
            and row.sort == expected["sort"]
            and row.is_active is True
        )
        if is_exact:
            exact_keys.add((row.type, row.code))
            continue
        deletions.append({
            "id": row.id,
            "type": row.type,
            "code": row.code,
            "label": row.label,
            "sort": row.sort,
            "is_active": bool(row.is_active),
        })
    additions = [
        row
        for row in expected_rows
        if (row["type"], row["code"]) not in exact_keys
    ]
    return {"delete": deletions, "add": additions}


def _special_crafts(db: Session, *, lock: bool) -> dict[str, set[str]]:
    result = {product_type: set() for product_type in ROUTE_BY_PRODUCT_TYPE}
    for product_type, dict_types in SPECIAL_CRAFT_DICTS.items():
        query = db.query(SysDict).filter(SysDict.type.in_(dict_types))
        if lock:
            query = query.with_for_update()
        result[product_type] = {row.code for row in query.all()}
    return result


def _mapping_changes(db: Session, routes: dict, *, lock: bool) -> dict:
    query = db.query(DomesticCraftRoute).filter(
        DomesticCraftRoute.product_type.in_(ROUTE_BY_PRODUCT_TYPE)
    )
    if lock:
        query = query.with_for_update()
    existing = query.order_by(
        DomesticCraftRoute.product_type.asc(),
        DomesticCraftRoute.craft.asc(),
        DomesticCraftRoute.id.asc(),
    ).all()
    desired = {
        (product_type, craft): routes[product_type]["id"]
        for product_type, dict_type in CRAFT_DICT_BY_PRODUCT_TYPE.items()
        for craft in STANDARD_DICTIONARIES[dict_type]
    }
    special_crafts = _special_crafts(db, lock=lock)
    exact_pairs = set()
    deletions = []
    for row in existing:
        pair = (row.product_type, row.craft)
        is_exact_standard = (
            desired.get(pair) == row.route_id
            and row.updated_by is None
        )
        if is_exact_standard:
            exact_pairs.add(pair)
            continue
        is_custom_special = (
            row.craft in special_crafts[row.product_type]
            and pair not in desired
        )
        if is_custom_special:
            continue
        deletions.append({
            "id": row.id,
            "product_type": row.product_type,
            "craft": row.craft,
            "route_id": row.route_id,
        })
    additions = [
        {
            "product_type": product_type,
            "craft": craft,
            "route_id": routes[product_type]["id"],
            "route_name": routes[product_type]["name"],
        }
        for product_type, dict_type in CRAFT_DICT_BY_PRODUCT_TYPE.items()
        for craft in STANDARD_DICTIONARIES[dict_type]
        if (product_type, craft) not in exact_pairs
    ]
    return {"delete": deletions, "add": additions}


def _history_counts(db: Session) -> dict:
    return {
        "products": db.query(DomesticProduct).count(),
        "orders": db.query(DomesticOrder).count(),
        "order_items": db.query(DomesticOrderItem).count(),
        "product_route_id": True,
        "order_item_attrs_snapshot": True,
        "order_item_route_id": True,
        "orders_deleted": False,
    }


def build_plan(db: Session, *, lock: bool = False) -> dict:
    routes = {
        product_type: _load_route(db, route_name, lock=lock)
        for product_type, route_name in ROUTE_BY_PRODUCT_TYPE.items()
    }
    if len({route["id"] for route in routes.values()}) != len(routes):
        raise CutoverError("头套与发片必须绑定两条不同路线")
    return {
        "mode": "preflight",
        "routes": routes,
        "dictionary_changes": _dictionary_changes(db, lock=lock),
        "mapping_changes": _mapping_changes(db, routes, lock=lock),
        "history_unchanged": _history_counts(db),
    }


def _replace_standard_dictionaries(db: Session, changes: dict) -> None:
    delete_ids = [row["id"] for row in changes["delete"]]
    if delete_ids:
        db.query(SysDict).filter(SysDict.id.in_(delete_ids)).delete(
            synchronize_session=False
        )
        db.flush()
    db.add_all([
        SysDict(
            type=row["type"],
            code=row["code"],
            label=row["label"],
            sort=row["sort"],
            is_active=row["is_active"],
        )
        for row in changes["add"]
    ])
    db.flush()


def _replace_standard_mappings(db: Session, changes: dict) -> None:
    delete_ids = [row["id"] for row in changes["delete"]]
    if delete_ids:
        db.query(DomesticCraftRoute).filter(DomesticCraftRoute.id.in_(delete_ids)).delete(
            synchronize_session=False
        )
        db.flush()
    db.add_all([
        DomesticCraftRoute(
            product_type=row["product_type"],
            craft=row["craft"],
            route_id=row["route_id"],
            updated_by=None,
        )
        for row in changes["add"]
    ])
    db.flush()


def apply_cutover(db: Session) -> dict:
    db.rollback()
    try:
        plan = build_plan(db, lock=True)
        _replace_standard_dictionaries(db, plan["dictionary_changes"])
        _replace_standard_mappings(db, plan["mapping_changes"])
        verification = build_plan(db, lock=True)
        if verification["dictionary_changes"]["delete"] or verification["dictionary_changes"]["add"]:
            raise CutoverError("标准字典替换后校验失败")
        if verification["mapping_changes"]["delete"] or verification["mapping_changes"]["add"]:
            raise CutoverError("标准工艺路线映射替换后校验失败")
        if verification["history_unchanged"] != plan["history_unchanged"]:
            raise CutoverError("历史产品、订单或明细数量发生变化，已拒绝提交")
        result = {
            "mode": "applied",
            "routes": plan["routes"],
            "dictionary_changes": {
                "deleted": len(plan["dictionary_changes"]["delete"]),
                "added": len(plan["dictionary_changes"]["add"]),
            },
            "mapping_changes": {
                "deleted": len(plan["mapping_changes"]["delete"]),
                "added": len(plan["mapping_changes"]["add"]),
            },
            "history_unchanged": verification["history_unchanged"],
        }
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        logger.warning("domestic attribute cutover failed: %s", exc, exc_info=True)
        print(f"[domestic_attribute_cutover] failed: {exc}", file=sys.stderr, flush=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="内贸标准属性与工艺路线切换（默认只读预检）")
    parser.add_argument("--apply", action="store_true", help="执行切换；省略即只打印预检计划")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        result = apply_cutover(db) if args.apply else build_plan(db)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        db.rollback()
        logger.warning("domestic attribute cutover command failed: %s", exc, exc_info=True)
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
