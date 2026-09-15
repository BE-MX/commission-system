/**
 * 方舟客户邮件触达 API（/api/mail-outreach）。
 *
 * 契约来源：docs/2026-09-11-mail-outreach-auto-send-design.md §5.1。
 * 响应统一信封 { code, data }，分页 data 形如 { items, total, page, page_size }；
 * 列表/快照类请求一律 showLoading: false（避免遮挡抽屉内交互）。
 */
import { mailOutreachClient } from './clients'

export function createMailOutreachApi(client) {
  return {
    /** 触达安全快照：客户/联系人语言时区、邮箱点资格与缺项、证据事实 */
    getOutreachContext: customerId => client.get(`/context/${customerId}`, { showLoading: false }),
    /** 生成草稿（AI 版本），body 需带 request_key 幂等 */
    createDraft: payload => client.post('/drafts', payload),
    listDrafts: params => client.get('/drafts', { params, showLoading: false }),
    getDraft: draftId => client.get(`/drafts/${draftId}`, { showLoading: false }),
    /** 编辑 → 新 revision（使旧审批失效） */
    createRevision: (draftId, payload) => client.post(`/drafts/${draftId}/revisions`, payload),
    /** 排程候选时间预览；侧车不可达时后端返回错误，调用方降级为手动选时间 */
    previewSchedule: draftId => client.post(`/drafts/${draftId}/schedule-preview`, {}),
    /** 批准并排程：带 request_key + expected_content_sha256 + schedule_policy + scheduled_at_utc */
    approveDraft: (draftId, payload) => client.post(`/drafts/${draftId}/approve`, payload),
    rejectDraft: (draftId, payload) => client.post(`/drafts/${draftId}/reject`, payload),
    revokeDraft: (draftId, payload) => client.post(`/drafts/${draftId}/revoke`, payload),
    listJobs: params => client.get('/jobs', { params, showLoading: false }),
    cancelJob: (jobId, payload) => client.post(`/jobs/${jobId}/cancel`, payload),
    /** 邮箱绑定列表（不含凭据） */
    listMailboxes: params => client.get('/mailboxes', { params, showLoading: false }),
  }
}

export const {
  getOutreachContext, createDraft, listDrafts, getDraft, createRevision,
  previewSchedule, approveDraft, rejectDraft, revokeDraft,
  listJobs, cancelJob, listMailboxes,
} = createMailOutreachApi(mailOutreachClient)
