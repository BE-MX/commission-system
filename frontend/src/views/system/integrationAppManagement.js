import { formatBeijingDateTime, parseApiDateTime } from '../../utils/datetime.js'

export const INVOICE_API_ENDPOINT = 'https://leshine.work/api/integrations/v1'

export function buildServerEnvSnippet(token) {
  return [
    `ARK_INVOICE_API_BASE_URL=${INVOICE_API_ENDPOINT}`,
    `ARK_INVOICE_API_TOKEN=${String(token || '')}`,
  ].join('\n')
}

export function createOneTimeSecretState(onChange = () => {}) {
  let secret = null
  return {
    show(value) {
      secret = value
      onChange(secret)
    },
    clear() {
      secret = null
      onChange(null)
    },
    current() {
      return secret
    },
  }
}

export function getIntegrationAppStatus(row, now = new Date()) {
  if (!row?.is_active) return { key: 'revoked', label: '已吊销', type: 'info' }
  const expiresAt = parseApiDateTime(row.expires_at)
  if (expiresAt && expiresAt.getTime() <= now.getTime()) {
    return { key: 'expired', label: '已过期', type: 'warning' }
  }
  return { key: 'active', label: '有效', type: 'success' }
}

export function canRotateIntegrationApp(row, now = new Date()) {
  return getIntegrationAppStatus(row, now).key === 'active'
}

export function filterIntegrationApps(rows, filters, now = new Date()) {
  const keyword = String(filters?.keyword || '').trim().toLowerCase()
  const status = filters?.status || 'all'
  return (rows || []).filter((row) => {
    const searchable = [
      row.name,
      row.owner_username,
      row.owner_real_name,
      row.token_suffix,
      row.public_id,
    ]
    const matchesKeyword = !keyword || searchable.some(
      (value) => String(value || '').toLowerCase().includes(keyword),
    )
    const matchesStatus = status === 'all' || getIntegrationAppStatus(row, now).key === status
    return matchesKeyword && matchesStatus
  })
}

export function formatCredentialTime(value, emptyText = '尚未使用') {
  return formatBeijingDateTime(value, { seconds: false, fallback: emptyText })
}
