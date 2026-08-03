"""采购节大屏登录态路由（/api/festival）。

导航菜单「采购节看板」的换 key 通道：入口页 /festival/index.html 用主站
localStorage 的 JWT 调 /screen-key 换大屏访问 key，再跳 zhaiyao.html?key=。
key 本体只存 Settings.FESTIVAL_SCREEN_KEYS（.env），不进前端代码；
展厅电视等免登录场景仍走「书签 URL 固化 key」路径，与本端点无关。
"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_any_permission
from app.core.config import get_settings
from app.core.response import ok

router = APIRouter()

# 与 frontend/src/config/navigation.js 的 MENU_GROUPS.expo.anyPermission 保持同步：
# 侧边栏「展会营销」分组（含采购节看板条目）对谁可见，谁换 key 就应成功。
_MENU_GATE = (
    "expo:read", "expo:write", "expo:admin", "expo_lead:read", "expo_lead:write",
    "expo_hair_color:read", "expo_scene:read", "expo_script:read",
    "card:read", "card:write",
)


@router.get("/screen-key")
def get_screen_key(_user=Depends(require_any_permission(*_MENU_GATE))):
    """用登录态换大屏访问 key。

    固定发第一个 key：轮换菜单用户 key 时在 .env 前置新 key（勿直接删第一个——
    电视书签可能固化了它）；get_settings 有 lru_cache，改 .env 后需重启后端生效。
    """
    raw = get_settings().FESTIVAL_SCREEN_KEYS or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise HTTPException(503, "大屏取数未配置访问 key（FESTIVAL_SCREEN_KEYS），请联系管理员")
    return ok({"key": keys[0]})
