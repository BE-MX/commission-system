// Exercise the exact candidate entrypoint without real account state or sockets.
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

let temporary
let runtime
try {
  const major = Number(process.versions.node.split('.')[0])
  const minor = Number(process.versions.node.split('.')[1])
  if (major < 22 || (major === 22 && minor < 13)) throw new Error('node_version_required')
  let input = ''
  for await (const chunk of process.stdin) input += chunk
  const { source, env } = JSON.parse(input)
  temporary = mkdtempSync(path.join(tmpdir(), 'ark-connector-preflight-'))
  const { main } = await import(pathToFileURL(path.join(source, 'src/server.js')).href)
  runtime = await main({ ...env, WHATSAPP_DATA_DIR: temporary, WHATSAPP_RESTORE_ON_START: 'false', PORT: '0' })
  await new Promise((resolve, reject) => { runtime.server.once('listening', resolve); runtime.server.once('error', reject) })
  console.log('connector configuration and isolated startup verified')
} catch {
  console.error('Connector candidate startup failed; inspect Node and protected configuration locally')
  process.exitCode = 1
} finally {
  if (runtime) {
    runtime.manager.shutdown()
    await new Promise(resolve => runtime.server.close(resolve))
    runtime.store.close()
  }
  if (temporary) rmSync(temporary, { recursive: true, force: true })
}
