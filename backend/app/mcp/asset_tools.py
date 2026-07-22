"""MCP 工具集 — 素材库检索（标签体系 v2）。

面向内部 agent（个人 token 复用登录 claims）：
  - list_asset_taxonomy: 发现标签词表（维度/值/英文别名/用法说明）
  - search_assets: 按维度组合检索素材，返回签名下载 URL

设计要点（方案 4.3 节）：
  - 参数是自由字符串，运行时对标签库做 value/name_en/aliases 三路解析，
    不做静态 enum（FastMCP schema 在启动时固化，动态枚举会漂移）
  - 产品族值（发帘类等）自动展开全部子级
  - 数据范围过滤 AssetPermission：permission_group=all / specific(含本人) 可见，
    design_dept/sales 分组仅 super_admin 或 asset:admin 可见（用户部门未进 claims，
    收紧处理），allow_preview=0 一律不可见
"""

import json
import logging
from contextlib import contextmanager

from pydantic import BaseModel, ConfigDict, Field
from mcp.server.fastmcp import Context

from app.core.database import SessionLocal
from app.mcp.auth import require_identity, MCPAuthError

logger = logging.getLogger("commission.mcp.asset_tools")

# agent 异步消费场景放宽签名 URL 有效期（Web 端默认 2 小时）
MCP_SIGNED_URL_EXPIRY = 24 * 3600

SEARCHABLE_DIMS = (
    "content_category", "content_type", "product_type", "color_code",
    "color_family", "texture", "shoot_style", "process_step", "theme",
    "year", "media_trait",
)

DIM_USAGE_HINTS = {
    "content_category": "素材内容的顶层分类；回答「这张素材拍的是什么」",
    "content_type": "内容细分，挂靠内容大类",
    "product_type": "涉及的产品；族级值（发帘类/贴发类/接发条类/卡子发类）自动包含全部子型号",
    "color_code": "具体色号，如 #1B、#8TP8-18",
    "color_family": "色系（黑/棕/金/红/挑染/渐变等），比色号更宽的颜色检索入口",
    "year": "拍摄年份，如 2024年（传 2024 也可）",
}


@contextmanager
def _session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _err(message: str, **extra) -> str:
    return json.dumps({"ok": False, "error": message, **extra}, ensure_ascii=False)


def _ok(data: dict) -> str:
    return json.dumps({"ok": True, **data}, ensure_ascii=False, default=str, indent=2)


def _norm(s: str) -> str:
    return s.lower().replace(" ", "").strip()


def _visible_dims(db) -> list[dict]:
    from app.asset.tag_service import list_dimensions_cached
    return [d for d in list_dimensions_cached(db)
            if d.get("is_visible", 1) and d["name"] in SEARCHABLE_DIMS]


def _resolve_values(dim: dict, raw: str) -> tuple[list[int], list[str]]:
    """逗号分隔的自由文本 → 标签值 id 列表；族值展开子级。

    Returns: (匹配到的 id 列表, 未匹配的原文列表)
    """
    index: dict[str, dict] = {}
    children: dict[int, list[int]] = {}
    for v in dim["values"]:
        if not v.get("is_active", 1):
            continue
        for cand in [v["value"], v.get("name_en")] + list(v.get("aliases") or []):
            if cand:
                index.setdefault(_norm(str(cand)), v)
        if v.get("parent_value_id"):
            children.setdefault(v["parent_value_id"], []).append(v["id"])

    ids: list[int] = []
    misses: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        hit = index.get(_norm(token))
        if hit is None and dim["name"] == "year" and token.isdigit():
            hit = index.get(_norm(token + "年"))
        if hit is None:
            misses.append(token)
            continue
        ids.append(hit["id"])
        ids.extend(children.get(hit["id"], []))  # 族值/父级展开子级
    return list(dict.fromkeys(ids)), misses


def _suggest(dim: dict, token: str) -> list[str]:
    """给未命中的输入找最相近候选（简单包含匹配，够用）。"""
    t = _norm(token)
    out = []
    for v in dim["values"]:
        cands = [v["value"], v.get("name_en")] + list(v.get("aliases") or [])
        if any(c and (t in _norm(str(c)) or _norm(str(c)) in t) for c in cands):
            out.append(v["value"])
    return out[:5]


def _permission_visible(asset, user: dict) -> bool:
    """MCP 数据范围：见模块 docstring。"""
    perm = asset.permissions
    if perm is None:
        return True
    if not perm.allow_preview:
        return False
    group = perm.permission_group or "all"
    if group == "all":
        return True
    if "super_admin" in user.get("roles", []) or "asset:admin" in set(user.get("permissions", [])):
        return True
    if group == "specific":
        try:
            uid = int(user.get("sub", 0))
        except (TypeError, ValueError):
            return False
        return uid in (perm.specified_user_ids or [])
    return False  # design_dept / sales：部门信息未进 claims，收紧为不可见


# ── 输入模型 ──────────────────────────────────────────────

class SearchAssetsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content_category: str = Field(default="", description="内容大类，如 产品素材/公司活动")
    content_type: str = Field(default="", description="内容子类，如 产品展示/年会/详情页")
    product_type: str = Field(default="", description="产品类型，中英皆可，如 天才发帘 / Genius Weft / Tape-in；族级值自动含子型号；多值逗号分隔")
    color_code: str = Field(default="", description="色号，如 #1B；多值逗号分隔")
    color_family: str = Field(default="", description="色系，如 金色系 / Blonde / 渐变")
    texture: str = Field(default="", description="纹理造型，如 直发 / Body Wave / Curly")
    shoot_style: str = Field(default="", description="拍摄风格，如 白底图 / INS风 / 模特佩戴")
    process_step: str = Field(default="", description="工艺环节，如 跑帘子 / 漂染")
    theme: str = Field(default="", description="节日营销主题，如 圣诞节 / 万圣节 / 新贸节")
    year: str = Field(default="", description="年份，如 2024 或 2024年")
    media_trait: str = Field(default="", description="媒体特性，如 带字幕 / 未压缩原片")
    file_type: str = Field(default="", description="文件类型 image 或 video，留空不限")
    orientation: str = Field(default="", description="画幅 landscape/portrait/square，留空不限")
    keyword: str = Field(default="", description="文件名/备注模糊关键词")
    limit: int = Field(default=20, ge=1, le=100, description="返回条数上限")


class ListTaxonomyInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# ── 工具注册 ──────────────────────────────────────────────

def register_asset_tools(mcp) -> None:
    """把素材域 2 个工具注册到传入的 FastMCP 实例。"""

    @mcp.tool(
        name="list_asset_taxonomy",
        annotations={
            "title": "素材库标签词表",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": False,
        },
    )
    async def list_asset_taxonomy(params: ListTaxonomyInput, ctx: Context) -> str:
        """返回素材库全部可检索维度与值域（含英文别名与用法说明）。

        先调用本工具了解词表，再用 search_assets 按维度组合检索。

        Returns: {"ok": true, "dimensions": [{name, label, single_select, usage, values:
                  [{value, name_en, aliases, parent}]}]}
        """
        with _session() as db:
            try:
                user = require_identity(ctx, db)
            except MCPAuthError as e:
                return _err(str(e))
            if not {"asset:read"} & set(user.get("permissions", [])) and "super_admin" not in user.get("roles", []):
                return _err("权限不足：需要 asset:read 权限，请联系管理员分配")

            dims_out = []
            for d in _visible_dims(db):
                id2val = {v["id"]: v["value"] for v in d["values"]}
                dims_out.append({
                    "name": d["name"],
                    "label": d["label"],
                    "single_select": bool(d["is_single_select"]),
                    "usage": DIM_USAGE_HINTS.get(d["name"], ""),
                    "values": [{
                        "value": v["value"],
                        "name_en": v.get("name_en"),
                        "aliases": v.get("aliases") or [],
                        "parent": id2val.get(v.get("parent_value_id")),
                    } for v in d["values"] if v.get("is_active", 1)],
                })
            return _ok({"dimensions": dims_out})

    @mcp.tool(
        name="search_assets",
        annotations={
            "title": "检索素材库",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": False,
        },
    )
    async def search_assets(params: SearchAssetsInput, ctx: Context) -> str:
        """按标签维度组合检索素材，返回素材信息与 24 小时有效的签名下载 URL。

        维度参数值用中文规范值或英文别名均可，多值逗号分隔（同维度 OR、跨维度 AND）。
        值不认识时会报错并给出相近候选；完整词表用 list_asset_taxonomy 查看。

        Returns:
          成功: {"ok": true, "total": int, "count": int, "items": [{id, file_name,
                 file_type, orientation, tags: {维度label: [值]}, download_url}]}
          值无法解析: {"ok": false, "error": "...", "unresolved": [...], "suggestions": {...}}
        """
        with _session() as db:
            try:
                user = require_identity(ctx, db)
            except MCPAuthError as e:
                return _err(str(e))
            if not {"asset:read"} & set(user.get("permissions", [])) and "super_admin" not in user.get("roles", []):
                return _err("权限不足：需要 asset:read 权限，请联系管理员分配")

            dims = {d["name"]: d for d in _visible_dims(db)}
            tag_filters: dict[str, list[int]] = {}
            unresolved: list[str] = []
            suggestions: dict[str, list[str]] = {}

            for dim_name in SEARCHABLE_DIMS:
                raw = getattr(params, dim_name, "")
                if not raw:
                    continue
                dim = dims.get(dim_name)
                if dim is None:
                    unresolved.append(f"{dim_name}（维度当前不可用）")
                    continue
                ids, misses = _resolve_values(dim, raw)
                for m in misses:
                    unresolved.append(f"{dim_name}={m}")
                    sug = _suggest(dim, m)
                    if sug:
                        suggestions[m] = sug
                if ids:
                    tag_filters[dim_name] = ids

            if unresolved:
                return _err(
                    "以下标签值无法解析，请对照 list_asset_taxonomy 的词表调整",
                    unresolved=unresolved, suggestions=suggestions,
                )

            from app.asset.asset_service import query_assets, get_asset_download_url

            try:
                total, items, _avail = query_assets(
                    db,
                    file_type=params.file_type or None,
                    tag_filters=tag_filters or None,
                    keyword=params.keyword or None,
                    status="latest",
                    page=1,
                    # 权限过滤在结果侧做，多取一页余量避免过滤后不足 limit
                    page_size=min(params.limit * 3, 300),
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("MCP search_assets 失败: %s", e)
                print(f"[mcp.asset_tools] search_assets failed err={e}", flush=True)
                return _err("检索失败，请稍后重试")

            out = []
            for a in items:
                if params.orientation and a.orientation != params.orientation:
                    continue
                if not _permission_visible(a, user):
                    continue
                tags_by_dim: dict[str, list[str]] = {}
                for tv in (a.tags or []):
                    tags_by_dim.setdefault(tv.dimension.label, []).append(tv.value)
                out.append({
                    "id": a.id,
                    "file_name": a.file_name,
                    "file_type": a.file_type,
                    "file_format": a.file_format,
                    "orientation": a.orientation,
                    "created_at": a.created_at,
                    "tags": tags_by_dim,
                    "download_url": get_asset_download_url(a, expiry_seconds=MCP_SIGNED_URL_EXPIRY),
                })
                if len(out) >= params.limit:
                    break

            return _ok({"total": total, "count": len(out), "items": out})
