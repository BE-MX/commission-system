import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { EventEmitter } from 'node:events'
import { Store } from '../src/store.js'
import { Manager } from '../src/manager.js'

export const encryptionKey = Buffer.alloc(32, 7).toString('base64')
export const authorization = { allowed: true, provider: 'baileys', ark_user_id: 7, session_generation: 1,
  consent_version: '1', crm_shared: false }
export function fixture(t, options = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'ark-wa-test-'))
  const filename = join(directory, 'connector.sqlite')
  const store = new Store(filename, { encryptionKey, ...options })
  const cleanups = []
  t.after(() => {
    for (const cleanup of cleanups.reverse()) cleanup()
    try { store.close() } catch { /* tests explicitly exercise reopen */ }
    if (!resolve(directory).startsWith(resolve(tmpdir()))) throw new Error('Unsafe fixture cleanup')
    rmSync(directory, { recursive: true, force: true })
  })
  store.configure('account_a', authorization)
  return { store, filename, directory, onCleanup(fn) { cleanups.push(fn) } }
}
export function fakeManager(t, options = {}) {
  const { store, ...fixtureInfo } = fixture(t)
  const sockets = []
  let auth = { ...authorization }
  const manager = new Manager(store, { authorize: async () => {
    if (auth instanceof Error) throw auth
    return { ...auth }
  }, socketFactory: config => {
    const socket = { config, ev: new EventEmitter(), user: { id: '15550001111@s.whatsapp.net', name: 'Synthetic' },
      closed: false, end() { this.closed = true }, async logout() { this.loggedOut = true } }
    sockets.push(socket)
    return socket
  }, encodeQR: async qr => `data:image/png;base64,${Buffer.from(qr).toString('base64')}`, ...options })
  fixtureInfo.onCleanup(() => manager.shutdown())
  return { store, manager, sockets, ...fixtureInfo, setAuthorization(value) { auth = value } }
}
export const message = (id = 'message-1', text = 'Synthetic body', timestamp = 1000, overrides = {}) => ({
  key: { remoteJid: '15550002222@s.whatsapp.net', id, fromMe: false, ...overrides },
  message: { conversation: text }, messageTimestamp: timestamp, pushName: 'Synthetic contact' })
export const tick = () => new Promise(resolveTick => setImmediate(resolveTick))
export const sleep = ms => new Promise(resolveSleep => setTimeout(resolveSleep, ms))
