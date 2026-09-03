"""按公司名从 OKKI 手动同步单个客户的最新资料。

背景：发票录入的客户搜索读 lsordertest.customer_info 只读镜像（外部同步管道
维护），OKKI 新客户或负责人变更存在同步延迟，私海过滤下会查不到客户。
本服务直连 OKKI 开放平台（company scope，查重 + 详情两个只读接口）拉取该客户
最新数据，写入方舟自有 overlay 表（不动业务库只读红线），
product_service.search_customers 合并 overlay 后立即可搜到。
"""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.invoice import okki_client
from app.invoice.models import InvoiceCustomerOverlay
from app.models.business import CustomerInfo, UserBasic

logger = logging.getLogger(__name__)


class CustomerSyncError(ValueError):
    """业务可读错误（未找到/多候选/OKKI 失败），message 直接给前端。"""


# 返回给前端的变更字段中文化（source_update_time 是内部比对字段，不展示）
_FIELD_LABELS = {
    "company_name": "公司名称",
    "country_name": "国家/地区",
    "origin_name": "客户来源",
    "archive_type": "建档类型",
    "trail_status_name": "客户阶段",
    "owner_user_ids": "负责人",
}


def _normalize_name(value) -> str:
    """公司名匹配归一化：去全部空白 + 小写（OKKI 公司名以英文为主）。"""
    return "".join(str(value or "").split()).lower()


def _pick_candidate(candidates: list[dict], company_name: str) -> dict:
    """名称/简称归一化精确命中优先；否则唯一模糊命中兜底；多候选要求补全名称。"""
    norm = _normalize_name(company_name)
    exact = [
        c for c in candidates
        if _normalize_name(c.get("name")) == norm or _normalize_name(c.get("short_name")) == norm
    ]
    pool = exact or candidates
    if len(pool) == 1:
        return pool[0]
    names = "、".join(str(c.get("name") or c.get("company_id") or "?") for c in pool[:5])
    raise CustomerSyncError(f"OKKI 中找到 {len(pool)} 个相似客户（{names}），请输入更完整准确的公司名称")


def _apply_info(row: InvoiceCustomerOverlay, info: dict) -> list[str]:
    """把 OKKI 详情映射到 overlay 行，返回发生变化的字段名列表。

    OKKI 响应字段形状不设防（文档与实际可能漂移）：非标量/列表字段一律
    isinstance 兜底，形状异常按空值处理而不是抛 AttributeError 变 500。
    """
    owners_raw = info.get("owner")
    owners = owners_raw if isinstance(owners_raw, list) else []
    owner_ids = [
        str(o.get("user_id")) for o in owners
        if isinstance(o, dict) and o.get("user_id") not in (None, "")
    ]
    trail = info.get("trail_status")
    trail = trail if isinstance(trail, dict) else {}
    country = str(info.get("country") or "").strip()
    if not country:
        region = info.get("country_region")
        region = region if isinstance(region, dict) else {}
        country = str(region.get("country") or "").strip()
    values = {
        "company_name": str(info.get("name") or "").strip(),
        "country_name": country or None,
        "origin_name": str(info.get("origin_name") or "").strip() or None,
        "archive_type": str(info.get("archive_type") or "").strip() or None,
        "trail_status_name": str(info.get("trail_status_name") or trail.get("status_name") or "").strip() or None,
        "owner_user_ids": owner_ids,
        "source_update_time": str(info.get("update_time") or "").strip() or None,
    }
    if not values["company_name"]:
        raise CustomerSyncError("OKKI 返回的客户详情缺少公司名称，请稍后重试")
    changed = []
    for field, value in values.items():
        current = getattr(row, field)
        if field == "owner_user_ids":
            current = [str(v) for v in (current or [])]
        if current != value:
            changed.append(field)
        setattr(row, field, value)
    return changed


def _owner_names(db: Session, owner_ids: list[str]) -> list[str]:
    """OKKI owner user_id → 业务库人员姓名；镜像不可用时退回展示 ID。"""
    if not owner_ids:
        return []
    try:
        rows = db.query(UserBasic).filter(UserBasic.user_id.in_(owner_ids)).all()
    except Exception as exc:  # noqa: BLE001 - 人员镜像不可读不阻断同步结果
        logger.warning("owner name lookup failed: %s", exc)
        return list(owner_ids)
    by_id = {str(r.user_id): str(r.full_name or r.nickname or r.user_id) for r in rows}
    return [by_id.get(oid, oid) for oid in owner_ids]


def sync_customer_from_okki(db: Session, *, company_name: str, operator_id: int | None = None) -> dict:
    """按公司名同步一个 OKKI 客户的最新资料到 overlay。抛 CustomerSyncError（可读）。"""
    name = str(company_name or "").strip()
    if not name:
        raise CustomerSyncError("请输入客户公司名称")

    try:
        candidates = okki_client.query_companies_by_name(db, name)
    except okki_client.OkkiApiError as exc:
        raise CustomerSyncError(str(exc)) from exc
    if not candidates:
        raise CustomerSyncError(
            f"OKKI 中未找到名称含「{name}」的客户，请核对公司名称"
            "（以 OKKI 客户列表中的名称为准；模糊匹配仅取前 20 条，建议输入完整名称）"
        )
    chosen = _pick_candidate(candidates, name)
    company_id = str(chosen.get("company_id") or "").strip()
    if not company_id.isdigit():
        raise CustomerSyncError(f"OKKI 返回的客户 ID「{company_id}」异常，请联系管理员")

    try:
        info = okki_client.get_company_info(db, int(company_id))
    except okki_client.OkkiApiError as exc:
        raise CustomerSyncError(str(exc)) from exc

    row = db.get(InvoiceCustomerOverlay, company_id)
    created = row is None
    if created:
        # 并发同步同一客户：savepoint 兜底 PK 冲突，回退到更新分支（同 ensure_custom_product 范式）
        try:
            with db.begin_nested():
                row = InvoiceCustomerOverlay(company_id=company_id, company_name=name)
                db.add(row)
                db.flush()
        except IntegrityError:
            logger.warning("customer overlay 并发插入回退为更新 company_id=%s", company_id)
            row = db.get(InvoiceCustomerOverlay, company_id)
            if row is None:
                raise
            created = False
    changed = _apply_info(row, info)
    row.synced_by = operator_id
    db.flush()

    owner_ids = [str(v) for v in (row.owner_user_ids or [])]
    owner_names = _owner_names(db, owner_ids)
    # 镜像里本来就有 → 本次是纠偏（owner 过期等）；完全没有 → 新客户补入
    in_mirror = db.get(CustomerInfo, company_id) is not None

    display_changed = [_FIELD_LABELS[f] for f in changed if f in _FIELD_LABELS]
    if created and not in_mirror:
        message = f"已从 OKKI 同步新客户「{row.company_name}」，现在可以在客户框中搜索到它"
    elif display_changed:
        message = f"已更新客户「{row.company_name}」的最新信息（变更：{'、'.join(display_changed)}）"
    else:
        message = f"客户「{row.company_name}」的本地信息已是最新"
    return {
        "company_id": row.company_id,
        "company_name": row.company_name,
        "country_name": row.country_name,
        "owner_user_ids": owner_ids,
        "owner_names": owner_names,
        "is_public_sea": not owner_ids,
        "created": created and not in_mirror,
        "changed_fields": display_changed,
        "message": message,
    }
