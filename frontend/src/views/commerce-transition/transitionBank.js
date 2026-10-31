const positiveId = value => {
  const id = Number(value)
  if (!Number.isSafeInteger(id) || id < 1) throw new Error('请选择有效的原账本身份')
  return id
}

export function bankDomainAccounts(ids, accounts) {
  if (!Array.isArray(ids) || !ids.length) throw new Error('请选择同一真实账户的全部银行账户别名')
  const selected = ids.map(positiveId)
  const known = new Set(accounts.map(account => positiveId(account.id)))
  if (new Set(selected).size !== selected.length || selected.some(id => !known.has(id))) {
    throw new Error('银行账户资料已变化，请刷新后重新核验')
  }
  return selected
}

export function legacyBankReconciliationPayload(form, unmapped, domains) {
  const domainId = positiveId(form.domain_id)
  if (!domains.some(domain => Number(domain.id) === domainId)) throw new Error('账户域已变化，请刷新后重新选择')
  const sourceKind = form.source_kind || 'legacy-money'
  let identity
  if (sourceKind === 'return-paid' || sourceKind === 'return-recovered') {
    const returnId = positiveId(form.sales_return_id)
    const movement = sourceKind === 'return-paid' ? 'paid' : 'recovered'
    if (!unmapped.includes(`legacy-return-${movement}:${returnId}`)) throw new Error('该退货现金记录不在待核对清单中，请刷新并核实实际退款或收回凭据')
    identity = { sales_return_id: returnId, cash_movement: movement }
  } else {
    if (sourceKind !== 'legacy-money') throw new Error('请选择有效的原款来源')
    const match = /^(legacy-receipt|legacy-batch):([1-9]\d*)$/.exec(form.source || '')
    if (!match || !unmapped.includes(form.source)) throw new Error('请选择尚未核对的原旧款或完整批次')
    identity = { [match[1] === 'legacy-receipt' ? 'receipt_id' : 'batch_id']: positiveId(match[2]) }
  }
  const transactionId = String(form.transaction_id || '').trim()
  const reference = String(form.statement_reference || '').trim()
  if (!transactionId || transactionId.length > 128) throw new Error('请填写真实银行流水号（128 字以内）')
  if (!reference || reference.length > 500) throw new Error('请填写可追溯的银行对账依据（500 字以内）')
  return { domain_id: domainId, transaction_id: transactionId,
    ...identity,
    statement_reference: reference }
}
