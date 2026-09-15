"""邮件触达域集中策略常量与规范化哈希。

所有跨模块共享的口径只在这里维护一份；业务默认值可被 settings 覆盖。
"""

import hashlib
import json

# 收件人冷却期（同一联系点在冷却期内不得重复触达）
RECIPIENT_COOLDOWN_DAYS = 14
# 政策内允许的最大顺延次数（与原型 MAX_LATE_MINUTES 对齐）
MAX_RESCHEDULES = 2
MAX_LATE_MINUTES = 30
# 排程默认办公开始时间（客户当地），算法侧另加 5 分钟
OFFICE_START_DEFAULT = "09:00"
# 排程侧车调用超时（秒）
SCHEDULE_SERVICE_TIMEOUT_SEC = 5
# 邮箱默认日额度（上线时以腾讯页面口径为准）
DEFAULT_DAILY_QUOTA = 50


def canonical_sha256(payload: dict) -> str:
    """对规范化 JSON（排序键、紧凑分隔符）计算 SHA-256。"""
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_content_sha256(*, subject: str, body_text: str, language_tag: str, claims: list) -> str:
    """revision 内容哈希：subject+body+language+claims 变化即产生新哈希。"""
    return canonical_sha256({
        "subject": subject,
        "body_text": body_text,
        "language_tag": language_tag,
        "claims": claims,
    })


def compute_approval_sha256(
    *,
    content_sha256: str,
    mailbox_binding_id: int,
    to_contact_point_id: int,
    to_email_snapshot: str,
    language_tag: str,
    schedule_policy: dict,
    scheduled_at_utc: str,
) -> str:
    """批准载荷哈希：绑定版本内容、发件身份、精确收件人、语言与排程政策。"""
    return canonical_sha256({
        "content_sha256": content_sha256,
        "mailbox_binding_id": mailbox_binding_id,
        "to_contact_point_id": to_contact_point_id,
        "to_email_snapshot": to_email_snapshot,
        "language_tag": language_tag,
        "schedule_policy": schedule_policy,
        "scheduled_at_utc": scheduled_at_utc,
    })


def job_idempotency_key(message_id: int, revision_id: int) -> str:
    """同一批准只生成一个 job 的派生幂等键。"""
    return hashlib.sha256(f"mailjob:{message_id}:{revision_id}".encode("utf-8")).hexdigest()
