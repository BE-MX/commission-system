"""Validated display-only overrides with transactional compare-and-swap publishing."""
import hashlib
import json
import logging
import re
import unicodedata
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import get_live_user_authorization
from app.core.time import beijing_now
from app.system.navigation_config_models import NavigationConfig, NavigationVersion, NavigationConfigAudit

logger = logging.getLogger("commission")
CATALOG_PATH = Path(__file__).with_name("navigation_config_catalog.json")
SOURCE_PATH = Path(__file__).resolve().parents[3] / "frontend/src/config/navigation.js"
FIELDS = {"id", "kind", "label", "icon", "parent", "order", "visible", "badge", "badgePlace", "badgeTone", "titleSync"}
READONLY = {"builtin", "protected", "path", "rule", "business", "phase", "entry_key", "sourceGroup", "external"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def catalog():
    try:
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        if raw.get("source_sha256") != hashlib.sha256(SOURCE_PATH.read_text(encoding="utf-8").encode()).hexdigest():
            raise ValueError("stale navigation catalog")
        if not raw.get("nodes") or not raw.get("icons"):
            raise ValueError("empty navigation catalog")
        return {"nodes": raw["nodes"], "icons": raw["icons"], "catalog_hash": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()}
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("Navigation catalog unavailable: %s", exc)
        print(f"[navigation] catalog unavailable: {exc}", flush=True)
        raise HTTPException(503, "导航注册目录不可用，请重新构建前端") from exc


def authorize(db, user, permission):
    roles, permissions = get_live_user_authorization(db, int(user["sub"]))
    if "super_admin" not in roles and permission not in permissions:
        raise HTTPException(403, "导航管理权限已撤销或不足")


def invalid(message):
    raise HTTPException(422, message)


def normalize(nodes, cat):
    sources = {n["id"]: n for n in cat["nodes"]}
    result = []
    ids = set()
    for item in nodes:
        if set(item) - FIELDS - READONLY:
            invalid("包含不可编辑的导航字段")
        key = item.get("id")
        if not isinstance(key, str) or (key not in sources and not re.fullmatch(r"custom-[A-Za-z0-9-]{1,90}", key)) or key in ids:
            invalid("导航标识无效或重复")
        ids.add(key)
        source = sources.get(key)
        for field in READONLY & item.keys():
            if source is None or item[field] != source.get(field):
                invalid("不能修改导航来源策略")
        if source is None and (item.get("kind") != "group" or not key.startswith("custom-")):
            invalid("只能创建 custom- 标识的自建分类")
        n = {field: item.get(field) for field in FIELDS}
        if n["kind"] not in ("group", "page") or (source and n["kind"] != source["kind"]):
            invalid("导航类型不可更改")
        if not isinstance(n["label"], str):
            invalid("导航名称必须是文本")
        n["label"] = n["label"].strip()
        if not 1 <= len(n["label"]) <= 24 or any(unicodedata.category(c).startswith("C") for c in n["label"]):
            invalid("导航名称须为1–24个可见字符")
        if not isinstance(n["icon"], str) or n["icon"] not in cat["icons"]:
            invalid("图标未注册")
        if not isinstance(n["parent"], str) or type(n["order"]) is not int or not 0 <= n["order"] <= 100000:
            invalid("归属分类或排序无效")
        if type(n["visible"]) is not bool or type(n["titleSync"]) is not bool:
            invalid("显示与标题同步必须为布尔值")
        if not isinstance(n["badge"], str) or len(n["badge"]) > 8 or any(unicodedata.category(c).startswith("C") for c in n["badge"]):
            invalid("文字角标最多8个可见字符")
        if n["badgePlace"] not in ("text", "icon") or n["badgeTone"] not in ("gold", "blue", "neutral"):
            invalid("角标样式无效")
        if source and source["kind"] == "group" and n["parent"] != source["parent"]:
            invalid("内置分类不可移动，只有自建分类可修改归属")
        if source and source.get("protected") and (not n["visible"] or n["parent"] != source["parent"]):
            invalid("受保护导航不可隐藏或移动")
        result.append(n)
    if set(sources) - ids:
        invalid("内置导航不可删除")
    lookup = {n["id"]: n for n in result}
    siblings = set()
    for n in result:
        duplicate = (n["parent"], unicodedata.normalize("NFKC", n["label"]).casefold())
        if duplicate in siblings:
            invalid("同级导航名称重复")
        siblings.add(duplicate)
        parent = n["parent"]
        visited = {n["id"]}
        depth = int(n["kind"] == "group")
        while parent:
            if parent not in lookup or lookup[parent]["kind"] != "group" or parent in visited:
                invalid("归属分类不存在、形成循环或挂在页面下")
            visited.add(parent)
            depth += 1
            parent = lookup[parent]["parent"]
        if depth > 2:
            invalid("分类最多两级")
        if sources.get(n["id"], {}).get("external") and not n["parent"]:
            invalid("外部入口必须位于分类下")
    return result


def defaults(cat):
    return [{k: n[k] for k in FIELDS} for n in cat["nodes"]]


def state(db, cat):
    row = db.get(NavigationConfig, 1)
    return row


def get_draft(db):
    cat = catalog()
    row = state(db, cat)
    nodes = row.draft_nodes if row else defaults(cat)
    ids = {n["id"] for n in nodes}
    nodes = nodes + [n for n in defaults(cat) if n["id"] not in ids]
    return {"nodes": nodes, "draft_revision": row.draft_revision if row else 0,
            "base_version": row.base_version if row else 0, "catalog_hash": cat["catalog_hash"]}


def differences(before, after):
    old = {n["id"]: n for n in before}
    new = {n["id"]: n for n in after}
    return [{"id": key, "before": old.get(key), "after": new.get(key)} for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]


def ensure_state(db, cat):
    row = state(db, cat)
    if row is None:
        # A savepoint handles simultaneous first saves without aborting the outer transaction.
        try:
            with db.begin_nested():
                db.add(NavigationConfig(id=1, draft_nodes=defaults(cat), draft_revision=0, current_version=0,
                                        base_version=0, catalog_hash=cat["catalog_hash"], updated_by=0))
                db.flush()
        except IntegrityError:
            logger.warning("Concurrent navigation initialization; using winning row")
            print("[navigation] concurrent initialization", flush=True)
        # A locking current read bypasses an older MySQL REPEATABLE READ snapshot.
        # The losing INSERT may see a committed singleton that plain get() cannot see yet.
        row = db.execute(select(NavigationConfig).where(NavigationConfig.id == 1)
                         .with_for_update().execution_options(populate_existing=True)).scalar_one()
    return row


def cas(db, payload, cat, values):
    if payload.catalog_hash != cat["catalog_hash"]:
        raise HTTPException(409, "导航注册目录已更新，请重新加载")
    ensure_state(db, cat)
    count = db.execute(update(NavigationConfig).where(
        NavigationConfig.id == 1, NavigationConfig.draft_revision == payload.draft_revision,
        NavigationConfig.base_version == payload.base_version,
        NavigationConfig.current_version == payload.base_version,
    ).values(**values).execution_options(synchronize_session=False)).rowcount
    if count != 1:
        db.rollback()
        raise HTTPException(409, "共享草稿或已发布版本已更新，请比较后重试")


def audit(db, action, user_id, payload, new_version, changes):
    db.add(NavigationConfigAudit(action=action, actor_id=user_id, old_version=payload.base_version,
                                new_version=new_version, draft_revision=payload.draft_revision + 1, changes=changes))


def commit(db):
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Navigation transaction failed", exc_info=True)
        print("[navigation] transaction failed; rolled back", flush=True)
        raise


def save_draft(db, payload, user_id, action="save", nodes=None):
    cat = catalog()
    clean = normalize(payload.nodes if nodes is None else nodes, cat)
    previous = get_draft(db)["nodes"]
    # Deleting a custom group is permitted only if it was already empty.
    deleted = {n["id"] for n in previous} - {n["id"] for n in clean}
    if action == "save" and any(n["parent"] in deleted for n in previous):
        invalid("非空自建分类须先迁移并保存子项，才能删除")
    cas(db, payload, cat, {"draft_nodes": clean, "draft_revision": payload.draft_revision + 1,
                          "catalog_hash": cat["catalog_hash"], "updated_by": user_id, "updated_at": beijing_now()})
    audit(db, action, user_id, payload, payload.base_version, differences(previous, clean))
    commit(db)
    db.expire_all()
    return get_draft(db)


def serialize_version(row):
    return {"id": row.id, "version": row.version, "nodes": row.nodes, "catalog_hash": row.catalog_hash,
            "created_by": row.created_by, "created_at": row.created_at.isoformat(), "changes": row.changes}


def publish(db, payload, user_id):
    fingerprint = digest({"actor": user_id, **payload.model_dump(exclude={"request_id"})})
    existing = db.query(NavigationVersion).filter_by(request_id=payload.request_id).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "发布请求标识已用于其他请求")
        return serialize_version(existing)
    cat = catalog()
    row = ensure_state(db, cat)
    clean = normalize(get_draft(db)["nodes"], cat)
    previous = db.query(NavigationVersion).filter_by(version=row.current_version).first()
    changes = differences(previous.nodes if previous else defaults(cat), clean)
    new_version = payload.base_version + 1
    try:
        cas(db, payload, cat, {"current_version": new_version, "base_version": new_version,
                              "draft_revision": payload.draft_revision + 1, "catalog_hash": cat["catalog_hash"],
                              "updated_by": user_id, "updated_at": beijing_now()})
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        # A concurrent retry may have committed this exact idempotency key while CAS waited.
        existing = db.query(NavigationVersion).filter_by(request_id=payload.request_id).first()
        if existing and existing.request_fingerprint == fingerprint:
            return serialize_version(existing)
        raise
    version = NavigationVersion(version=new_version, nodes=clean, catalog_hash=cat["catalog_hash"],
                                request_id=payload.request_id, request_fingerprint=fingerprint, created_by=user_id, changes=changes)
    db.add(version)
    audit(db, "publish", user_id, payload, new_version, changes)
    commit(db)
    return serialize_version(version)


def versions(db):
    cat = catalog()
    baseline = {"id": 0, "version": 0, "nodes": defaults(cat), "catalog_hash": cat["catalog_hash"],
                "created_by": None, "created_at": None, "changes": [], "description": "当前构建默认导航（注册目录更新时同步变化）"}
    return {"items": [serialize_version(v) for v in db.query(NavigationVersion).order_by(NavigationVersion.version.desc()).all()] + [baseline]}


def restore(db, version_id, payload, user_id):
    if version_id == 0:
        return save_draft(db, payload, user_id, action="restore", nodes=defaults(catalog()))
    version = db.get(NavigationVersion, version_id)
    if version is None:
        raise HTTPException(404, "导航版本不存在")
    cat = catalog()
    current_ids = {n["id"] for n in version.nodes}
    # Newly registered entries are appended at source defaults; retired references fail validation.
    nodes = version.nodes + [n for n in defaults(cat) if n["id"] not in current_ids]
    return save_draft(db, payload, user_id, action="restore", nodes=nodes)


def effective(db):
    cat = catalog()
    row = state(db, cat)
    version = db.query(NavigationVersion).filter_by(version=row.current_version).first() if row else None
    nodes = version.nodes if version else defaults(cat)
    ids = {n["id"] for n in nodes}
    nodes = nodes + [n for n in defaults(cat) if n["id"] not in ids]
    # Only display fields cross the authenticated-user boundary; source access policy stays in code.
    return {"version": version.version if version else 0, "nodes": nodes, "catalog_hash": cat["catalog_hash"]}
