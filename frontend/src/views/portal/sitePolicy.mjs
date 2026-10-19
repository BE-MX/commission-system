export function sitePolicyPayload(form) {
  const name = form.name.trim(), reason = form.reason.trim()
  if (!name || name.length > 100 || !reason || reason.length > 500) throw new Error('请填写站点名称和 1–500 字的操作原因。')
  if (!['enabled', 'disabled'].includes(form.status)) throw new Error('请选择站点状态。')
  const minutes = form.quote_valid_minutes
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 30) throw new Error('报价有效期应为 1–30 分钟的整数。')
  const parts = form.proposal_hours.split(',').map(x => x.trim())
  if (!parts.length || parts.length > 8 || parts.some(x => !/^[1-9][0-9]*$/.test(x) || Number(x) > 168) || new Set(parts.map(Number)).size !== parts.length) throw new Error('提案有效期请输入 1–168 小时的整数，用英文逗号分隔，最多 8 项且不重复。')
  if (form.payment_terms.length > 20) throw new Error('付款条件最多 20 项。')
  const terms = form.payment_terms.map(term => {
    const code = term.code.trim(), display_text = term.display_text.trim(), deposit_percent = term.deposit_percent.trim()
    const method_label = (term.method_label || '').trim(), surcharge_percent = (term.surcharge_percent || '0.00').trim()
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(code)) throw new Error('付款条件代码应以小写字母开头，仅含小写字母、数字及下划线。')
    if (!display_text || display_text.length > 256 || /[<>\p{C}]/u.test(display_text)) throw new Error('客户付款说明须为 1–256 字的纯文本。')
    if (!/^(0|[1-9][0-9]?|100)\.[0-9]{2}$/.test(deposit_percent) || Number(deposit_percent) > 100) throw new Error('定金比例请输入 0.00–100.00，保留两位小数。')
    if (method_label.length > 40 || /[<>\p{C}]/u.test(method_label)) throw new Error('付款方式名称须为 40 字以内的纯文本。')
    if (!/^(0|[1-9][0-9]?)\.[0-9]{2}$/.test(surcharge_percent)) throw new Error('付款手续费比例请输入 0.00–99.99，保留两位小数。')
    return { code, display_text, deposit_percent, method_label, surcharge_percent }
  })
  if (new Set(terms.map(x => x.code)).size !== terms.length) throw new Error('付款条件代码不能重复。')
  const defaultCode = form.default_payment_term_code || null
  if (terms.length ? !terms.some(x => x.code === defaultCode) : defaultCode !== null) throw new Error('请选择已配置的默认付款条件。')
  if (form.status === 'enabled' && !terms.length) throw new Error('启用前必须配置并确认付款条件。')
  const contacts = (form.sales_contacts || []).map(row => ({ user_id: String(row.user_id || ''), display_name: row.display_name.trim(), approved: row.approved === true, email: row.email?.trim() || null, whatsapp: row.whatsapp?.trim() || null }))
  if (contacts.length > 200 || new Set(contacts.map(row => row.user_id)).size !== contacts.length) throw new Error('员工对外名片不能重复，最多 200 项。')
  if (contacts.some(row => !/^[1-9][0-9]{0,19}$/.test(row.user_id) || !row.display_name || row.display_name.length > 100 || /[<>\p{C}]/u.test(row.display_name) || row.approved && !row.email && !row.whatsapp)) throw new Error('请选择员工、填写对外称呼，并为获准名片填写联系渠道。')
  const enabled = form.auto_fees_enabled === true
  // Empty tiers are allowed only while disabled; the server then keeps the business default tiers.
  const auto_fees = !enabled && !String(form.shipping_tiers || '').trim() ? { enabled } : { enabled, shipping_tiers: parseTiers(form.shipping_tiers) }
  return { name, status: form.status, reason, policy: { sales_contacts: contacts, quote_valid_minutes: minutes, proposal_valid_hours: parts.map(Number), payment_terms: terms, default_payment_term_code: defaultCode, auto_fees } }
}

/** "300=40.00, 600=48.00" -> [{ max_grams: 300, fee: '40.00' }, ...]; strictly increasing weights. */
export function parseTiers(text) {
  const parts = String(text || '').split(/[,，\n]/).map(x => x.trim()).filter(Boolean)
  if (!parts.length || parts.length > 20) throw new Error('运费阶梯请填写 1–20 档，格式如 300=40.00, 600=48.00。')
  const tiers = parts.map(part => {
    const match = /^([1-9][0-9]{0,6})\s*=\s*((0|[1-9][0-9]{0,11})\.[0-9]{2})$/.exec(part)
    if (!match) throw new Error(`运费阶梯“${part}”格式不正确，应为 克重上限=运费（两位小数）。`)
    return { max_grams: Number(match[1]), fee: match[2] }
  })
  if (tiers.some((tier, index) => index && tier.max_grams <= tiers[index - 1].max_grams)) throw new Error('运费阶梯的克重上限须严格递增。')
  return tiers
}

export function formatTiers(tiers) {
  return (tiers || []).map(tier => `${tier.max_grams}=${tier.fee}`).join(', ')
}
