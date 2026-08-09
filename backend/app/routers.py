"""集中注册所有 FastAPI router。新增业务模块时在此追加。"""

from fastapi import FastAPI

from app.api import (
    employee_router, supervisor_router, customer_router,
    payment_router, commission_router, report_router,
)
from app.api.short_link import router as short_link_router
from app.report.router import router as report_center_router
from app.tracking.router import router as tracking_router
from app.design.router import router as design_router
from app.auth.router import router as auth_router
from app.auth.admin_router import router as admin_router
from app.dingtalk.router import router as dingtalk_router
from app.dingtalk.callback import router as dingtalk_callback_router
from app.system.router import router as system_router
from app.ai.router import router as ai_router
from app.insight.router import router as insight_router
from app.stock.router import router as stock_router
from app.stock.public_router import router as stock_public_router
from app.asset.router import router as asset_router
from app.color.router import router as color_router
from app.production.router import router as production_router
from app.mini.router import router as mini_router
from app.governance.router import router as governance_router
from app.training.router import router as training_router
from app.whatsapp.router import router as whatsapp_router
from app.invoice.router import router as invoice_router
from app.expo.router import router as expo_router
from app.aftersales.router import router as aftersales_router
from app.mcp.token_admin import router as mcp_token_router
from app.pm.router import router as pm_router
from app.dashboard.router import router as dashboard_router
from app.domestic.router import router as domestic_router
from app.festival.public_router import router as festival_public_router
from app.festival.router import router as festival_router
from app.card.router import router as card_admin_router
from app.card.public_router import router as card_public_router
from app.design_image.router import router as design_image_router
from app.ai_chat.router import router as ai_chat_router
from app.salary.router import router as salary_router
from app.customer_image.router import router as customer_image_router
from app.customer_image.public_router import (
    PublicSecurityHeadersMiddleware,
    router as customer_image_public_router,
)
from app.sales_automation.router import router as sales_automation_router
from app.sales_automation.agent_router import router as sales_automation_agent_router
from app.knowledge.router import router as knowledge_router


def register_routers(app: FastAPI) -> None:
    """注册所有业务路由到 FastAPI app"""
    app.add_middleware(PublicSecurityHeadersMiddleware)
    app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
    app.include_router(admin_router, prefix="/api/auth", tags=["用户角色管理"])
    app.include_router(employee_router, prefix="/api/v1/employee", tags=["员工属性"])
    app.include_router(supervisor_router, prefix="/api/v1/supervisor", tags=["主管关系"])
    app.include_router(customer_router, prefix="/api/v1/customer", tags=["客户归属"])
    app.include_router(payment_router, prefix="/api/v1/payment", tags=["回款同步"])
    app.include_router(commission_router, prefix="/api/v1/commission", tags=["提成计算"])
    app.include_router(report_router, prefix="/api/v1/report", tags=["报表导出"])
    app.include_router(tracking_router, prefix="/api/v1/tracking", tags=["物流跟踪"])
    app.include_router(design_router, prefix="/api/design", tags=["设计预约"])
    app.include_router(dingtalk_router, prefix="/api/dingtalk", tags=["钉钉集成"])
    app.include_router(dingtalk_callback_router, prefix="/api", tags=["钉钉回调"])
    app.include_router(short_link_router, tags=["短链接"])
    app.include_router(system_router, prefix="/api/system", tags=["系统字典"])
    app.include_router(ai_router, prefix="/api/ai", tags=["AI 接入"])
    app.include_router(insight_router, prefix="/api/insight", tags=["方舟洞见"])
    app.include_router(stock_router, prefix="/api/stock", tags=["备货管理"])
    app.include_router(stock_public_router, prefix="/api/public/stock", tags=["对外库存查询"])
    app.include_router(asset_router, prefix="/api/assets", tags=["素材管理"])
    app.include_router(color_router, prefix="/api/color", tags=["色彩管理"])
    app.include_router(report_center_router, prefix="/api/report", tags=["报表中心"])
    app.include_router(production_router, prefix="/api/production", tags=["生产报工"])
    app.include_router(mini_router, prefix="/api/mini", tags=["微信小程序"])
    app.include_router(governance_router, prefix="/api/governance", tags=["数据概念治理"])
    app.include_router(training_router, prefix="/api/training", tags=["培训速递"])
    app.include_router(whatsapp_router, prefix="/api/whatsapp", tags=["WhatsApp 同步"])
    app.include_router(invoice_router, prefix="/api/invoice", tags=["Order Invoice"])
    app.include_router(expo_router, prefix="/api/expo", tags=["展会 AI 试戴"])
    app.include_router(aftersales_router, prefix="/api/aftersales", tags=["客户售后管理"])
    app.include_router(mcp_token_router, prefix="/api/mcp", tags=["MCP 网关 token 管理"])
    app.include_router(pm_router, prefix="/api/pm", tags=["PM 项目资料协作站"])
    app.include_router(dashboard_router, prefix="/api/dashboard", tags=["工作台配置"])
    app.include_router(domestic_router, prefix="/api/domestic", tags=["内贸订单"])
    app.include_router(salary_router, prefix="/api/salary", tags=["薪资计算"])
    app.include_router(festival_public_router, prefix="/api/public/festival", tags=["采购节大屏"])
    app.include_router(festival_router, prefix="/api/festival", tags=["采购节大屏"])
    # card 管理路由（/admin/* 字面量路径）必须先于公开路由（/{slug}/*）注册，防路径参数吞噬
    app.include_router(card_admin_router, prefix="/api/card", tags=["名片管家"])
    app.include_router(card_public_router, prefix="/api/card", tags=["名片管家-公开"])
    app.include_router(design_image_router, prefix="/api/design-image", tags=["AI 生图工作台"])
    app.include_router(customer_image_public_router, prefix="/api/customer-image/public", tags=["客户生图门户-公开"])
    app.include_router(customer_image_router, prefix="/api/customer-image", tags=["客户生图门户"])
    app.include_router(ai_chat_router, prefix="/api/ai-chat", tags=["AI 方案对话"])
    app.include_router(sales_automation_router, prefix="/api/sales-automation", tags=["智能获客"])
    app.include_router(sales_automation_agent_router, prefix="/api/sales-automation", tags=["智能获客-Agent"])
    app.include_router(knowledge_router, prefix="/api/knowledge", tags=["知识库"])
