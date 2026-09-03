type PopupState = 'loading' | 'unpaired' | 'pairing' | 'ready' | 'blocked' | 'error'

const root = document.getElementById('popup') as HTMLElement
const sections = ['loading', 'unpaired', 'pairing', 'ready', 'blocked', 'error']
  .map(id => [id, document.getElementById(id) as HTMLElement] as const)
let deviceCode = ''

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

async function loadSession(): Promise<void> {
  const response = await runtimeRequest({ type: 'session/refresh' })
  if (response?.type === 'session/refresh') {
    const employee = document.getElementById('employee')
    const expiry = document.getElementById('expiry')
    if (!employee || !expiry) return
    employee.textContent = `已授权设备 #${response.session.deviceId}`
    expiry.textContent = `有效期至 ${response.session.expiresAt}`
    const preferences = await loadPreferences()
    const enabled = document.getElementById('enabled') as HTMLInputElement
    const language = document.getElementById('language') as HTMLSelectElement
    enabled.checked = preferences.enabled
    language.value = preferences.targetLanguage
    setState('ready')
    return
  }
  setState('unpaired')
}

document.getElementById('start-pairing')?.addEventListener('click', async () => {
  const response = await runtimeRequest({ type: 'pairing/start' })
  if (response?.type === 'pairing/start') {
    deviceCode = response.state.deviceCode
    setState('pairing')
    return
  }
  setState('error')
})

document.getElementById('check-pairing')?.addEventListener('click', async () => {
  const response = await runtimeRequest({ type: 'pairing/check', deviceCode })
  if (response?.type === 'pairing/check' && response.state.status === 'ready') {
    await loadSession()
    return
  }
  setState('pairing')
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
loadSession().catch(() => setState('error'))
