import { portalAdminClient } from './clients'

export const portalAdminApi = {
  async customerPreview(id, signal) {
    const response = await portalAdminClient.post(`/customers/${encodeURIComponent(id)}/preview`, {}, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async imageAssets(params, signal) {
    const response = await portalAdminClient.get('/image-assets', { params, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async previewImage(id, signal) {
    const response = await portalAdminClient.get(`/image-assets/${encodeURIComponent(id)}/preview`, { signal, responseType: 'blob', showLoading: false, suppressToast: true })
    return { blob: response.data, reference: response.headers['x-portal-image-reference'] }
  },
  async bindImage(id, body, version) {
    const response = await portalAdminClient.patch(`/catalog/${encodeURIComponent(id)}/image`, body, { headers: { 'If-Match': `"${version}"` }, showLoading: false, suppressToast: true })
    return response.data
  },
  async audit(id, params, signal) {
    const response = await portalAdminClient.get(`/orders/${encodeURIComponent(id)}/audit`, { params, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async notifications(id, params, signal) {
    const response = await portalAdminClient.get(`/orders/${encodeURIComponent(id)}/notifications`, { params, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async mappingNotifications(id, params, signal) {
    const response = await portalAdminClient.get(`/customers/${encodeURIComponent(id)}/mapping/notifications`, { params, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async retryMappingNotification({ id, eventId, key, body }) {
    const response = await portalAdminClient.post(`/customers/${encodeURIComponent(id)}/mapping/notifications/${encodeURIComponent(eventId)}/retry`, body, { headers: { 'Idempotency-Key': key }, showLoading: false, suppressToast: true })
    return response.data
  },
  async retryNotification({ id, eventId, key, body }) {
    const response = await portalAdminClient.post(`/orders/${encodeURIComponent(id)}/notifications/${encodeURIComponent(eventId)}/retry`, body, { headers: { 'Idempotency-Key': key }, showLoading: false, suppressToast: true })
    return response.data
  },
  async proposalCatalog(id, params, signal) {
    const response = await portalAdminClient.get(`/orders/${encodeURIComponent(id)}/proposal-catalog`, { params, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async previewProposal(id, version, body, signal) {
    if (!Number.isSafeInteger(version) || version < 0) throw new Error('无效请求版本，请刷新。')
    const response = await portalAdminClient.post(`/orders/${encodeURIComponent(id)}/proposal-preview`, body, { headers: { 'If-Match': `"${version}"` }, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async bindingReview(id, signal) {
    const response = await portalAdminClient.get(`/customers/${encodeURIComponent(id)}/binding-review`, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async bindingMutation({ action, id, version, body }) {
    if (!['transfer', 'rebind'].includes(action) || !Number.isSafeInteger(version) || version < 0) throw new Error('无效复核操作或版本。')
    const response = await portalAdminClient.post(`/customers/${encodeURIComponent(id)}/${action}`, body, { headers: { 'If-Match': `"${version}"` }, showLoading: false, suppressToast: true })
    return response.data
  },
  async catalogItems(params, signal) {
    const response = await portalAdminClient.get('/catalog', { params: { ...params, keyword: params.keyword || undefined, status: params.status || undefined }, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async catalogItem(id, signal) {
    const response = await portalAdminClient.get(`/catalog/${encodeURIComponent(id)}`, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async catalogSource(params, signal) {
    const response = await portalAdminClient.get('/catalog/source', { params, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async catalogImportStatus({ product_id, sku_id }, signal) {
    const response = await portalAdminClient.get('/catalog/import-status', { params: { product_id, sku_id }, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async catalogMutation({ action, id, version, body }) {
    if (!['import', 'update'].includes(action) || !Number.isSafeInteger(version) || version < 0) throw new Error('无效商品操作或版本。')
    const method = action === 'import' ? 'post' : 'patch', path = action === 'import' ? '/catalog/import' : `/catalog/${encodeURIComponent(id)}`
    const response = await portalAdminClient[method](path, body, { headers: { 'If-Match': `"${version}"` }, showLoading: false, suppressToast: true })
    return response.data
  },
  async siteSettings(signal) {
    const response = await portalAdminClient.get('/settings', { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async updateSiteSettings(body, version) {
    if (!Number.isSafeInteger(version) || version < 0) throw new Error('无效站点版本，请重新读取。')
    const response = await portalAdminClient.patch('/settings', body, { headers: { 'If-Match': `"${version}"` }, showLoading: false, suppressToast: true })
    return response.data
  },
  async onboardingCustomers(params, signal) {
    const response = await portalAdminClient.get('/onboarding/customers', { params: { ...params, keyword: params.keyword || undefined }, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async onboardingStatus(customerId, signal) {
    const response = await portalAdminClient.get(`/onboarding/customers/${encodeURIComponent(customerId)}`, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async onboardingCatalog(params, signal) {
    const response = await portalAdminClient.get('/onboarding/catalog', { params: { ...params, keyword: params.keyword || undefined }, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async createCustomer(body) {
    const response = await portalAdminClient.post('/customers', body, { showLoading: false, suppressToast: true })
    return response.data
  },
  async customerCatalog(id, signal) {
    const response = await portalAdminClient.get(`/customers/${encodeURIComponent(id)}/catalog`, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async mapping(id, signal) {
    const response = await portalAdminClient.get(`/customers/${encodeURIComponent(id)}/mapping`, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async previewMapping(id, body, signal) {
    const response = await portalAdminClient.post(`/customers/${encodeURIComponent(id)}/mapping/preview`, body, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async publishMapping(id, body, version) {
    if (!Number.isSafeInteger(version) || version < 0) throw new Error('无效映射版本，请重新读取。')
    const response = await portalAdminClient.post(`/customers/${encodeURIComponent(id)}/mapping/publish`, body, { headers: { 'If-Match': `"${version}"` }, showLoading: false, suppressToast: true })
    return response.data
  },
  async customers(params, signal) {
    const response = await portalAdminClient.get('/customers', { params: { ...params, keyword: params.keyword || undefined, status: params.status || undefined }, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async customer(id, params, signal) {
    const response = await portalAdminClient.get(`/customers/${encodeURIComponent(id)}`, { params, signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async accessMutation({ action, id, version, key, body }) {
    const routes = { catalog: ['patch', `/customers/${encodeURIComponent(id)}/catalog`], access: ['patch', `/customers/${encodeURIComponent(id)}`], account: ['patch', `/accounts/${encodeURIComponent(id)}`], invite: ['post', `/customers/${encodeURIComponent(id)}/invitations`], revoke: ['post', `/invitations/${encodeURIComponent(id)}/revoke`] }
    if (!routes[action]) throw new Error('无效操作。')
    if (action !== 'invite' && (!Number.isSafeInteger(version) || version < 0)) throw new Error('无效版本，请刷新。')
    const [method, url] = routes[action]
    const headers = action === 'invite' ? { 'Idempotency-Key': key } : { 'If-Match': `"${version}"` }
    const response = await portalAdminClient[method](url, body, { headers, showLoading: false, suppressToast: true })
    return response.data
  },
  async piReview(id, signal) {
    const response = await portalAdminClient.get(`/orders/${encodeURIComponent(id)}/pi-review`, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async review(id, signal) {
    const response = await portalAdminClient.get(`/orders/${encodeURIComponent(id)}/review`, { signal, showLoading: false, suppressToast: true })
    return response.data
  },
  async command({ id, action, version, body }) {
    const paths = { propose: 'proposals', approve: 'approve', reject: 'reject', propose_pi: 'pi-proposals', publish_pi: 'publish-pi', void_pi: 'void-pi' }
    if (!paths[action] || !Number.isSafeInteger(version) || version < 0) throw new Error('无效操作或版本，请刷新。')
    const response = await portalAdminClient.post(`/orders/${encodeURIComponent(id)}/${paths[action]}`, body, {
      headers: { 'If-Match': `"${version}"` }, showLoading: false, suppressToast: true,
    })
    return response.data
  },
  async orders(params, signal) {
    const response = await portalAdminClient.get('/orders', {
      params: { ...params, status: params.status || undefined }, signal,
      showLoading: false, suppressToast: true,
    })
    return response.data
  },
  async order(id, signal) {
    if (!/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(id)) throw new Error('无效的请求编号')
    const response = await portalAdminClient.get(`/orders/${id}`, {
      signal, showLoading: false, suppressToast: true,
    })
    return response.data
  },
}
