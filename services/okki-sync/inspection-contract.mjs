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
  return JSON.stringify(signature(verified.items || [], false)) === JSON.stringify(signature(records, true))
    && verified.items.every(row => verifiedMaterialEqual(row, records.find(current => row.item_id === 'okki:' + String(current.outbound_record_id))));
}

function verifiedMaterialEqual(before, after) {
  const fields = { product_id: 'product_id', product_name: 'product_name', sku: 'sku_code',
    unit: 'product_unit', spec: 'product_model', sku_id: 'sku_id', order_id: 'order_id',
    order_record_id: 'order_record_id', product_cn_name: 'product_cn_name' };
  return Object.entries(fields).every(([key, remote]) => !(key in before)
    || String(before[key] || '') === String(after[remote] || ''))
    && Number(before.qty) === Number(after.outbound_count);
}

export async function invalidateInspection(conn, state, inv, records, materialChanged, wholeChanged, localIds, changes) {
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
  const { schema, inspection, event } = state;
  // Evidence uploaded against an already verified edit belongs to that version,
  // even when the older mirror has not caught up before the next external edit.
  if (state.result.verified) {
    if (inv.update_time < state.result.verified.update_time) throw new Error('Outbound snapshot predates verified inspection evidence');
    const baseline = new Map(state.result.verified.items.map(row => [row.item_id.slice(5), row]));
    const current = new Map(records.map(row => [String(row.outbound_record_id), row]));
    changes.changedRemoteIds = new Set();
    changes.invalidItemIds = new Set(changes.removedItemIds);
    for (const [key, before] of baseline) {
      const after = current.get(key);
      if (!after || !verifiedMaterialEqual(before, after)) {
        changes.invalidItemIds.add('okki:' + key);
        if (localIds.has(key)) changes.invalidItemIds.add(String(localIds.get(key)));
        if (after) changes.changedRemoteIds.add(key);
        else changes.removedItemIds.add('okki:' + key);
      }
    }
    for (const [key] of current) if (!baseline.has(key)) changes.changedRemoteIds.add(key);
    materialChanged = changes.changedRemoteIds.size > 0 || [...baseline.keys()].some(key => !current.has(key));
    wholeChanged = (state.result.verified.remark || '') !== (inv.remark || '') || state.result.verified.serial_id !== inv.serial_id;
  }
  if (!materialChanged && !wholeChanged && !state.result.verified) return;
  const [photos] = await conn.query(`SELECT id,item_id FROM \`${schema}\`.ark_shipping_inspection_photos WHERE inspection_id=? FOR UPDATE`, [inspection.id]);
  const stale = new Set(state.result.stale_media_ids || []);
  const required = new Set(state.result.required_recheck_ids || []);
  for (const key of changes.removedItemIds) required.delete(key);
  for (const photo of photos) {
    if (photo.item_id == null && (materialChanged || wholeChanged) || changes.invalidItemIds.has(String(photo.item_id))) stale.add(photo.id);
  }
  for (const row of records) {
    const key = String(row.outbound_record_id);
    if (String(row.product_name || '').trim().toLowerCase() === 'other items') {
      required.delete('okki:' + key); required.delete(String(localIds.get(key)));
    } else if (changes.changedRemoteIds.has(key)) {
      required.add('okki:' + String(row.outbound_record_id));
    }
  }
  if (materialChanged || wholeChanged) required.add('__whole__');
  const mappings = [];
  for (const photo of photos) {
    const key = String(photo.item_id || '').startsWith('okki:') ? photo.item_id.slice(5) : null;
    if (key && localIds.has(key)) {
      await conn.query(`UPDATE \`${schema}\`.ark_shipping_inspection_photos SET item_id=? WHERE id=? AND inspection_id=?`, [String(localIds.get(key)), photo.id, inspection.id]);
      mappings.push({ photo_id: photo.id, before: photo.item_id, after: String(localIds.get(key)) });
    }
  }
  const result = { ...state.result, stale_media_ids: [...stale], required_recheck_ids: [...required],
    message: materialChanged || wholeChanged ? 'External outbound changed; fresh inspection evidence is required' : state.result.message };
  // A proven external change supersedes this overlay, including same-second OKKI edits.
  // Retain the previous verified snapshot in the new audit instead of covering the new mirror.
  if (materialChanged || wholeChanged) {
    delete result.print_before_recheck;
    delete result.verified;
  } else if (state.result.verified) {
    result.verified = { ...state.result.verified, update_time: inv.update_time };
    if (result.print_before_recheck?.verified_update_time === state.result.verified.update_time) {
      result.print_before_recheck = { ...result.print_before_recheck, verified_update_time: inv.update_time };
    }
  }
  // IDs 0 explicitly identify maintenance, never an authenticated human operator.
  if (materialChanged || wholeChanged) await conn.query(`UPDATE \`${schema}\`.ark_shipping_inspections SET recalled_at=CASE WHEN status='submitted' THEN NOW() ELSE recalled_at END,recalled_by=CASE WHEN status='submitted' THEN 0 ELSE recalled_by END,status='draft',edit_version=edit_version+1,outbound_no=?,updated_at=NOW(),updated_by=0 WHERE id=?`, [inv.serial_id || null, inspection.id]);
  await conn.query(`UPDATE \`${schema}\`.ark_shipping_operation_events SET action='sync_done',result=? WHERE id=?`, [JSON.stringify(result), event.id]);
  await conn.query(`INSERT INTO \`${schema}\`.ark_shipping_operation_events (scope,source,action,login_user_id,operator_user_id,operator_name,login_name,outbound_record_id,inspection_id,edit_version,payload,result,created_at) VALUES ('mirror-sync','mirror_sync','${materialChanged || wholeChanged ? 'mirror_recheck' : 'mirror_link'}',0,0,'OKKI mirror synchronization','No interactive login',?,?,?,?,?,NOW())`, [state.recordId, inspection.id, inspection.edit_version + Number(materialChanged || wholeChanged), JSON.stringify({ outbound_invoice_id: String(inv.outbound_invoice_id), update_time: inv.update_time, material_changed: materialChanged, whole_changed: wholeChanged, mappings, previous_verified: state.result.verified }), JSON.stringify({ stale_media_ids: [...stale], required_recheck_ids: [...required] })]);
}
