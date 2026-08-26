export const PORTAL_STATUS_META = Object.freeze({
  ready: { label: '已发布', tone: 'ready' },
  in_review: { label: '审核中', tone: 'in-review' },
  changes_requested: { label: '待修改', tone: 'changes-requested' },
  draft: { label: '准备中', tone: 'draft' },
  disabled: { label: '已停用', tone: 'disabled' },
  empty: { label: '暂无素材', tone: 'empty' },
})

export function portalStatusMeta(status) {
  return PORTAL_STATUS_META[status] || PORTAL_STATUS_META.empty
}

export function initials(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return 'CL'
  if (parts.length === 1) return [...parts[0]].slice(0, 2).join('').toUpperCase()
  return `${[...parts[0]][0] || ''}${[...parts.at(-1)][0] || ''}`.toUpperCase()
}

export function formatPortalDate(value) {
  return formatBeijingDate(value, { fallback: '尚未更新' })
}

export function formatFileSize(bytes) {
  const size = Number(bytes) || 0
  if (size < 1024 * 1024) return `${Math.max(size / 1024, 0).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function filterPreviewBatches(batches, { search = '', mediaType = 'all' } = {}) {
  const query = String(search).trim().toLowerCase()
  return (batches || []).map(batch => ({
    ...batch,
    assets: (batch.assets || []).filter(asset => {
      const matchesType = mediaType === 'all' || asset.media_type === mediaType
      const matchesSearch = !query || String(asset.file_name || '').toLowerCase().includes(query)
      return matchesType && matchesSearch
    }),
  })).filter(batch => batch.assets.length > 0)
}

export function appendDownload(url) {
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}download=true`
}
import { formatBeijingDate } from '../../../utils/datetime.js'
