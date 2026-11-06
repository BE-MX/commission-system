// Local-only fixture transport. It never contacts a backend or model.
export function installFeedFixture(feedClient, deskClient, { disabled = false, placeholders = false } = {}) {
  const calls = [], observed = '2026-11-05T09:45:00'
  const source = { source_account_uid: 'fixture-tm', name: '测试店铺 · 仅本地', integration_app_id: 1, ingest_enabled: true, consent_state: 'authorized', crm_shared: false, ai_egress_allowed: false, private_feed_enabled: false, owner_aliases: { 'Fixture Sales': 1 }, version: 1, mapping_version: 1, capability_version: 1, legacy_identity_blocked: true, verified_capabilities: { stable_message_ids: false, reliable_order: false, latest_coverage: false, human_identity: false, activity_scan: false, deletions: false, evidence_note: '本地测试来源，不代表生产核验结果。' } }
  const rows = [
    { id: 1, schema_version: '1.0', buyer: { name: 'Sample Buyer A', country: 'United States' }, record_type: 'TM', reply_status: 'unreplied', link: null, ai_eligible: false, issues: ['WINDOW_PRECISION_INSUFFICIENT'] },
    { id: 2, schema_version: '1.1', buyer: { name: 'Sample Buyer B', country: 'United Kingdom' }, record_type: 'inquiry', reply_status: 'replied', link: { id: 12, company_id: '9007199254740993', version: 1, mapping_version: 1 }, ai_eligible: true, issues: [] },
    { id: 3, schema_version: '1.0', buyer: { name: 'Coverage Gap Buyer', country: 'Canada' }, record_type: 'TM', reply_status: 'unknown', link: null, ai_eligible: false, issues: ['DETAIL_SCRAPE_INCOMPLETE'] },
  ].map(row => ({ ...row, source_account_uid: source.source_account_uid, source_name: source.name, inquiry_id: `fixture-${row.id}`, assignee_name: 'Fixture Sales', observed_at: observed, is_current: true, window_result: 'in_window', mapping_version: 1 }))
  if (placeholders) for (const [index, state] of ['link_revoked', 'mapping_changed'].entries()) rows.push({ ...rows[0], id: index + 4, inquiry_id: `fixture-${index + 4}`, buyer: { name: '资料待重新确认' }, link: null, ai_eligible: false, visibility_state: state })
  const copy = value => JSON.parse(JSON.stringify(value))
  const response = (config, data) => ({ config, data: { code: 200, message: 'ok', data: copy(data) }, status: 200, statusText: 'OK', headers: {} })
  const failure = (config, status, detail) => Promise.reject({ config, response: { status, data: { detail } }, message: detail })
  const adapter = async config => {
    calls.push({ url: config.url, method: config.method, body: config.data ? JSON.parse(config.data) : null })
    if (disabled && config.url.startsWith('/business/')) return failure(config, 503, 'disabled')
    if (config.url === '/sources' && config.method === 'get') return response(config, { items: [source] })
    if (config.url === '/owners') return response(config, { items: [{ id: 1, username: 'fixture', real_name: '测试业务员' }] })
    if (config.url === '/sources/fixture-tm' && config.method === 'patch') {
      const data = JSON.parse(config.data)
      if (data.expected_version !== source.version) return failure(config, 409, '配置版本已变化')
      Object.assign(source, data, { version: source.version + 1 })
      return response(config, source)
    }
    if (config.url === '/business/records') {
      const { linked = 'all', keyword = '', page = 1, page_size = 20 } = config.params || {}
      const items = rows.filter(row => (linked === 'all' || (linked === 'linked' ? !!row.link : !row.link)) && JSON.stringify(row.buyer).toLowerCase().includes(keyword.toLowerCase()))
      return response(config, { items: items.slice((page - 1) * page_size, page * page_size), total: items.length, page, page_size })
    }
    if (/^\/business\/records\/\d+$/.test(config.url)) {
      const row = rows.find(row => row.id === Number(config.url.split('/').at(-1)))
      if (!row || row.visibility_state) return failure(config, 404, '资料已失效')
      return response(config, { ...row, coverage_gaps: ['minute_precision', 'history_snapshot_only'], snapshot: { detail_scraped: true, scrape_status: 'success' }, messages: [{ key: `AF-${row.id}-1`, dir: 'buyer', at: '2026-11-05T09:40:00', text: 'Do you have this in 18 inches?\nhttps://example.invalid/product is text only.' }, { key: `AF-${row.id}-2`, dir: 'seller', at: '2026-11-05T09:40:00', text: 'I will check availability.\n<script>alert("fixture")</script>' }] })
    }
    if (config.url === '/business/customers') return response(config, { items: [{ company_id: '9007199254740993', name: 'Sample Private Customer', country: 'United Kingdom' }], total: 1, page: 1, page_size: 20 })
    if (config.url === '/business/links' && config.method === 'post') {
      const data = JSON.parse(config.data), row = rows.find(row => row.id === data.item_id)
      row.link = { id: row.id + 10, company_id: data.company_id, version: 1, mapping_version: 1 }
      if (row.visibility_state) { row.visibility_state = null; row.buyer = { name: `重新关联的样例买家 ${row.id}`, country: 'United Kingdom' } }
      return response(config, row.link)
    }
    if (/^\/business\/links\/\d+$/.test(config.url) && config.method === 'delete') {
      const row = rows.find(row => row.link?.id === Number(config.url.split('/').at(-1)))
      const id = row.link.id; row.link = null; row.ai_eligible = false; row.visibility_state = 'link_revoked'; row.buyer = { name: '资料待重新确认' }
      return response(config, { id, deleted: true, version: 2 })
    }
    return failure(config, 404, 'Fixture path not supported')
  }
  feedClient.defaults.adapter = adapter
  deskClient.defaults.adapter = config => {
    calls.push({ url: config.url, method: config.method, body: config.data ? JSON.parse(config.data) : null })
    if (config.method === 'post' && /\/reanalyze$/.test(config.url)) return Promise.resolve(response(config, { suggestion_id: 100, run_seq: 1, status: 'queued', remaining: 2 }))
    return failure(config, 404, 'Fixture desk path not supported')
  }
  return { calls, rows, source }
}
