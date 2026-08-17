"""提示词模板库与参考图库（公/私库）领域服务。

口径：
- 提示词模板：后台预置完整提示词，content 内 {key} 为参数占位；
  用户在前端选择参数取值后本地拼装，管理与种子导入仅 design_image:admin。
- 参考图库：scope=public 公库全员可见可用（上传/删除仅 admin）；
  scope=private 私库仅创建者本人可见可用（业务员为自己的客户备的私图）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.color.models import PantoneReference
from app.design_image import file_service
from app.design_image.models import (
    DesignImageAsset,
    DesignImageLibraryAsset,
    DesignImagePromptTemplate,
)
from app.design_image.schemas import PromptTemplateUpsert
from app.design_image.service import (
    AssetContent,
    DesignImageConsistencyError,
    DesignImageValidationError,
    _delete_files_best_effort,
    _not_found,
    _owner_session,
    _thumbnail_path,
    _utc_naive,
)

LIBRARY_SCOPES = ("public", "private")
_SUFFIX_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# ── 预置提示词模板（幂等种子，按 name 查重） ──
_PROMPT_TEMPLATE_SEED: list[dict] = [
    {
        "category": "刀版图生成包装效果图",
        "name": "通用刀版包装效果图",
        "content": (
            "根据上传的包装刀版图生成真实包装效果图。严格按照刀版中的结构、尺寸比例、"
            "图文位置、配色、开窗和折叠关系完成包装成型；包装材质为{material}，"
            "表面工艺为{finish}，以{display}展示。成品中不要出现刀线、折线、出血线、"
            "尺寸标注或其他辅助线，背景简洁，光影自然，输出高质量商业产品效果图"
        ),
        "options": [
            {
                "key": "material",
                "label": "包装材质",
                "choices": ["白卡纸", "牛皮纸", "瓦楞纸", "透明PVC", "磨砂塑料"],
            },
            {
                "key": "finish",
                "label": "表面工艺",
                "choices": ["哑光覆膜", "亮光覆膜", "烫金", "烫银", "局部UV", "无特殊工艺"],
            },
            {
                "key": "display",
                "label": "展示方式",
                "choices": ["单个包装45°视角", "正反面组合", "多个包装陈列场景"],
            },
        ],
        "sort": 0,
    },
    {
        "category": "product",
        "name": "白底产品图",
        "content": (
            "为图中的假发产品生成一张电商主图：{background}背景，产品居中完整呈现，"
            "保持发丝质感与颜色真实，{lighting}，高清商业摄影风格"
        ),
        "options": [
            {"key": "background", "label": "背景", "choices": ["纯白", "极浅灰", "暖米白"]},
            {"key": "lighting", "label": "光线", "choices": ["顶部柔光箱", "45°侧光带轻微阴影", "均匀无影光"]},
        ],
        "sort": 10,
    },
    {
        "category": "scene",
        "name": "佩戴场景图",
        "content": (
            "将图中的假发产品自然地融入{scene}场景中，模特佩戴效果真实，"
            "发丝与场景光影一致，景深浅、主体清晰，{style}，广告级成片质感"
        ),
        "options": [
            {"key": "scene", "label": "场景", "choices": ["高端美发沙龙", "简约居家梳妆台", "时尚街拍", "展会展台"]},
            {"key": "style", "label": "风格", "choices": ["暖调高级灰", "清新自然", "杂志大片感"]},
        ],
        "sort": 20,
    },
    {
        "category": "poster",
        "name": "海报主视觉",
        "content": (
            "以图中产品为主角生成一张{theme}主题的营销海报主视觉，{palette}色调，"
            "构图在顶部留出文案区，画面高级有呼吸感，画面中不要出现任何文字"
        ),
        "options": [
            {"key": "theme", "label": "主题", "choices": ["新品上市", "节日促销", "品牌会员日"]},
            {"key": "palette", "label": "色调", "choices": ["暖金奢华", "柔和粉彩", "高级黑白灰"]},
        ],
        "sort": 30,
    },
    {
        "category": "detail",
        "name": "细节特写图",
        "content": (
            "为图中假发产品生成细节特写图：聚焦{focus}部位，展现{aspect}，"
            "微距质感、纤维根根分明，浅色干净背景"
        ),
        "options": [
            {"key": "focus", "label": "部位", "choices": ["发际线/蕾丝网底", "发尾", "内网工艺"]},
            {"key": "aspect", "label": "卖点", "choices": ["手工钩织的精密工艺", "发丝光泽与柔顺度", "透气轻盈的结构"]},
        ],
        "sort": 40,
    },
    {
        "category": "restyle",
        "name": "换背景（保持主体）",
        "content": (
            "保持图中产品主体与造型完全不变，仅将背景替换为{background}，"
            "边缘抠图干净自然，光影与新环境一致"
        ),
        "options": [
            {"key": "background", "label": "新背景", "choices": ["纯白", "浅灰渐变", "暖米色摄影棚", "轻奢大理石台面"]},
        ],
        "sort": 50,
    },
]


# ── 提示词模板 ─────────────────────────────────

def seed_prompt_templates(db: Session) -> dict:
    """按 name 幂等导入预置模板；已存在的同名模板仅补齐缺省字段，不覆盖人工修改。"""
    created, skipped = 0, 0
    for item in _PROMPT_TEMPLATE_SEED:
        existing = (
            db.query(DesignImagePromptTemplate)
            .filter(DesignImagePromptTemplate.name == item["name"])
            .first()
        )
        if existing is not None:
            skipped += 1
            continue
        db.add(DesignImagePromptTemplate(**item, is_active=True))
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped, "total": len(_PROMPT_TEMPLATE_SEED)}


def list_prompt_templates(db: Session, *, include_inactive: bool = False) -> list[DesignImagePromptTemplate]:
    statement = db.query(DesignImagePromptTemplate)
    if not include_inactive:
        statement = statement.filter(DesignImagePromptTemplate.is_active.is_(True))
    return statement.order_by(DesignImagePromptTemplate.sort, DesignImagePromptTemplate.id).all()


def create_prompt_template(db: Session, payload: PromptTemplateUpsert) -> DesignImagePromptTemplate:
    row = DesignImagePromptTemplate(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_prompt_template(
    db: Session, template_id: int, payload: PromptTemplateUpsert
) -> DesignImagePromptTemplate:
    row = db.get(DesignImagePromptTemplate, template_id)
    if row is None:
        raise _not_found()
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def delete_prompt_template(db: Session, template_id: int) -> None:
    row = db.get(DesignImagePromptTemplate, template_id)
    if row is None:
        raise _not_found()
    row.is_active = False
    db.commit()


# ── 参考图库 ─────────────────────────────────

def _visible_library_asset(
    db: Session, owner_user_id: int, asset_id: int
) -> DesignImageLibraryAsset:
    row = db.get(DesignImageLibraryAsset, asset_id)
    if row is None or row.deleted_at is not None:
        raise _not_found()
    if row.scope == "private" and row.owner_user_id != owner_user_id:
        # 与随机不存在 ID 同为 404，不泄露他人私库存在性
        raise _not_found()
    return row


def list_library_assets(
    db: Session, owner_user_id: int, scope: str
) -> list[DesignImageLibraryAsset]:
    if scope not in LIBRARY_SCOPES:
        raise DesignImageValidationError("图库范围无效")
    statement = db.query(DesignImageLibraryAsset).filter(
        DesignImageLibraryAsset.deleted_at.is_(None),
        DesignImageLibraryAsset.scope == scope,
    )
    if scope == "private":
        statement = statement.filter(DesignImageLibraryAsset.owner_user_id == owner_user_id)
    return statement.order_by(DesignImageLibraryAsset.created_at.desc(), DesignImageLibraryAsset.id.desc()).all()


def create_library_asset(
    db: Session,
    owner_user_id: int,
    content: bytes,
    declared_mime: str,
    scope: str,
    title: str,
) -> DesignImageLibraryAsset:
    if scope not in LIBRARY_SCOPES:
        raise DesignImageValidationError("图库范围无效")
    normalized = file_service.normalize_upload(content, declared_mime)
    stored = file_service.save_private_image(
        normalized, owner_user_id=owner_user_id, kind="library"
    )
    try:
        row = DesignImageLibraryAsset(
            scope=scope,
            owner_user_id=owner_user_id,
            title=(title or "").strip()[:200],
            storage_path=stored.relative_path,
            mime_type=stored.mime_type,
            file_size=stored.file_size,
            width=stored.width,
            height=stored.height,
            sha256=stored.sha256,
            created_by=owner_user_id,
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        _delete_files_best_effort(
            [stored.relative_path, stored.thumbnail_relative_path], "library database rollback"
        )
        raise
    db.refresh(row)
    return row


def delete_library_asset(
    db: Session, owner_user_id: int, asset_id: int, *, is_admin: bool
) -> None:
    row = db.get(DesignImageLibraryAsset, asset_id)
    if row is None or row.deleted_at is not None:
        raise _not_found()
    if row.scope == "public":
        if not is_admin:
            raise DesignImageValidationError("公库图片仅管理员可以删除")
    elif not is_admin and row.owner_user_id != owner_user_id:
        # 与随机不存在 ID 同为 404，不泄露他人私库存在性
        raise _not_found()
    row.deleted_at = _utc_naive()
    db.commit()
    _delete_files_best_effort(
        [row.storage_path, _thumbnail_path(row.storage_path)], "library delete"
    )


def open_library_asset_content(
    db: Session,
    owner_user_id: int,
    asset_id: int,
    *,
    thumbnail: bool = False,
) -> AssetContent:
    """可见性校验后原子打开图库图片用于流式返回。"""
    row = _visible_library_asset(db, owner_user_id, asset_id)
    relative_path = _thumbnail_path(row.storage_path) if thumbnail else row.storage_path
    try:
        path = file_service.resolve_private_path(relative_path)
    except file_service.ImageStorageError as exc:
        raise DesignImageConsistencyError("图片存储暂不可用，请稍后重试") from exc
    suffix = _SUFFIX_BY_MIME.get(row.mime_type)
    if suffix is None:
        raise DesignImageConsistencyError("图片格式记录异常，请联系管理员")
    try:
        stream = path.open("rb")
    except (FileNotFoundError, IsADirectoryError):
        raise _not_found() from None
    except OSError as exc:
        raise DesignImageConsistencyError("图片存储暂不可用，请稍后重试") from exc
    return AssetContent(stream=stream, mime_type=row.mime_type, suffix=suffix)


def clone_library_asset_to_session(
    db: Session,
    owner_user_id: int,
    asset_id: int,
    session_id: int,
    *,
    now: datetime | None = None,
) -> DesignImageAsset:
    """把图库图片复制为指定会话的草稿资产，供 base_asset_id 走现有生成链路。"""
    row = _visible_library_asset(db, owner_user_id, asset_id)
    session = _owner_session(db, owner_user_id, session_id)
    try:
        source_path = file_service.resolve_private_path(row.storage_path)
        content = source_path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        raise _not_found() from None
    except (OSError, file_service.ImageStorageError) as exc:
        raise DesignImageConsistencyError("图片存储暂不可用，请稍后重试") from exc
    normalized = file_service.NormalizedImage(
        content=content,
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        sha256=row.sha256,
    )
    stored = file_service.save_private_image(
        normalized, owner_user_id=owner_user_id, kind="upload"
    )
    try:
        asset = DesignImageAsset(
            session_id=session.id,
            asset_type="upload",
            storage_path=stored.relative_path,
            mime_type=stored.mime_type,
            file_size=stored.file_size,
            width=stored.width,
            height=stored.height,
            sha256=stored.sha256,
            status="draft",
            expires_at=_utc_naive(now) + timedelta(
                hours=get_settings().DESIGN_IMAGE_DRAFT_TTL_HOURS
            ),
            created_by=owner_user_id,
        )
        db.add(asset)
        db.commit()
    except Exception:
        db.rollback()
        _delete_files_best_effort(
            [stored.relative_path, stored.thumbnail_relative_path], "library clone rollback"
        )
        raise
    db.refresh(asset)
    return asset


# ── 潘通色卡 ─────────────────────────────────

def list_pantone_colors(db: Session) -> list[dict]:
    """提示词颜色参数的色卡库数据源：复用色彩模块的 Pantone 参考库。"""
    rows = (
        db.query(PantoneReference)
        .filter(PantoneReference.collection == "coated")
        .order_by(PantoneReference.pantone_code)
        .all()
    )
    return [
        {"code": row.pantone_code, "name": row.pantone_name, "hex": row.hex_code}
        for row in rows
    ]


__all__ = [
    "LIBRARY_SCOPES",
    "clone_library_asset_to_session",
    "create_library_asset",
    "create_prompt_template",
    "delete_library_asset",
    "delete_prompt_template",
    "list_library_assets",
    "list_pantone_colors",
    "list_prompt_templates",
    "open_library_asset_content",
    "seed_prompt_templates",
    "update_prompt_template",
]
