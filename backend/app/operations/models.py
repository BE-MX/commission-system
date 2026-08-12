"""Stable catalog metadata for runtime units shown in the operations center."""

from dataclasses import dataclass


@dataclass(frozen=True)
class JobMetadata:
    name: str
    domain: str
    owner: str


JOB_METADATA = {
    "design_shoot_reminder": JobMetadata("设计拍摄提醒", "设计预约", "设计中心"),
    "shipping_daily_report": JobMetadata("物流日报生成", "物流跟踪", "物流团队"),
    "staging_scan": JobMetadata("运单暂存区扫描", "物流跟踪", "物流团队"),
    "insight_industry_daily": JobMetadata("行业情报日报", "方舟洞见", "业务运营"),
    "insight_ai_tools": JobMetadata("AI 工具速递", "方舟洞见", "业务运营"),
    "insight_intelligence_overview": JobMetadata("行业情报速览", "方舟洞见", "业务运营"),
    "stock_daily_report": JobMetadata("安全库存日报", "备货管理", "供应链"),
    "tracking_poll_active": JobMetadata("在途运单轮询", "物流跟踪", "物流团队"),
    "color_social_extract": JobMetadata("社媒发色采集", "发色数字化", "产品中心"),
    "color_sales_aggregate": JobMetadata("发色销量聚合", "发色数字化", "产品中心"),
    "whatsapp_auto_sync": JobMetadata("WhatsApp 自动同步", "客户沟通", "销售运营"),
    "aftersales_notification_retry": JobMetadata("售后通知重试", "客户售后", "售后团队"),
    "festival_event_monitor": JobMetadata("采购节事件监控", "采购节", "业务运营"),
    "festival_daily_report": JobMetadata("采购节日报", "采购节", "业务运营"),
    "design_image_queue": JobMetadata("设计生图队列", "AI 生图", "设计中心"),
    "customer_image_queue": JobMetadata("客户生图队列", "客户生图", "设计中心"),
    "customer_image_cleanup": JobMetadata("客户生图清理", "客户生图", "设计中心"),
    "sales_public_pool_daily": JobMetadata("公海背调日批次", "智能获客", "销售运营"),
    "runtime_heartbeat_monitor": JobMetadata("云端实例心跳巡检", "平台运维", "平台研发"),
    "operations_history_cleanup": JobMetadata("运行历史保留期清理", "平台运维", "平台研发"),
}
