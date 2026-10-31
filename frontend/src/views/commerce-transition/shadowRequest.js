export function shadowReplayPayload(form) {
  const ids = key => String(form[key] || '').split(/[,，\s]+/).filter(Boolean).map(value => {
    if (!/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error('源对象 ID 必须为有效整数')
    return Number(value)
  })
  const invoice_ids = ids('invoice_ids'), payment_ids = ids('payment_ids'), local_customer_ids = ids('local_customer_ids')
  const through = Number(form.through_observation_id)
  if (!String(form.dataset_id || '').trim() || ![...invoice_ids, ...payment_ids, ...local_customer_ids].length || !Number.isSafeInteger(through) || through <= 0) throw new Error('请填写数据集、有效源对象 ID 与截至观察 ID')
  return { dataset_id: form.dataset_id.trim(), invoice_ids, payment_ids, local_customer_ids, through_observation_id: through }
}
