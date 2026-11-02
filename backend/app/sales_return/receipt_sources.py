"""Exact receipt tombstones and request-scoped evidence for missing mirror fees.

The mirror's service fee comes from receipt.info.order_info, not bank_charge.
Remote reads happen before the return transaction; no mirror data is repaired here.
"""
from dataclasses import dataclass
import hashlib
import json
import logging

from fastapi import HTTPException
from sqlalchemy import select

from app.invoice.okki_client import OkkiApiError
from app.receipt import deletion_service, remote
from app.receipt.models import Receipt
from app.sales_return import access
from app.sales_return.models import SalesReturn

logger = logging.getLogger(__name__)

MIRROR_FIELDS = ('cash_collection_id', 'order_id', 'company_id', 'currency', 'collect_status',
                 'amount', 'amount_usd', 'real_amount', 'real_amount_usd', 'bank_charge',
                 'bank_charge_usd', 'service_fee_amount_usd', 'collection_date')
LOCAL_FIELDS = ('id', 'invoice_id', 'xiaoman_receipt_id', 'xiaoman_order_id', 'customer_id',
                'currency', 'status', 'sync_status', 'version', 'amount', 'bank_charge')


@dataclass(frozen=True)
class Evidence:
    binding: str
    details: dict


def _conflict(message):
    raise HTTPException(409, message)


def read(db, order):
    """Read the complete mirror set and exact local deletion bindings together."""
    from app.sales_return import sources
    sources._require(db, 'okki_receipts', set(MIRROR_FIELDS))
    rows = sources._rows(db, 'okki_receipts', 'order_id=:oid', {'oid': order['order_id']})
    ids = [str(row['cash_collection_id']) for row in rows]
    local = db.scalars(select(Receipt).where(Receipt.xiaoman_receipt_id.in_(ids))
        .execution_options(populate_existing=True)).all() if ids else []
    by_id = {str(row.xiaoman_receipt_id): row for row in local}
    if len(by_id) != len(local):
        _conflict('原回款本地关联重复，请核对原单')
    included, seen = [], set()
    for row in rows:
        identity = sources._identity(row.get('cash_collection_id'), '原回款 ID')
        if identity in seen or str(row.get('company_id')) != str(order['company_id']):
            _conflict('原回款重复或客户关联不一致')
        seen.add(identity)
        receipt = by_id.get(identity)
        if receipt:
            if (str(receipt.xiaoman_order_id) != str(order['order_id'])
                    or str(receipt.customer_id) != str(order['company_id'])
                    or receipt.currency != row.get('currency')):
                _conflict('原回款本地记录与镜像的订单、客户或币种不一致，请先核对')
            if receipt.status == 'remote_deleted' and receipt.sync_status == 'synced':
                continue
            if (receipt.status != 'active' or receipt.sync_status != 'synced'
                    or deletion_service.pending(db, receipt)):
                _conflict('原回款正在变更、删除或结果待核对，请先完成原回款核验')
        included.append(row)
    payload = {
        'order': {key: order.get(key) for key in ('order_id', 'company_id', 'user_id')},
        'mirror': [{key: row.get(key) for key in MIRROR_FIELDS}
                   for row in sorted(rows, key=lambda row: str(row['cash_collection_id']))],
        'local': [{key: getattr(row, key) for key in LOCAL_FIELDS} for row in sorted(local, key=lambda row: row.id)],
    }
    binding = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return included, binding


def prepare(db, user, *, order_id=None, return_id=None, request_key=None):
    """Authorized read capture -> end snapshot -> remote GET -> end token session.

    Callers reauthorize and recompute the complete binding in their final transaction.
    Existing create/activate requests keep their normal idempotent result path.
    """
    from app.sales_return import sources
    if db.new or db.dirty or db.deleted:
        _conflict('原回款取证必须在业务写入前完成，请重新读取')
    try:
        if request_key:
            existing = db.scalar(select(SalesReturn).where(SalesReturn.request_key == request_key))
            if existing:
                access.ensure(db, existing, user)
                return None
        if return_id is not None:
            existing = access.ensure(db, db.get(SalesReturn, return_id), user)
            if existing.status != 'draft' or existing.activate_key:
                return None
            order_id = existing.order_id
        order = sources.order_row(db, order_id, user)
        rows, binding = read(db, order)
        missing = [row for row in rows if str(row.get('collect_status')) == '1'
                   and row.get('service_fee_amount_usd') is None]
    finally:
        db.rollback()  # A later transaction must see concurrent mirror/receipt changes.
    if not missing:
        return None
    details = {}
    try:
        for row in missing:
            identity = str(row['cash_collection_id'])
            data = remote.receipt_info(db, identity)
            details[identity] = {key: data.get(key) for key in MIRROR_FIELDS if key != 'service_fee_amount_usd'}
            details[identity]['enable_flag'] = data.get('enable_flag')
            nested = data.get('order_info')
            details[identity]['order_info'] = ({key: nested.get(key) for key in
                ('order_id', 'currency', 'service_fee_amount_usd')} if isinstance(nested, dict) else None)
        db.commit()  # Only the existing OKKI token cache may have been refreshed.
    except (OkkiApiError, OSError) as error:
        logger.warning('Sales return receipt evidence unavailable (%s)', type(error).__name__)
        print('[sales-return] Receipt evidence unavailable (' + type(error).__name__ + ')', flush=True)
        raise HTTPException(503, '原回款取证暂不可用，尚未保存或生效退货，请稍后重试') from None
    finally:
        db.rollback()
        db.expire_all()
    return Evidence(binding=binding, details=details)


def fee(row, evidence):
    """Never infer a transaction service fee from the bank charge or a null."""
    from app.sales_return import sources
    if row.get('service_fee_amount_usd') is not None:
        return sources._decimal(row['service_fee_amount_usd'], '原回款美元手续费')
    detail = evidence.details.get(str(row['cash_collection_id'])) if evidence else None
    if not isinstance(detail, dict):
        _conflict('原回款美元手续费缺少已核验依据，请重新读取原单')
    for key in ('cash_collection_id', 'order_id', 'company_id', 'currency', 'collect_status'):
        if str(detail.get(key)) != str(row.get(key)):
            _conflict('原回款远端身份或财务状态与镜像不一致，请先核对同步')
    if str(detail.get('enable_flag')) != '1':
        _conflict('原回款远端已停用或删除状态未核实，请先核对原回款')
    if str(detail.get('collection_date'))[:10] != str(row.get('collection_date'))[:10]:
        _conflict('原回款远端日期与镜像不一致，请先核对同步')
    for key in ('amount', 'amount_usd', 'real_amount', 'real_amount_usd', 'bank_charge', 'bank_charge_usd'):
        if sources._decimal(detail.get(key), '原回款远端金额') != sources._decimal(row.get(key), '原回款镜像金额'):
            _conflict('原回款远端金额或银行手续费与镜像不一致，请先核对同步')
    nested = detail.get('order_info')
    if (not isinstance(nested, dict) or str(nested.get('order_id')) != str(row['order_id'])
            or nested.get('currency') != row['currency']):
        _conflict('原回款交易服务费的原订单关联或币种缺失，请核对原单')
    return sources._decimal(nested.get('service_fee_amount_usd'), '原回款美元手续费')


def goods_payments(db, invoice, goods, rows, payments):
    """Separate a single fully paid USD stock PI's proven non-goods components.

    Split/partial payments need allocation evidence; never cap unknown cash to G.
    The original cash and commission basis remain visible in the frozen source.
    """
    from app.sales_return import sources
    if invoice is None or invoice.order_type != 'stock' or not payments:
        return payments
    shipping = sources._decimal(invoice.shipping_fee, '原订单运费')
    surcharge = sources._decimal(invoice.surcharge_amount, '原订单附加费')
    if shipping + surcharge == 0:
        return payments
    if invoice.currency != 'USD':
        _conflict('含运费或附加费的非美元原单尚缺商品本金分摊依据，请先核对')
    if (sources._decimal(invoice.product_amount, '原订单商品金额') != goods
            or sources._decimal(invoice.total_amount, '原订单总额') != goods + shipping + surcharge):
        _conflict('原订单商品、运费、附加费与总额不一致，不能分离可退商品本金')
    local = db.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id, Receipt.status == 'active')
        .execution_options(populate_existing=True)).all()
    if len(payments) != 1 or len(local) != 1:
        _conflict('含费用原单存在分笔或待处理回款，商品本金尚未精确分摊，请先核对')
    receipt, payment = local[0], payments[0]
    amount = sources._decimal(receipt.amount, '本地原回款金额')
    charge = sources._decimal(receipt.bank_charge, '本地原回款附加费')
    mirror = next(row for row in rows if str(row['cash_collection_id']) == payment['payment_id'])
    if (receipt.sync_status != 'synced' or str(receipt.xiaoman_receipt_id) != payment['payment_id']
            or str(receipt.xiaoman_order_id) != str(invoice.xiaoman_order_id)
            or str(receipt.customer_id) != str(invoice.customer_id) or receipt.currency != invoice.currency
            or amount != invoice.total_amount or charge > surcharge
            or amount - charge != sources._decimal(mirror['amount'], '原回款镜像金额')):
        _conflict('原回款未按原订单全额精确核验，不能推算费用与商品本金')
    cash = sources._decimal(payment['principal'], '原回款现金本金')
    non_goods = shipping + surcharge - charge
    goods_cash = cash - non_goods
    if goods_cash != goods:
        _conflict('扣除运费和附加费后的商品本金与原单不一致，请先核对其他手续费或回款差额')
    return [{**payment, 'cash_principal': payment['principal'], 'cash_principal_usd': payment['principal_usd'],
             'non_goods_amount': sources._money(non_goods), 'non_goods_amount_usd': sources._money(non_goods),
             'principal': sources._money(goods_cash), 'principal_usd': sources._money(goods_cash)}]
