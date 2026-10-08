// Preserve the existing Python event -> inspection lock order across both databases.
export async function lockInspection(conn, invoiceId, schema) {
  if (!/^[A-Za-z0-9_]+$/.test(schema)) throw new Error('Invalid inspection schema');
  const [headers] = await conn.query('SELECT id FROM okki_outbound_records WHERE outbound_invoice_id=?', [invoiceId]);
  if (!headers.length) return null;
  const recordId = String(headers[0].id);
  const [events] = await conn.query(`SELECT id,action,result FROM \`${schema}\`.ark_shipping_operation_events WHERE scope='outbound-invoice-sync' AND request_id=? FOR UPDATE`, [recordId]);
  const event = events[0];
  if (event && ['sync_pending', 'sync_sending', 'sync_uncertain', 'recheck_required'].includes(event.action)) {
    throw new Error('Outbound inspection reconciliation is active; defer mirror sync');
  }
  const [inspections] = await conn.query(`SELECT id,status,edit_version FROM \`${schema}\`.ark_shipping_inspections WHERE outbound_record_id=? FOR UPDATE`, [recordId]);
  if (!inspections.length) return null;
  if (!event) throw new Error('Inspection synchronization audit is missing; reconcile before mirror sync');
  const result = typeof event.result === 'string' ? JSON.parse(event.result) : (event.result || {});
  return { schema, recordId, event, inspection: inspections[0], result };
}

function snapshotMatches(result, inv, records) {
  const verified = result.verified;
  if (!verified || verified.update_time !== inv.update_time || verified.serial_id !== inv.serial_id || (verified.remark || '') !== (inv.remark || '')) return false;
  const signature = (rows, remote) => rows.map(row => JSON.stringify([
    remote ? 'okki:' + String(row.outbound_record_id) : row.item_id,
    String(row.product_id || ''), row.product_name || '', row.sku ?? row.sku_code ?? '',
    row.unit ?? row.product_unit ?? '', row.spec ?? row.product_model ?? '',
    Number(row.qty ?? row.outbound_count),
  ])).sort();
  return JSON.stringify(signature(verified.items || [], false)) === JSON.stringify(signature(records, true));
}

export async function invalidateInspection(conn, state, inv, records, materialChanged, wholeChanged, localIds) {
  if (!state) return;
  // A manual edit already recorded the verified snapshot and its recheck contract.
  // Catching that mirror up must not recall again or clear its audit/grant.
  if (snapshotMatches(state.result, inv, records)) {
    const [photos] = await conn.query(`SELECT id,item_id FROM \`${state.schema}\`.ark_shipping_inspection_photos WHERE inspection_id=? FOR UPDATE`, [state.inspection.id]);
    const mappings = [];
    const historical = [];
    for (const photo of photos) {
      if (!String(photo.item_id || '').startsWith('okki:')) continue;
      const remoteId = photo.item_id.slice(5);
      const verified = state.result.verified.items.find(item => item.item_id === photo.item_id);
      if (!verified || !localIds.has(remoteId)) {
        if ((state.result.stale_media_ids || []).includes(photo.id)) { historical.push(photo.id); continue; }
        throw new Error('Verified photo identity cannot be reconciled');
      }
      const current = records.find(row => String(row.outbound_record_id) === remoteId);
      if (String(verified.product_id) !== String(current.product_id) || Number(verified.qty) !== Number(current.outbound_count)
          || (verified.sku || '') !== (current.sku_code || '') || (verified.spec || '') !== (current.product_model || '')
          || (verified.unit || '') !== (current.product_unit || '') || (verified.product_name || '') !== (current.product_name || '')) throw new Error('Verified photo product identity changed');
      await conn.query(`UPDATE \`${state.schema}\`.ark_shipping_inspection_photos SET item_id=? WHERE id=? AND inspection_id=?`, [String(localIds.get(remoteId)), photo.id, state.inspection.id]);
      mappings.push({ photo_id: photo.id, before: photo.item_id, after: String(localIds.get(remoteId)) });
    }
    // Keep verified remote IDs intact: Python retires the overlay by matching
    // those IDs against raw mirror rows, independently of product size/color.
    if (mappings.length) await conn.query(`INSERT INTO \`${state.schema}\`.ark_shipping_operation_events (scope,source,action,login_user_id,operator_user_id,operator_name,login_name,outbound_record_id,inspection_id,edit_version,payload,result,created_at) VALUES ('mirror-sync','mirror_sync','mirror_link',0,0,'OKKI mirror synchronization','No interactive login',?,?,?,?,?,NOW())`, [state.recordId, state.inspection.id, state.inspection.edit_version, JSON.stringify({ update_time: inv.update_time, mappings }), JSON.stringify({ restored_photos: mappings.length, preserved_stale_media_ids: historical })]);
    return;
  }
  if (!materialChanged && !wholeChanged) return;
  const { schema, inspection, event } = state;
  const [photos] = await conn.query(`SELECT id,item_id FROM \`${schema}\`.ark_shipping_inspection_photos WHERE inspection_id=? FOR UPDATE`, [inspection.id]);
  const stale = new Set(state.result.stale_media_ids || []);
  const required = new Set(state.result.required_recheck_ids || []);
  for (const photo of photos) if (materialChanged || photo.item_id == null) stale.add(photo.id);
  if (materialChanged) required.add('__all_items__');
  if (wholeChanged) required.add('__whole__');
  const result = { ...state.result, stale_media_ids: [...stale], required_recheck_ids: [...required], message: 'External outbound changed; fresh inspection evidence is required' };
  delete result.print_before_recheck;
  // A proven external change supersedes this overlay, including same-second OKKI edits.
  // Retain the previous verified snapshot in the new audit instead of covering the new mirror.
  delete result.verified;
  // IDs 0 explicitly identify maintenance, never an authenticated human operator.
  await conn.query(`UPDATE \`${schema}\`.ark_shipping_inspections SET recalled_at=CASE WHEN status='submitted' THEN NOW() ELSE recalled_at END,recalled_by=CASE WHEN status='submitted' THEN 0 ELSE recalled_by END,status='draft',edit_version=edit_version+1,outbound_no=?,updated_at=NOW(),updated_by=0 WHERE id=?`, [inv.serial_id || null, inspection.id]);
  await conn.query(`UPDATE \`${schema}\`.ark_shipping_operation_events SET action='sync_done',result=? WHERE id=?`, [JSON.stringify(result), event.id]);
  await conn.query(`INSERT INTO \`${schema}\`.ark_shipping_operation_events (scope,source,action,login_user_id,operator_user_id,operator_name,login_name,outbound_record_id,inspection_id,edit_version,payload,result,created_at) VALUES ('mirror-sync','mirror_sync','mirror_recheck',0,0,'OKKI mirror synchronization','No interactive login',?,?,?,?,?,NOW())`, [state.recordId, inspection.id, inspection.edit_version + 1, JSON.stringify({ outbound_invoice_id: String(inv.outbound_invoice_id), update_time: inv.update_time, material_changed: materialChanged, whole_changed: wholeChanged, previous_verified: state.result.verified }), JSON.stringify({ stale_media_ids: [...stale], required_recheck_ids: [...required] })]);
}
