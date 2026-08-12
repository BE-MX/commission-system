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

export function formatDateTime(value) {
  if (!value) return '尚未使用'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}
