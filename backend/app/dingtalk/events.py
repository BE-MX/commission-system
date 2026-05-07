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


@_safe_notify
async def notify_design_request_submitted(
    request_no: str,
    customer_name: str,
    applicant_name: str,
    designer_name: str,
    schedule_date: str,
    link: str = "",
):
    """设计预约申请提交通知（群消息广播）"""
    sender = get_webhook_sender()
    text = (
        f"###  新的设计预约申请\n"
        f"**单号：** {request_no}\n"
        f"**客户：** {customer_name}\n"
        f"**申请人：** {applicant_name}\n"
        f"**指派设计师：** {designer_name}\n"
        f"**预约日期：** {schedule_date}\n"
    )
    if link:
        text += f"[去审批]({link})\n"

    await sender.send_markdown(title="新设计预约", text=text)


@_safe_notify
async def notify_design_audit_needed(
    reviewer_dingtalk_ids: list[str],
    request_no: str,
    customer_name: str,
    applicant_name: str,
    schedule_date: str,
    conflict_summary: str = "",
    link: str = "",
):
    """设计预约需要审批 — 向主管发送点对点工作通知"""
    if not reviewer_dingtalk_ids:
        logger.info("无主管钉钉ID，跳过审批点对点通知 (单号: %s)", request_no)
        return

    notifier = get_work_notifier()
    md = (
        f"### 📋 设计预约待审批\n"
        f"**单号：** {request_no}\n"
        f"**客户：** {customer_name}\n"
        f"**申请人：** {applicant_name}\n"
        f"**预约日期：** {schedule_date}\n"
    )
    if conflict_summary:
        md += f"**冲突原因：** {conflict_summary}\n"
    if link:
        md += f"\n[去审批]({link})\n"

    await notifier.send_to_users(
        user_ids=reviewer_dingtalk_ids,
        title="设计预约待审批",
        markdown_text=md,
    )


@_safe_notify
async def notify_design_request_approved(
    request_no: str,
    customer_name: str,
    designer_name: str,
    schedule_date: str,
    applicant_dingtalk_id: str = "",
    link: str = "",
):
    """设计预约审批通过 — 群消息 + 向申请人发点对点通知"""
    sender = get_webhook_sender()
    text = (
        f"### ✅ 设计预约已通过\n"
        f"**单号：** {request_no}\n"
        f"**客户：** {customer_name}\n"
        f"**设计师：** {designer_name}\n"
        f"**预约日期：** {schedule_date}\n"
    )
    if link:
        text += f"[查看详情]({link})\n"

    await sender.send_markdown(title="设计预约通过", text=text)

    # 同时给申请人发工作通知
    if applicant_dingtalk_id:
        notifier = get_work_notifier()
        md = (
            f"### ✅ 你的设计预约已通过\n"
            f"**单号：** {request_no}\n"
            f"**客户：** {customer_name}\n"
            f"**预约日期：** {schedule_date}\n"
        )
        if link:
            md += f"\n[查看详情]({link})\n"
        await notifier.send_to_users(
            user_ids=[applicant_dingtalk_id],
            title="设计预约已通过",
            markdown_text=md,
        )


@_safe_notify
async def notify_design_request_rejected(
    request_no: str,
    customer_name: str,
    reason: str,
    applicant_dingtalk_id: str = "",
    link: str = "",
):
    """设计预约审批拒绝 — 群消息 + 向申请人发点对点通知"""
    sender = get_webhook_sender()
    text = (
        f"### ❌ 设计预约被拒绝\n"
        f"**单号：** {request_no}\n"
        f"**客户：** {customer_name}\n"
        f"**拒绝原因：** {reason}\n"
    )
    if link:
        text += f"[查看详情]({link})\n"

    await sender.send_markdown(title="设计预约被拒", text=text)

    # 同时给申请人发工作通知
    if applicant_dingtalk_id:
        notifier = get_work_notifier()
        md = (
            f"### ❌ 你的设计预约被拒绝\n"
            f"**单号：** {request_no}\n"
            f"**客户：** {customer_name}\n"
            f"**拒绝原因：** {reason}\n"
        )
        if link:
            md += f"\n[查看详情]({link})\n"
        await notifier.send_to_users(
            user_ids=[applicant_dingtalk_id],
            title="设计预约被拒绝",
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
