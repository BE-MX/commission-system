"""AI 预设与调用来源的功能目录（唯一后端来源）。

主体对齐 frontend/src/config/navigation.js 的导航分组与子页，
并补充平台内置非导航分类（外部站点网关、Agent 引擎、系统测试）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class FeatureEntry:
    key: str
    label: str
    nav_group: str
    route_path: Optional[str] = None
    caller_modules: tuple[str, ...] = ()


FEATURE_CATALOG: tuple[FeatureEntry, ...] = (
    FeatureEntry("tracking", "物流跟踪", "物流管理", "/tracking", ("logistics", "tracking")),
    FeatureEntry("expo", "展会营销", "展会营销", "/expo/leads", ("expo", "expo_beautify")),
    FeatureEntry(
        "domestic_followup",
        "内贸客户跟进",
        "内贸订单",
        "/domestic/followups",
        (
            "domestic_followup",
            "domestic_followup_insights_public",
            "domestic_followup_audio_organize",
            "domestic_decision",
        ),
    ),
    FeatureEntry("mail_outreach", "客户邮件触达", "客户经营", "/mail-outreach", ("mail_outreach",)),
    FeatureEntry("client_desk", "私海客户工作台", "客户经营", "/client-desk", ("client_desk", "client_desk_unlinked", "pcw")),
    FeatureEntry(
        "invoice",
        "订单与经营分析",
        "订单管理",
        "/invoices",
        ("invoice", "order_intelligence", "fx_settlement", "product_sales"),
    ),
    FeatureEntry("aftersales", "售后管理", "售后管理", "/aftersales", ("aftersales",)),
    FeatureEntry("stock", "备货与工厂到货", "备货管理", "/stock/daily-report", ("stock", "factory_inbound")),
    FeatureEntry("asset", "素材管理", "素材管理", "/assets", ("asset",)),
    FeatureEntry("color", "色彩与色卡", "色彩管理", "/color/library", ("color", "swatch")),
    FeatureEntry("insight", "方舟洞见", "方舟洞见", "/insight/daily", ("insight",)),
    FeatureEntry("training", "培训速递", "方舟洞见", "/training", ("training",)),
    FeatureEntry("knowledge", "企业知识库", "企业知识库", "/knowledge", ("knowledge",)),
    FeatureEntry("design_image", "AI 生图", "设计中心", "/design/image-studio", ("design_image", "design_booking")),
    FeatureEntry("customer_image", "客户生图", "设计中心", "/design/customer-images", ("customer_image",)),
    FeatureEntry("ai_chat", "AI 工作台聊天", "设计中心", "/design/ai-chat", ("ai_chat",)),
    FeatureEntry("task", "个人任务中心", "个人效率", "/tasks", ("task",)),
    FeatureEntry(
        "whatsapp",
        "WhatsApp 助手与翻译",
        "系统管理",
        "/system/whatsapp-translation",
        ("whatsapp", "whatsapp_assistant", "whatsapp_translation", "whatsapp_reply"),
    ),
    FeatureEntry("commission", "提成管理", "提成管理", "/commission", ("commission",)),
    # 平台内置非导航分类（无独立侧边栏菜单）
    FeatureEntry("ai_gateway", "外部站点网关", "平台内置", None, ("ai_gateway",)),
    FeatureEntry("agent_runtime", "Agent 引擎", "平台内置", None, ("agent_runtime",)),
    FeatureEntry("pm_hub", "PM 协作站", "平台内置", None, ("pm",)),
    FeatureEntry("system_test", "系统与内部测试", "平台内置", None, ("system", "ai_preset_test")),
)

FEATURE_BY_KEY: dict[str, FeatureEntry] = {item.key: item for item in FEATURE_CATALOG}

# 供启动自动种子（seed_ai.py / pm/bootstrap.py 等）查找默认归属
SEED_PRESET_FEATURES: dict[str, str] = {
    "waybill_ocr": "tracking",
    "tracking_summary": "tracking",
    "expo_face_analysis": "expo",
    "expo_wig_composite": "expo",
    "expo_sales_strategy": "expo",
    "expo_scene_generation": "expo",
    "expo_beautify": "expo",
    "domestic_followup_parse": "domestic_followup",
    "domestic_followup_ocr": "domestic_followup",
    "domestic_followup_insights": "domestic_followup",
    "domestic_followup_strategy": "domestic_followup",
    "domestic_followup_audio_organize": "domestic_followup",
    "domestic_decision_brief": "domestic_followup",
    "mail_outreach_generate": "mail_outreach",
    "mail_outreach_internal_test": "system_test",
    "client_desk_daily": "client_desk",
    "client_desk_unlinked": "client_desk",
    "pcw_conversation_summary": "client_desk",
    "order_intelligence_brief": "invoice",
    "invoice_screenshot_extract": "invoice",
    "fx_settlement_advisor": "invoice",
    "product_sales_grade_insight": "invoice",
    "aftersales_solution_advice": "aftersales",
    "factory_delivery_ocr": "stock",
    "factory_inbound_delivery_note": "stock",
    "asset_analyze": "asset",
    "swatch_image_generation": "color",
    "insight_daily_organize": "insight",
    "case_library_format": "insight",
    "training_digest_draft": "training",
    "knowledge_ai_edit": "knowledge",
    "knowledge_ai_verify": "knowledge",
    "design_image_generation": "design_image",
    "customer_image_generation": "customer_image",
    "customer_ai_chat": "ai_chat",
    "task_draft": "task",
    "task_brief": "task",
    "whatsapp_message_assistant": "whatsapp",
    "whatsapp_assistant_summary": "whatsapp",
    "whatsapp_text_translation": "whatsapp",
    "whatsapp_outgoing_translation": "whatsapp",
    "whatsapp_reply_generator": "whatsapp",
    "whatsapp_reply_query_rewrite": "whatsapp",
    "agent_runtime_copilot": "agent_runtime",
    "agent_runtime_repurchase": "agent_runtime",
    "agent_runtime_sales_shadow": "agent_runtime",
    "pm_diff": "pm_hub",
}


def is_valid_feature_key(key: Optional[str]) -> bool:
    return bool(key and key in FEATURE_BY_KEY)


def get_feature(key: Optional[str]) -> Optional[FeatureEntry]:
    if not key:
        return None
    return FEATURE_BY_KEY.get(key)


def default_feature_for_preset(preset_name: str) -> Optional[str]:
    if preset_name in SEED_PRESET_FEATURES:
        return SEED_PRESET_FEATURES[preset_name]
    if preset_name.startswith("design_image_generation_"):
        return "design_image"
    return None


def list_feature_catalog() -> list[dict]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "nav_group": item.nav_group,
            "route_path": item.route_path,
            "caller_modules": list(item.caller_modules),
        }
        for item in FEATURE_CATALOG
    ]


def caller_module_labels() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in FEATURE_CATALOG:
        for mod in item.caller_modules:
            mapping[mod] = item.label
    return mapping
