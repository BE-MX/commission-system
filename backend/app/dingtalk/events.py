"""业务事件 → 钉钉消息模板映射

所有通知函数：异步触发、失败不影响主流程。
业务模块直接 import 此文件中的函数调用即可。
"""

import logging
from datetime import date, datetime

from app.dingtalk.webhook import get_webhook_sender
from app.dingtalk.work_notify import get_work_notifier

logger = logging.getLogger("commission.dingtalk")


def _safe_notify(coro):
    """安全包装：通知失败仅 log，不抛异常"""

    async def wrapper(*args, **kwargs):
        try:
            await coro(*args, **kwargs)
        except Exception as e:
            logger.warning("钉钉通知发送失败（不影响业务）: %s", e)

    return wrapper


# ══════════════════════════════════════════════════════════════
#  提成相关
# ══════════════════════════════════════════════════════════════


@_safe_notify
async def notify_commission_ready(
    batch_id: int,
    period: str,
    result_count: int,
    total_amount: float,
    link: str = "",
):
    """提成批次计算完成通知"""
    sender = get_webhook_sender()
    text = (
        f"###  提成批次计算完成\n"
        f"**批次号：** {batch_id}\n"
        f"**计算期间：** {period}\n"
        f"**涉及人数：** {result_count} 人\n"
        f"**总提成金额：** ¥{total_amount:,.2f}\n"
    )
    if link:
        text += f"[查看详情]({link})\n"

    await sender.send_markdown(title="提成计算完成", text=text)


# ══════════════════════════════════════════════════════════════
#  回款相关
# ══════════════════════════════════════════════════════════════


@_safe_notify
async def notify_payment_alert(
    customer_name: str,
    order_id: str,
    alert_type: str,
    detail: str,
):
    """回款异常预警"""
    sender = get_webhook_sender()
    text = (
        f"###  回款异常预警\n"
        f"**客户：** {customer_name}\n"
        f"**订单号：** {order_id}\n"
        f"**异常类型：** {alert_type}\n"
        f"**详情：** {detail}\n"
    )
    await sender.send_markdown(title="回款异常预警", text=text, is_at_all=True)


@_safe_notify
async def notify_payment_sync_done(
    date_start: str,
    date_end: str,
    new_synced: int,
    total_payments: int,
):
    """回款同步完成通知"""
    sender = get_webhook_sender()
    text = (
        f"###  回款数据同步完成\n"
        f"**同步区间：** {date_start} ~ {date_end}\n"
        f"**回款总数：** {total_payments} 条\n"
        f"**新同步：** {new_synced} 条\n"
    )
    await sender.send_markdown(title="回款同步完成", text=text)


# ══════════════════════════════════════════════════════════════
#  设计预约相关
# ══════════════════════════════════════════════════════════════

# 优先级中文映射
_PRIORITY_LABELS = {"normal": "普通", "urgent": "加急"}


def _build_request_markdown(
    title: str,
    *,
    request_no: str,
    salesperson_name: str = "",
    customer_name: str = "",
    customer_level: str = "",
    shoot_type: str = "",
    schedule_date: str = "",
    priority: str = "",
    remark: str = "",
    extra_lines: list[str] | None = None,
) -> str:
    """构建统一的设计预约通知 Markdown 文本

    所有字段值应已翻译为显示名（由调用方完成字典转换）。
    使用分隔线让各行在钉钉客户端清晰可读。
    """
    sep = "———————————"
    lines = [
        f"### {title}",
        sep,
        f"预约编号：{request_no}",
        f"业务员：{salesperson_name}",
        f"客户名称：{customer_name}",
        f"客户等级：{customer_level}",
        f"拍摄类型：{shoot_type}",
        f"期望日期：{schedule_date}",
        f"优先级：{_PRIORITY_LABELS.get(priority, priority)}",
        f"备注：{remark or '无'}",
    ]
    if extra_lines:
        lines.append(sep)
        lines.extend(extra_lines)
    lines.append(sep)
    return "\n\n".join(lines)


@_safe_notify
async def notify_design_audit_needed(
    reviewer_dingtalk_ids: list[str],
    *,
    request_no: str,
    salesperson_name: str = "",
    customer_name: str = "",
    customer_level: str = "",
    shoot_type: str = "",
    schedule_date: str = "",
    priority: str = "",
    remark: str = "",
    conflict_summary: str = "",
):
    """设计预约需要审批 — 向主管发送点对点工作通知"""
    if not reviewer_dingtalk_ids:
        logger.info("无主管钉钉ID，跳过审批点对点通知 (单号: %s)", request_no)
        return

    extra = []
    if conflict_summary:
        extra.append(f"**冲突原因：** {conflict_summary}")

    md = _build_request_markdown(
        "📋 设计预约待审批",
        request_no=request_no,
        salesperson_name=salesperson_name,
        customer_name=customer_name,
        customer_level=customer_level,
        shoot_type=shoot_type,
        schedule_date=schedule_date,
        priority=priority,
        remark=remark,
        extra_lines=extra,
    )

    notifier = get_work_notifier()
    await notifier.send_to_users(
        user_ids=reviewer_dingtalk_ids,
        title="设计预约待审批",
        markdown_text=md,
    )


@_safe_notify
async def notify_design_request_approved(
    applicant_dingtalk_id: str = "",
    *,
    request_no: str,
    salesperson_name: str = "",
    customer_name: str = "",
    customer_level: str = "",
    shoot_type: str = "",
    schedule_date: str = "",
    priority: str = "",
    remark: str = "",
):
    """设计预约审批通过 — 向申请人发点对点通知"""
    if not applicant_dingtalk_id:
        logger.info("申请人无钉钉ID，跳过审批通过通知 (单号: %s)", request_no)
        return

    md = _build_request_markdown(
        "✅ 你的设计预约已通过",
        request_no=request_no,
        salesperson_name=salesperson_name,
        customer_name=customer_name,
        customer_level=customer_level,
        shoot_type=shoot_type,
        schedule_date=schedule_date,
        priority=priority,
        remark=remark,
    )

    notifier = get_work_notifier()
    await notifier.send_to_users(
        user_ids=[applicant_dingtalk_id],
        title="设计预约已通过",
        markdown_text=md,
    )


@_safe_notify
async def notify_design_request_rejected(
    applicant_dingtalk_id: str = "",
    *,
    request_no: str,
    salesperson_name: str = "",
    customer_name: str = "",
    customer_level: str = "",
    shoot_type: str = "",
    schedule_date: str = "",
    priority: str = "",
    remark: str = "",
    reject_reason: str = "",
):
    """设计预约审批拒绝 — 向申请人发点对点通知"""
    if not applicant_dingtalk_id:
        logger.info("申请人无钉钉ID，跳过审批拒绝通知 (单号: %s)", request_no)
        return

    extra = [f"**拒绝原因：** {reject_reason}"] if reject_reason else []

    md = _build_request_markdown(
        "❌ 你的设计预约被拒绝",
        request_no=request_no,
        salesperson_name=salesperson_name,
        customer_name=customer_name,
        customer_level=customer_level,
        shoot_type=shoot_type,
        schedule_date=schedule_date,
        priority=priority,
        remark=remark,
        extra_lines=extra,
    )

    notifier = get_work_notifier()
    await notifier.send_to_users(
        user_ids=[applicant_dingtalk_id],
        title="设计预约被拒绝",
        markdown_text=md,
    )


@_safe_notify
async def notify_design_ready_for_design(
    designer_dingtalk_ids: list[str],
    *,
    request_no: str,
    salesperson_name: str = "",
    customer_name: str = "",
    customer_level: str = "",
    shoot_type: str = "",
    schedule_date: str = "",
    priority: str = "",
    remark: str = "",
    source: str = "",
):
    """预约单进入待排期 — 向设计部成员发送点对点工作通知

    source: "审核通过" 或 "直接提交"，用于区分来源
    """
    if not designer_dingtalk_ids:
        logger.info("无设计部钉钉ID，跳过待排期通知 (单号: %s)", request_no)
        return

    extra = [f"**来源：** {source}"] if source else []

    md = _build_request_markdown(
        "📐 新预约单待排期",
        request_no=request_no,
        salesperson_name=salesperson_name,
        customer_name=customer_name,
        customer_level=customer_level,
        shoot_type=shoot_type,
        schedule_date=schedule_date,
        priority=priority,
        remark=remark,
        extra_lines=extra,
    )

    notifier = get_work_notifier()
    await notifier.send_to_users(
        user_ids=designer_dingtalk_ids,
        title="新预约单待排期",
        markdown_text=md,
    )


# ══════════════════════════════════════════════════════════════
#  超期/预警
# ══════════════════════════════════════════════════════════════


@_safe_notify
async def notify_overdue_alert(
    alert_title: str,
    items: list[dict],
):
    """超期预警汇总通知"""
    sender = get_webhook_sender()
    text = f"### ⏰ {alert_title}\n"
    for item in items[:10]:  # 最多展示 10 条
        text += f"- {item.get('desc', str(item))}\n"
    if len(items) > 10:
        text += f"- ...共 {len(items)} 条\n"

    await sender.send_markdown(title=alert_title, text=text, is_at_all=True)


# ══════════════════════════════════════════════════════════════
#  工作通知（企业内部应用）
# ══════════════════════════════════════════════════════════════


@_safe_notify
async def notify_user_work(
    user_ids: list[str],
    title: str,
    content: str,
    link: str = "",
):
    """向指定用户发送工作通知"""
    notifier = get_work_notifier()
    md = f"{content}\n"
    if link:
        md += f"[查看详情]({link})\n"

    await notifier.send_to_users(user_ids=user_ids, title=title, markdown_text=md)
