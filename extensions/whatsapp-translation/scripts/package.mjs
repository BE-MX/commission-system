import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { isAbsolute, join, relative, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { zipSync } from 'fflate'

const EXTENSION_ID = 'bnkecbkoidckffckbefjjcbchmngjobi'
const FIXED_TIME = new Date('1980-01-01T00:00:00Z')
const REQUIRED_DIST_ENTRIES = ['assets', 'background.js', 'content.js', 'manifest.json', 'src/popup/index.html']
const ALLOWED_DIST_ROOTS = new Set(['assets', 'background.js', 'content.js', 'manifest.json', 'popup.js', 'src'])
const TEXT_PACKAGE_FILE = /\.(?:css|html|js|json)$/i

function collect(directory, prefix = '', output = {}) {
  for (const entry of readdirSync(directory).sort()) {
    const path = join(directory, entry)
    const key = prefix ? `${prefix}/${entry}` : entry
    if (statSync(path).isDirectory()) {
      collect(path, key, output)
    } else {
      const content = readFileSync(path)
      if (TEXT_PACKAGE_FILE.test(key)) {
        let normalized = content.toString('utf8').replace(/\r\n?/g, '\n')
        if (key.endsWith('.html')) normalized = normalized.replace(/^[\t ]*\n/gm, '')
        output[key] = Buffer.from(normalized, 'utf8')
      } else {
        output[key] = content
      }
    }
  }
  return output
}

export function assertSafeOutputPath(outputDir, repositoryRoot = resolve(import.meta.dirname, '../../..')) {
  const resolvedOutput = resolve(outputDir)
  const resolvedRoot = resolve(repositoryRoot)
  const relativePath = relative(resolvedRoot, resolvedOutput)
  const normalizedRelativePath = relativePath.replaceAll('\\', '/')
  const allowed = normalizedRelativePath === 'extensions/whatsapp-translation/release'
    || normalizedRelativePath === 'frontend/public/downloads/whatsapp-translation'
  if (!isAbsolute(resolvedOutput) || !allowed || isAbsolute(relativePath) || relativePath.startsWith('..') || resolve(resolvedRoot, relativePath) !== resolvedOutput) {
    throw new Error('unsafe_output_path')
  }
}

export function packageRelease({
  distDir = 'dist',
  outputDir = 'release',
  manifestPath = 'manifest.json',
  repositoryRoot = resolve(import.meta.dirname, '../../..'),
} = {}) {
  assertSafeOutputPath(outputDir, repositoryRoot)

  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  if (!/^\d+\.\d+\.\d+$/.test(manifest.version) || manifest.manifest_version !== 3) throw new Error('invalid_manifest')
  if (!existsSync(distDir)) throw new Error('invalid_dist')

  const distEntries = readdirSync(distDir)
  for (const required of REQUIRED_DIST_ENTRIES) {
    if (!distEntries.includes(required.split('/')[0])) throw new Error('invalid_dist')
  }

  const files = collect(distDir)
  for (const file of Object.keys(files)) {
    const root = file.split('/', 1)[0]
    const reviewed = (
      root === 'assets' && (file.endsWith('.css') || /^assets\/icon-(16|32|48|128)\.png$/.test(file))
    ) || root === 'background.js' || root === 'content.js' || root === 'manifest.json' || root === 'popup.js' || file === 'src/popup/index.html'
    if (!ALLOWED_DIST_ROOTS.has(root) || !reviewed) {
      throw new Error(`forbidden_package_file:${file}`)
    }
  }

  const filename = `whatsapp-translation-${manifest.version}.zip`
  const zip = zipSync(files, { mtime: FIXED_TIME })
  const sha256 = createHash('sha256').update(zip).digest('hex')
  const release = {
    extension_id: EXTENSION_ID,
    filename,
    sha256,
    size: zip.byteLength,
    version: manifest.version,
  }

  rmSync(outputDir, { recursive: true, force: true })
  mkdirSync(outputDir, { recursive: true })
  writeFileSync(join(outputDir, filename), zip)
  writeFileSync(join(outputDir, 'latest.json'), `${JSON.stringify(release)}\n`)
  return release
}

function run() {
  const outputIndex = process.argv.indexOf('--output')
  if (outputIndex !== -1) {
    const value = process.argv[outputIndex + 1]
    if (!isAbsolute(value)) throw new Error('--output must be an absolute path')
    packageRelease({ outputDir: value })
    return
  }
  packageRelease()
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) run()
