"""色板库（公库 / 私库）与色差仪测量 service。

授权口径：
- 公库：color_library:read 可读，color_library:admin 可维护与审核晋升。
- 私库：必须绑定客户，复用 customer.access_service 的实时归属判定（主负责人/协作人，
  customer:read_all 全局，customer:admin 同部门）。无权一律按 404 返回，不泄露存在性。
- 统计（平均 Lab、组内 ΔE、对基准 ΔE）只由后端按参与组重算，前端值仅作预览。
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, ROUND_HALF_UP

import colour
from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.color.models import ColorPalette
from app.color.swatch_library_models import (
    ColorLibraryEvent,
    ColorLibraryMeasurement,
    ColorLibrarySwatch,
)
from app.core.time import beijing_now, to_beijing_naive
from app.customer.access_service import (
    CustomerAccessDenied,
    apply_customer_scope,
    require_customer_access,
)
from app.customer.models import CustomerAccount, CustomerAssignment

logger = logging.getLogger("color.swatch_library")

PERM_READ = "color_library:read"
PERM_WRITE = "color_library:write"
PERM_ADMIN = "color_library:admin"
MANAGE_PERMS = ("customer:admin",)
SIZE_UNITS = {"inch", "cm"}
SOURCES = {"device", "simulation", "manual"}
RECEIPTS = {"matched", "late", "manual"}
MAX_BATCH = 20
TWO = Decimal("0.01")


# ── 基础工具 ──────────────────────────────────────────────


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="色板不存在或无权访问")


def _bad(msg: str) -> HTTPException:
    return HTTPException(status_code=422, detail=msg)


def _live_user(db: Session, user: dict) -> dict:
    """权限按数据库实时授权与 token 取交集，防止 token 内旧权限越权。"""
    from app.auth.service import get_live_user_authorization

    roles, permissions = get_live_user_authorization(db, int(user["sub"]))
    return {
        **user,
        "roles": sorted(set(roles) & set(user.get("roles", []))),
        "permissions": sorted(set(permissions) & set(user.get("permissions", []))),
    }


def _has(user: dict, perm: str) -> bool:
    return "super_admin" in (user.get("roles") or []) or perm in (user.get("permissions") or [])


def _uid(user: dict) -> int:
    return int(user["sub"])


def normalize_code(code: str) -> str:
    return re.sub(r"\s+", "", code or "").upper()


def _dec(value, q=TWO):
    return None if value is None else Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def _f(value):
    return None if value is None else float(value)


def _event(db: Session, swatch_id: int, event_type: str, actor: int, detail: dict | None = None):
    db.add(ColorLibraryEvent(
        swatch_id=swatch_id, event_type=event_type, operated_by=actor,
        detail_json=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
    ))


def de00(lab1, lab2) -> float:
    return float(colour.delta_E(list(lab1), list(lab2), method="CIE 2000"))


# ── 授权 ──────────────────────────────────────────────────


def _customer_access(db: Session, user: dict, customer_id: int, *, write: bool, fresh: bool = False):
    try:
        return require_customer_access(
            db, customer_id=customer_id, user=user,
            action_permissions=(PERM_WRITE,) if write else (PERM_READ, PERM_WRITE),
            manage_permissions=MANAGE_PERMS, fresh=fresh,
        )
    except CustomerAccessDenied as exc:
        raise _not_found() from exc


def _load(db: Session, user: dict, swatch_id: int, *, write: bool, lock: bool = False) -> ColorLibrarySwatch:
    query = db.query(ColorLibrarySwatch).filter(ColorLibrarySwatch.id == swatch_id)
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise _not_found()
    if row.library_scope == "public":
        if not _has(user, PERM_ADMIN if write else PERM_READ):
            raise _not_found()
    else:
        _customer_access(db, user, row.customer_id, write=write)
    return row


def _visible_customer_ids(db: Session, user: dict):
    query = db.query(CustomerAccount.id)
    try:
        return apply_customer_scope(
            query, user=user, read_permissions=(PERM_READ, PERM_WRITE), include_public_pool=False,
        )
    except CustomerAccessDenied as exc:
        raise _not_found() from exc


# ── 基准与统计 ────────────────────────────────────────────


def _base_lab(db: Session, row: ColorLibrarySwatch):
    if row.base_swatch_id:
        base = db.get(ColorLibrarySwatch, row.base_swatch_id)
        if base is not None and base.stat_count:
            return [float(base.stat_lab_l), float(base.stat_lab_a), float(base.stat_lab_b)]
    if row.base_palette_id:
        palette = db.get(ColorPalette, row.base_palette_id)
        if palette is not None and palette.lab_l is not None:
            return [float(palette.lab_l), float(palette.lab_a), float(palette.lab_b_val)]
    return None


def compute_stats(labs: list[list[float]], base_lab=None) -> dict:
    """纯函数：参与组 Lab → 平均 Lab、组内平均/最大 ΔE00（≥2 组）、对基准 ΔE00。"""
    if not labs:
        return {"count": 0, "avg": None, "mean_de": None, "max_de": None, "base_de": None}
    avg = [sum(lab[i] for lab in labs) / len(labs) for i in range(3)]
    spreads = [de00(lab, avg) for lab in labs] if len(labs) > 1 else []
    return {
        "count": len(labs),
        "avg": avg,
        "mean_de": sum(spreads) / len(spreads) if spreads else None,
        "max_de": max(spreads) if spreads else None,
        "base_de": de00(avg, base_lab) if base_lab else None,
    }


def recompute(db: Session, row: ColorLibrarySwatch) -> None:
    labs = [
        [float(m.lab_l), float(m.lab_a), float(m.lab_b)]
        for m in db.query(ColorLibraryMeasurement).filter(
            ColorLibraryMeasurement.swatch_id == row.id,
            ColorLibraryMeasurement.is_included == 1,
        ).all()
    ]
    st = compute_stats(labs, _base_lab(db, row))
    row.stat_count = st["count"]
    row.stat_lab_l, row.stat_lab_a, row.stat_lab_b = (
        [_dec(v) for v in st["avg"]] if st["avg"] else [None, None, None]
    )
    row.stat_mean_de = _dec(st["mean_de"])
    row.stat_max_de = _dec(st["max_de"])
    row.stat_base_de = _dec(st["base_de"])
    db.flush()
    if row.library_scope == "public":
        # 公库实测变化后，以它为基准的私库色板对基准 ΔE 需同步更新
        for dependent in db.query(ColorLibrarySwatch).filter(ColorLibrarySwatch.base_swatch_id == row.id).all():
            if dependent.stat_count:
                avg = [float(dependent.stat_lab_l), float(dependent.stat_lab_a), float(dependent.stat_lab_b)]
                base = _base_lab(db, dependent)
                dependent.stat_base_de = _dec(de00(avg, base)) if base else None
        db.flush()


def _verdict(row: ColorLibrarySwatch) -> str:
    if not row.stat_count:
        return "none"
    if row.stat_base_de is None:
        return "ok"
    return "ok" if row.stat_base_de <= row.tolerance_de else "warn"


# ── 序列化 ────────────────────────────────────────────────


def _base_info(db: Session, row: ColorLibrarySwatch):
    if row.base_swatch_id:
        base = db.get(ColorLibrarySwatch, row.base_swatch_id)
        if base is not None:
            return {"type": "swatch", "id": base.id, "color_code": base.color_code,
                    "size_value": _f(base.size_value), "size_unit": base.size_unit, "lab": _base_lab(db, row)}
    if row.base_palette_id:
        palette = db.get(ColorPalette, row.base_palette_id)
        if palette is not None:
            return {"type": "palette", "id": palette.id, "color_code": palette.industry_code,
                    "hex": palette.hex_code, "lab": _base_lab(db, row)}
    return None


def serialize_swatch(row: ColorLibrarySwatch, *, customer_name: str | None = None) -> dict:
    return {
        "id": row.id,
        "library_scope": row.library_scope,
        "customer_id": row.customer_id,
        "customer_name": customer_name,
        "color_code": row.color_code,
        "size_value": _f(row.size_value),
        "size_unit": row.size_unit,
        "display_name": row.display_name,
        "base_swatch_id": row.base_swatch_id,
        "base_palette_id": row.base_palette_id,
        "tolerance_de": _f(row.tolerance_de),
        "stats": {
            "count": row.stat_count,
            "avg_lab": [_f(row.stat_lab_l), _f(row.stat_lab_a), _f(row.stat_lab_b)] if row.stat_count else None,
            "mean_de": _f(row.stat_mean_de),
            "max_de": _f(row.stat_max_de),
            "base_de": _f(row.stat_base_de),
        },
        "verdict": _verdict(row),
        "record_status": row.record_status,
        "promotion_status": row.promotion_status,
        "owner_user_id": row.owner_user_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_measurement(m: ColorLibraryMeasurement) -> dict:
    return {
        "id": m.id,
        "seq_no": m.seq_no,
        "lab": [_f(m.lab_l), _f(m.lab_a), _f(m.lab_b)],
        "luv": [_f(m.luv_l), _f(m.luv_u), _f(m.luv_v)],
        "lch": [_f(m.lch_l), _f(m.lch_c), _f(m.lch_h)],
        "yxy": [_f(m.yxy_y), _f(m.yxy_x), _f(m.yxy_yy)],
        "cmyk": [m.cmyk_c, m.cmyk_m, m.cmyk_y, m.cmyk_k],
        "rgb": [m.rgb_r, m.rgb_g, m.rgb_b],
        "raw_hex": m.raw_hex,
        "source": m.source,
        "receipt_status": m.receipt_status,
        "device_name": m.device_name,
        "device_sn": m.device_sn,
        "device_fw": m.device_fw,
        "session_id": m.session_id,
        "requested_at": m.requested_at,
        "received_at": m.received_at,
        "is_included": bool(m.is_included),
        "exclude_reason": m.exclude_reason,
        "measured_by": m.measured_by,
        "created_at": m.created_at,
    }


# ── 查询 ──────────────────────────────────────────────────


def list_my_customers(db: Session, user: dict, keyword: str | None = None) -> dict:
    user = _live_user(db, user)
    uid = _uid(user)
    query = _visible_customer_ids(db, user).add_columns(
        CustomerAccount.display_name, CustomerAccount.primary_country_code,
    )
    if keyword:
        query = query.filter(CustomerAccount.display_name.like(f"%{keyword.strip()}%"))
    rows = query.order_by(CustomerAccount.display_name).limit(200).all()
    ids = [r[0] for r in rows]
    counts = dict(
        db.query(ColorLibrarySwatch.customer_id, func.count(ColorLibrarySwatch.id)).filter(
            ColorLibrarySwatch.customer_id.in_(ids), ColorLibrarySwatch.record_status == "active",
        ).group_by(ColorLibrarySwatch.customer_id).all()
    ) if ids else {}
    roles = dict(
        db.query(CustomerAssignment.customer_id, CustomerAssignment.assignment_role).filter(
            CustomerAssignment.customer_id.in_(ids), CustomerAssignment.user_id == uid,
            CustomerAssignment.assignment_status == "active", CustomerAssignment.effective_to.is_(None),
        ).all()
    ) if ids else {}
    items = [
        {"customer_id": cid, "display_name": name, "country_code": country,
         "assignment_role": roles.get(cid), "swatch_count": counts.get(cid, 0)}
        for cid, name, country in rows
    ]
    return {"items": items, "total": len(items)}


def list_swatches(db: Session, user: dict, *, scope: str, customer_id: int | None = None,
                  keyword: str | None = None, verdict: str | None = None,
                  page: int = 1, page_size: int = 50) -> dict:
    user = _live_user(db, user)
    query = db.query(ColorLibrarySwatch, CustomerAccount.display_name).outerjoin(
        CustomerAccount, CustomerAccount.id == ColorLibrarySwatch.customer_id,
    ).filter(ColorLibrarySwatch.record_status == "active", ColorLibrarySwatch.library_scope == scope)
    if scope == "public":
        if not _has(user, PERM_READ):
            raise _not_found()
    elif customer_id is not None:
        _customer_access(db, user, customer_id, write=False)
        query = query.filter(ColorLibrarySwatch.customer_id == customer_id)
    else:
        query = query.filter(ColorLibrarySwatch.customer_id.in_(
            _visible_customer_ids(db, user).with_entities(CustomerAccount.id).scalar_subquery()))
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(ColorLibrarySwatch.color_code.like(like), ColorLibrarySwatch.display_name.like(like)))
    if verdict == "none":
        query = query.filter(ColorLibrarySwatch.stat_count == 0)
    elif verdict == "warn":
        query = query.filter(ColorLibrarySwatch.stat_count > 0, ColorLibrarySwatch.stat_base_de > ColorLibrarySwatch.tolerance_de)
    elif verdict == "ok":
        query = query.filter(ColorLibrarySwatch.stat_count > 0, or_(
            ColorLibrarySwatch.stat_base_de.is_(None), ColorLibrarySwatch.stat_base_de <= ColorLibrarySwatch.tolerance_de))
    total = query.count()
    rows = query.order_by(ColorLibrarySwatch.color_code_key, ColorLibrarySwatch.size_value).offset(
        (page - 1) * page_size).limit(page_size).all()
    return {"items": [serialize_swatch(r, customer_name=n) for r, n in rows], "total": total,
            "page": page, "page_size": page_size}


def get_swatch(db: Session, user: dict, swatch_id: int) -> dict:
    user = _live_user(db, user)
    row = _load(db, user, swatch_id, write=False)
    name = db.query(CustomerAccount.display_name).filter(CustomerAccount.id == row.customer_id).scalar() \
        if row.customer_id else None
    data = serialize_swatch(row, customer_name=name)
    data["base"] = _base_info(db, row)
    data["measurements"] = [serialize_measurement(m) for m in db.query(ColorLibraryMeasurement).filter(
        ColorLibraryMeasurement.swatch_id == row.id).order_by(ColorLibraryMeasurement.seq_no).all()]
    data["can_write"] = _has(user, PERM_ADMIN) if row.library_scope == "public" else _has(user, PERM_WRITE)
    return data


# ── 写入 ──────────────────────────────────────────────────


def _validate_base(db: Session, base_swatch_id, base_palette_id):
    if base_swatch_id:
        base = db.get(ColorLibrarySwatch, base_swatch_id)
        if base is None or base.library_scope != "public" or base.record_status != "active":
            raise _bad("对比基准必须是公库中的有效色板")
    if base_palette_id and db.get(ColorPalette, base_palette_id) is None:
        raise _bad("对比基准色号不存在")


def _apply_identity(row: ColorLibrarySwatch, color_code: str, size_value, size_unit: str):
    code = (color_code or "").strip()
    if not code:
        raise _bad("请填写色号")
    if size_unit not in SIZE_UNITS:
        raise _bad("尺寸单位只支持 inch / cm")
    size = _dec(size_value, Decimal("0.1"))
    if size is None or size <= 0:
        raise _bad("请填写有效尺寸")
    row.color_code, row.color_code_key, row.size_value, row.size_unit = code, normalize_code(code), size, size_unit


def _commit_unique(db: Session, row: ColorLibrarySwatch):
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("swatch identity conflict: %s", exc.orig)
        print(f"[swatch_library] identity conflict {row.color_code} {row.size_value}{row.size_unit}", flush=True)
        where = "公库" if row.library_scope == "public" else "该客户"
        raise HTTPException(status_code=409,
                            detail=f"{where}下已存在 {row.color_code} · {row.size_value:g} {row.size_unit}") from exc


def create_swatch(db: Session, user: dict, payload: dict) -> dict:
    user = _live_user(db, user)
    scope = payload.get("library_scope")
    if scope == "public":
        if not _has(user, PERM_ADMIN):
            raise HTTPException(status_code=403, detail="仅色彩管理员可维护公库")
        customer_id = None
    elif scope == "private":
        customer_id = payload.get("customer_id")
        if not customer_id:
            raise _bad("私库色板必须绑定客户")
        customer_id = _customer_access(db, user, int(customer_id), write=True).customer_id
    else:
        raise _bad("library_scope 只支持 public / private")
    _validate_base(db, payload.get("base_swatch_id"), payload.get("base_palette_id"))
    row = ColorLibrarySwatch(
        library_scope=scope, customer_id=customer_id, customer_scope_key=customer_id or 0,
        owner_user_id=_uid(user), display_name=(payload.get("display_name") or "").strip() or None,
        base_swatch_id=payload.get("base_swatch_id"), base_palette_id=payload.get("base_palette_id"),
        tolerance_de=_dec(payload.get("tolerance_de") or 1.5), stat_count=0, record_status="active",
    )
    _apply_identity(row, payload.get("color_code"), payload.get("size_value"), payload.get("size_unit") or "inch")
    db.add(row)
    _commit_unique(db, row)
    _event(db, row.id, "created", _uid(user), {"color_code": row.color_code, "size": f"{row.size_value} {row.size_unit}"})
    db.commit()
    return get_swatch(db, user, row.id)


def update_swatch(db: Session, user: dict, swatch_id: int, payload: dict) -> dict:
    user = _live_user(db, user)
    row = _load(db, user, swatch_id, write=True, lock=True)
    before = serialize_swatch(row)
    if any(k in payload for k in ("color_code", "size_value", "size_unit")):
        _apply_identity(row, payload.get("color_code", row.color_code),
                        payload.get("size_value", row.size_value), payload.get("size_unit", row.size_unit))
    if "display_name" in payload:
        row.display_name = (payload["display_name"] or "").strip() or None
    if "tolerance_de" in payload:
        tol = _dec(payload["tolerance_de"])
        if tol is None or tol <= 0:
            raise _bad("允许色差必须大于 0")
        row.tolerance_de = tol
    if "base_swatch_id" in payload or "base_palette_id" in payload:
        bs, bp = payload.get("base_swatch_id"), payload.get("base_palette_id")
        if bs and bs == row.id:
            raise _bad("不能以自身作为对比基准")
        _validate_base(db, bs, bp)
        row.base_swatch_id, row.base_palette_id = bs, bp
    _commit_unique(db, row)
    recompute(db, row)
    _event(db, row.id, "updated", _uid(user), {"before": {k: before[k] for k in (
        "color_code", "size_value", "size_unit", "display_name", "tolerance_de", "base_swatch_id", "base_palette_id")}})
    db.commit()
    return get_swatch(db, user, row.id)


def archive_swatch(db: Session, user: dict, swatch_id: int) -> dict:
    user = _live_user(db, user)
    row = _load(db, user, swatch_id, write=True, lock=True)
    row.record_status = "archived"
    _event(db, row.id, "archived", _uid(user))
    db.commit()
    return {"id": row.id, "record_status": row.record_status}


def _triple(values, name: str, *, required: bool, scale=TWO):
    if values is None:
        if required:
            raise _bad(f"缺少 {name}")
        return [None, None, None]
    if len(values) != 3:
        raise _bad(f"{name} 必须是 3 个数值")
    return [_dec(v, scale) for v in values]


def _byte(v):
    if v is None:
        return None
    iv = int(v)
    if not 0 <= iv <= 255:
        raise _bad("CMYK/RGB 取值超出 0-255")
    return iv


def add_measurements(db: Session, user: dict, swatch_id: int, items: list[dict]) -> dict:
    """批量写入测量组；client_request_id 幂等，重试不会重复入库。"""
    user = _live_user(db, user)
    if not items or len(items) > MAX_BATCH:
        raise _bad(f"一次写入 1-{MAX_BATCH} 组测量")
    row = _load(db, user, swatch_id, write=True, lock=True)
    if row.record_status != "active":
        raise HTTPException(status_code=409, detail="色板已归档，不能继续测量")
    existing = {
        m.client_request_id for m in db.query(ColorLibraryMeasurement.client_request_id).filter(
            ColorLibraryMeasurement.swatch_id == row.id).all()
    }
    next_seq = (db.query(func.max(ColorLibraryMeasurement.seq_no)).filter(
        ColorLibraryMeasurement.swatch_id == row.id).scalar() or 0) + 1
    created = 0
    for item in items:
        request_id = str(item.get("client_request_id") or "").strip()
        if not request_id or len(request_id) > 64:
            raise _bad("每组测量必须带 client_request_id（≤64 字符）")
        if request_id in existing:
            continue
        source = item.get("source") or "device"
        receipt = item.get("receipt_status") or ("manual" if source == "manual" else "matched")
        if source not in SOURCES or receipt not in RECEIPTS:
            raise _bad("source / receipt_status 取值无效")
        lab = _triple(item.get("lab"), "lab", required=True)
        luv = _triple(item.get("luv"), "luv", required=False)
        lch = _triple(item.get("lch"), "lch", required=False)
        yxy = item.get("yxy")
        if yxy is not None and len(yxy) != 3:
            raise _bad("yxy 必须是 3 个数值")
        cmyk = item.get("cmyk") or [None] * 4
        rgb = item.get("rgb") or [None] * 3
        if len(cmyk) != 4 or len(rgb) != 3:
            raise _bad("cmyk 需 4 个、rgb 需 3 个数值")
        db.add(ColorLibraryMeasurement(
            swatch_id=row.id, seq_no=next_seq,
            lab_l=lab[0], lab_a=lab[1], lab_b=lab[2],
            luv_l=luv[0], luv_u=luv[1], luv_v=luv[2],
            lch_l=lch[0], lch_c=lch[1], lch_h=lch[2],
            yxy_y=_dec(yxy[0]) if yxy else None,
            yxy_x=_dec(yxy[1], Decimal("0.0001")) if yxy else None,
            yxy_yy=_dec(yxy[2], Decimal("0.0001")) if yxy else None,
            cmyk_c=_byte(cmyk[0]), cmyk_m=_byte(cmyk[1]), cmyk_y=_byte(cmyk[2]), cmyk_k=_byte(cmyk[3]),
            rgb_r=_byte(rgb[0]), rgb_g=_byte(rgb[1]), rgb_b=_byte(rgb[2]),
            raw_hex=(item.get("raw_hex") or None), source=source, receipt_status=receipt,
            device_name=item.get("device_name"), device_sn=item.get("device_sn"), device_fw=item.get("device_fw"),
            session_id=item.get("session_id"), client_request_id=request_id,
            requested_at=to_beijing_naive(item.get("requested_at")),
            received_at=to_beijing_naive(item.get("received_at")) or beijing_now(),
            is_included=1, measured_by=_uid(user),
        ))
        existing.add(request_id)
        next_seq += 1
        created += 1
    if created:
        db.flush()
        recompute(db, row)
        _event(db, row.id, "measured", _uid(user), {"count": created})
    db.commit()
    data = get_swatch(db, user, row.id)
    data["created_count"] = created
    return data


def set_inclusion(db: Session, user: dict, swatch_id: int, measurement_id: int,
                  included: bool, reason: str | None) -> dict:
    user = _live_user(db, user)
    row = _load(db, user, swatch_id, write=True, lock=True)
    m = db.query(ColorLibraryMeasurement).filter(
        ColorLibraryMeasurement.id == measurement_id, ColorLibraryMeasurement.swatch_id == row.id,
    ).one_or_none()
    if m is None:
        raise _not_found()
    if not included and not (reason or "").strip():
        raise _bad("剔除测量组需填写原因")
    m.is_included = 1 if included else 0
    m.exclude_reason = None if included else reason.strip()[:255]
    recompute(db, row)
    _event(db, row.id, "restored" if included else "excluded", _uid(user),
           {"measurement_id": m.id, "seq_no": m.seq_no, "reason": m.exclude_reason})
    db.commit()
    return get_swatch(db, user, row.id)


def request_promotion(db: Session, user: dict, swatch_id: int) -> dict:
    user = _live_user(db, user)
    row = _load(db, user, swatch_id, write=True, lock=True)
    if row.library_scope != "private":
        raise _bad("只有私库色板可申请纳入公库")
    if not row.stat_count:
        raise _bad("至少完成一组测量后再申请")
    if row.promotion_status == "pending":
        raise HTTPException(status_code=409, detail="已在审核中")
    row.promotion_status = "pending"
    _event(db, row.id, "promotion_requested", _uid(user))
    db.commit()
    return get_swatch(db, user, row.id)


def review_promotion(db: Session, user: dict, swatch_id: int, approve: bool) -> dict:
    """管理员审核：通过时复制为公库色板（含测量组），私库原记录保留。"""
    user = _live_user(db, user)
    if not _has(user, PERM_ADMIN):
        raise HTTPException(status_code=403, detail="仅色彩管理员可审核")
    row = db.query(ColorLibrarySwatch).filter(ColorLibrarySwatch.id == swatch_id).with_for_update().one_or_none()
    if row is None or row.library_scope != "private" or row.promotion_status != "pending":
        raise HTTPException(status_code=409, detail="该色板不在待审核状态")
    actor = _uid(user)
    if not approve:
        row.promotion_status = "rejected"
        _event(db, row.id, "promotion_rejected", actor)
        db.commit()
        return {"id": row.id, "promotion_status": row.promotion_status}
    public = ColorLibrarySwatch(
        library_scope="public", customer_id=None, customer_scope_key=0, owner_user_id=actor,
        color_code=row.color_code, color_code_key=row.color_code_key, size_value=row.size_value,
        size_unit=row.size_unit, display_name=row.display_name, base_palette_id=row.base_palette_id,
        tolerance_de=row.tolerance_de, stat_count=0, record_status="active", promoted_from_id=row.id,
    )
    db.add(public)
    _commit_unique(db, public)
    for m in db.query(ColorLibraryMeasurement).filter(
            ColorLibraryMeasurement.swatch_id == row.id, ColorLibraryMeasurement.is_included == 1).all():
        clone = {c.name: getattr(m, c.name) for c in ColorLibraryMeasurement.__table__.columns
                 if c.name not in {"id", "swatch_id", "created_at", "updated_at"}}
        clone["client_request_id"] = f"promote-{m.id}"
        db.add(ColorLibraryMeasurement(swatch_id=public.id, **clone))
    db.flush()
    recompute(db, public)
    row.promotion_status = "approved"
    _event(db, row.id, "promotion_approved", actor, {"public_swatch_id": public.id})
    _event(db, public.id, "created", actor, {"promoted_from_id": row.id})
    db.commit()
    return {"id": row.id, "promotion_status": row.promotion_status, "public_swatch_id": public.id}


def list_promotions(db: Session, user: dict) -> dict:
    user = _live_user(db, user)
    if not _has(user, PERM_ADMIN):
        raise HTTPException(status_code=403, detail="仅色彩管理员可审核")
    rows = db.query(ColorLibrarySwatch, CustomerAccount.display_name).join(
        CustomerAccount, CustomerAccount.id == ColorLibrarySwatch.customer_id,
    ).filter(ColorLibrarySwatch.promotion_status == "pending").order_by(ColorLibrarySwatch.updated_at).all()
    return {"items": [serialize_swatch(r, customer_name=n) for r, n in rows], "total": len(rows)}
