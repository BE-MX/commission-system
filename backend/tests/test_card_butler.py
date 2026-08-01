"""名片管家：口令归一化 / 解锁隔离 / 询盘回填（口令即客户数据可见性闸门）"""

import pytest

from app.card import service
from app.card.models import (  # noqa: F401 —— 注册进 Base.metadata 供 conftest 建表
    CardCustomer,
    CardEntry,
    CardInquiry,
    CardSalesperson,
)


@pytest.fixture(autouse=True)
def _mute_inquiry_push(monkeypatch):
    """默认静音钉钉推送——开发机 .env 配有真实 webhook，不静音则每跑一次测试群里响一次。"""
    monkeypatch.setattr(service, "_notify_inquiry", lambda *a: None)


def _reset(db):
    """FK 安全顺序清场（commit 过的行不受 fixture 回滚保护，与 festival 先例一致）。"""
    db.query(CardInquiry).delete()
    db.query(CardEntry).delete()
    db.query(CardCustomer).delete()
    db.query(CardSalesperson).delete()
    db.flush()


def _seed(db):
    _reset(db)
    sp = CardSalesperson(slug="ginny", name="Ginny", email="ginny@leshinehair.com")
    other = CardSalesperson(slug="katy", name="Katy", email="katy@leshinehair.com")
    db.add_all([sp, other])
    db.flush()
    customer = CardCustomer(
        salesperson_id=sp.id, display_name="Maria",
        email_norm="maria@buyer.com", whatsapp_norm="8613800138000",
    )
    db.add(customer)
    db.flush()
    db.add_all([
        CardEntry(customer_id=customer.id, entry_type="text", title="Quotation", content="Lace wig 20pcs"),
        CardEntry(customer_id=customer.id, entry_type="image", attachment_path="card/abc.jpg"),
    ])
    db.flush()
    return sp, other, customer


# ---------- 归一化 ----------

def test_normalize_email_lower_and_strip():
    assert service.normalize_passcode("  Maria@Buyer.COM ") == ("maria@buyer.com", None)


def test_normalize_whatsapp_digits_only():
    assert service.normalize_passcode("+86 138-0013-8000") == (None, "8613800138000")


def test_normalize_rejects_short_and_empty():
    assert service.normalize_passcode("123") == (None, None)
    assert service.normalize_passcode("   ") == (None, None)


# ---------- 解锁 ----------

def test_unlock_by_email_returns_entries(db):
    _seed(db)
    data = service.unlock(db, "ginny", " MARIA@buyer.com ")
    assert data is not None
    assert data["customer"]["name"] == "Maria"
    assert len(data["entries"]) == 2
    assert data["entries"][1]["attachment_url"] == "/uploads/card/abc.jpg"


def test_unlock_by_whatsapp_formatted(db):
    _seed(db)
    data = service.unlock(db, "ginny", "+86 138 0013 8000")
    assert data is not None and data["customer"]["name"] == "Maria"


def test_unlock_wrong_passcode_or_slug_is_none(db):
    _seed(db)
    assert service.unlock(db, "ginny", "nobody@else.com") is None
    assert service.unlock(db, "no-such-slug", "maria@buyer.com") is None
    assert service.unlock(db, "ginny", "12") is None


def test_unlock_scoped_to_salesperson(db):
    """同一口令在别的业务员页面必须打不开——客户档案跟人。"""
    _seed(db)
    assert service.unlock(db, "katy", "maria@buyer.com") is None


def test_unlock_inactive_salesperson_is_none(db):
    sp, _, _ = _seed(db)
    sp.is_active = 0
    db.flush()
    assert service.unlock(db, "ginny", "maria@buyer.com") is None


def test_unlock_duplicate_customer_latest_name_merged_entries(db):
    """重复建档：称呼取最新，纪要聚合全部命中档案（旧档照片不许对客户隐身）。"""
    sp, _, first = _seed(db)
    dup = CardCustomer(
        salesperson_id=sp.id, display_name="Maria (new)", email_norm="maria@buyer.com",
    )
    db.add(dup)
    db.flush()
    data = service.unlock(db, "ginny", "maria@buyer.com")
    assert data["customer"]["name"] == "Maria (new)"
    assert len(data["entries"]) == 2  # 旧档案的两条纪要仍然可见


def test_unlock_whatsapp_suffix_bridges_country_code(db):
    """库存 +86 全号、客户输本地号（或反向）——尾部 9 位后缀兜底。"""
    _seed(db)  # 库存 8613800138000
    data = service.unlock(db, "ginny", "13800138000")
    assert data is not None and data["customer"]["name"] == "Maria"


def test_unlock_whatsapp_suffix_reverse_direction(db):
    sp, _, _ = _seed(db)
    local = CardCustomer(
        salesperson_id=sp.id, display_name="LocalNo", whatsapp_norm="15500001111",
    )
    db.add(local)
    db.flush()
    data = service.unlock(db, "ginny", "+86 155 0000 1111")
    assert data is not None and data["customer"]["name"] == "LocalNo"


def test_unlock_short_number_no_suffix_fallback(db):
    """不足 9 位的号码只做精确匹配，不做后缀兜底（防短串误撞）。"""
    _seed(db)
    assert service.unlock(db, "ginny", "38000") is None


# ---------- 录入侧归一化（与口令同源） ----------

def test_apply_contacts_normalizes_like_unlock(db):
    sp, _, customer = _seed(db)
    service.apply_customer_contacts(customer, "  NEW@Buyer.com ", "+86 155 0000 1111")
    assert customer.email_norm == "new@buyer.com"
    assert customer.whatsapp_norm == "8615500001111"


def test_apply_contacts_rejects_bad_input(db):
    _, _, customer = _seed(db)
    with pytest.raises(ValueError):
        service.apply_customer_contacts(customer, "not-an-email", None)
    with pytest.raises(ValueError):
        service.apply_customer_contacts(customer, None, "123")


def test_apply_contacts_empty_string_clears(db):
    _, _, customer = _seed(db)
    service.apply_customer_contacts(customer, "", None)
    assert customer.email_norm is None
    assert customer.whatsapp_norm == "8613800138000"


# ---------- 询盘 ----------

def test_inquiry_links_matching_customer(db):
    _, _, customer = _seed(db)
    inquiry = service.create_inquiry(db, "ginny", "+86-138-0013-8000", "Need 100pcs quotation")
    assert inquiry is not None
    assert inquiry.customer_id == customer.id
    assert inquiry.status == "new"


def test_inquiry_unknown_contact_unlinked(db):
    _seed(db)
    inquiry = service.create_inquiry(db, "ginny", "stranger@x.com", "hello")
    assert inquiry is not None and inquiry.customer_id is None


def test_inquiry_invalid_slug_is_none(db):
    _seed(db)
    assert service.create_inquiry(db, "ghost", "a@b.com", "hi") is None


def test_inquiry_blank_message_rejected(db):
    _seed(db)
    assert service.create_inquiry(db, "ginny", "a@b.com", "   ") is None


def test_inquiry_triggers_dingtalk_notify(db, monkeypatch):
    """落库后触发群推送，参数带业务员名/联系方式/命中标记。"""
    _, _, customer = _seed(db)
    calls = []
    monkeypatch.setattr(service, "_notify_inquiry", lambda *a: calls.append(a))
    service.create_inquiry(db, "ginny", "maria@buyer.com", "need quotation")
    assert calls == [("Ginny", "maria@buyer.com", "need quotation", True)]


def test_push_inquiry_failure_returns_false_no_raise(monkeypatch):
    """推送链路失败（未配置/接口炸）安静返回 False，绝不炸询盘链路。

    必须 mock 失败——开发机 .env 配有真实 webhook，直调会发真消息进群（实测踩过）。
    """
    import app.dingtalk.webhook as webhook
    from app.card import push_service

    def boom():
        raise RuntimeError("no webhook configured")

    monkeypatch.setattr(webhook, "get_webhook_sender", boom)
    assert push_service.push_inquiry("Ginny", "a@b.com", "hi", False) is False
