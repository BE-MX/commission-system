"""用户/角色/权限管理 & 个人资料路由"""

import logging
from datetime import datetime

import os
from pathlib import Path
from fastapi import APIRouter, Depends, Query, UploadFile, File
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import (
    ArkUser, ArkRole, ArkPermission,
    ArkUserRole, ArkRolePermission,
)
from app.auth.utils import hash_password, verify_password
from app.auth.admin_schemas import (
    UserCreateRequest, UserUpdateRequest, PasswordResetRequest,
    ChangePasswordRequest, ProfileUpdateRequest,
    RoleCreateRequest, RoleUpdateRequest,
    UserListItem, RoleListItem,
    PermissionItem, PermissionGroupItem,
)
from app.schemas.common import ResponseModel, PageResponse

logger = logging.getLogger("commission.auth")

router = APIRouter()


# ============================================================
# 用户管理
# ============================================================

@router.get("/users/list", summary="用户列表")
def list_users(
    keyword: str = Query("", description="搜索用户名/姓名"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:read")),
) -> ResponseModel:
    base_filter = [ArkUser.deleted_at.is_(None)]
    if keyword:
        like = f"%{keyword}%"
        base_filter.append(or_(
            ArkUser.username.like(like),
            ArkUser.real_name.like(like),
        ))

    total = db.query(func.count(ArkUser.id)).filter(*base_filter).scalar()
    rows = db.query(ArkUser).options(
        joinedload(ArkUser.roles),
    ).filter(*base_filter).order_by(ArkUser.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = [
        UserListItem(
            id=u.id,
            username=u.username,
            real_name=u.real_name,
            email=u.email,
            phone=u.phone,
            dingtalk_id=u.dingtalk_id,
            is_active=bool(u.is_active),
            roles=[r.label for r in u.roles],
            role_ids=[r.id for r in u.roles],
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in rows
    ]

    return ResponseModel(data=PageResponse(
        items=items, total=total, page=page, page_size=page_size,
    ))


@router.post("/users", summary="创建用户")
def create_user(
    req: UserCreateRequest,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    # 检查用户名唯一性
    exists = db.query(ArkUser).filter(
        ArkUser.username == req.username,
        ArkUser.deleted_at.is_(None),
    ).first()
    if exists:
        return ResponseModel(code=400, message="用户名已存在")

    user = ArkUser(
        username=req.username,
        password_hash=hash_password(req.password),
        real_name=req.real_name,
        email=req.email,
        phone=req.phone,
        is_active=True,
    )
    db.add(user)
    db.flush()

    # 分配角色
    if req.role_ids:
        for rid in req.role_ids:
            db.add(ArkUserRole(user_id=user.id, role_id=rid))
    db.commit()

    return ResponseModel(data={"id": user.id, "username": user.username})


@router.put("/users/{user_id}", summary="编辑用户")
def update_user(
    user_id: int,
    req: UserUpdateRequest,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.deleted_at.is_(None),
    ).first()
    if not user:
        return ResponseModel(code=404, message="用户不存在")

    if req.real_name is not None:
        user.real_name = req.real_name
    if req.email is not None:
        user.email = req.email
    if req.phone is not None:
        user.phone = req.phone
    if req.is_active is not None:
        user.is_active = req.is_active

    # 更新角色
    if req.role_ids is not None:
        # 删除现有角色
        db.query(ArkUserRole).filter(ArkUserRole.user_id == user_id).delete()
        # 添加新角色
        for rid in req.role_ids:
            db.add(ArkUserRole(user_id=user_id, role_id=rid))

    user.updated_at = datetime.utcnow()
    db.commit()

    return ResponseModel(message="更新成功")


@router.delete("/users/{user_id}", summary="删除用户")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("user:delete")),
) -> ResponseModel:
    # 不能删除自己
    if int(current_user["sub"]) == user_id:
        return ResponseModel(code=400, message="不能删除当前登录账号")

    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.deleted_at.is_(None),
    ).first()
    if not user:
        return ResponseModel(code=404, message="用户不存在")

    user.deleted_at = datetime.utcnow()
    user.is_active = False
    db.commit()

    return ResponseModel(message="删除成功")


@router.put("/users/{user_id}/password", summary="管理员重置密码")
def reset_user_password(
    user_id: int,
    req: PasswordResetRequest,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.deleted_at.is_(None),
    ).first()
    if not user:
        return ResponseModel(code=404, message="用户不存在")

    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    user.updated_at = datetime.utcnow()
    db.commit()

    return ResponseModel(message="密码已重置")


@router.put("/users/{user_id}/toggle-active", summary="启用/禁用用户")
def toggle_user_active(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    # 不能禁用自己
    if int(current_user["sub"]) == user_id:
        return ResponseModel(code=400, message="不能禁用当前登录账号")

    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.deleted_at.is_(None),
    ).first()
    if not user:
        return ResponseModel(code=404, message="用户不存在")

    user.is_active = not user.is_active
    user.updated_at = datetime.utcnow()
    db.commit()

    return ResponseModel(data={"is_active": bool(user.is_active)})


@router.post("/users/{user_id}/sync-dingtalk", summary="同步单个用户的钉钉ID")
async def sync_user_dingtalk(
    user_id: int,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    """根据用户手机号自动查询并回填钉钉 userId"""
    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.deleted_at.is_(None),
    ).first()
    if not user:
        return ResponseModel(code=404, message="用户不存在")
    if not user.phone:
        return ResponseModel(code=400, message="该用户未填写手机号，请先补充手机号")

    logger.info("同步钉钉 — 用户 %s (id=%s)，手机号: [%s]", user.real_name, user_id, repr(user.phone))
    phone = user.phone.strip()

    from app.dingtalk.client import get_dingtalk_client, DingTalkError
    client = get_dingtalk_client()
    try:
        dingtalk_id = await client.get_userid_by_mobile(phone)
    except DingTalkError as e:
        logger.error("钉钉 API 调用失败: %s", e)
        return ResponseModel(code=400, message=f"钉钉接口调用失败: {e}")

    if not dingtalk_id:
        return ResponseModel(code=400, message=f"未找到手机号 {user.phone} 对应的钉钉用户，请确认手机号与钉钉注册号一致")

    user.dingtalk_id = dingtalk_id
    user.updated_at = datetime.utcnow()
    db.commit()

    return ResponseModel(
        message="钉钉绑定成功",
        data={"dingtalk_id": dingtalk_id},
    )


@router.post("/users/sync-dingtalk-all", summary="批量同步所有用户的钉钉ID")
async def sync_all_users_dingtalk(
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    """遍历所有有手机号但无钉钉ID的用户，自动匹配钉钉 userId"""
    users = db.query(ArkUser).filter(
        ArkUser.deleted_at.is_(None),
        ArkUser.phone.isnot(None),
        ArkUser.phone != "",
        (ArkUser.dingtalk_id.is_(None)) | (ArkUser.dingtalk_id == ""),
    ).all()

    if not users:
        return ResponseModel(message="没有需要同步的用户（所有有手机号的用户都已绑定）")

    from app.dingtalk.client import get_dingtalk_client, DingTalkError
    client = get_dingtalk_client()

    success_count = 0
    fail_list = []

    for user in users:
        try:
            dingtalk_id = await client.get_userid_by_mobile(user.phone.strip())
        except DingTalkError:
            dingtalk_id = None
        if dingtalk_id:
            user.dingtalk_id = dingtalk_id
            user.updated_at = datetime.utcnow()
            success_count += 1
        else:
            fail_list.append({"user_id": user.id, "real_name": user.real_name, "phone": user.phone})

    db.commit()

    return ResponseModel(
        message=f"同步完成：成功 {success_count} 人，失败 {len(fail_list)} 人",
        data={"success_count": success_count, "fail_list": fail_list},
    )


# ============================================================
# 角色管理
# ============================================================

@router.get("/roles/list", summary="角色列表")
def list_roles(
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:read")),
) -> ResponseModel:
    roles = db.query(ArkRole).order_by(ArkRole.id).all()

    items = []
    for role in roles:
        user_count = db.query(func.count()).select_from(ArkUserRole).filter(
            ArkUserRole.role_id == role.id,
        ).scalar()
        role_perms = db.query(ArkRolePermission).filter(
            ArkRolePermission.role_id == role.id,
        ).all()
        items.append(RoleListItem(
            id=role.id,
            name=role.name,
            label=role.label,
            description=role.description,
            is_system=bool(role.is_system),
            user_count=user_count,
            permission_count=len(role_perms),
            permission_ids=[rp.permission_id for rp in role_perms],
            created_at=role.created_at.isoformat() if role.created_at else "",
        ))

    return ResponseModel(data=items)


@router.post("/roles", summary="创建角色")
def create_role(
    req: RoleCreateRequest,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    exists = db.query(ArkRole).filter(ArkRole.name == req.name).first()
    if exists:
        return ResponseModel(code=400, message="角色标识已存在")

    role = ArkRole(
        name=req.name,
        label=req.label,
        description=req.description,
        is_system=False,
    )
    db.add(role)
    db.flush()

    # 分配权限
    for pid in req.permission_ids:
        db.add(ArkRolePermission(role_id=role.id, permission_id=pid))
    db.commit()

    return ResponseModel(data={"id": role.id, "name": role.name})


@router.put("/roles/{role_id}", summary="编辑角色")
def update_role(
    role_id: int,
    req: RoleUpdateRequest,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    role = db.get(ArkRole, role_id)
    if not role:
        return ResponseModel(code=404, message="角色不存在")
    if role.name == "super_admin":
        return ResponseModel(code=400, message="超级管理员角色不可编辑")

    if req.label is not None:
        role.label = req.label
    if req.description is not None:
        role.description = req.description

    # 更新权限
    if req.permission_ids is not None:
        db.query(ArkRolePermission).filter(
            ArkRolePermission.role_id == role_id,
        ).delete()
        for pid in req.permission_ids:
            db.add(ArkRolePermission(role_id=role_id, permission_id=pid))

    db.commit()
    return ResponseModel(message="更新成功")


@router.delete("/roles/{role_id}", summary="删除角色")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:write")),
) -> ResponseModel:
    role = db.get(ArkRole, role_id)
    if not role:
        return ResponseModel(code=404, message="角色不存在")
    if role.name == "super_admin":
        return ResponseModel(code=400, message="超级管理员角色不可删除")

    # 检查是否有用户关联
    user_count = db.query(func.count()).select_from(ArkUserRole).filter(
        ArkUserRole.role_id == role_id,
    ).scalar()
    if user_count > 0:
        return ResponseModel(code=400, message=f"该角色下还有 {user_count} 个用户，请先移除")

    # 删除权限关联
    db.query(ArkRolePermission).filter(ArkRolePermission.role_id == role_id).delete()
    db.delete(role)
    db.commit()

    return ResponseModel(message="删除成功")


# ============================================================
# 权限参考
# ============================================================

@router.get("/permissions/list", summary="权限列表（按模块分组）")
def list_permissions(
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("user:read")),
) -> ResponseModel:
    perms = db.query(ArkPermission).order_by(ArkPermission.module, ArkPermission.id).all()

    groups: dict[str, list[PermissionItem]] = {}
    for p in perms:
        if p.module not in groups:
            groups[p.module] = []
        groups[p.module].append(PermissionItem(
            id=p.id, code=p.code, label=p.label, action=p.action,
        ))

    result = [
        PermissionGroupItem(module=mod, permissions=items)
        for mod, items in groups.items()
    ]

    return ResponseModel(data=result)


# ============================================================
# 个人资料
# ============================================================

@router.put("/profile", summary="修改个人资料")
def update_profile(
    req: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ResponseModel:
    user_id = int(current_user["sub"])
    user = db.get(ArkUser, user_id)
    if not user:
        return ResponseModel(code=404, message="用户不存在")

    if req.real_name is not None:
        user.real_name = req.real_name
    if req.email is not None:
        user.email = req.email
    if req.phone is not None:
        user.phone = req.phone
    if req.avatar_url is not None:
        user.avatar_url = req.avatar_url

    user.updated_at = datetime.utcnow()
    db.commit()

    return ResponseModel(message="资料已更新")


# 头像上传目录
AVATAR_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads" / "avatars"
AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/avatar", summary="上传头像")
async def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ResponseModel:
    user_id = int(current_user["sub"])
    user = db.get(ArkUser, user_id)
    if not user:
        return ResponseModel(code=404, message="用户不存在")

    # 校验文件类型
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        return ResponseModel(code=400, message="仅支持 JPG/PNG/GIF/WebP 图片")

    # 校验文件大小（最大 2MB）
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        return ResponseModel(code=400, message="图片大小不能超过 2MB")

    # 删除旧头像
    if user.avatar_url:
        old_path = AVATAR_UPLOAD_DIR / os.path.basename(user.avatar_url)
        if old_path.exists():
            old_path.unlink()

    # 保存新头像
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    filename = f"avatar_{user_id}_{int(datetime.utcnow().timestamp())}{ext}"
    file_path = AVATAR_UPLOAD_DIR / filename
    with open(file_path, "wb") as f:
        f.write(content)

    # 更新用户头像 URL
    avatar_url = f"/uploads/avatars/{filename}"
    user.avatar_url = avatar_url
    user.updated_at = datetime.utcnow()
    db.commit()

    return ResponseModel(message="头像上传成功", data={"avatar_url": avatar_url})


@router.put("/profile/password", summary="修改个人密码")
def change_password(
    req: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ResponseModel:
    user_id = int(current_user["sub"])
    user = db.get(ArkUser, user_id)
    if not user:
        return ResponseModel(code=404, message="用户不存在")

    if not verify_password(req.old_password, user.password_hash):
        return ResponseModel(code=400, message="原密码错误")

    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    user.updated_at = datetime.utcnow()
    db.commit()

    return ResponseModel(message="密码已修改")
