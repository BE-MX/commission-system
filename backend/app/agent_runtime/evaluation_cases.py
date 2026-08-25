"""Versioned business-owned evaluation cases for the customer copilot."""

from __future__ import annotations


COPILOT_EVALUATION_SUITE = "customer_order_copilot_v1"


def _case(
    number: int,
    category: str,
    title: str,
    question: str,
    *,
    requires: tuple[str, ...],
    quantitative: bool = True,
) -> dict:
    return {
        "case_id": f"standard-{number:02d}",
        "suite": COPILOT_EVALUATION_SUITE,
        "category": category,
        "title": title,
        "question": question,
        "requires": list(requires),
        "quantitative_expected": quantitative,
        "rubric": [
            "只使用当前客户和授权业务数据，不补造事实",
            "事实、风险与建议逐条绑定成功工具调用证据",
            "结论可直接支持销售判断，信息不足时明确指出缺口",
        ],
    }


COPILOT_EVALUATION_CASES = (
    _case(1, "画像", "客户经营概览", "请概括这个客户当前的经营状态、价值和最需要关注的事项。", requires=("customer_profile",)),
    _case(2, "画像", "画像事实核对", "当前客户画像里的标签和判断分别由哪些近期事实支持？", requires=("customer_profile", "profile_events")),
    _case(3, "画像", "最近变化", "这个客户最近发生了哪些值得业务员关注的变化？按时间说明。", requires=("profile_events",)),
    _case(4, "画像", "数据新鲜度", "客户画像和关键经营信号分别更新到什么时候？哪些信息可能已经过期？", requires=("customer_profile", "profile_events")),
    _case(5, "画像", "信息缺口", "要做出可靠的下一步经营判断，目前还缺少哪些关键客户信息？", requires=("customer_profile",), quantitative=False),
    _case(6, "订单", "订单时间线", "请梳理这个客户近三年的订单时间线，并指出关键节点。", requires=("order_history",)),
    _case(7, "订单", "最近订单", "客户最近一笔有效订单的单号、日期和可确认金额是什么？", requires=("order_history",)),
    _case(8, "订单", "订单规模趋势", "客户的订单次数、金额和采购规模呈现什么趋势？", requires=("order_history",)),
    _case(9, "订单", "来源与国家", "近三年订单记录中可确认的客户国家和来源类别有哪些？是否存在前后不一致？", requires=("order_history",)),
    _case(10, "订单", "采购节奏", "客户通常间隔多久复购？当前距离其历史采购节奏还有多久？", requires=("order_history", "repurchase_analysis")),
    _case(11, "复购", "复购窗口", "这个客户是否已经进入复购窗口？请给出可核验依据。", requires=("repurchase_analysis",)),
    _case(12, "复购", "流失风险", "客户当前有哪些流失或沉默风险信号？风险判断的证据是什么？", requires=("repurchase_analysis", "profile_events")),
    _case(13, "复购", "复购优先级", "与该客户当前信号相比，为什么现在应该或不应该优先跟进？", requires=("repurchase_analysis", "customer_actions")),
    _case(14, "复购", "唤醒策略", "仅基于客户已确认的订单节奏和近期事件，如果要唤醒该客户，建议什么时机和切入点？", requires=("repurchase_analysis", "profile_events"), quantitative=False),
    _case(15, "复购", "异常周期", "客户最近一次采购间隔是否显著偏离其历史节奏？可能原因有哪些？", requires=("order_history", "repurchase_analysis")),
    _case(16, "行动", "今日行动", "针对这个客户，今天最值得执行的一项行动是什么？为什么？", requires=("customer_actions", "customer_profile"), quantitative=False),
    _case(17, "行动", "行动冲突检查", "系统里是否已有针对该客户的待办或跟进行动？请避免重复建议。", requires=("customer_actions",)),
    _case(18, "行动", "跟进顺序", "请把这个客户现有的待办按紧迫性和业务价值排序，并说明依据。", requires=("customer_actions", "customer_profile")),
    _case(19, "行动", "沟通草稿", "请基于已确认事实起草一段跟进消息，不承诺价格、库存或交期。", requires=("customer_profile", "order_history"), quantitative=False),
    _case(20, "行动", "人工确认点", "执行下一步行动前，业务员还必须人工确认哪些事项？", requires=("customer_profile", "customer_actions"), quantitative=False),
    _case(21, "订单证据", "新签与首返", "近三年哪些订单被系统标记为新签或首返？请按时间说明。", requires=("order_history",)),
    _case(22, "订单证据", "最大最小订单", "在当前三年窗口内，可确认金额最大和最小的订单分别是哪一笔？", requires=("order_history",)),
    _case(23, "订单证据", "订单均值", "根据当前有效订单数和总金额，近三年平均每笔订单金额是多少？", requires=("order_history",)),
    _case(24, "订单证据", "窗口与截断", "当前订单时间窗口和返回条数是什么？结果是否被截断，对结论有什么限制？", requires=("order_history",)),
    _case(25, "订单证据", "金额与次数核对", "请核对订单摘要的订单数和总金额是否与返回明细一致；若被截断则明确说明无法完整核对。", requires=("order_history",)),
    _case(26, "订单证据", "订单事实边界", "从现有订单时间线可以确认哪些事实？哪些产品、交付或报价信息当前不能得出？", requires=("order_history",), quantitative=False),
    _case(27, "综合", "多源一致性", "客户画像、订单与现有行动信息之间是否存在相互矛盾之处？", requires=("customer_profile", "order_history", "customer_actions")),
    _case(28, "综合", "机会与风险", "请分别列出这个客户当前最重要的机会、风险和证据。", requires=("customer_profile", "order_history", "repurchase_analysis")),
    _case(29, "综合", "管理层摘要", "请给管理者一份简短客户摘要：现状、变化、风险和下一步。", requires=("customer_profile", "order_history", "customer_actions")),
    _case(30, "综合", "证据充分性", "仅依据现有可验证数据，当前能得出哪些结论，哪些结论暂时不能得出？", requires=("customer_profile", "order_history", "repurchase_analysis")),
)


COPILOT_CASES_BY_ID = {item["case_id"]: item for item in COPILOT_EVALUATION_CASES}
