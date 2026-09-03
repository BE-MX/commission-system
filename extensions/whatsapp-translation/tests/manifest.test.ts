import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const manifest = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'))
const alphabet = 'abcdefghijklmnop'

function extensionId(publicKey: string): string {
  const digest = createHash('sha256').update(Buffer.from(publicKey, 'base64')).digest().subarray(0, 16)
  return [...digest].map(byte => alphabet[byte >> 4] + alphabet[byte & 15]).join('')
}

describe('manifest privacy boundary', () => {
  it('has the approved stable identity and minimum permissions', () => {
    expect(manifest.manifest_version).toBe(3)
    expect(extensionId(manifest.key)).toBe('bnkecbkoidckffckbefjjcbchmngjobi')
    expect(manifest.permissions).toEqual(['storage'])
    expect(manifest.host_permissions).toEqual([
      'https://leshine.work/*',
    ])
    expect(manifest.content_scripts[0].matches).toEqual(['https://web.whatsapp.com/*'])
  })

  it('does not request surveillance or sending capabilities', () => {
    expect(JSON.stringify(manifest)).not.toMatch(/all_urls|cookies|history|webRequest|declarativeNetRequest|clipboard|tabs/)
  })
})
