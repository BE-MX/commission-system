type PopupState = 'loading' | 'unpaired' | 'pairing' | 'ready' | 'blocked' | 'error'
type SessionLoadState = 'ready' | 'missing' | 'error'

const root = document.getElementById('popup') as HTMLElement
const sections = ['loading', 'unpaired', 'pairing', 'ready', 'blocked', 'error']
  .map(id => [id, document.getElementById(id) as HTMLElement] as const)

function setState(state: PopupState): void {
  root.dataset.state = state
  for (const [id, section] of sections) section.hidden = id !== state
}

async function runtimeRequest(request: unknown) {
  return chrome.runtime.sendMessage(request)
}

async function loadPreferences(): Promise<{ enabled: boolean; targetLanguage: string }> {
  return await runtimeRequest({ type: 'preferences/get' })
}

function initials(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return '·'
  const parts = trimmed.split(/\s+/u)
  if (parts.length > 1) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  return trimmed[0].toUpperCase()
}

function formatExpiry(value: string | undefined): string {
  if (!value || Number.isNaN(Date.parse(value))) return ''
  const date = new Date(value)
  return `有效期至 ${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

async function loadSession(): Promise<SessionLoadState> {
  const response = await runtimeRequest({ type: 'session/refresh' })
  if (response?.type === 'session/refresh') {
    const employee = document.getElementById('employee')
    const expiry = document.getElementById('expiry')
    const avatar = document.getElementById('avatar')
    if (!employee || !expiry || !avatar) return 'error'
    employee.textContent = response.session.realName || `已授权`
    expiry.textContent = formatExpiry(response.session.expiresAt)
    avatar.textContent = initials(response.session.realName || '')
    const preferences = await loadPreferences()
    const enabled = document.getElementById('enabled') as HTMLInputElement
    const language = document.getElementById('language') as HTMLSelectElement
    enabled.checked = preferences.enabled
    language.value = preferences.targetLanguage
    setState('ready')
    return 'ready'
  }
  return response?.type === 'error' && response.message === 'device_token_missing' ? 'missing' : 'error'
}

async function resumePairing(): Promise<void> {
  const response = await runtimeRequest({ type: 'pairing/resume' })
  if (response?.type !== 'pairing/resume') {
    setState('error')
    return
  }
  if (!response.state) {
    setState('unpaired')
    return
  }
  if (response.state.status === 'ready') {
    if (await loadSession() !== 'ready') setState('error')
    return
  }
  setState('pairing')
}

async function restoreState(): Promise<void> {
  const sessionState = await loadSession()
  if (sessionState === 'ready') return
  if (sessionState === 'error') {
    setState('error')
    return
  }
  await resumePairing()
}

document.getElementById('start-pairing')?.addEventListener('click', async () => {
  const response = await runtimeRequest({ type: 'pairing/start' })
  if (response?.type === 'pairing/start') {
    setState('pairing')
    return
  }
  setState('error')
})

document.getElementById('check-pairing')?.addEventListener('click', async () => {
  await resumePairing()
})

document.getElementById('reauthorize')?.addEventListener('click', async () => {
  await runtimeRequest({ type: 'pairing/start' })
  setState('pairing')
})

document.getElementById('enabled')?.addEventListener('change', async event => {
  const target = event.target as HTMLInputElement
  const language = document.getElementById('language') as HTMLSelectElement
  await runtimeRequest({ enabled: target.checked, targetLanguage: language.value, type: 'preferences/set' })
})

document.getElementById('language')?.addEventListener('change', async event => {
  const language = event.target as HTMLSelectElement
  const enabled = document.getElementById('enabled') as HTMLInputElement
  await runtimeRequest({ enabled: enabled.checked, targetLanguage: language.value, type: 'preferences/set' })
})

setState('loading')
restoreState().catch(() => setState('error'))

export {}
