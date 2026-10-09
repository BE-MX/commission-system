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
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(code)) throw new Error('付款条件代码应以小写字母开头，仅含小写字母、数字及下划线。')
    if (!display_text || display_text.length > 256 || /[<>\p{C}]/u.test(display_text)) throw new Error('客户付款说明须为 1–256 字的纯文本。')
    if (!/^(0|[1-9][0-9]?|100)\.[0-9]{2}$/.test(deposit_percent) || Number(deposit_percent) > 100) throw new Error('定金比例请输入 0.00–100.00，保留两位小数。')
    return { code, display_text, deposit_percent }
  })
  if (new Set(terms.map(x => x.code)).size !== terms.length) throw new Error('付款条件代码不能重复。')
  const defaultCode = form.default_payment_term_code || null
  if (terms.length ? !terms.some(x => x.code === defaultCode) : defaultCode !== null) throw new Error('请选择已配置的默认付款条件。')
  if (form.status === 'enabled' && !terms.length) throw new Error('启用前必须配置并确认付款条件。')
  const contacts = (form.sales_contacts || []).map(row => ({ user_id: String(row.user_id || ''), display_name: row.display_name.trim(), approved: row.approved === true, email: row.email?.trim() || null, whatsapp: row.whatsapp?.trim() || null }))
  if (contacts.length > 200 || new Set(contacts.map(row => row.user_id)).size !== contacts.length) throw new Error('员工对外名片不能重复，最多 200 项。')
  if (contacts.some(row => !/^[1-9][0-9]{0,19}$/.test(row.user_id) || !row.display_name || row.display_name.length > 100 || /[<>\p{C}]/u.test(row.display_name) || row.approved && !row.email && !row.whatsapp)) throw new Error('请选择员工、填写对外称呼，并为获准名片填写联系渠道。')
  return { name, status: form.status, reason, policy: { sales_contacts: contacts, quote_valid_minutes: minutes, proposal_valid_hours: parts.map(Number), payment_terms: terms, default_payment_term_code: defaultCode } }
}
