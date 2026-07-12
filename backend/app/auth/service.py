"""Auth 业务逻辑"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkLoginLog, ArkRefreshToken
from app.auth.utils import (
    verify_password, create_access_token, generate_refresh_token,
    hash_token,
)
from app.core.config import get_settings

settings = get_settings()


def get_user_by_username(db: Session, username: str) -> ArkUser | None:
    """通过用户名查找用户（含 roles + permissions eager load）"""
    return db.query(ArkUser).filter(
        ArkUser.username == username,
        ArkUser.deleted_at.is_(None),
    ).first()


def get_user_roles(user: ArkUser) -> list[str]:
    return [r.name for r in user.roles]


def get_user_permissions(user: ArkUser) -> list[str]:
    """获取用户所有角色下的去重权限列表"""
    perms = set()
    for role in user.roles:
        for perm in role.permissions:
            perms.add(perm.code)
    return sorted(perms)


def check_account_lockout(db: Session, username: str) -> None:
    """30 分钟内连续失败 5 次则锁定"""
    cutoff = datetime.utcnow() - timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
    fail_count = db.query(func.count()).filter(
        ArkLoginLog.username == username,
        ArkLoginLog.status == "failed",
        ArkLoginLog.created_at >= cutoff,
    ).scalar()
    if fail_count >= settings.LOGIN_MAX_FAIL:
        raise AccountLockedException(
            f"账号已锁定，{settings.LOGIN_LOCK_MINUTES}分钟内失败次数过多，请稍后再试"
        )


def record_login_log(
    db: Session,
    username: str,
    status: str,
    ip: str,
    user_agent: str = "",
    user_id: int | None = None,
    fail_reason: str | None = None,
):
    log = ArkLoginLog(
        user_id=user_id,
        username=username,
        ip_address=ip,
        user_agent=user_agent[:500] if user_agent else "",
        status=status,
        fail_reason=fail_reason,
    )
    db.add(log)
    db.commit()


def authenticate_user(
    db: Session,
    username: str,
    password: str,
    ip: str,
    user_agent: str = "",
) -> tuple:
    """
    验证用户，返回 (access_token, refresh_token_plain, user_info_dict)
    失败抛异常
    """
    # 锁定检查
    check_account_lockout(db, username)

    user = get_user_by_username(db, username)

    if not user:
        record_login_log(db, username, "failed", ip, user_agent, fail_reason="用户不存在")
        raise InvalidCredentialsException("用户名或密码错误")

    if not user.is_active:
        record_login_log(db, username, "failed", ip, user_agent, user.id, "账号已禁用")
        raise AccountDisabledException("账号已被禁用，请联系管理员")

    if not verify_password(password, user.password_hash):
        record_login_log(db, username, "failed", ip, user_agent, user.id, "密码错误")
        raise InvalidCredentialsException("用户名或密码错误")

    # 认证成功
    roles = get_user_roles(user)
    permissions = get_user_permissions(user)

    # 生成 Access Token
    at_payload = {
        "sub": str(user.id),
        "username": user.username,
        "roles": roles,
        "permissions": permissions,
        "must_change_password": user.must_change_password,
    }
    access_token = create_access_token(at_payload)

    # 生成 Refresh Token
    rt_plain, rt_hash = generate_refresh_token()
    rt_record = ArkRefreshToken(
        token_hash=rt_hash,
        user_id=user.id,
        device_info=user_agent[:255] if user_agent else "",
        ip_address=ip,
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt_record)

    # 更新最后登录
    user.last_login_at = datetime.utcnow()
    user.last_login_ip = ip

    # 记录成功日志
    record_login_log(db, username, "success", ip, user_agent, user.id)
    db.commit()

    user_info = {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "avatar_url": user.avatar_url,
        "roles": roles,
        "permissions": permissions,
        "must_change_password": bool(user.must_change_password),
    }

    return access_token, rt_plain, user_info


def init_admin_password(db: Session):
    """启动时检查 admin 密码是否为占位符，若是则生成真实 hash"""
    user = db.query(ArkUser).filter(ArkUser.username == "admin").first()
    if user and (user.password_hash == "__PENDING_HASH__" or not user.password_hash.startswith("$2")):
        import bcrypt as _bcrypt
        hashed = _bcrypt.hashpw(b"Admin@leisa2026", _bcrypt.gensalt(rounds=12)).decode("utf-8")
        user.password_hash = hashed
        db.commit()


# kind 派生规则（权限重设计方案）：data=数据范围，read/日报=页面可见，其余=操作级
_DATA_KIND_CODES = {"tracking:read_all", "commission:self_read", "insight:internal_read"}
_PAGE_KIND_EXTRA = {"tracking:daily_report"}


def _perm_kind(code: str, action: str) -> str:
    if code in _DATA_KIND_CODES:
        return "data"
    if action == "read" or code in _PAGE_KIND_EXTRA:
        return "page"
    return "action"


# 已下架权限（2026-07-03 死码核清：全部零引用）。回填 seed 是为了能在 DB 里标记
# is_legacy=1（UI 隐藏）；admin 自动授权会跳过它们。彻底删除待观察一个版本后进行。
LEGACY_SEEDS = [
    ("commission:read_own", "commission", "read_own", "查看本人提成（旧）"),
    ("commission:read_all", "commission", "read_all", "查看全部提成（旧）"),
    ("commission:settle",   "commission", "settle",   "提成结算（旧）"),
    ("commission:export",   "commission", "export",   "提成导出（旧）"),
    ("design:submit",       "design",     "submit",   "提交预约（旧）"),
    ("design:read_own",     "design",     "read_own", "查看本人预约（旧）"),
    ("design:read_all",     "design",     "read_all", "查看全部预约（旧）"),
    ("design:approve",      "design",     "approve",  "审批预约（旧）"),
    ("system:config",       "system",     "config",   "系统配置（旧）"),
    ("system:logs",         "system",     "logs",     "系统日志（旧）"),
    ("system:backup",       "system",     "backup",   "系统备份（旧）"),
    ("user:assign_role",    "user",       "assign_role", "分配角色（旧）"),
    # 2026-07-12 功能单元拆分：案例库/周会纪要写权限拆为 insight_case:write /
    # insight_minutes:write，本码职责拆空（061 迁移已给持有者补授新码）
    ("insight:write",       "insight",    "write",    "上传案例/周会纪要（旧，已拆分）"),
]


def seed_role_permissions(db: Session):
    """启动时 upsert 全部权限（含元数据刷新），并给 admin 角色补齐非 legacy 权限。

    注意：2026-07-03 起从 insert-only 改为 upsert——存在时同步更新
    module/action/label/kind/is_legacy/sort（code 永不改）。这同时修复了
    历史上改了 seed 但 DB 不同步的漂移（如 user:* 的 module 归属）。
    """
    from app.auth.models import ArkPermission, ArkRole, ArkRolePermission

    seeds = [
        # 人员管理
        ("employee:read",  "employee", "read",   "查看员工属性"),
        ("employee:write", "employee", "write",  "编辑员工属性"),
        # 主管关系（2026-07-12 从 employee:* 拆出，独立控制主管关系页）
        ("supervisor:read",  "supervisor", "read",  "查看主管关系"),
        ("supervisor:write", "supervisor", "write", "设置/变更/导入主管关系"),
        # 客户管理
        ("customer:read",  "customer", "read",   "查看客户归属"),
        ("customer:write", "customer", "write",  "编辑客户归属"),
        # 提成管理
        ("commission:read",      "commission", "read",       "查看提成批次"),
        ("commission:write",     "commission", "write",      "管理提成批次"),
        ("commission:self_read", "commission", "self_read",  "查看本人提成"),
        ("payment:read",         "commission", "read",       "查看回款记录"),
        ("payment:write",        "commission", "write",      "同步回款"),
        # 物流跟踪
        ("tracking:read",         "tracking", "read",         "查看物流跟踪（仅本人）"),
        ("tracking:read_all",     "tracking", "read_all",     "查看全部运单"),
        ("tracking:write",        "tracking", "write",        "编辑物流记录"),
        ("tracking:delete",       "tracking", "delete",       "删除运单"),
        ("tracking:daily_report", "tracking", "daily_report", "查看物流日报"),
        # 设计预约（2026-07-12 甘特图/我的预约/设计统计拆独立页面码；
        # design:read 保留为数据读取码，提交预约=write、审批队列=audit、设计管理=manage 不变）
        ("design:read",    "design", "read",     "查看设计预约数据"),
        ("design:write",   "design", "write",    "提交/编辑预约"),
        ("design:audit",   "design", "audit",    "审批设计预约"),
        ("design:manage",  "design", "manage",   "设计管理"),
        ("design_gantt:read", "design", "read",  "查看排期甘特图"),
        ("design_my:read",    "design", "read",  "查看我的预约"),
        ("design_stats:read", "design", "read",  "查看设计统计"),
        # 账号体系（2026-07-03 起 user/role 统一挂 module=user，随 upsert 修复 DB 漂移）
        ("user:read",      "user", "read",     "查看用户/角色"),
        ("user:write",     "user", "write",    "创建/编辑用户"),
        ("user:delete",    "user", "delete",   "删除用户"),
        ("role:read",      "user", "read",     "查看角色权限页"),
        ("role:write",     "user", "write",    "创建/编辑角色 / 配置角色权限"),
        ("role:delete",    "user", "delete",   "删除角色"),
        # 基础字典（2026-07-12 从 user:* 拆出；字典数据 GET 保持任意登录可读，
        # dict:read 只控页面入口，dict:write 控增删改）
        ("dict:read",      "system", "read",   "查看基础字典页"),
        ("dict:write",     "system", "write",  "新增/编辑/删除字典项"),
        # AI 接入
        ("ai:admin",       "ai",     "admin",    "AI 接入管理"),
        ("ai:invoke",      "ai",     "invoke",   "AI 调用权限"),
        # 方舟洞见（2026-07-12 案例库/周会纪要拆独立子域；同日情报三页+AI 工具速递逐页拆分，
        # insight:read 保留给行业情报速览页，internal_read 保留给内部经营报告页）
        ("insight:read",          "insight", "read",          "查看行业情报速览"),
        ("insight:internal_read", "insight", "internal_read", "查看内部经营报告"),
        ("insight:admin",         "insight", "admin",         "信源管理 / 重新生成报告"),
        ("insight_library:read",  "insight", "read",          "查看情报采集库"),
        ("insight_daily:read",    "insight", "read",          "查看行业情报日报"),
        ("insight_ai_tools:read", "insight", "read",          "查看 AI 工具速递"),
        ("insight_case:read",     "insight", "read",          "查看业务员案例库"),
        ("insight_case:write",    "insight", "write",         "上传/编辑案例"),
        ("insight_minutes:read",  "insight", "read",          "查看周会纪要"),
        ("insight_minutes:write", "insight", "write",         "上传/管理周会纪要"),
        # 备货管理（2026-07-12 日报页拆独立码，stock:read 保留给销量备货一览）
        ("stock:read",            "stock",   "read",          "查看销量备货一览"),
        ("stock:write",           "stock",   "write",         "设置安全库存 / AI 生成建议"),
        ("stock:admin",           "stock",   "admin",         "手动触发日报生成 / 调试推送"),
        ("stock_daily:read",      "stock",   "read",          "查看安全库存日报"),
        # 生产订单管理（2026-07-12 产品管理/生产看板/工序路线拆独立页面码；
        # production:read 保留给生产订单管理页+流转卡打印，production:admin 保留给工序管理页+操作）
        ("production:read",       "production", "read",       "查看生产订单"),
        ("production:write",      "production", "write",      "创建/编辑生产订单 / 入库录入"),
        ("production:print",      "production", "print",      "生产订单打印工作台"),
        ("production:admin",      "production", "admin",      "工序管理页 / 删除生产订单 / 管理全部订单"),
        ("production_product:read",   "production", "read",   "查看产品管理"),
        ("production_dashboard:read", "production", "read",   "查看生产看板"),
        ("production_route:read",     "production", "read",   "查看工序路线"),
        # 订单发票管理（2026-07-12 三个 admin 配置页拆出独立页面码，invoice:admin 保留为操作码）
        ("invoice:read",          "invoice", "read",          "查看订单发票"),
        ("invoice:write",         "invoice", "write",         "创建/编辑订单发票"),
        ("invoice:sync",          "invoice", "sync",          "同步订单发票到小满"),
        ("invoice:admin",         "invoice", "admin",         "价格配置 / OKKI 同步配置 / 自定义产品管理(操作)"),
        ("invoice_price:read",    "invoice", "read",          "查看价格与产品配置页"),
        ("invoice_okki:read",     "invoice", "read",          "OKKI 推单设置页菜单（页面数据需 invoice:admin）"),
        ("invoice_repair:read",   "invoice", "read",          "查看回款日期修复页"),
        # 客户售后管理（2026-07-12 售后分析拆为独立码，四页各自独立：单/审/SOP/分析）
        ("aftersales:read",       "aftersales", "read",       "查看授权范围内售后单"),
        ("aftersales:write",      "aftersales", "write",      "登记、分析、提交、审核和关闭售后单"),
        ("aftersales:admin",      "aftersales", "admin",      "维护 SOP、重试通知和处理异常售后单"),
        ("aftersales:read_all",   "aftersales", "read_all",   "查看全部售后单"),
        ("aftersales_analytics:read", "aftersales", "read",   "查看售后分析"),
        # 钉钉集成
        ("dingtalk:admin",        "dingtalk", "admin",        "手动发送钉钉消息 / 查看消息与回调日志"),
        # 展会 AI 试戴（2026-07-12 线索台拆 expo_lead:*；同日四个素材页逐页拆分，
        # expo:read 保留给发型库页 + kiosk 素材数据读取，端点仍兼容旧码）
        ("expo:read",             "expo",    "read",          "查看试戴发型库（含 kiosk 素材数据读取）"),
        ("expo:write",            "expo",    "write",         "展位试戴操作(kiosk 设备)"),
        ("expo:admin",            "expo",    "admin",         "发型库话术库维护 / 删除客户数据"),
        ("expo_hair_color:read",  "expo",    "read",          "查看试戴发色库"),
        ("expo_scene:read",       "expo",    "read",          "查看场景示意图"),
        ("expo_script:read",      "expo",    "read",          "查看话术卡库"),
        ("expo_lead:read",        "expo",    "read",          "查看展会线索台"),
        ("expo_lead:write",       "expo",    "write",         "线索操作 / 销售反馈录入"),
        # 素材管理（2026-07-12 收藏/统计页拆独立码，asset:read 保留给素材库页+数据操作）
        ("asset:read",            "asset",   "read",          "查看素材库（含预览/下载/收藏操作）"),
        ("asset:write",           "asset",   "write",         "上传素材 / 编辑标签 / 版本迭代"),
        ("asset:delete",          "asset",   "delete",        "删除素材"),
        ("asset:admin",           "asset",   "admin",         "标签维度管理 / 权限设置"),
        ("asset_favorites:read",  "asset",   "read",          "查看我的收藏"),
        ("asset_stats:read",      "asset",   "read",          "查看下载统计"),
        # 色彩管理（2026-07-12 混合色/趋势页拆独立码，color:read 保留给色板数据库页）
        ("color:read",            "color",   "read",          "查看色板数据库"),
        ("color:write",           "color",   "write",         "编辑色号 / 混合色 / 生成色板图"),
        ("color:admin",           "color",   "admin",         "管理竞品监控 / 趋势数据源 / 色板图任务"),
        ("color_blend:read",      "color",   "read",          "查看混合色管理"),
        ("color_trend:read",      "color",   "read",          "查看色彩趋势看板"),
        # 报表中心（jimureport 集成）
        ("report:read",           "report",  "read",          "查看报表 / 数据大屏"),
        ("report:design",         "report",  "design",        "进入报表设计器 / 编辑报表"),
        ("report:admin",          "report",  "admin",         "管理报表元数据 / 数据源"),
        # 数据概念治理（2026-07-12 图谱/变更历史页拆独立码，governance:read 保留给概念注册表+详情）
        ("governance:read",       "governance", "read",       "查看概念注册表 / 概念详情"),
        ("governance:write",      "governance", "write",      "创建/编辑概念 / 提交审批 / 添加关联"),
        ("governance:admin",      "governance", "admin",      "审批/废弃/回滚/批量导入/删除关联"),
        ("governance_graph:read", "governance", "read",       "查看全景关系图"),
        ("governance_log:read",   "governance", "read",       "查看变更历史"),
        # 客户机会台
        ("customer_opportunity:read",   "customer_opportunity", "read",   "查看客户机会（本人）"),
        ("customer_opportunity:write",  "customer_opportunity", "write",  "更新机会状态/添加反馈"),
        ("customer_opportunity:import", "customer_opportunity", "import", "ACCIO 导入询盘"),
        ("customer_opportunity:manage", "customer_opportunity", "manage", "管理全部机会/分配/管理未分配"),
        # 外部账号绑定
        ("external_binding:read",  "external_binding", "read",  "查看外部账号绑定"),
        ("external_binding:write", "external_binding", "write", "创建/删除绑定/管理候选"),
        # WhatsApp 同步
        ("whatsapp:read",  "whatsapp", "read",  "查看 WhatsApp 绑定账号/会话/消息"),
        ("whatsapp:write", "whatsapp", "write", "创建绑定/触发同步/解绑账号"),
        ("whatsapp:admin", "whatsapp", "admin", "管理全部 WhatsApp 同步账号"),
        # 客户经营雷达
        ("customer_radar:read",   "customer_radar", "read",   "查看客户经营雷达"),
        ("customer_radar:write",  "customer_radar", "write",  "完成/延后/反馈行动"),
        ("customer_radar:manage", "customer_radar", "manage", "管理所有客户档案/手动分配"),
        # MCP 网关(物流录单/查询的入口无关 MCP 服务)
        ("mcp:admin", "mcp", "admin", "发放/吊销 MCP 个人 access token"),
    ]
    # upsert：活跃权限 + 已下架权限统一处理，元数据每次启动刷新
    existing_map = {p.code: p for p in db.query(ArkPermission).all()}
    module_counter: dict = {}
    for entry in [(s, 0) for s in seeds] + [(s, 1) for s in LEGACY_SEEDS]:
        (code, module, action, label), legacy = entry
        module_counter[module] = module_counter.get(module, 0) + 1
        meta = dict(
            module=module, action=action, label=label,
            kind=_perm_kind(code, action),
            is_legacy=legacy,
            sort=module_counter[module] * 10,
        )
        perm = existing_map.get(code)
        if perm:
            for k, v in meta.items():
                setattr(perm, k, v)
        else:
            db.add(ArkPermission(code=code, **meta))
    db.flush()

    # 给 admin 角色补齐所有非 legacy 权限（跳过已下架，避免复活死码授权）
    admin_role = db.query(ArkRole).filter(ArkRole.name == "admin").first()
    if admin_role:
        for code, _, _, _ in seeds:
            perm = db.query(ArkPermission).filter(ArkPermission.code == code).first()
            if perm:
                link = db.query(ArkRolePermission).filter(
                    ArkRolePermission.role_id == admin_role.id,
                    ArkRolePermission.permission_id == perm.id,
                ).first()
                if not link:
                    db.add(ArkRolePermission(role_id=admin_role.id, permission_id=perm.id))
    db.commit()


# ── Refresh Token ─────────────────────────────────────

def refresh_access_token(db: Session, refresh_token_plain: str) -> tuple:
    """
    用 refresh_token 换取新的 access_token。
    返回 (new_access_token, user_info_dict)。
    失败抛 InvalidCredentialsException。
    """
    token_hash = hash_token(refresh_token_plain)
    rt_record = (
        db.query(ArkRefreshToken)
        .filter(
            ArkRefreshToken.token_hash == token_hash,
            ArkRefreshToken.revoked_at.is_(None),
        )
        .first()
    )

    if not rt_record:
        raise InvalidCredentialsException("Refresh Token 无效")

    if rt_record.expires_at < datetime.utcnow():
        raise InvalidCredentialsException("Refresh Token 已过期")

    user = db.query(ArkUser).filter(
        ArkUser.id == rt_record.user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).first()

    if not user:
        raise InvalidCredentialsException("用户不存在或已禁用")

    roles = get_user_roles(user)
    permissions = get_user_permissions(user)

    at_payload = {
        "sub": str(user.id),
        "username": user.username,
        "roles": roles,
        "permissions": permissions,
        "must_change_password": user.must_change_password,
    }
    access_token = create_access_token(at_payload)

    user_info = {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "avatar_url": user.avatar_url,
        "roles": roles,
        "permissions": permissions,
        "must_change_password": bool(user.must_change_password),
    }

    return access_token, user_info


def logout_user(db: Session, refresh_token_plain: str | None) -> None:
    """注销：标记 refresh_token 为已撤销。"""
    if not refresh_token_plain:
        return
    token_hash = hash_token(refresh_token_plain)
    rt_record = (
        db.query(ArkRefreshToken)
        .filter(ArkRefreshToken.token_hash == token_hash)
        .first()
    )
    if rt_record:
        rt_record.revoked_at = datetime.utcnow()
        db.commit()


# ── 异常类 ────────────────────────────────────────────
class InvalidCredentialsException(Exception):
    pass


class AccountLockedException(Exception):
    pass


class AccountDisabledException(Exception):
    pass
