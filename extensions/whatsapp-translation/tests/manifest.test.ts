import { createHash } from 'node:crypto'
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { assertSafeOutputPath, packageRelease } from '../scripts/package.mjs'

const manifest = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'))
const repositoryRoot = resolve(import.meta.dirname, '../../..')
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

describe('release packaging', () => {
  it('creates a deterministic release with the exact manifest shape', () => {
    const outputDir = mkdtempSync(join(tmpdir(), 'whatsapp-release-'))
    const secondDir = mkdtempSync(join(tmpdir(), 'whatsapp-release-'))
    try {
      writeFileSync(join(outputDir, 'whatsapp-translation-stale.zip'), 'stale')
      const release = packageRelease({ distDir: 'dist', outputDir, repositoryRoot: tmpdir() })
      const second = packageRelease({ distDir: 'dist', outputDir: secondDir, repositoryRoot: tmpdir() })

      expect(release).toEqual({
        extension_id: 'bnkecbkoidckffckbefjjcbchmngjobi',
        filename: 'whatsapp-translation-1.0.2.zip',
        sha256: expect.stringMatching(/^[0-9a-f]{64}$/),
        size: expect.any(Number),
        version: '1.0.2',
      })
      expect(release.size).toBeGreaterThan(0)
      expect(release.sha256).toBe(second.sha256)
      expect(readdirSync(outputDir).sort()).toEqual(['latest.json', release.filename])
    } finally {
      rmSync(outputDir, { recursive: true, force: true })
      rmSync(secondDir, { recursive: true, force: true })
    }
  })

  it('rejects a missing dist and unsafe output paths', () => {
    assertSafeOutputPath(resolve(repositoryRoot, 'frontend/public/downloads/whatsapp-translation'))
    expect(() => assertSafeOutputPath(resolve(repositoryRoot, '..', 'unsafe-output'))).toThrow('unsafe_output_path')
    expect(() => assertSafeOutputPath(tmpdir())).toThrow('unsafe_output_path')
    expect(() => packageRelease({ distDir: 'missing-dist', outputDir: tmpdir(), repositoryRoot: tmpdir() }))
      .toThrow('invalid_dist')
    expect(() => packageRelease({
      distDir: 'dist',
      outputDir: resolve(repositoryRoot, '..', 'unsafe-output'),
      repositoryRoot,
    })).toThrow('unsafe_output_path')
  })

  it('allows only reviewed production files in the ZIP', () => {
    const taintedDist = mkdtempSync(join(tmpdir(), 'tainted-dist-'))
    const outputDir = mkdtempSync(join(tmpdir(), 'whatsapp-release-'))
    try {
      cpSync('dist', taintedDist, { recursive: true })
      writeFileSync(join(taintedDist, 'package-lock.json'), '{}')

      expect(() => packageRelease({ distDir: taintedDist, outputDir, repositoryRoot: tmpdir() })).toThrow(
        'forbidden_package_file:package-lock.json',
      )
    } finally {
      rmSync(taintedDist, { recursive: true, force: true })
      rmSync(outputDir, { recursive: true, force: true })
    }
  })
})
