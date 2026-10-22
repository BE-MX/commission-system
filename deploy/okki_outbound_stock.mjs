/** Same successful-generation stock claims as invoice/stock_reservations.py. */
import {randomUUID} from 'node:crypto';
export function reservationAmounts(rows) {
  if (!Array.isArray(rows) || !rows.length) throw Error('Incomplete stock reservation snapshot');
  const amounts = new Map();
  for (const row of rows) {
    if (row.remove) continue;
    if (![row.product_id,row.sku_id].every(value => /^[1-9]\d*$/.test(String(value))) ||
        !Number.isSafeInteger(Number(row.count)) || Number(row.count) <= 0)
      throw Error('Invalid stock reservation quantity or mapping');
    const key = `${row.product_id}:${row.sku_id}`;
    const total = (amounts.get(key) || 0) + Number(row.count);
    if (!Number.isSafeInteger(total)) throw Error('Invalid stock reservation total');
    amounts.set(key,total);
  }
  if (!amounts.size) throw Error('Empty stock reservation snapshot');
  return amounts;
}

export async function protectedStock(conn, orderId) {
  const [[current]] = await conn.query('SELECT id FROM ark_okki_outbound_tasks WHERE order_id=?',[orderId]);
  const [tasks] = await conn.query(`SELECT t.id,t.invoice_id,t.order_id,t.status,i.sync_status,
      l.id AS log_id,l.request_digest,l.response_body,(l.created_at<=t.processed_at) AS generation_completed
    FROM ark_okki_outbound_tasks t JOIN ark_invoices i ON i.id=t.invoice_id AND i.xiaoman_order_id=t.order_id
    LEFT JOIN ark_invoice_sync_logs l ON l.id=(SELECT MAX(s.id) FROM ark_invoice_sync_logs s
      WHERE s.invoice_id=i.id AND s.success=1 AND s.action IN ('create','update'))
    WHERE (t.status IN ('pending','waiting_stock','running','failed','uncertain','done')
      OR (t.status='skipped' AND (t.reason LIKE 'existing:%' OR t.reason='Existing outbound requires manual handling')))
      AND i.order_type<>'presale' AND (i.status<>'cancelled' OR t.status IN ('running','uncertain'))
      AND t.order_id<>? AND (? IS NULL OR t.id<?) ORDER BY t.id`,[orderId,current?.id ?? null,current?.id ?? null]);
  const result = new Map();
  for (const task of tasks) {
    const [[snapshot]] = await conn.query(`SELECT payload,request_id FROM ark_shipping_operation_events
      WHERE scope='outbound-stock-reservation' AND outbound_record_id=? ORDER BY id DESC LIMIT 1`,['create:'+task.invoice_id]);
    let payload = snapshot && (task.sync_status !== 'synced' || snapshot.request_id === `${task.id}:${task.log_id || 0}`)
      ? snapshot.payload : null;
    if (typeof payload === 'string') payload = JSON.parse(payload);
    if (payload && (String(payload.order_id) !== String(task.order_id) || payload.warehouse_id !== '8193514242746'))
      throw Error('Reservation order or warehouse differs');
    if (!payload && task.request_digest) {
      const candidate = JSON.parse(task.request_digest);
      if (Array.isArray(candidate?.product_list)) {
        const response = JSON.parse(task.response_body || '{}');
        if (String(response.order_id) !== String(task.order_id)) throw Error('Reservation order identity differs');
        payload = candidate;
      }
    }
    if (!payload) {
      if (task.sync_status !== 'synced') throw Error('Unsynced historical reservation needs review');
      const [items] = await conn.query(`SELECT COALESCE(i.product_id,c.okki_product_id) AS product_id,
        COALESCE(i.sku_id,c.okki_sku_id) AS sku_id,i.quantity AS count FROM ark_invoice_items i
        LEFT JOIN ark_custom_products c ON c.id=i.custom_product_id
        WHERE i.invoice_id=? AND i.presale_archived=0`,[task.invoice_id]);
      payload = {product_list:items};
    }
    let transferred = new Map();
    if (task.status === 'skipped' || task.status === 'done') {
      const [[changing]] = await conn.query(`SELECT id FROM ark_shipping_operation_events
        WHERE scope='outbound-invoice-sync' AND action IN ('sync_pending','sync_sending','sync_uncertain')
        AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.invoice_id'))=? LIMIT 1`,[String(task.invoice_id)]);
      const [[native]] = await conn.query(`SELECT payload FROM ark_shipping_operation_events
        WHERE scope='outbound-stock-native' AND outbound_record_id=? ORDER BY id DESC LIMIT 1`,['create:'+task.invoice_id]);
      const data = typeof native?.payload === 'string' ? JSON.parse(native.payload) : native?.payload;
      if (!changing && data) {
        if (String(data.order_id)!==String(task.order_id) || data.warehouse_id!=='8193514242746') throw Error('Native reservation identity differs');
        transferred=reservationAmounts(data.product_list);
      } else if (!changing && !data && task.status === 'done' && task.generation_completed) {
        continue; // The strict original create covered this unchanged generation.
      }
    }
    for (const [key,quantity] of reservationAmounts(payload.product_list)) {
      const total = (result.get(key) || 0)+Math.max(0,quantity-(transferred.get(key) || 0));
      if (!Number.isSafeInteger(total)) throw Error('Invalid protected stock total');
      result.set(key,total);
    }
  }
  return result;
}

export async function recordNativeAssociation(conn,invoiceId,orderId,detail,at) {
  if (String(detail?.invoice_warehouse_info?.id)!=='8193514242746' || !Array.isArray(detail.record_list) ||
      detail.record_list.some(row=>String(row.order_id)!==String(orderId))) throw Error('Existing native outbound warehouse/order is unconfirmed');
  const amounts=reservationAmounts(detail.record_list.map(row=>({product_id:row.product_id,sku_id:row.sku_id,count:row.outbound_count})));
  const product_list=[...amounts].map(([key,count])=>{const [product_id,sku_id]=key.split(':');return {product_id,sku_id,count};});
  await conn.query(`INSERT INTO ark_shipping_operation_events
    (scope,request_id,source,action,login_user_id,operator_user_id,operator_name,login_name,outbound_record_id,payload,result,created_at)
    VALUES ('outbound-stock-native',?,'invoice','stock_observed',0,0,'系统库存核验','系统库存核验',?,?,?,?)`,
    [randomUUID(),'create:'+invoiceId,JSON.stringify({order_id:String(orderId),warehouse_id:'8193514242746',product_list}),'{}',at]);
}

export async function assertNoOriginalAttempt(conn, invoiceId) {
  const [events] = await conn.query(`SELECT id,scope,request_id,payload FROM ark_shipping_operation_events
    WHERE outbound_record_id=? AND scope IN ('outbound-create-attempt','outbound-create-fact','outbound-create-finish')
    ORDER BY id`,['create:'+invoiceId]);
  const attempts = new Map();
  for (const event of events) {
    const payload = typeof event.payload === 'string' ? JSON.parse(event.payload) : event.payload;
    const nonce = event.scope === 'outbound-create-attempt' ? event.request_id : payload?.nonce;
    if (!nonce) throw Error('Original outbound evidence is incomplete');
    if (event.scope === 'outbound-create-attempt') attempts.set(nonce,false);
    else if (attempts.has(nonce)) attempts.set(nonce,event.scope === 'outbound-create-finish');
  }
  if ([...attempts.values()].some(done => !done))
    throw Object.assign(Error('Original Python outbound requires verification; no legacy submission'),{uncertain:true});
}
