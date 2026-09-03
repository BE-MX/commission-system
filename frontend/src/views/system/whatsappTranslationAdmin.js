const PRIVATE_KEYS = new Set(['token', 'token_hash', 'text', 'translation', 'contact', 'phone'])
const RELEASE_KEYS = new Set(['version', 'filename', 'sha256', 'size', 'extension_id'])
const EXTENSION_ID = 'bnkecbkoidckffckbefjjcbchmngjobi'

export function healthLabel(row = {}) {
  const total = Number(row.request_count) || 0
  const success = Number(row.success_count) || 0
  if (!total) return '—'
  return `${((success / total) * 100).toFixed(1)}%`
}

export function deviceStatusLabel(row = {}) {
  if (row.revoked_at) return '已撤销'
  if (!row.is_active) return '停用'
  return row.expires_at && new Date(row.expires_at) < new Date() ? '已过期' : '有效'
}

export function parseReleaseManifest(value) {
  if (!value || typeof value !== 'object') throw new Error('invalid_release_manifest')
  const keys = Object.keys(value)
  if (keys.length !== 5 || keys.some(key => !RELEASE_KEYS.has(key))) {
    throw new Error('invalid_release_manifest')
  }
  if (value.extension_id !== EXTENSION_ID) throw new Error('invalid_release_manifest')
  if (!/^whatsapp-translation-[0-9]+\.[0-9]+\.[0-9]+\.zip$/.test(value.filename)) {
    throw new Error('invalid_release_manifest')
  }
  if (value.filename.includes('/') || value.filename.includes('\\\\') || value.filename.includes('..')) {
    throw new Error('invalid_release_manifest')
  }
  if (!/^[0-9a-f]{64}$/.test(value.sha256) || !Number.isInteger(value.size) || value.size <= 0) {
    throw new Error('invalid_release_manifest')
  }
  return value
}

export function releaseDownloadUrl(release) {
  const parsed = parseReleaseManifest(release)
  return `/downloads/whatsapp-translation/${encodeURIComponent(parsed.filename)}`
}

export function sanitizeDeviceRows(rows) {
  return rows.map(row => Object.fromEntries(
    Object.entries(row).filter(([key]) => !PRIVATE_KEYS.has(key)),
  ))
}
