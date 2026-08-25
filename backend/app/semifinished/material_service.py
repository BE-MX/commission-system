"""半成品主数据、产品解析同步与需求报价。"""

from decimal import Decimal
from hashlib import sha1

from sqlalchemy import func, text
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.semifinished.inventory_service import qty
from app.semifinished.models import (
    InventoryBalance, ProductComponent, ProductMapping, SemifinishedMaterial,
)
from app.semifinished.parser import PARSER_VERSION, ParsedProduct, parse_product


settings = get_settings()


def _product_rows(db: Session) -> list[dict]:
    schema = settings.BUSINESS_DB_NAME
    rows = db.execute(text(f"""
        SELECT product_id, name AS product_name, model, color, size, unit
        FROM `{schema}`.okki_products
        WHERE disable_flag = 0
        ORDER BY product_id
    """)).mappings().all()
    return [dict(row) for row in rows]


def _parsed_rows(db: Session) -> tuple[list[tuple[dict, ParsedProduct]], int]:
    parsed: list[tuple[dict, ParsedProduct]] = []
    excluded = 0
    for row in _product_rows(db):
        result = parse_product(
            row.get("product_name") or "",
            structured_size=row.get("size"),
            structured_color=row.get("color"),
            structured_unit=row.get("unit"),
        )
        if result is None:
            excluded += 1
            continue
        parsed.append((row, result))
    return parsed, excluded


def sync_preview(db: Session) -> dict:
    parsed, excluded = _parsed_rows(db)
    existing = {
        int(row.product_id): row
        for row in db.query(ProductMapping).filter(ProductMapping.source_type == "okki").all()
    }
    new_count = changed_count = review_count = 0
    examples = []
    material_keys: set[tuple[str, str]] = set()
    for row, result in parsed:
        material_keys.update((result.size, component) for component in result.components)
        if result.parse_status != "confirmed":
            review_count += 1
        old = existing.get(int(row["product_id"]))
        if old is None:
            new_count += 1
        elif old.source != "manual" and (
            old.product_name != row["product_name"]
            or old.color_expression != result.color_expression
            or qty(old.unit_grams) != result.unit_grams
            or old.parser_version != PARSER_VERSION
        ):
            changed_count += 1
        if len(examples) < 50 and (old is None or result.parse_status != "confirmed"):
            examples.append({
                "product_id": int(row["product_id"]),
                "product_name": row["product_name"],
                "size": result.size,
                "color_expression": result.color_expression,
                "unit_grams": result.unit_grams,
                "components": list(result.components),
                "parse_status": result.parse_status,
                "message": result.message,
            })
    return {
        "active_products": len(parsed) + excluded,
        "eligible_products": len(parsed),
        "excluded_products": excluded,
        "material_count": len(material_keys),
        "new_mappings": new_count,
        "changed_mappings": changed_count,
        "needs_review": review_count,
        "parser_version": PARSER_VERSION,
        "examples": examples,
    }


def _material_code(size: str, color_key: str) -> str:
    digest = sha1(f"{size}|{color_key}".encode("utf-8")).hexdigest()[:8].upper()
    clean_size = size.replace(".", "_")[:8]
    return f"SF-{clean_size}-{digest}"


def _get_or_create_material(db: Session, size: str, color_key: str, color_type: str) -> SemifinishedMaterial:
    material = db.query(SemifinishedMaterial).filter_by(size=size, color_key=color_key).one_or_none()
    if material is None:
        material = SemifinishedMaterial(
            material_code=_material_code(size, color_key),
            size=size,
            color_code=color_key,
            color_key=color_key,
            color_type=color_type,
        )
        db.add(material)
        db.flush()
        db.add(InventoryBalance(material_id=material.id, on_hand_grams=0, reserved_grams=0))
    return material


def _component_color_type(color_key: str) -> str:
    """物料类型描述半成品本身，而不是来源产品的组合表达式。"""
    if not color_key.startswith("#"):
        return "named_t"
    if "T/" in color_key.upper():
        return "t"
    return "solid"


def apply_sync(db: Session) -> dict:
    parsed, excluded = _parsed_rows(db)
    mappings = {
        row.product_id: row
        for row in db.query(ProductMapping).options(
            selectinload(ProductMapping.components).selectinload(ProductComponent.material)
        ).filter(ProductMapping.source_type == "okki").all()
    }
    material_cache = {
        (row.size, row.color_key): row for row in db.query(SemifinishedMaterial).all()
    }
    applied = unchanged = skipped_manual = review_count = 0
    for row, result in parsed:
        product_id = int(row["product_id"])
        mapping = mappings.get(product_id)
        if mapping and mapping.source == "manual":
            skipped_manual += 1
            continue
        existing_components = tuple(
            component.material.color_key
            for component in sorted(mapping.components, key=lambda item: item.component_order)
        ) if mapping else ()
        if mapping and (
            mapping.product_name == row["product_name"]
            and mapping.model == row.get("model")
            and mapping.size == result.size
            and mapping.color_expression == result.color_expression
            and qty(mapping.unit_grams) == qty(result.unit_grams)
            and mapping.parse_status == result.parse_status
            and mapping.parser_version == PARSER_VERSION
            and mapping.parse_message == result.message
            and existing_components == result.components
        ):
            unchanged += 1
            if result.parse_status != "confirmed":
                review_count += 1
            continue
        if mapping is None:
            mapping = ProductMapping(source_type="okki", product_id=product_id, product_name=row["product_name"])
            db.add(mapping)
            mappings[product_id] = mapping
        mapping.product_name = row["product_name"]
        mapping.model = row.get("model")
        mapping.size = result.size
        mapping.color_expression = result.color_expression
        mapping.unit_grams = result.unit_grams
        mapping.parse_status = result.parse_status
        mapping.source = "auto"
        mapping.parser_version = PARSER_VERSION
        mapping.parse_message = result.message
        db.flush()
        mapping.components.clear()
        component_count = len(result.components)
        base_ratio = (Decimal("1") / Decimal(component_count)).quantize(Decimal("0.000001"))
        assigned = Decimal("0")
        for index, color_key in enumerate(result.components, start=1):
            ratio = Decimal("1") - assigned if index == component_count else base_ratio
            assigned += ratio
            cache_key = (result.size, color_key)
            material = material_cache.get(cache_key)
            if material is None:
                material = _get_or_create_material(
                    db, result.size, color_key, _component_color_type(color_key),
                )
                material_cache[cache_key] = material
            mapping.components.append(ProductComponent(
                material_id=material.id,
                component_order=index,
                ratio=ratio,
                grams_per_piece=qty(result.unit_grams * ratio),
            ))
        if result.parse_status != "confirmed":
            review_count += 1
        applied += 1
    db.commit()
    return {
        "applied": applied,
        "unchanged": unchanged,
        "skipped_manual": skipped_manual,
        "needs_review": review_count,
        "excluded": excluded,
    }


def list_materials(db: Session, page: int, page_size: int, keyword: str | None, review_only: bool) -> dict:
    counts = (
        db.query(ProductComponent.material_id, func.count(ProductComponent.id).label("product_count"))
        .join(ProductMapping, ProductMapping.id == ProductComponent.mapping_id)
        .group_by(ProductComponent.material_id)
        .subquery()
    )
    query = (
        db.query(SemifinishedMaterial, InventoryBalance, func.coalesce(counts.c.product_count, 0))
        .outerjoin(InventoryBalance, InventoryBalance.material_id == SemifinishedMaterial.id)
        .outerjoin(counts, counts.c.material_id == SemifinishedMaterial.id)
    )
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            (SemifinishedMaterial.material_code.like(like))
            | (SemifinishedMaterial.size.like(like))
            | (SemifinishedMaterial.color_code.like(like))
        )
    if review_only:
        query = query.filter(SemifinishedMaterial.id.in_(
            db.query(ProductComponent.material_id)
            .join(ProductMapping, ProductMapping.id == ProductComponent.mapping_id)
            .filter(ProductMapping.parse_status == "needs_review")
        ))
    total = query.count()
    rows = query.order_by(SemifinishedMaterial.size, SemifinishedMaterial.color_key).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [{
            "id": material.id,
            "material_code": material.material_code,
            "size": material.size,
            "color_code": material.color_code,
            "color_type": material.color_type,
            "safety_stock_grams": material.safety_stock_grams,
            "status": material.status,
            "source": material.source,
            "product_count": int(product_count or 0),
            "on_hand_grams": qty(balance.on_hand_grams if balance else 0),
            "reserved_grams": qty(balance.reserved_grams if balance else 0),
            "available_grams": qty((balance.on_hand_grams if balance else 0) - (balance.reserved_grams if balance else 0)),
        } for material, balance, product_count in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_mappings(db: Session, page: int, page_size: int, keyword: str | None, review_only: bool) -> dict:
    query = db.query(ProductMapping).options(
        selectinload(ProductMapping.components).selectinload(ProductComponent.material)
    )
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            (ProductMapping.product_name.like(like))
            | (ProductMapping.model.like(like))
            | (ProductMapping.color_expression.like(like))
        )
    if review_only:
        query = query.filter(ProductMapping.parse_status == "needs_review")
    total = query.count()
    rows = query.order_by(ProductMapping.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [{
            "id": mapping.id,
            "product_id": mapping.product_id,
            "product_name": mapping.product_name,
            "model": mapping.model,
            "size": mapping.size,
            "color_expression": mapping.color_expression,
            "unit_grams": mapping.unit_grams,
            "parse_status": mapping.parse_status,
            "source": mapping.source,
            "parse_message": mapping.parse_message,
            "components": [{
                "material_id": component.material_id,
                "material_code": component.material.material_code,
                "size": component.material.size,
                "color_code": component.material.color_code,
                "ratio": component.ratio,
                "grams_per_piece": component.grams_per_piece,
            } for component in sorted(mapping.components, key=lambda item: item.component_order)],
        } for mapping in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def update_mapping(db: Session, mapping_id: int, components: list[dict]) -> dict:
    mapping = db.query(ProductMapping).options(selectinload(ProductMapping.components)).filter(ProductMapping.id == mapping_id).one_or_none()
    if mapping is None:
        raise ValueError("产品映射不存在")
    materials = {
        row.id: row for row in db.query(SemifinishedMaterial).filter(
            SemifinishedMaterial.id.in_([item["material_id"] for item in components]),
            SemifinishedMaterial.status == "active",
        ).all()
    }
    if len(materials) != len(components):
        raise ValueError("包含不存在或已停用的半成品")
    mapping.components.clear()
    for index, item in enumerate(components, start=1):
        ratio = Decimal(str(item["ratio"]))
        mapping.components.append(ProductComponent(
            material_id=item["material_id"],
            component_order=index,
            ratio=ratio,
            grams_per_piece=qty(mapping.unit_grams * ratio),
        ))
    mapping.parse_status = "confirmed"
    mapping.source = "manual"
    mapping.parse_message = None
    db.commit()
    return {"id": mapping.id, "parse_status": mapping.parse_status}


def quote_product(db: Session, product_id: int, finished_qty: int) -> dict:
    mapping = (
        db.query(ProductMapping)
        .options(selectinload(ProductMapping.components).selectinload(ProductComponent.material))
        .filter(ProductMapping.source_type == "okki", ProductMapping.product_id == product_id)
        .one_or_none()
    )
    if mapping is None:
        raise ValueError("产品尚未生成半成品关联，请先同步半成品列表")
    if mapping.parse_status != "confirmed":
        raise ValueError("产品半成品配比尚未审核，不能自动计算")
    material_ids = [item.material_id for item in mapping.components]
    balances = {row.material_id: row for row in db.query(InventoryBalance).filter(InventoryBalance.material_id.in_(material_ids)).all()}
    return {
        "mapping_id": mapping.id,
        "product_id": mapping.product_id,
        "product_name": mapping.product_name,
        "unit_grams": mapping.unit_grams,
        "finished_qty": finished_qty,
        "items": [{
            "material_id": component.material_id,
            "material_code": component.material.material_code,
            "size": component.material.size,
            "color_code": component.material.color_code,
            "ratio": component.ratio,
            "grams_per_piece": component.grams_per_piece,
            "suggested_qty_grams": qty(component.grams_per_piece * finished_qty),
            "on_hand_grams": qty(balances.get(component.material_id).on_hand_grams if balances.get(component.material_id) else 0),
            "reserved_grams": qty(balances.get(component.material_id).reserved_grams if balances.get(component.material_id) else 0),
            "available_grams": qty(
                (balances.get(component.material_id).on_hand_grams if balances.get(component.material_id) else 0)
                - (balances.get(component.material_id).reserved_grams if balances.get(component.material_id) else 0)
            ),
        } for component in sorted(mapping.components, key=lambda item: item.component_order)],
    }
