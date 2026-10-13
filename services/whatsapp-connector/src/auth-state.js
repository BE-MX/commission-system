import { initAuthCreds, proto } from 'baileys'

// Baileys key methods return only after a fenced, FULL synchronous commit.
export function authState(store, lease, onFailure) {
  const revisions = new Map()
  const run = fn => {
    try { return fn() }
    catch (err) { onFailure(err); throw err }
  }
  const read = (type, ids) => run(() => {
    const rows = store.authGet(lease, type, ids)
    return Object.fromEntries(ids.map(id => {
      const row = rows[id]
      revisions.set(`${type}:${id}`, row?.revision || 0)
      let value = row?.value || null
      if (type === 'app-state-sync-key' && value) value = proto.Message.AppStateSyncKeyData.fromObject(value)
      return [id, value]
    }))
  })
  const write = updates => run(() => {
    const expected = {}
    for (const [type, entries] of Object.entries(updates)) for (const id of Object.keys(entries)) {
      const key = `${type}:${id}`
      expected[key] = revisions.get(key) ?? store.authGet(lease, type, [id])[id]?.revision ?? 0
    }
    for (const [key, revision] of Object.entries(store.authSet(lease, updates, expected))) revisions.set(key, revision)
  })
  const creds = read('creds', ['current']).current || initAuthCreds()
  // Persist initial identity before creating the socket, never silently regenerate a corrupt store.
  if (!revisions.get('creds:current')) write({ creds: { current: creds } })
  return {
    state: { creds, keys: { get: async (type, ids) => read(type, ids), set: async updates => write(updates) } },
    saveCreds: update => { Object.assign(creds, update); write({ creds: { current: creds } }) },
  }
}
