import { Store } from '../src/store.js'
const store = new Store(process.argv[2], { encryptionKey: process.argv[3] })
try {
  const lease = store.acquire('account_a', 'child-process', Number(process.argv[4]))
  store.authSet(lease, { session: { child: Buffer.from('synthetic-signal-key') } })
  process.send({ acquired: true, token: lease.token })
} catch (err) { process.send({ acquired: false, code: err.code }) }
setInterval(() => {}, 1000)
