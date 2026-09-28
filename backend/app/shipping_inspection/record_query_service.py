"""Inspection salesperson lookup by actual outbound-item order links, never API creator."""
from sqlalchemy import bindparam, text
from app.shipping_inspection import outbound_service as outbound


def _source(db):
    link, rm, im = outbound._link(db)
    if not link or 'order_id' not in outbound._table_columns(db, outbound.ITEMS_TABLE):
        return None
    rk, ik = (rm['invoice_id'], im['invoice_id']) if link == 'invoice' else (rm['id'], im['record_id'])
    schema = outbound._schema()
    return rm, f"""FROM `{schema}`.`{outbound.RECORDS_TABLE}` r
        JOIN `{schema}`.`{outbound.ITEMS_TABLE}` i ON i.`{ik}`=r.`{rk}`
        JOIN `{schema}`.okki_orders o ON o.order_id=i.order_id
        LEFT JOIN `{schema}`.user_basic u ON u.user_id=o.user_id
        LEFT JOIN ark_user_external_bindings b ON b.provider='okki' AND b.external_account_id=o.user_id
          AND b.binding_status='active' AND b.deleted_at IS NULL
        LEFT JOIN ark_users a ON a.id=b.ark_user_id AND a.deleted_at IS NULL"""


def salesperson_record_ids(db, name):
    source = _source(db)
    if source is None:
        raise outbound.OutboundTableError('出库明细缺少订单关联字段，无法按业务员筛选')
    rm, joins = source
    escaped = name.strip().replace('!', '!!').replace('%', '!%').replace('_', '!_')
    return text(f"""SELECT DISTINCT r.`{rm['id']}` {joins}
        WHERE u.full_name LIKE :salesperson ESCAPE '!' OR u.nickname LIKE :salesperson ESCAPE '!'
           OR a.real_name LIKE :salesperson ESCAPE '!'""").bindparams(salesperson=f"%{escaped}%")


def order_record_ids(db, order_id):
    link, rm, im = outbound._link(db)
    if not link or 'order_id' not in outbound._table_columns(db, outbound.ITEMS_TABLE):
        raise outbound.OutboundTableError('出库明细缺少订单关联字段，无法按订单 ID 筛选')
    rk, ik = (rm['invoice_id'], im['invoice_id']) if link == 'invoice' else (rm['id'], im['record_id'])
    schema = outbound._schema()
    return text(f"""SELECT DISTINCT r.`{rm['id']}` FROM `{schema}`.`{outbound.RECORDS_TABLE}` r
        JOIN `{schema}`.`{outbound.ITEMS_TABLE}` i ON i.`{ik}`=r.`{rk}`
        WHERE i.order_id=:order_id""").bindparams(order_id=order_id)


def salesperson_names(db, record_ids):
    if not record_ids:
        return {}
    source = _source(db)
    if source is None:
        return {}  # Unlinked records show 'unmatched', never the creator or another customer order.
    rm, joins = source
    rows = db.execute(text(f"""SELECT DISTINCT r.`{rm['id']}` AS rid,
        u.full_name, u.nickname, a.real_name {joins} WHERE r.`{rm['id']}` IN :record_ids""")
        .bindparams(bindparam('record_ids', expanding=True)), {'record_ids': record_ids}).mappings().all()
    names = {}
    for row in rows:
        display = str(row['full_name'] or row['nickname'] or '').strip()
        local = str(row['real_name'] or '').strip()
        label = f'{display}（{local}）' if display and local and local != display else display or local
        if label:
            names.setdefault(str(row['rid']), set()).add(label)
    return {key: '、'.join(sorted(values)) for key, values in names.items()}
