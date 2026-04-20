"""回款增量同步 + 客户归属校验服务"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rule_config import build_batch_order_match_query
from app.models.commission import SyncedPayment
from app.models.customer import CustomerCommissionSnapshot
from app.models.employee import EmployeeAttributeHistory, SupervisorRelationHistory
from app.services.rate_utils import calc_commission_rates, to_date

logger = logging.getLogger("commission.sync")

BATCH_CHUNK = 500


@dataclass
class SyncResult:
    """回款同步结果"""
    total_payments: int = 0
    new_synced: int = 0
    already_synced: int = 0
    customers_checked: int = 0
    snapshots_auto_created: int = 0
    snapshots_incomplete: int = 0
    incomplete_customers: list = field(default_factory=list)


def _batch_query_in(db: Session, model_cls, field, values, extra_filters=None):
    """通用分批 IN 查询，避免单次 IN 子句过大"""
    results = []
    vals = list(values)
    for i in range(0, len(vals), BATCH_CHUNK):
        chunk = vals[i:i + BATCH_CHUNK]
        q = db.query(model_cls).filter(field.in_(chunk))
        if extra_filters:
            for f in extra_filters:
                q = q.filter(f)
        results.extend(q.all())
    return results


def _batch_get_employee_attributes(db: Session, employee_ids: set[str]) -> dict[str, str]:
    """批量查询员工当前属性"""
    rows = _batch_query_in(
        db, EmployeeAttributeHistory, EmployeeAttributeHistory.employee_id,
        employee_ids, [EmployeeAttributeHistory.is_current == True]
    )
    return {r.employee_id: r.attribute_type for r in rows}


def _batch_get_supervisor_ids(db: Session, salesperson_ids: set[str]) -> dict[str, str]:
    """批量查询业务员当前主管"""
    rows = _batch_query_in(
        db, SupervisorRelationHistory, SupervisorRelationHistory.salesperson_id,
        salesperson_ids, [SupervisorRelationHistory.is_current == True]
    )
    return {r.salesperson_id: r.supervisor_id for r in rows}


def _batch_find_matching_orders(db: Session, customer_ids: list[str]) -> dict[str, dict]:
    """批量按配置规则查找匹配订单（每个客户取首条）"""
    if not customer_ids:
        return {}
    result_map = {}
    for i in range(0, len(customer_ids), BATCH_CHUNK):
        chunk = customer_ids[i:i + BATCH_CHUNK]
        sql = build_batch_order_match_query(chunk)
        rows = db.execute(text(sql)).mappings().all()
        for row in rows:
            cid = str(row["company_id"])
            if cid not in result_map:
                result_map[cid] = dict(row)
    return result_map


def _get_order_by_id(db: Session, order_id: str) -> Optional[dict]:
    """从业务库按 order_id 查询订单"""
    settings = get_settings()
    schema = settings.BUSINESS_DB_NAME
    sql = f"SELECT * FROM `{schema}`.`okki_orders` WHERE `order_id` = :oid LIMIT 1"
    result = db.execute(text(sql), {"oid": order_id}).mappings().first()
    if result:
        return dict(result)
    return None


def _batch_get_orders_by_ids(db: Session, order_ids: list[str]) -> dict[str, dict]:
    """批量从业务库查询订单"""
    if not order_ids:
        return {}
    settings = get_settings()
    schema = settings.BUSINESS_DB_NAME
    result_map = {}
    unique_ids = list(set(order_ids))
    for i in range(0, len(unique_ids), BATCH_CHUNK):
        chunk = unique_ids[i:i + BATCH_CHUNK]
        placeholders = ", ".join(f"'{oid}'" for oid in chunk)
        sql = f"SELECT * FROM `{schema}`.`okki_orders` WHERE `order_id` IN ({placeholders})"
        rows = db.execute(text(sql)).mappings().all()
        for row in rows:
            result_map[str(row["order_id"])] = dict(row)
    return result_map


def sync_payments(db: Session, date_start: date, date_end: date) -> SyncResult:
    """
    回款增量同步 + 客户归属校验（批量优化版）。

    从业务库拉取指定日期范围的回款，增量同步到 synced_payment，
    并为没有归属快照的客户尝试自动生成。
    """
    result = SyncResult()
    settings = get_settings()
    schema = settings.BUSINESS_DB_NAME

    # ---- Step 1: 从业务库拉取回款 ----
    sql = (
        f"SELECT cash_collection_id, cash_collection_no, collection_date, "
        f"amount_usd, order_id, company_id, order_no, company_name "
        f"FROM `{schema}`.`okki_receipts` "
        f"WHERE `collection_date` >= :ds AND `collection_date` <= :de"
    )
    rows = db.execute(text(sql), {"ds": date_start, "de": date_end}).mappings().all()
    result.total_payments = len(rows)
    logger.info(f"查询到 {len(rows)} 条回款 ({date_start} ~ {date_end})")

    # ---- Step 2: 批量查询已同步的 payment_id ----
    all_pids = [str(row["cash_collection_id"]) for row in rows]
    existing_pids = set()
    for i in range(0, len(all_pids), BATCH_CHUNK):
        chunk = all_pids[i:i + BATCH_CHUNK]
        existing = db.query(SyncedPayment.payment_id).filter(
            SyncedPayment.payment_id.in_(chunk)
        ).all()
        existing_pids.update(r.payment_id for r in existing)

    # ---- Step 3: 批量写入（高延迟远程库优化）----
    customer_ids_this_batch: dict[str, list[str]] = {}
    new_payments = []

    for row in rows:
        pid = str(row["cash_collection_id"])
        if pid in existing_pids:
            result.already_synced += 1
            continue

        new_payments.append({
            "payment_id": pid,
            "order_id": str(row["order_id"]),
            "customer_id": str(row["company_id"]),
            "payment_date": to_date(row["collection_date"]),
            "payment_amount": Decimal(str(row["amount_usd"])),
        })
        result.new_synced += 1

        cid = str(row["company_id"])
        customer_ids_this_batch.setdefault(cid, []).append(str(row["order_id"]))

    if new_payments:
        db.execute(SyncedPayment.__table__.insert(), new_payments)
        db.flush()
    logger.info(f"新增同步 {result.new_synced} 条，跳过已同步 {result.already_synced} 条")

    # ---- Step 4: 批量查询已有归属快照 ----
    unique_customers = set(customer_ids_this_batch.keys())
    result.customers_checked = len(unique_customers)

    existing_snapshot_cids = set()
    cid_list = list(unique_customers)
    for i in range(0, len(cid_list), BATCH_CHUNK):
        chunk = cid_list[i:i + BATCH_CHUNK]
        snaps = db.query(CustomerCommissionSnapshot.customer_id).filter(
            CustomerCommissionSnapshot.customer_id.in_(chunk),
            CustomerCommissionSnapshot.is_current == True,
        ).all()
        existing_snapshot_cids.update(r.customer_id for r in snaps)

    customers_needing_snapshot = list(unique_customers - existing_snapshot_cids)
    if not customers_needing_snapshot:
        logger.info("所有客户均已有归属快照，无需生成")
        return result

    logger.info(f"{len(customers_needing_snapshot)} 个客户需要生成归属快照")

    # ---- Step 5: 批量订单匹配 ----
    matched_orders = _batch_find_matching_orders(db, customers_needing_snapshot)
    logger.info(f"批量订单匹配完成：{len(matched_orders)} 个客户匹配到订单")

    # 收集所有需要查询属性的员工 ID
    # 先批量预加载所有 fallback 订单
    unmatched_cids = [cid for cid in customers_needing_snapshot if cid not in matched_orders]
    all_fallback_oids = []
    for cid in unmatched_cids:
        all_fallback_oids.extend(customer_ids_this_batch.get(cid, []))
    fallback_orders_map = _batch_get_orders_by_ids(db, all_fallback_oids)

    # 建立 customer_id → fallback order 映射
    cid_fallback_order: dict[str, dict] = {}
    for cid in unmatched_cids:
        for oid in customer_ids_this_batch.get(cid, []):
            if oid in fallback_orders_map:
                cid_fallback_order[cid] = fallback_orders_map[oid]
                break

    sp_ids_needed = set()
    for cid in customers_needing_snapshot:
        if cid in matched_orders:
            sp_ids_needed.add(str(matched_orders[cid]["user_id"]))
        elif cid in cid_fallback_order and cid_fallback_order[cid].get("user_id"):
            sp_ids_needed.add(str(cid_fallback_order[cid]["user_id"]))

    # 批量查询员工属性和主管关系
    attr_map = _batch_get_employee_attributes(db, sp_ids_needed)
    supervisor_map = _batch_get_supervisor_ids(db, sp_ids_needed)

    # 主管也需要查属性
    sv_ids = set(supervisor_map.values())
    if sv_ids:
        sv_attr_map = _batch_get_employee_attributes(db, sv_ids)
        attr_map.update(sv_attr_map)

    # ---- Step 6: 批量生成快照 ----
    snapshot_rows = []
    for cid in customers_needing_snapshot:
        try:
            if cid in matched_orders:
                order = matched_orders[cid]
                sp_id = str(order["user_id"])
                sp_attr = attr_map.get(sp_id)
                sv_id = supervisor_map.get(sp_id)
                sv_attr = attr_map.get(sv_id) if sv_id else None

                sp_rate, sv_rate = None, None
                is_complete = sp_attr is not None
                if is_complete:
                    sp_rate, sv_rate, _ = calc_commission_rates(sp_id, sp_attr, sv_id, sv_attr)

                snapshot_rows.append({
                    "customer_id": cid,
                    "first_order_id": str(order["order_id"]),
                    "first_order_date": to_date(order.get("account_date")),
                    "salesperson_id": sp_id,
                    "salesperson_attribute": sp_attr,
                    "salesperson_rate": sp_rate,
                    "supervisor_id": sv_id,
                    "supervisor_attribute": sv_attr,
                    "supervisor_rate": sv_rate,
                    "is_complete": is_complete,
                    "is_current": True,
                    "source": "auto",
                })

                if is_complete:
                    result.snapshots_auto_created += 1
                else:
                    result.snapshots_incomplete += 1
                    result.incomplete_customers.append(cid)
                continue

            fallback_order = cid_fallback_order.get(cid)

            if fallback_order and fallback_order.get("user_id"):
                sp_id = str(fallback_order["user_id"])
                sv_id = supervisor_map.get(sp_id)
                snapshot_rows.append({
                    "customer_id": cid,
                    "salesperson_id": sp_id,
                    "supervisor_id": sv_id,
                    "salesperson_attribute": None,
                    "salesperson_rate": None,
                    "supervisor_attribute": None,
                    "supervisor_rate": None,
                    "is_complete": False,
                    "is_current": True,
                    "source": "auto",
                })
                result.snapshots_incomplete += 1
                result.incomplete_customers.append(cid)
            else:
                logger.error(f"客户 {cid} 无法生成归属快照：找不到关联订单")
                result.snapshots_incomplete += 1
                result.incomplete_customers.append(cid)

        except Exception as e:
            logger.error(f"客户 {cid} 归属校验异常: {e}")
            result.incomplete_customers.append(cid)

    if snapshot_rows:
        db.execute(CustomerCommissionSnapshot.__table__.insert(), snapshot_rows)
        db.flush()
    logger.info(
        f"归属校验完成: 自动创建 {result.snapshots_auto_created}, "
        f"不完整 {result.snapshots_incomplete}"
    )

    return result
