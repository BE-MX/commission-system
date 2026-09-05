export const COUNTRY_OPTIONS = [
  ['US', '美国'], ['CA', '加拿大'], ['DE', '德国'], ['NL', '荷兰'], ['BE', '比利时'], ['GB', '英国'],
  ['AU', '澳大利亚'], ['NZ', '新西兰'], ['IE', '爱尔兰'], ['PR', '波多黎各'], ['CZ', '捷克'], ['SK', '斯洛伐克'], ['FR', '法国'],
]

export function parseRuleDocument(text) {
  let parsed
  try { parsed = JSON.parse(text) } catch { throw new Error('JSON 格式错误，请检查括号、引号和逗号。') }
  if (!parsed || Array.isArray(parsed) || !parsed.rules || !parsed.quotas) throw new Error('JSON 须包含 rules 和 quotas 两部分。')
  const assertKeys = (value, keys, name) => {
    if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).some(key => !keys.includes(key)) || keys.some(key => !(key in value))) throw new Error(`${name} 存在未知或缺少的字段，请从可视化配置生成完整 JSON。`)
  }
  assertKeys(parsed, ['rules', 'quotas'], '配置')
  assertKeys(parsed.rules, ['schema_version', 'commerce', 'countries', 'contact_channels', 'prefer_instagram', 'product_terms', 'product_exclusions', 'no_order_days', 'no_followup_days', 'missing_followup'], '筛选规则')
  assertKeys(parsed.rules.commerce, ['min_orders', 'total_usd_gt', 'single_usd_gt', 'allow_sample_only', 'sample_requires_product'], '成交条件')
  assertKeys(parsed.quotas, ['schema_version', 'tiers', 'team_scope', 'total_limit'], '配额')
  assertKeys(parsed.quotas.tiers, ['T1', 'T2', 'T3'], '档位')
  if (parsed.rules.schema_version !== 'public_pool_selection_v2' || parsed.quotas.schema_version !== 'public_pool_quotas_v1' || parsed.quotas.team_scope !== 'all') throw new Error('不支持的规则版本或团队范围。')
  const number = (v, min, max, integer = true) => typeof v === 'number' && Number.isFinite(v) && (!integer || Number.isInteger(v)) && v >= min && v <= max
  const c = parsed.rules.commerce, r = parsed.rules, q = parsed.quotas
  if (!number(c.min_orders, 1, 10000) || !number(c.total_usd_gt, 0, 1e9, false) || !number(c.single_usd_gt, 0, 1e9, false) || !number(r.no_order_days, 1, 3650) || !number(r.no_followup_days, 1, 3650) || !number(q.total_limit, 1, 1500) || Object.values(q.tiers).some(v => !number(v, 0, 500)) || !Object.values(q.tiers).some(v => v > 0)) throw new Error('金额、天数或配额超出允许范围。')
  if ([c.allow_sample_only, c.sample_requires_product, r.prefer_instagram].some(v => typeof v !== 'boolean') || !['exclude', 'include'].includes(r.missing_followup)) throw new Error('开关或缺失跟进日期的处理值不正确。')
  if (!Array.isArray(r.countries) || !r.countries.length || r.countries.length > 250 || r.countries.some(v => typeof v !== 'string' || !/^[A-Za-z]{2}$/.test(v))) throw new Error('国家须为两位字母代码列表。')
  if (!Array.isArray(r.contact_channels) || !r.contact_channels.length || r.contact_channels.length > 3 || r.contact_channels.some(v => !['instagram', 'facebook', 'phone'].includes(v))) throw new Error('联系渠道须包含 Instagram、Facebook、电话中的至少一种。')
  for (const key of ['product_terms', 'product_exclusions']) {
    if (!Array.isArray(r[key]) || r[key].length > 50 || (key === 'product_terms' && !r[key].length) || r[key].some(v => typeof v !== 'string' || !v.replace(/[\s_\-]+/g, '') || v.trim().length > 80)) throw new Error('产品词须为非空文本，最多50项，每项不超过80字。')
  }
  r.countries = [...new Set(r.countries.map(v => v.toUpperCase()))]
  return parsed
}

export function ruleDocument(config) {
  return { rules: structuredClone(config.rules), quotas: structuredClone(config.quotas) }
}
