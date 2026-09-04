import { createHash } from 'node:crypto'
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { assertSafeOutputPath, packageRelease } from '../scripts/package.mjs'

const manifest = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'))
const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
const repositoryRoot = resolve(import.meta.dirname, '../../..')
const alphabet = 'abcdefghijklmnop'

function extensionId(publicKey: string): string {
  const digest = createHash('sha256').update(Buffer.from(publicKey, 'base64')).digest().subarray(0, 16)
  return [...digest].map(byte => alphabet[byte >> 4] + alphabet[byte & 15]).join('')
}

describe('manifest privacy boundary', () => {
  it('has the approved stable identity and minimum permissions', () => {
    expect(manifest.manifest_version).toBe(3)
    expect(manifest.version).toBe('1.2.0')
    expect(packageJson.version).toBe('1.2.0')
    expect(extensionId(manifest.key)).toBe('bnkecbkoidckffckbefjjcbchmngjobi')
    expect(manifest.permissions).toEqual(['storage'])
    expect(manifest.host_permissions).toEqual([
      'https://leshine.work/*',
    ])
    expect(manifest.content_scripts[0].matches).toEqual(['https://web.whatsapp.com/*'])
    expect(manifest.icons).toEqual({
      16: 'assets/icon-16.png',
      32: 'assets/icon-32.png',
      48: 'assets/icon-48.png',
      128: 'assets/icon-128.png',
    })
    expect(manifest.action.default_icon).toEqual(manifest.icons)
  })

  it('ships exact PNG icon sizes and LeShine theme colors', () => {
    for (const size of [16, 32, 48, 128]) {
      const image = readFileSync(new URL(`../assets/icon-${size}.png`, import.meta.url))
      expect(image.subarray(1, 4).toString()).toBe('PNG')
      expect(image.readUInt32BE(16)).toBe(size)
      expect(image.readUInt32BE(20)).toBe(size)
    }
    const styles = [
      readFileSync(new URL('../src/popup/popup.css', import.meta.url), 'utf8'),
      readFileSync(new URL('../src/content/render.ts', import.meta.url), 'utf8'),
      readFileSync(new URL('../src/content/toolbarView.ts', import.meta.url), 'utf8'),
    ].join('\n').toUpperCase()
    expect(styles).toContain('#FDD956')
    expect(styles).toContain('#080303')
    expect(styles).toContain('#25D366')
    expect(styles).toContain('#147A3D')
  })

  it('does not request surveillance or sending capabilities', () => {
    expect(JSON.stringify(manifest)).not.toMatch(/all_urls|cookies|history|webRequest|declarativeNetRequest|clipboard|tabs/)
  })
})

describe('release packaging', () => {
  it('creates a deterministic release with the exact manifest shape', () => {
    const firstRoot = mkdtempSync(join(tmpdir(), 'whatsapp-release-'))
    const secondRoot = mkdtempSync(join(tmpdir(), 'whatsapp-release-'))
    const crlfDist = join(secondRoot, 'dist-crlf')
    const outputDir = join(firstRoot, 'extensions', 'whatsapp-translation', 'release')
    const secondDir = join(secondRoot, 'extensions', 'whatsapp-translation', 'release')
    try {
      mkdirSync(outputDir, { recursive: true })
      mkdirSync(secondDir, { recursive: true })
      cpSync('dist', crlfDist, { recursive: true })
      const popupHtml = join(crlfDist, 'src', 'popup', 'index.html')
      writeFileSync(
        popupHtml,
        readFileSync(popupHtml, 'utf8')
          .replace('</title>', '</title>\n\n')
          .replace(/\r?\n/g, '\r\n'),
      )
      writeFileSync(join(outputDir, 'whatsapp-translation-stale.zip'), 'stale')
      const release = packageRelease({ distDir: 'dist', outputDir, repositoryRoot: firstRoot })
      const second = packageRelease({ distDir: crlfDist, outputDir: secondDir, repositoryRoot: secondRoot })

      expect(release).toEqual({
        extension_id: 'bnkecbkoidckffckbefjjcbchmngjobi',
        filename: 'whatsapp-translation-1.2.0.zip',
        sha256: expect.stringMatching(/^[0-9a-f]{64}$/),
        size: expect.any(Number),
        version: '1.2.0',
      })
      expect(release.size).toBeGreaterThan(0)
      expect(release.sha256).toBe(second.sha256)
      expect(readdirSync(outputDir).sort()).toEqual(['latest.json', release.filename])
    } finally {
      rmSync(firstRoot, { recursive: true, force: true })
      rmSync(secondRoot, { recursive: true, force: true })
    }
  })

  it('rejects a missing dist and unsafe output paths', () => {
    assertSafeOutputPath(resolve(repositoryRoot, 'frontend/public/downloads/whatsapp-translation'))
    expect(() => assertSafeOutputPath(repositoryRoot, repositoryRoot)).toThrow('unsafe_output_path')
    expect(() => assertSafeOutputPath(resolve(repositoryRoot, 'backend'), repositoryRoot)).toThrow('unsafe_output_path')
    expect(() => assertSafeOutputPath(resolve(repositoryRoot, '..', 'unsafe-output'))).toThrow('unsafe_output_path')
    expect(() => assertSafeOutputPath(tmpdir())).toThrow('unsafe_output_path')
    const missingRoot = mkdtempSync(join(tmpdir(), 'whatsapp-missing-'))
    expect(() => packageRelease({
      distDir: 'missing-dist',
      outputDir: join(missingRoot, 'extensions', 'whatsapp-translation', 'release'),
      repositoryRoot: missingRoot,
    }))
      .toThrow('invalid_dist')
    rmSync(missingRoot, { recursive: true, force: true })
    expect(() => packageRelease({
      distDir: 'dist',
      outputDir: resolve(repositoryRoot, '..', 'unsafe-output'),
      repositoryRoot,
    })).toThrow('unsafe_output_path')
  })

  it('allows only reviewed production files in the ZIP', () => {
    const taintedDist = mkdtempSync(join(tmpdir(), 'tainted-dist-'))
    const outputRoot = mkdtempSync(join(tmpdir(), 'whatsapp-release-'))
    const outputDir = join(outputRoot, 'extensions', 'whatsapp-translation', 'release')
    try {
      cpSync('dist', taintedDist, { recursive: true })
      writeFileSync(join(taintedDist, 'package-lock.json'), '{}')

      expect(() => packageRelease({ distDir: taintedDist, outputDir, repositoryRoot: outputRoot })).toThrow(
        'forbidden_package_file:package-lock.json',
      )
    } finally {
      rmSync(taintedDist, { recursive: true, force: true })
      rmSync(outputRoot, { recursive: true, force: true })
    }
  })
})
