"""首批 v1 场景模板。迁移快照只追加新模板，不在此处改已发布定义。"""

DEFAULT_PARAMS = {"prep_minutes": [3, 5], "talk_minutes": [5, 8], "wechat_sentences": [2, 4], "recontact_workdays": [3, 5]}


def field(key, label, kind="text", *, emphasis="more", nature="business_fact", options=None, hint=None):
    return {"key": key, "label": label, "kind": kind, "emphasis": emphasis, "nature": nature,
            "options": options, "hint": hint, "show_when": None}


TEMPLATE_SEEDS = [
    {"code": "T01", "name": "未接通 / 未回复 / 忙碌", "short_form": "本次已触达，尚未获得新反馈；下一步我方待安排。",
     "guidance": "只记触达事实，不推断客户不回复的原因。", "record_fields": [field("contact_reason", "联系理由", emphasis="key"), field("touch_detail", "实际触达", "textarea")],
     "avoid": [{"rule": "未回复不等于拒绝或没有兴趣", "keywords": ["拒绝", "没兴趣", "预算不足"]}]},
    {"code": "T02", "name": "首次有效接触", "short_form": "已了解门店基本需求，决策角色和采购时机仍待确认。",
     "guidance": "先了解门店需求，不首次沟通就强求完整画像。", "record_fields": [field("contact_role", "联系人角色", emphasis="key", nature="to_confirm"), field("main_products", "主做品类", emphasis="key", nature="customer_said"), field("core_need", "当前最关心的问题", "textarea", nature="customer_said"), field("amount_meaning", "金额及含义", "amount", nature="to_confirm")],
     "avoid": [{"rule": "金额范围不能自动补成采购预算", "keywords": ["采购预算", "高意向"]}]},
    {"code": "T03", "name": "价格异议 / 报价后犹豫", "short_form": "客户觉得价格高，比较对象和金额含义待确认；下一步先核实比较口径。",
     "guidance": "同样说贵原因不同。先分清采购价、终端售价、比较价格，再问比较的是哪一款、什么规格；不要直接给降价方案。",
     "prep_fields": [field("quoted_product", "报价产品与规格", emphasis="key")],
     "record_fields": [field("product", "涉及产品", emphasis="key"), field("amount_meaning", "金额及含义", "amount", emphasis="key", nature="to_confirm", options={"inline": ["我方报价", "客户采购预算", "终端售价", "比较价格", "未确认"]}, hint="不确定就选未确认"), field("concerns", "已确认的顾虑", "multiselect", emphasis="key", nature="customer_said", options={"inline": ["采购投入", "售价空间", "压货", "效果价值", "交期", "其他"]}), field("response_result", "本次回应及客户反应", "textarea"), field("comparison", "比较对象", nature="customer_said")],
     "avoid": [{"rule": "客户说贵 ≠ 预算不足", "keywords": ["预算不足", "买不起", "没预算"]}, {"rule": "解释过价值 ≠ 客户已接受", "keywords": ["已接受", "认可价格"]}]},
    {"code": "T04", "name": "询单、报价与规格确认", "short_form": "已记录询单与已知规格，未确认项仍需逐项核对。",
     "guidance": "区分业务员口头说下单与系统正式订单，未确认的库存交期不能补齐。", "record_fields": [field("business_stage", "业务阶段", "select", emphasis="key", options={"inline": ["询单", "已报价", "待确认", "已下单"]}), field("purpose", "用途", "select", emphasis="key", nature="customer_said", options={"inline": ["具体终端顾客", "门店样品", "备货", "未确认"]}), field("confirmed_specs", "已经确认", "textarea"), field("open_specs", "尚未确认", "textarea", nature="to_confirm"), field("commitment", "我方对外承诺", "textarea", nature="business_fact")], "avoid": [{"rule": "询单不等于已正式下单", "keywords": ["已投产", "全部确认"]}]},
    {"code": "T05", "name": "寄样、收货与试戴回访", "short_form": "已记录收货与试用进度，实际效果和后续决定仍待验证。",
     "guidance": "区分物流显示与客户确认，区分已试用与尚未试用，不把无问题反馈扩大成全部指标通过。", "record_fields": [field("product_batch", "样品 / 货品与批次", emphasis="key"), field("receipt_state", "实际收货情况", "select", emphasis="key", options={"inline": ["物流显示签收", "客户确认收货", "尚未收到", "未确认"]}), field("validation_goal", "本次验证目标", "textarea", emphasis="key"), field("actual_feedback", "客户反馈", "textarea", nature="customer_said"), field("next_validation", "下一步验证", "event", nature="to_confirm")], "avoid": [{"rule": "拿样不等于满意或准备批量采购", "keywords": ["样品满意", "准备批量采购"]}]},
    {"code": "T06", "name": "售后、投诉与技术问题", "short_form": "已记录售后问题与处理进度，技术原因和最终效果仍待核实。",
     "guidance": "先处理售后再谈销售。保留不同角色的意见，客户诉求不等于我方方案已被接受。", "prep_fields": [field("affected_product", "受影响产品 / 批次", emphasis="key")],
     "record_fields": [field("affected_product", "受影响产品 / 批次", emphasis="key"), field("affected_quantity", "受影响数量", nature="to_confirm"), field("customer_request", "客户诉求", "select", emphasis="key", nature="customer_said", options={"inline": ["调整 / 维修", "退", "换", "说明", "尚未提出"]}), field("problem_fact", "问题事实与证据", "textarea", emphasis="key", nature="customer_said"), field("handling_done", "已做的处理"), field("acceptance", "怎样算解决", "textarea", nature="to_confirm"), field("customer_cooperation", "待客户配合", "textarea", nature="to_confirm")],
     "avoid": [{"rule": "已发起处理不等于客户确认解决", "keywords": ["已经解决", "客户满意", "技术合格"]}]},
    {"code": "T07", "name": "短视频 / 直播 / 经营支持", "short_form": "已记录经营问题与本次支持，作品效果和采购关联仍待观察。",
     "guidance": "只记录实际交付与客户回应，未读取的视频不评价，不虚构播放量和采购意向。", "record_fields": [field("business_problem", "客户已表达的经营问题", "select", emphasis="key", nature="customer_said", options={"inline": ["曝光", "咨询", "到店", "试戴成交", "其他"]}), field("deliverable", "本次交付", "textarea", emphasis="key"), field("customer_response", "客户回应", "textarea", nature="customer_said"), field("review_trigger", "复核条件", "event", nature="to_confirm")], "avoid": [{"rule": "收到或答应尝试不等于已发布或已产生效果", "keywords": ["播放量提高", "因此会采购"]}]},
    {"code": "T08", "name": "老客户维护与复购", "short_form": "已核对上批反馈与补货意向，未结售后和实际补货决定分开记录。",
     "guidance": "以上批产品和明确反馈为依据，先处理阻碍复购的售后。", "record_fields": [field("last_batch", "本次依据", emphasis="key"), field("sales_feedback", "销售 / 使用情况", "textarea", emphasis="key", nature="customer_said"), field("replenishment", "剩余产品 / 补货需求", "textarea", nature="customer_said"), field("blockers", "阻碍复购的事项", "textarea", nature="to_confirm")], "avoid": [{"rule": "备货意向不等于已下单", "keywords": ["已经复购", "确定下单"]}]},
    {"code": "T09", "name": "休眠激活 / 开新店", "short_form": "已记录重新联系的真实触发，新变化和当前需求仍待核实。",
     "guidance": "围绕真实经营节点重新联系，区分计划与已发生，不预填样品数量或订单金额。", "record_fields": [field("trigger", "重新联系的触发", emphasis="key", nature="business_fact"), field("new_change", "这次新确认的变化", "textarea", emphasis="key", nature="customer_said"), field("fit_assessment", "产品适配判断及依据", "textarea", nature="assessment"), field("next_milestone", "下一经营节点", "event", nature="to_confirm")], "avoid": [{"rule": "计划开店不等于已开店或有确定采购", "keywords": ["已经开业", "确定采购"]}]},
    {"code": "T10", "name": "拒绝、不适配或交接", "short_form": "已记录拒绝或暂停事实，拒绝范围、未结事项和重新评估条件待明确。",
     "guidance": "明确拒绝时停止对应营销触达，不换渠道继续逼单；保留未结售后和我方承诺。", "record_fields": [field("refusal_fact", "本次事实与来源", "textarea", emphasis="key", nature="customer_said"), field("refusal_scope", "拒绝范围", "select", emphasis="key", nature="customer_said", options={"inline": ["本次产品", "当前时机", "该渠道", "所有营销联系", "尚不清楚"]}), field("open_commitments", "未结事项", "textarea"), field("reevaluate_when", "未来重新评估条件", "event", nature="to_confirm")], "avoid": [{"rule": "拒绝当前触达不等于永久不适配或客户失信", "keywords": ["永久不适配", "失信客户", "换渠道继续"]}]},
]

for template in TEMPLATE_SEEDS:
    template.setdefault("prep_fields", [])
    template.setdefault("params", dict(DEFAULT_PARAMS))
