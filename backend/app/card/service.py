"""Service layer for the sales-card butler module.

口令语义：客户输入自己的邮箱或 WhatsApp 号。归一化规则必须与录入侧完全一致，
否则「录得进、解不开」——两侧都只经 normalize_passcode() 一个入口。
"""

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session, selectinload

from app.card.models import CardCustomer, CardEntry, CardInquiry, CardSalesperson

logger = logging.getLogger("commission.card")

_MIN_WA_DIGITS = 5  # 短于 5 位的纯数字当作无效口令，避免 "123" 之类碰撞


def normalize_passcode(raw: str) -> tuple[Optional[str], Optional[str]]:
    """原始输入 → (email_norm, whatsapp_norm)，两者至多一个非空。

    含 @ → 邮箱：去空白、小写。
    否则 → WhatsApp：剥掉一切非数字（+86 155-0000 → 86155…）；不足 5 位视为无效。
    """
    value = (raw or "").strip()
    if not value:
        return None, None
    if "@" in value:
        return value.lower().replace(" ", ""), None
    digits = re.sub(r"\D", "", value)
    if len(digits) < _MIN_WA_DIGITS:
        return None, None
    return None, digits


def get_salesperson(db: Session, slug: str, active_only: bool = True) -> Optional[CardSalesperson]:
    q = db.query(CardSalesperson).filter(CardSalesperson.slug == slug)
    if active_only:
        q = q.filter(CardSalesperson.is_active == 1)
    return q.first()


def entry_dict(entry: CardEntry) -> dict:
    return {
        "id": entry.id,
        "entry_type": entry.entry_type,
        "title": entry.title,
        "content": entry.content,
        "attachment_url": f"/uploads/{entry.attachment_path}" if entry.attachment_path else None,
        "created_at": entry.created_at.strftime("%Y-%m-%d") if entry.created_at else None,
    }


def unlock(db: Session, slug: str, passcode: str) -> Optional[dict]:
    """口令解锁：返回该业务员名下命中客户的档案+纪要；未命中返回 None。

    多条命中（同客户重复建档）取最新一条，不报错——展会现场录重是常态。
    """
    sp = get_salesperson(db, slug)
    if sp is None:
        return None
    email_norm, wa_norm = normalize_passcode(passcode)
    if email_norm is None and wa_norm is None:
        return None
    q = (
        db.query(CardCustomer)
        .options(selectinload(CardCustomer.entries))
        .filter(CardCustomer.salesperson_id == sp.id)
    )
    if email_norm is not None:
        q = q.filter(CardCustomer.email_norm == email_norm)
    else:
        q = q.filter(CardCustomer.whatsapp_norm == wa_norm)
    customer = q.order_by(CardCustomer.id.desc()).first()
    if customer is None:
        return None
    entries = sorted(customer.entries, key=lambda e: (e.created_at, e.id))
    return {
        "customer": {"name": customer.display_name, "expo_code": customer.expo_code},
        "entries": [entry_dict(e) for e in entries],
    }


def create_inquiry(db: Session, slug: str, contact: str, message: str) -> Optional[CardInquiry]:
    """公开表单落库；联系方式若命中该业务员的客户档案则回填 customer_id。"""
    sp = get_salesperson(db, slug)
    if sp is None:
        return None
    email_norm, wa_norm = normalize_passcode(contact)
    customer_id = None
    if email_norm is not None or wa_norm is not None:
        q = db.query(CardCustomer.id).filter(CardCustomer.salesperson_id == sp.id)
        if email_norm is not None:
            q = q.filter(CardCustomer.email_norm == email_norm)
        else:
            q = q.filter(CardCustomer.whatsapp_norm == wa_norm)
        row = q.order_by(CardCustomer.id.desc()).first()
        customer_id = row[0] if row else None
    inquiry = CardInquiry(
        salesperson_id=sp.id, customer_id=customer_id,
        contact=contact.strip()[:128], message=message.strip(),
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return inquiry


# ---------- 管理侧 ----------

def customer_dict(c: CardCustomer, entry_count: Optional[int] = None) -> dict:
    return {
        "id": c.id,
        "salesperson_id": c.salesperson_id,
        "display_name": c.display_name,
        "email_norm": c.email_norm,
        "whatsapp_norm": c.whatsapp_norm,
        "expo_code": c.expo_code,
        "remark": c.remark,
        "entry_count": entry_count if entry_count is not None else len(c.entries),
        "created_at": c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else None,
    }


def apply_customer_contacts(customer: CardCustomer, email: Optional[str], whatsapp: Optional[str]) -> None:
    """录入侧与口令同源归一化。传 None 表示不改，传空串表示清除。

    录入错误显式报 ValueError（如邮箱漏 @ 被当号码、号码位数不足）——静默归一成
    另一个口径会让客户「录得进、解不开」，这里必须挡在录入时。
    """
    if email is not None:
        value = email.strip()
        if not value:
            customer.email_norm = None
        elif "@" not in value:
            raise ValueError("邮箱格式不对（缺 @）")
        else:
            customer.email_norm = value.lower().replace(" ", "")
    if whatsapp is not None:
        value = whatsapp.strip()
        if not value:
            customer.whatsapp_norm = None
        else:
            digits = re.sub(r"\D", "", value)
            if len(digits) < _MIN_WA_DIGITS:
                raise ValueError(f"WhatsApp 号至少 {_MIN_WA_DIGITS} 位数字")
            customer.whatsapp_norm = digits


def customer_has_passcode(customer: CardCustomer) -> bool:
    return bool(customer.email_norm or customer.whatsapp_norm)
