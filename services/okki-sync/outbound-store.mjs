import { lockInspection, invalidateInspection } from './inspection-contract.mjs';

const FIELDS = ['outbound_record_id', 'outbound_invoice_id', 'sku_id', 'product_id', 'sku_code', 'product_no', 'product_name', 'product_cn_name', 'product_model', 'product_unit', 'outbound_count', 'sale_count', 'sale_price', 'product_amount', 'cost_unit_price_rmb', 'moment_enable_count', 'order_id', 'order_no', 'order_record_id', 'product_type', 'product_disable_flag'];
const MATERIAL = ['product_id', 'sku_id', 'sku_code', 'product_name', 'product_cn_name', 'product_model', 'product_unit', 'order_id', 'order_record_id'];

function identity(value) {
  const key = String(value ?? '');
  if (!/^[1-9][0-9]*$/.test(key) || (typeof value === 'number' && !Number.isSafeInteger(value))) throw new Error('Missing or unsafe OKKI detail identity');
  return key;
}
function index(rows) {
  const map = new Map();
  for (const row of rows) {
    const key = identity(row.outbound_record_id);
    if (map.has(key)) throw new Error('Duplicate OKKI detail identity');
    map.set(key, row);
  }
  return map;
}
function materialEqual(before, after) {
  return MATERIAL.every(key => String(before[key] ?? '') === String(after[key] ?? ''))
    && Number(before.outbound_count) === Number(after.outbound_count);
}
function values(row, invoice, num) {
  return FIELDS.map(key => {
    if (key === 'outbound_invoice_id') return invoice;
    if (['outbound_count','sale_count','sale_price','product_amount','cost_unit_price_rmb','moment_enable_count'].includes(key)) return num(row[key]);
    if (['product_type','product_disable_flag'].includes(key)) return row[key] ?? null;
    return row[key] || null;
  });
}

export async function saveOutboundSnapshot(pool, inv, detail, { parseTs, num, inspectionSchema = 'commission_db' }) {
  identity(inv.outbound_invoice_id);
  if (!detail || !Array.isArray(detail.record_list)) throw new Error('Complete outbound detail is required before advancing the mirror');
  if (String(detail.outbound_invoice_id) !== String(inv.outbound_invoice_id)) throw new Error('Outbound detail belongs to another invoice');
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(inv.update_time || '') || detail.update_time !== inv.update_time) throw new Error('Outbound list and detail versions differ; retry the complete snapshot');
  for (const row of detail.record_list) if (row.outbound_count == null || !Number.isFinite(Number(row.outbound_count)) || Number(row.outbound_count) < 0) throw new Error('Invalid outbound quantity');
  const wanted = index(detail.record_list);
  const conn = await pool.getConnection();
  try {
    await conn.query("SET time_zone = '+08:00'");
    await conn.beginTransaction();
    const inspection = await lockInspection(conn, inv.outbound_invoice_id, inspectionSchema);
    const [heads] = await conn.query("SELECT id,DATE_FORMAT(update_time,'%Y-%m-%d %H:%i:%s') AS update_time,serial_id,remark FROM okki_outbound_records WHERE outbound_invoice_id=? FOR UPDATE", [inv.outbound_invoice_id]);
    const previous = heads[0];
    if (previous?.update_time && (!inv.update_time || inv.update_time < previous.update_time)) throw new Error('Older outbound snapshot cannot overwrite the mirror');
    const warehouseInfo = inv.invoice_warehouse_info || {};
    const companyInfo   = inv.company_info || {};
    const createUser    = inv.create_user_info || {};

    await conn.query(
      `INSERT INTO okki_outbound_records
        (outbound_invoice_id, serial_id, status, warehouse_invoice_time,
         warehouse_id, warehouse_name,
         company_id, company_name,
         remark, discount, discount_rate,
         product_total_amount, product_total_amount_rmb, product_total_amount_usd,
         currency, exchange_rate, exchange_rate_usd,
         product_total_count, source_type,
         create_user_id, create_user_name,
         create_time, update_time)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
       ON DUPLICATE KEY UPDATE
         serial_id                 = VALUES(serial_id),
         status                    = VALUES(status),
         warehouse_invoice_time    = VALUES(warehouse_invoice_time),
         warehouse_id              = VALUES(warehouse_id),
         warehouse_name            = VALUES(warehouse_name),
         company_id                = VALUES(company_id),
         company_name              = VALUES(company_name),
         remark                    = VALUES(remark),
         discount                  = VALUES(discount),
         discount_rate             = VALUES(discount_rate),
         product_total_amount      = VALUES(product_total_amount),
         product_total_amount_rmb  = VALUES(product_total_amount_rmb),
         product_total_amount_usd  = VALUES(product_total_amount_usd),
         currency                  = VALUES(currency),
         exchange_rate             = VALUES(exchange_rate),
         exchange_rate_usd         = VALUES(exchange_rate_usd),
         product_total_count       = VALUES(product_total_count),
         source_type               = VALUES(source_type),
         create_user_id            = VALUES(create_user_id),
         create_user_name          = VALUES(create_user_name),
         update_time               = VALUES(update_time),
         synced_at                 = CURRENT_TIMESTAMP`,
      [
        inv.outbound_invoice_id,
        inv.serial_id || null,
        inv.status ?? null,
        parseTs(inv.warehouse_invoice_time),
        warehouseInfo.id   || null,
        warehouseInfo.name || null,
        companyInfo.id   || null,
        companyInfo.name || null,
        inv.remark || null,
        num(inv.discount),
        num(inv.discount_rate),
        num(inv.product_total_amount),
        num(inv.product_total_amount_rmb),
        num(inv.product_total_amount_usd),
        inv.currency || null,
        num(inv.exchange_rate),
        num(inv.exchange_rate_usd),
        num(inv.product_total_count),
        inv.source_type ?? null,
        createUser.user_id   || null,
        createUser.nickname  || null,
        parseTs(inv.create_time),
        parseTs(inv.update_time),
      ]
    );
    // The unique header locks each invoice before we read/update its detail rows.
    const [existing] = await conn.query('SELECT * FROM okki_outbound_record_items WHERE outbound_invoice_id=? FOR UPDATE', [inv.outbound_invoice_id]);
    const old = index(existing);
    const localIds = new Map();
    let materialChanged = old.size !== wanted.size;
    for (const [key, row] of wanted) {
      const before = old.get(key);
      const params = values(row, inv.outbound_invoice_id, num);
      if (before) {
        localIds.set(key, before.id);
        materialChanged ||= !materialEqual(before, row);
        await conn.query(`UPDATE okki_outbound_record_items SET ${FIELDS.map(field => '`' + field + '`=?').join(',')},synced_at=CURRENT_TIMESTAMP WHERE id=? AND outbound_invoice_id=?`, [...params, before.id, inv.outbound_invoice_id]);
      } else {
        materialChanged = true;
        const [inserted] = await conn.query(`INSERT INTO okki_outbound_record_items (${FIELDS.map(field => '`' + field + '`').join(',')}) VALUES (${FIELDS.map(() => '?').join(',')})`, params);
        localIds.set(key, inserted.insertId);
      }
    }
    const removed = existing.filter(row => !wanted.has(identity(row.outbound_record_id))).map(row => row.id);
    if (removed.length) {
      materialChanged = true;
      await conn.query('DELETE FROM okki_outbound_record_items WHERE outbound_invoice_id=? AND id IN (?)', [inv.outbound_invoice_id, removed]);
    }
    const wholeChanged = previous && ((previous.remark || '') !== (inv.remark || '') || previous.serial_id !== inv.serial_id);
    await invalidateInspection(conn, inspection, inv, detail.record_list, materialChanged, Boolean(wholeChanged), localIds);
    await conn.commit();
  } catch (error) {
    try { await conn.rollback(); } catch (rollbackError) { console.warn('Outbound rollback failed:', rollbackError.code || rollbackError.name); conn.destroy?.(); }
    throw error;
  } finally {
    conn.release();
  }
}
