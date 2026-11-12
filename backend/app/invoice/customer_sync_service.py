"""按公司名从 OKKI 手动同步单个客户的最新资料。

背景：发票录入的客户搜索读 lsordertest.customer_info 只读镜像（外部同步管道
维护），OKKI 新客户或负责人变更存在同步延迟，私海过滤下会查不到客户。
本服务直连 OKKI 开放平台（company scope，查重 + 详情两个只读接口）拉取该客户
最新数据，更新 customer_info 负责人（缺行则补最小客户记录），并同事务写入
方舟 overlay 与镜像变更审计，确保直接读取镜像的客户选择器也立即可见。
"""

import logging
from copy import deepcopy

from sqlalchemy.orm import Session

from app.invoice import customer_mirror_service, okki_client, product_service
from app.invoice.models import InvoiceCustomerOverlay
from app.models.business import UserBasic

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

    负责人影响真实客户归属：缺失或结构异常必须拒绝，只有明确空列表才是公海。
    其余展示字段继续容忍上游字段形状漂移。
    """
    owners_raw = info.get("owner")
    if not isinstance(owners_raw, list):
        raise CustomerSyncError("OKKI 返回的客户负责人信息不完整，未更新客户归属，请稍后重试")
    owner_ids = []
    for owner in owners_raw:
        value = owner.get("user_id") if isinstance(owner, dict) else None
        if (not isinstance(value, (int, str)) or isinstance(value, bool)
                or not str(value).isascii() or not str(value).isdigit()
                or not 0 < int(value) <= 9223372036854775807):
            raise CustomerSyncError("OKKI 返回的客户负责人 ID 异常，未更新客户归属，请稍后重试")
        value = str(int(value))
        if value not in owner_ids:
            owner_ids.append(value)
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
    if not isinstance(info.get("name"), str) or not values["company_name"] or len(values["company_name"]) > 255:
        raise CustomerSyncError("OKKI 返回的客户公司名称缺失或无效，请稍后重试")
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
        logger.warning("owner name lookup failed: %s", type(exc).__name__)
        print(f"[customer-sync] owner name lookup failed: {type(exc).__name__}", flush=True)
        return list(owner_ids)
    by_id = {str(r.user_id): str(r.full_name or r.nickname or r.user_id) for r in rows}
    return [by_id.get(oid, oid) for oid in owner_ids]


def _overlay_snapshot(row):
    if row is None:
        return None
    return {field: deepcopy(getattr(row, field)) for field in (*_FIELD_LABELS, "source_update_time", "updated_at")}


def sync_customer_from_okki(db: Session, *, company_name: str, operator_id: int | None = None) -> dict:
    """同步客户镜像归属与 overlay；调用者负责一并提交或回滚审计。"""
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
    if not company_id.isascii() or not company_id.isdigit() or not 0 < int(company_id) <= 9223372036854775807:
        raise CustomerSyncError(f"OKKI 返回的客户 ID「{company_id}」异常，请联系管理员")
    company_id = str(int(company_id))

    expected_overlay = _overlay_snapshot(db.get(InvoiceCustomerOverlay, company_id))
    expected_mirror = customer_mirror_service.capture(db, company_id)

    try:
        info = okki_client.get_company_info(db, int(company_id))
    except okki_client.OkkiApiError as exc:
        raise CustomerSyncError(str(exc)) from exc

    if not isinstance(info, dict) or str(info.get("company_id")) != company_id:
        raise CustomerSyncError("OKKI 返回的客户身份与查询结果不一致，未更新客户资料")
    incoming = InvoiceCustomerOverlay(company_id=company_id)
    _apply_info(incoming, info)  # Validate before any customer write.

    # Lock only after the external request. A slower response cannot overwrite
    # another completed manual sync, even if OKKI update_time did not advance.
    row = db.query(InvoiceCustomerOverlay).filter_by(company_id=company_id).populate_existing().with_for_update().one_or_none()
    if _overlay_snapshot(row) != expected_overlay:
        raise CustomerSyncError("客户资料已被其他同步更新，请重新同步")
    previous_time = product_service._parse_ts(row.source_update_time) if row else None
    incoming_time = product_service._parse_ts(incoming.source_update_time)
    if previous_time and (incoming_time is None or incoming_time < previous_time):
        raise CustomerSyncError("OKKI 返回的客户资料早于上次手动同步，请稍后重试")

    try:
        mirror_changed = customer_mirror_service.apply(db, incoming, expected_mirror, operator_id=operator_id)
    except customer_mirror_service.CustomerMirrorSyncError as exc:
        raise CustomerSyncError(str(exc)) from exc

    created = row is None
    if created:
        row = InvoiceCustomerOverlay(company_id=company_id, company_name=name)
        db.add(row)
    changed = _apply_info(row, info)
    if mirror_changed and "owner_user_ids" not in changed:
        changed.append("owner_user_ids")
    row.synced_by = operator_id
    db.flush()

    owner_ids = [str(v) for v in (row.owner_user_ids or [])]
    owner_names = _owner_names(db, owner_ids)
    # 镜像里本来就有 → 本次是纠偏（owner 过期等）；完全没有 → 新客户补入
    in_mirror = expected_mirror is not None

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
