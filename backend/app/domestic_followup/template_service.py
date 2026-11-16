import re

from sqlalchemy.orm import Session

from app.domestic_followup.template_models import DomesticFollowupTemplate

FIELD_KINDS = {"text", "textarea", "select", "multiselect", "amount", "date", "event"}
NATURES = {"customer_said", "business_fact", "assessment", "to_confirm"}
PARAM_RANGES = {"prep_minutes", "talk_minutes", "wechat_sentences", "recontact_workdays"}


class TemplateConflictError(Exception):
    pass


def serialize(row: DomesticFollowupTemplate) -> dict:
    return {
        "code": row.code, "version": row.version, "name": row.name, "status": row.status,
        "prep_fields": row.prep_fields or [], "record_fields": row.record_fields or [],
        "short_form": row.short_form, "guidance": row.guidance, "params": row.params or {},
        "avoid": row.avoid or [], "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_active(db: Session) -> list[dict]:
    rows = (db.query(DomesticFollowupTemplate).filter(DomesticFollowupTemplate.status == "active")
            .order_by(DomesticFollowupTemplate.code).all())
    return [serialize(row) for row in rows]


def get_template(db: Session, code: str, version: int | None = None) -> DomesticFollowupTemplate:
    query = db.query(DomesticFollowupTemplate).filter(DomesticFollowupTemplate.code == code.upper())
    if version is None:
        query = query.filter(DomesticFollowupTemplate.status == "active")
    else:
        query = query.filter(DomesticFollowupTemplate.version == version)
    row = query.first()
    if row is None:
        raise LookupError("跟进模板不存在或已停用")
    return row


def versions(db: Session, code: str) -> list[dict]:
    rows = (db.query(DomesticFollowupTemplate).filter(DomesticFollowupTemplate.code == code.upper())
            .order_by(DomesticFollowupTemplate.version.desc()).all())
    if not rows:
        raise LookupError("跟进模板不存在")
    return [serialize(row) for row in rows]


def _validate_fields(groups) -> None:
    for fields in groups:
        keys = set()
        for field in fields:
            data = field.model_dump() if hasattr(field, "model_dump") else dict(field)
            key = data.get("key") or ""
            if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in keys:
                raise ValueError("字段 key 必须唯一且使用小写 snake_case")
            keys.add(key)
            if data.get("kind") not in FIELD_KINDS or not (data.get("label") or "").strip():
                raise ValueError("字段名称或类型不合法")
            if data.get("emphasis") not in ("key", "more"):
                raise ValueError("字段展示方式不合法")
            if data.get("nature") is not None and data["nature"] not in NATURES:
                raise ValueError("字段默认性质不合法")
            options = data.get("options")
            if options is not None:
                if set(options) - {"inline", "dict"} or not (options.get("inline") or options.get("dict")):
                    raise ValueError("字段选项只支持 inline 或 dict")
                if "inline" in options and (not isinstance(options["inline"], list)
                                           or not all(isinstance(v, str) and v.strip() for v in options["inline"])):
                    raise ValueError("inline 选项必须是非空文字列表")


def _validate_params(params: dict) -> None:
    if set(params) - PARAM_RANGES:
        raise ValueError("模板时长参数不合法")
    for value in params.values():
        if (not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, int) and v > 0 for v in value)
                or value[0] > value[1]):
            raise ValueError("模板参数必须是正整数范围")


def save_new_version(db: Session, code: str, payload, user_id: int) -> DomesticFollowupTemplate:
    code = code.upper()
    _validate_fields((payload.prep_fields, payload.record_fields))
    _validate_params(payload.params)
    current = (db.query(DomesticFollowupTemplate).filter(DomesticFollowupTemplate.code == code,
               DomesticFollowupTemplate.status == "active").populate_existing().with_for_update().first())
    if current is None:
        raise LookupError("跟进模板不存在或已停用")
    if current.version != payload.version:
        raise TemplateConflictError("模板已被他人修改，请刷新后再保存")
    current.status = "retired"
    values = payload.model_dump(exclude={"version"})
    row = DomesticFollowupTemplate(code=code, version=current.version + 1, status="active",
                                   updated_by=user_id, **values)
    db.add(row)
    db.flush()
    return row
