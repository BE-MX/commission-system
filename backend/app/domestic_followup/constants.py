"""内贸客户跟进：状态机常量与配置默认值。

描述性值域（状态变化 / 异常意见分类 / 沟通方式）存 sys_dict，运行时读取并
注入 AI user message（红线 7）。DICT_SEEDS 只是迁移初值的同一份清单，供测试
造数和文档对照；业务代码不得把它当值域来源。
"""

DICT_STATE_CHANGE = "domestic_followup_state_change"
DICT_CATEGORY = "domestic_followup_category"
DICT_CHANNEL = "domestic_followup_channel"

DICT_SEEDS = {
    DICT_STATE_CHANGE: [
        "订单减少", "订单增长", "补货周期变长", "开始买低价款", "开始买高端款",
        "竞争品牌增加", "店里增加直播", "店里增加短视频", "老板换人", "客户定位改变",
        "稳定没变化", "已成交", "未成交", "链接未回复",
    ],
    DICT_CATEGORY: ["质量", "发货物流", "色差", "尺寸", "价格", "售后退换", "服务", "产品需求", "其他"],
    DICT_CHANNEL: ["微信", "电话", "视频号", "到店", "展会", "其他"],
}

SOURCES = ("web", "mobile", "mini", "wechat_agent", "import")
FOLLOWUP_STATUSES = ("draft", "confirmed", "discarded")
AI_STATUSES = ("none", "running", "done", "failed")

ITEM_KINDS = ("content", "issue", "suggestion")
TRACKED_KINDS = ("issue", "suggestion")
SEVERITIES = ("一般", "紧急")
URGENT = "紧急"
ITEM_STATES = ("open", "handling", "resolved", "closed_no_action")
OPEN_ITEM_STATES = ("open", "handling")
ORIGINS = ("user", "ai_inferred")
OTHER_CATEGORY = "其他"

TASK_TYPES = ("plan", "receipt", "issue", "suggestion")
TASK_STATUSES = ("todo", "done", "expired", "cancelled")

CLOSE_RECEIPT_DONE = "回访完成"
CLOSE_NEW_FOLLOWUP = "有新跟进"
CLOSE_ITEM_RESOLVED = "条目已解决"
CLOSE_EXPIRED = "超时过期"
CLOSE_RELEASED = "客户释放"

DRAFT_TTL_DAYS = 7
RECEIPT_EXPIRE_AFTER_DAYS = 7
URGENT_MAX_ATTEMPTS = 5
RECEIPT_OK_TEXT = "已回访，客户无问题反馈"
PROSPECT_LIFECYCLE = "潜在"
HINT_MIN_CONFIDENCE = 0.7
INQUIRY_FOLLOWUP_DAYS = 1  # 询单次日跟进；作为 rules.inquiry_days 注入 AI，不写死在 prompt 里

CONFIG_DEFAULTS = {
    "receipt_delay_days": 3,
    "receipt_launch_date": None,
    "urgent_receiver_user_ids": [],
    "fallback_assignee_user_id": None,
    "frequency_days": {"S级": 7, "A级": 14, "B级": 30, "C级": 60},  # 键 = sys_dict domestic_customer_level 的值（迁移 133）
}

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
