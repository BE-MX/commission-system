type PopupState = 'loading' | 'unpaired' | 'pairing' | 'ready' | 'blocked' | 'error'

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

async function loadSession(): Promise<boolean> {
  const response = await runtimeRequest({ type: 'session/refresh' })
  if (response?.type === 'session/refresh') {
    const employee = document.getElementById('employee')
    const expiry = document.getElementById('expiry')
    if (!employee || !expiry) return false
    employee.textContent = `已授权设备 #${response.session.deviceId}`
    expiry.textContent = `有效期至 ${response.session.expiresAt}`
    const preferences = await loadPreferences()
    const enabled = document.getElementById('enabled') as HTMLInputElement
    const language = document.getElementById('language') as HTMLSelectElement
    enabled.checked = preferences.enabled
    language.value = preferences.targetLanguage
    setState('ready')
    return true
  }
  return false
}

async function resumePairing(): Promise<void> {
  const response = await runtimeRequest({ type: 'pairing/resume' })
  if (response?.type !== 'pairing/resume' || !response.state) {
    setState('unpaired')
    return
  }
  if (response.state.status === 'ready') {
    if (!await loadSession()) setState('error')
    return
  }
  setState('pairing')
}

async function restoreState(): Promise<void> {
  if (await loadSession()) return
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
