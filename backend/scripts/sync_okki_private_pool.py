"""
OKKI 私海客户回填：把业务库（OKKI 镜像）里某业务员的私海客户及其订单
经统一客户域受治理投影管线写入方舟，并建立私海归属。

背景：统一客户域（ark_customer_*）此前只有获客调研客户；OKKI 客户/订单的
正式同步适配器尚未建设。本脚本只做"业务库已落地镜像 → 投影管线"这一段，
不直接访问 OKKI API，范围限定单个业务员的私海客户，供私海背调使用。

投影口径：
- 客户：project_okki_customer（okki_customer_v1），payload 只放 company_id /
  company_name / updated_at 三个键，保证幂等重放干净。
- 订单：project_okki_order（okki_order_v1），有效性判定沿用
  order_intelligence.is_valid_business_order；明细 item_type 无可靠来源，统一
  unknown。
- 归属：workflow_service.assign_customer（source=import），与提案执行器同一入口。
- 之后逐客户 compile_customer_profile，生成列表投影与目标画像匹配分。

注意：OKKI_ACCOUNT_KEY 是统一域里 OKKI 租户的命名空间常量，未来正式 OKKI
同步必须复用同一值，否则同一公司会因命名空间不同而重复建档。

执行方式：
  cd backend
  python -m scripts.sync_okki_private_pool --owner Sylvia --operator admin [--limit 5] [--dry-run]
  python -m scripts.sync_okki_private_pool --owner Sylvia --operator admin --create-research-tasks
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.core.database import SessionLocal
from app.core.config import get_settings
from app.customer.profile_service import compile_customer_profile
from app.customer.projection_common import ProjectionRetryRequired
from app.customer.projection_service import project_okki_customer, project_okki_order
from app.customer.workflow_service import CustomerWorkflowError, assign_customer
from app.sales_automation import private_research_service

OKKI_ACCOUNT_KEY = "leshine-okki"


def _business_schema() -> str:
    return get_settings().BUSINESS_DB_NAME


def _active_user(db, username: str) -> ArkUser:
    user = db.query(ArkUser).filter(ArkUser.username == username).one_or_none()
    if user is None or not user.is_active or user.deleted_at is not None:
        raise SystemExit(f"用户不存在或已停用: {username}")
    return user


def _resolve_okki_owner(db, username: str) -> tuple[ArkUser, str]:
    user = _active_user(db, username)
    binding = db.query(ArkUserExternalBinding).filter(
        ArkUserExternalBinding.ark_user_id == user.id,
        ArkUserExternalBinding.provider == "okki",
        ArkUserExternalBinding.binding_status == "active",
        ArkUserExternalBinding.deleted_at.is_(None),
    ).one_or_none()
    if binding is None:
        raise SystemExit(f"用户 {username} 没有启用的 OKKI 外部账号绑定")
    return user, str(binding.external_account_id)


def _owned_customers(db, okki_user_id: str, limit: int | None) -> list[dict]:
    numeric_owner = str(int(okki_user_id))
    sql = text(
        f"SELECT company_id, company_name, update_time "
        f"FROM `{_business_schema()}`.customer_info "
        f"WHERE (JSON_CONTAINS(owner_user_ids, :numeric_owner) "
        f"OR JSON_CONTAINS(owner_user_ids, :string_owner)) "
        f"ORDER BY company_id"
        + (" LIMIT :limit" if limit else "")
    )
    params = {"numeric_owner": numeric_owner, "string_owner": json.dumps(numeric_owner)}
    if limit:
        params["limit"] = int(limit)
    return [
        {"company_id": str(row.company_id), "company_name": row.company_name,
         "update_time": row.update_time}
        for row in db.execute(sql, params)
    ]


def _order_payloads(db, company_id: str) -> list[dict]:
    schema = _business_schema()
    columns = db.execute(text(f"SHOW COLUMNS FROM `{schema}`.`okki_orders`")).mappings().all()
    name_expr = "o.name" if any(row["Field"] == "name" for row in columns) else "NULL"
    from app.order_intelligence.service import RESOURCE_SOURCE_FIELD, classify_source
    source_expr = (
        f"COALESCE(NULLIF(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(o.custom_fields, "
        f"'$.\\\"{RESOURCE_SOURCE_FIELD}\\\"')), ''), 'null'), ci.origin_name, '')"
    )
    orders = db.execute(text(
        f"SELECT o.order_id, o.order_no, {name_expr} AS name, o.status, o.status_name, o.trail, "
        f"o.account_date, o.amount_usd, o.user_id, {source_expr} AS source_raw "
        f"FROM `{schema}`.okki_orders o "
        f"LEFT JOIN `{schema}`.customer_info ci ON ci.company_id = o.company_id "
        f"WHERE o.company_id = :cid ORDER BY o.order_id"
    ), {"cid": company_id}).all()
    items = db.execute(text(
        f"SELECT id, order_id, product_id, sku_id, product_name, product_model, "
        f"quantity, unit_price, amount, unit "
        f"FROM `{schema}`.okki_order_items WHERE order_id IN "
        f"(SELECT order_id FROM `{schema}`.okki_orders WHERE company_id = :cid) "
        f"ORDER BY id"
    ), {"cid": company_id}).all()
    items_by_order: dict[str, list] = {}
    for item in items:
        items_by_order.setdefault(str(item.order_id), []).append({
            "item_id": str(item.id),
            "product_id": str(item.product_id) if item.product_id is not None else None,
            "sku_id": str(item.sku_id) if item.sku_id is not None else None,
            "product_name": item.product_name,
            "model": item.product_model,
            "quantity": str(item.quantity) if item.quantity is not None else None,
            "quantity_unit": item.unit,
            "unit_price": str(item.unit_price) if item.unit_price is not None else None,
            "line_amount": str(item.amount) if item.amount is not None else None,
            "item_type": "unknown",
        })
    return [
        {
            "order_id": str(order.order_id),
            "company_id": company_id,
            "order_no": order.order_no,
            "order_name": order.name,
            "status": str(order.status) if order.status is not None else None,
            "status_name": order.status_name,
            "trail": order.trail,
            "account_date": order.account_date.isoformat() if order.account_date else None,
            "amount_usd": str(order.amount_usd) if order.amount_usd is not None else None,
            "owner_external_user_id": str(order.user_id) if order.user_id is not None else None,
            "source_category": classify_source(order.source_raw),
            "item_snapshot_mode": "full",
            "items": items_by_order.get(str(order.order_id), []),
        }
        for order in orders
    ]


def _sync_one_customer(db, row: dict, *, owner: ArkUser, operator: ArkUser,
                       with_orders: bool) -> dict:
    payload = {"company_id": row["company_id"]}
    if row["company_name"]:
        payload["company_name"] = row["company_name"]
    if row["update_time"]:
        payload["updated_at"] = row["update_time"].isoformat()
    receipt = project_okki_customer(db, source_account_key=OKKI_ACCOUNT_KEY, payload=payload)
    result = {
        "company_id": row["company_id"],
        "customer_id": receipt.customer_id,
        "customer_outcome": (
            receipt.outcome if receipt.customer_id is not None
            else f"quarantined:{receipt.error_code}"
        ),
        "assigned": False,
        "orders": {"processed": 0, "quarantined": 0},
    }
    if receipt.customer_id is None:
        return result
    try:
        assign_customer(
            db,
            customer_id=receipt.customer_id,
            user_id=owner.id,
            assignment_role="primary",
            assignment_source="import",
            operated_by=operator.id,
            change_reason="OKKI私海归属回填",
        )
        result["assigned"] = True
    except CustomerWorkflowError as exc:
        result["assign_error"] = str(exc)
    if with_orders:
        for order_payload in _order_payloads(db, row["company_id"]):
            order_receipt = project_okki_order(
                db, source_account_key=OKKI_ACCOUNT_KEY, payload=order_payload,
            )
            key = "processed" if order_receipt.status == "processed" else "quarantined"
            result["orders"][key] += 1
    return result


def sync_owner(db, *, owner: ArkUser, okki_user_id: str, operator: ArkUser,
               limit: int | None, dry_run: bool, with_orders: bool,
               with_profile: bool, create_research_tasks: bool) -> dict:
    customers = _owned_customers(db, okki_user_id, limit)
    summary = {
        "owner": {"id": owner.id, "username": owner.username, "okki_user_id": okki_user_id},
        "dry_run": dry_run,
        "customer_count": len(customers),
        "results": [],
        "errors": [],
        "profiles_compiled": 0,
    }
    if dry_run:
        schema = _business_schema()
        for row in customers:
            orders = db.execute(text(
                f"SELECT COUNT(*) FROM `{schema}`.okki_orders WHERE company_id = :cid"
            ), {"cid": row["company_id"]}).scalar()
            summary["results"].append({
                "company_id": row["company_id"], "company_name": row["company_name"],
                "order_count": orders,
            })
        return summary
    for row in customers:
        last_error = None
        for _attempt in (1, 2):
            try:
                result = _sync_one_customer(db, row, owner=owner, operator=operator,
                                            with_orders=with_orders)
                db.commit()
                last_error = None
                break
            except ProjectionRetryRequired:
                last_error = "retry_exhausted"
            except Exception as exc:  # noqa: BLE001 - 单客户失败不阻断整批
                db.rollback()
                last_error = f"{type(exc).__name__}: {exc}"
                break
        if last_error:
            summary["errors"].append({"company_id": row["company_id"], "error": last_error})
            continue
        summary["results"].append(result)
        if with_profile and result.get("customer_id"):
            try:
                compile_customer_profile(SessionLocal, int(result["customer_id"]))
                summary["profiles_compiled"] += 1
            except Exception as exc:  # noqa: BLE001 - 编译失败不影响投影结果
                summary["errors"].append({
                    "company_id": row["company_id"], "error": f"profile_compile: {exc}",
                })
    if create_research_tasks:
        imported_ids = [int(row["customer_id"]) for row in summary["results"]
                        if row.get("customer_id") is not None]
        summary["research"] = private_research_service.create_private_research_tasks(
            db,
            owner_ids=[owner.id],
            customer_ids=imported_ids,
            run_tag=f"private-research-{owner.username}",
            operator_id=operator.id,
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="OKKI 私海客户回填进统一客户域")
    parser.add_argument("--owner", required=True, help="业务员登录用户名（需有 OKKI 绑定）")
    parser.add_argument("--operator", required=True, help="操作人用户名（归属变更记录的操作者）")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个客户（试跑用）")
    parser.add_argument("--dry-run", action="store_true", help="只列出将处理的客户与订单数，不写入")
    parser.add_argument("--skip-orders", action="store_true", help="只投影客户，不带订单")
    parser.add_argument("--skip-profile", action="store_true", help="跳过档案编译")
    parser.add_argument("--create-research-tasks", action="store_true",
                        help="回填完成后直接为该业务员的私海客户创建 full_research 背调任务")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer")

    db = SessionLocal()
    try:
        owner, okki_user_id = _resolve_okki_owner(db, args.owner)
        operator = _active_user(db, args.operator)
        summary = sync_owner(
            db,
            owner=owner,
            okki_user_id=okki_user_id,
            operator=operator,
            limit=args.limit,
            dry_run=args.dry_run,
            with_orders=not args.skip_orders,
            with_profile=not args.skip_profile,
            create_research_tasks=args.create_research_tasks,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
