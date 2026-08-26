import { formatBeijingDateTime } from '../../utils/datetime.js'

export const MCP_ENDPOINT = 'https://leshine.work/mcp/'

export function isKnowledgeReady(candidate) {
  return Boolean(candidate?.has_knowledge_read && Number(candidate?.knowledge_library_count) > 0)
}

export function filterTokens(rows, filters) {
  const keyword = String(filters?.keyword || '').trim().toLowerCase()
  const status = filters?.status || 'all'
  return (rows || []).filter((row) => {
    const matchesKeyword = !keyword || [row.label, row.username, row.real_name]
      .some((value) => String(value || '').toLowerCase().includes(keyword))
    const matchesStatus = status === 'all'
      || (status === 'active' && row.is_active)
      || (status === 'revoked' && !row.is_active)
    return matchesKeyword && matchesStatus
  })
}

export function buildAgentConfig(token) {
  return JSON.stringify({
    mcpServers: {
      leshineArk: {
        type: 'streamable-http',
        url: MCP_ENDPOINT,
        headers: { Authorization: `Bearer ${token}` },
      },
    },
  }, null, 2)
}

export async function copyToClipboard(value, {
  clipboard = globalThis.navigator?.clipboard,
  documentRef = globalThis.document,
} = {}) {
  const text = String(value ?? '')

  if (clipboard?.writeText) {
    try {
      await clipboard.writeText(text)
      return true
    } catch {
      // Some embedded browsers expose Clipboard API but reject it at runtime.
    }
  }

  if (
    !documentRef?.body
    || typeof documentRef.createElement !== 'function'
    || typeof documentRef.execCommand !== 'function'
  ) return false

  const textarea = documentRef.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '-9999px'
  textarea.style.opacity = '0'
  documentRef.body.appendChild(textarea)

  try {
    textarea.focus({ preventScroll: true })
    textarea.select()
    textarea.setSelectionRange?.(0, text.length)
    return Boolean(documentRef.execCommand('copy'))
  } catch {
    return false
  } finally {
    textarea.remove()
  }
}

export function formatDateTime(value) {
  if (!value) return '尚未使用'
  return formatBeijingDateTime(value, { seconds: false, fallback: value })
}
