import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { zipSync } from 'fflate'

function collect(directory, prefix = '', output = {}) {
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry)
    const key = prefix ? `${prefix}/${entry}` : entry
    if (statSync(path).isDirectory()) {
      collect(path, key, output)
    } else {
      output[key] = readFileSync(path)
    }
  }
  return output
}

mkdirSync('release', { recursive: true })
writeFileSync('release/whatsapp-translation-v1.0.0.zip', zipSync(collect('dist')))
