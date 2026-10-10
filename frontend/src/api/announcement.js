import { announcementClient } from './clients'
const unwrap = response => response.data?.data ?? response.data
export const announcementApi = {
  get: (path = '', params, config = {}) => announcementClient.get(path, { ...config, params, showLoading: false }).then(unwrap),
  post: (path, data = {}) => announcementClient.post(path, data).then(unwrap),
  put: (path, data) => announcementClient.put(path, data).then(unwrap),
  delete: path => announcementClient.delete(path).then(unwrap),
}

// Inbox owns inline errors; background refresh must not interrupt other pages.
const inboxConfig = config => ({ ...config, showLoading: false, suppressToast: true })
export const announcementInboxApi = {
  summary: config => announcementClient.get('/inbox/summary', inboxConfig(config)).then(unwrap),
  list: (params, config) => announcementClient.get('/inbox', { ...inboxConfig(config), params }).then(unwrap),
  detail: (id, config) => announcementClient.get(`/inbox/${id}`, inboxConfig(config)).then(unwrap),
  markRead: (id, revisionId, config) => announcementClient.post(`/inbox/${id}/read`, { revision_id: revisionId }, inboxConfig(config)).then(unwrap),
  markAll: config => announcementClient.post('/inbox/read-all', {}, inboxConfig(config)).then(unwrap),
}
