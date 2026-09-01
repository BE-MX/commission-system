"""Directly switch domestic products to their product-type routes.

Every cap craft/product is bound to ``头套网帽`` and every piece craft/product
to ``发片网底``. Existing order items keep their route snapshots unchanged.
Dry-run is the default; apply requires a domestic-write maintenance window.
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.database import SessionLocal
from app.domestic import constants as C, route_rule_service
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticOrderItem,
    DomesticProduct,
    DomesticRouteRule,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep, UserProcessBinding
from app.system.models import SysDict


ROUTE_BY_PRODUCT_TYPE = {"cap": "头套网帽", "piece": "发片网底"}
CRAFT_DICT_BY_PRODUCT_TYPE = {
    "cap": C.DICT_CAP_CRAFT,
    "piece": C.DICT_PIECE_CRAFT,
}
REQUIRED_CAP_RULES = {
    "发加工点": {
        "rule_type": "decision",
        "options": {
            "dandong": {"李晓宏手钩", "李晓宏递针"},
            "lixiaohong": {"丹东收货", "丹东发货"},
        },
    },
    "李晓宏手钩": {
        "rule_type": "decision",
        "options": {
            "needle": set(),
            "no_needle": {"李晓宏递针"},
        },
    },
    "毛坯质检": {
        "rule_type": "decision",
        "options": {
            "qualified": {"毛坯维修"},
            "repair": set(),
        },
    },
    "后处理定型": {"rule_type": "optional", "options": None},
}
WRITE_FREEZE_CONFIRMATION = "DOMESTIC_WRITES_STOPPED"


class CutoverError(ValueError):
    """The direct-switch preconditions were not satisfied."""


def confirm_writes_stopped(value: str | None) -> None:
    if value != WRITE_FREEZE_CONFIRMATION:
        raise CutoverError(
            "--apply 前必须停止内贸写入并等待在途事务排空，然后精确传入 "
            f"--confirm-writes-stopped {WRITE_FREEZE_CONFIRMATION}"
        )


def _load_route(db: Session, name: str, *, lock: bool) -> ProcessRoute:
    query = db.query(ProcessRoute).filter(ProcessRoute.name == name)
    if lock:
        query = query.with_for_update()
    exact = [row for row in query.all() if row.name == name]
    if not exact:
        raise CutoverError(f"目标路线“{name}”不存在")
    if len(exact) != 1:
        raise CutoverError(f"目标路线“{name}”匹配到多条记录，拒绝切换")
    route = exact[0]
    if route.status != 1:
        raise CutoverError(f"目标路线“{name}”已停用")
    return route


def _route_details(
    db: Session,
    route: ProcessRoute,
    *,
    product_type: str,
    lock: bool,
) -> dict:
    steps_query = (
        db.query(ProcessRouteStep, Process)
        .join(Process, Process.id == ProcessRouteStep.process_id)
        .filter(ProcessRouteStep.route_id == route.id)
        .order_by(ProcessRouteStep.step_order.asc())
    )
    if lock:
        steps_query = steps_query.with_for_update()
    steps = steps_query.all()
    if not steps:
        raise CutoverError(f"目标路线“{route.name}”没有工序")
    disabled = [process.name for _step, process in steps if process.status != 1]
    if disabled:
        raise CutoverError(f"目标路线“{route.name}”含停用工序：{'、'.join(disabled)}")

    process_ids = [step.process_id for step, _process in steps]
    covered_process_ids = {
        process_id
        for (process_id,) in (
            db.query(UserProcessBinding.process_id)
            .join(ArkUser, ArkUser.id == UserProcessBinding.user_id)
            .filter(
                UserProcessBinding.process_id.in_(process_ids),
                ArkUser.is_active.is_(True),
                ArkUser.deleted_at.is_(None),
            )
            .distinct()
            .all()
        )
    }
    missing_workers = [
        process.name
        for step, process in steps
        if step.process_id not in covered_process_ids
    ]
    if missing_workers:
        raise CutoverError(
            f"目标路线“{route.name}”工序未绑定在职人员：{'、'.join(missing_workers)}"
        )

    rules_query = (
        db.query(DomesticRouteRule)
        .filter(DomesticRouteRule.route_id == route.id)
        .order_by(DomesticRouteRule.process_id.asc())
    )
    if lock:
        rules_query = rules_query.with_for_update()
    rules = rules_query.all()
    rule_payload = [
        {
            "process_id": rule.process_id,
            "rule_type": rule.rule_type,
            "config": rule.config_json,
        }
        for rule in rules
    ]
    if rule_payload:
        try:
            route_rule_service.validate_rules(db, route.id, rule_payload)
        except (TypeError, KeyError, ValueError) as exc:
            raise CutoverError(f"目标路线“{route.name}”规则校验失败：{exc}") from exc

    if product_type == "cap":
        process_ids_by_name: dict[str, list[int]] = {}
        process_name_by_id = {}
        for step, process in steps:
            process_ids_by_name.setdefault(process.name, []).append(step.process_id)
            process_name_by_id[step.process_id] = process.name
        rules_by_process_id = {rule.process_id: rule for rule in rules}
        errors = []
        required_rule_process_ids = set()
        for process_name, required in REQUIRED_CAP_RULES.items():
            process_ids_for_name = process_ids_by_name.get(process_name, [])
            if len(process_ids_for_name) != 1:
                errors.append(f"{process_name}=缺少或重名")
                continue
            process_id = process_ids_for_name[0]
            required_rule_process_ids.add(process_id)
            rule = rules_by_process_id.get(process_id)
            actual_rule_type = rule.rule_type if rule else None
            required_rule_type = required["rule_type"]
            if actual_rule_type != required_rule_type:
                errors.append(
                    f"{process_name}={actual_rule_type or '未配置'}，应为{required_rule_type}"
                )
                continue
            expected_options = required["options"]
            if expected_options is not None:
                options = (rule.config_json or {}).get("options", [])
                actual_options = {
                    option.get("code"): {
                        process_name_by_id.get(process_id, f"#{process_id}")
                        for process_id in option.get("skip_process_ids", [])
                    }
                    for option in options
                }
                if actual_options != expected_options:
                    errors.append(f"{process_name}=结果编码或跳过目标与业务路线不一致")
        configured_rule_process_ids = set(rules_by_process_id)
        if configured_rule_process_ids != required_rule_process_ids:
            extra_names = sorted(
                process_name_by_id.get(process_id, f"#{process_id}")
                for process_id in configured_rule_process_ids - required_rule_process_ids
            )
            if extra_names:
                errors.append(f"存在未批准的额外条件规则：{'、'.join(extra_names)}")
        if errors:
            raise CutoverError(
                f"目标路线“{route.name}”缺少头套必需条件规则：{'；'.join(errors)}"
            )

    return {
        "id": route.id,
        "name": route.name,
        "step_count": len(steps),
        "rule_count": len(rules),
    }


def _count_by_product_type(db: Session, model) -> dict[str, int]:
    return {
        product_type: int(count)
        for product_type, count in (
            db.query(model.product_type, func.count(model.id))
            .filter(model.product_type.in_(ROUTE_BY_PRODUCT_TYPE))
            .group_by(model.product_type)
            .all()
        )
    }


def _active_crafts(db: Session, *, lock: bool) -> dict[str, list[str]]:
    query = db.query(SysDict).filter(
        SysDict.type.in_(CRAFT_DICT_BY_PRODUCT_TYPE.values()),
        SysDict.is_active.is_(True),
    )
    if lock:
        query = query.with_for_update()
    rows = query.order_by(SysDict.type.asc(), SysDict.sort.asc(), SysDict.id.asc()).all()
    by_dict_type: dict[str, list[str]] = {
        dict_type: [] for dict_type in CRAFT_DICT_BY_PRODUCT_TYPE.values()
    }
    for row in rows:
        by_dict_type[row.type].append(row.code)
    result = {
        product_type: by_dict_type[dict_type]
        for product_type, dict_type in CRAFT_DICT_BY_PRODUCT_TYPE.items()
    }
    empty = [product_type for product_type, crafts in result.items() if not crafts]
    if empty:
        raise CutoverError(f"以下产品类型没有启用的工艺字典项：{'、'.join(empty)}")
    return result


def build_plan(db: Session, *, lock: bool = False) -> dict:
    routes = {}
    route_ids = {}
    for product_type, route_name in ROUTE_BY_PRODUCT_TYPE.items():
        route = _load_route(db, route_name, lock=lock)
        routes[product_type] = _route_details(
            db,
            route,
            product_type=product_type,
            lock=lock,
        )
        route_ids[product_type] = route.id
    if len(set(route_ids.values())) != len(route_ids):
        raise CutoverError("头套与发片必须绑定两条不同路线")

    mappings_query = db.query(DomesticCraftRoute).filter(
        DomesticCraftRoute.product_type.in_(ROUTE_BY_PRODUCT_TYPE)
    )
    products_query = db.query(DomesticProduct).filter(
        DomesticProduct.product_type.in_(ROUTE_BY_PRODUCT_TYPE)
    )
    if lock:
        mappings_query.with_for_update().all()
        products_query.with_for_update().all()

    active_crafts = _active_crafts(db, lock=lock)
    existing_mapping_pairs = {
        (product_type, craft)
        for product_type, craft in db.query(
            DomesticCraftRoute.product_type,
            DomesticCraftRoute.craft,
        ).filter(DomesticCraftRoute.product_type.in_(ROUTE_BY_PRODUCT_TYPE)).all()
    }
    missing_mappings = {
        product_type: [
            craft
            for craft in crafts
            if (product_type, craft) not in existing_mapping_pairs
        ]
        for product_type, crafts in active_crafts.items()
    }
    mapping_counts = _count_by_product_type(db, DomesticCraftRoute)
    product_counts = _count_by_product_type(db, DomesticProduct)
    item_counts = {
        product_type: int(count)
        for product_type, count in (
            db.query(DomesticProduct.product_type, func.count(DomesticOrderItem.id))
            .join(DomesticOrderItem, DomesticOrderItem.product_id == DomesticProduct.id)
            .filter(DomesticProduct.product_type.in_(ROUTE_BY_PRODUCT_TYPE))
            .group_by(DomesticProduct.product_type)
            .all()
        )
    }
    return {
        "mode": "apply-preflight" if lock else "dry-run",
        "routes": routes,
        "active_crafts": active_crafts,
        "missing_mappings_to_create": missing_mappings,
        "mapping_counts": {
            product_type: mapping_counts.get(product_type, 0)
            for product_type in ROUTE_BY_PRODUCT_TYPE
        },
        "product_counts": {
            product_type: product_counts.get(product_type, 0)
            for product_type in ROUTE_BY_PRODUCT_TYPE
        },
        "existing_order_items_unchanged": {
            product_type: item_counts.get(product_type, 0)
            for product_type in ROUTE_BY_PRODUCT_TYPE
        },
    }


def apply_cutover(db: Session, *, writes_stopped: bool) -> dict:
    if writes_stopped is not True:
        raise CutoverError("apply 前必须停止内贸写入并等待在途事务排空")
    db.rollback()
    try:
        plan = build_plan(db, lock=True)
        updated_mappings = {}
        created_mappings = {}
        updated_products = {}
        for product_type, route in plan["routes"].items():
            route_id = route["id"]
            missing_crafts = plan["missing_mappings_to_create"][product_type]
            db.add_all([
                DomesticCraftRoute(
                    product_type=product_type,
                    craft=craft,
                    route_id=route_id,
                    updated_by=None,
                )
                for craft in missing_crafts
            ])
            db.flush()
            created_mappings[product_type] = len(missing_crafts)
            updated_mappings[product_type] = (
                db.query(DomesticCraftRoute)
                .filter(DomesticCraftRoute.product_type == product_type)
                .update(
                    {
                        DomesticCraftRoute.route_id: route_id,
                        DomesticCraftRoute.updated_by: None,
                    },
                    synchronize_session=False,
                )
            )
            updated_products[product_type] = (
                db.query(DomesticProduct)
                .filter(DomesticProduct.product_type == product_type)
                .update({DomesticProduct.route_id: route_id}, synchronize_session=False)
            )
        db.flush()

        for product_type, route in plan["routes"].items():
            wrong_mapping_count = (
                db.query(DomesticCraftRoute)
                .filter(
                    DomesticCraftRoute.product_type == product_type,
                    or_(
                        DomesticCraftRoute.route_id.is_(None),
                        DomesticCraftRoute.route_id != route["id"],
                    ),
                )
                .count()
            )
            wrong_product_count = (
                db.query(DomesticProduct)
                .filter(
                    DomesticProduct.product_type == product_type,
                    or_(
                        DomesticProduct.route_id.is_(None),
                        DomesticProduct.route_id != route["id"],
                    ),
                )
                .count()
            )
            if wrong_mapping_count or wrong_product_count:
                raise CutoverError(
                    f"{product_type} 路线切换校验失败："
                    f"mapping={wrong_mapping_count}, product={wrong_product_count}"
                )
            mapped_crafts = {
                craft
                for (craft,) in db.query(DomesticCraftRoute.craft).filter(
                    DomesticCraftRoute.product_type == product_type,
                    DomesticCraftRoute.craft.in_(plan["active_crafts"][product_type]),
                ).all()
            }
            if mapped_crafts != set(plan["active_crafts"][product_type]):
                raise CutoverError(f"{product_type} 启用工艺映射未完整建立")

        result = {
            "mode": "applied",
            "routes": plan["routes"],
            "created_mapping_counts": created_mappings,
            "updated_mapping_counts": updated_mappings,
            "updated_product_counts": updated_products,
            "existing_order_items_unchanged": plan["existing_order_items_unchanged"],
        }
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="内贸两类产品路线直接切换（默认只读预检）")
    parser.add_argument("--apply", action="store_true", help="执行切换；省略即只读预检")
    parser.add_argument(
        "--confirm-writes-stopped",
        help=f"apply 强制停写确认；必须精确输入 {WRITE_FREEZE_CONFIRMATION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        if args.apply:
            confirm_writes_stopped(args.confirm_writes_stopped)
            result = apply_cutover(db, writes_stopped=True)
        else:
            result = build_plan(db)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except CutoverError as exc:
        db.rollback()
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
