import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const SIZES = [16, 32, 48, 128]
const CHROME_PATHS = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean)

function findBrowser() {
  const browser = CHROME_PATHS.find(candidate => existsSync(candidate))
  if (!browser) throw new Error('chromium_browser_not_found: set CHROME_PATH')
  return browser
}

function compactSvg(source) {
  return source
    .replace(/\s*<g id="wordmark">[\s\S]*?<\/g>\s*/, '\n')
    .replace('<g id="icon-mark">', '<g id="icon-mark" transform="translate(-34 28) scale(1.14)">')
    .replace('y="324"', 'y="350"')
    .replace('font-size="113"', 'font-size="190"')
}

function renderDocument(svg, browserSize) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;width:${browserSize}px;height:${browserSize}px;overflow:hidden}svg{display:block;width:${browserSize}px;height:${browserSize}px}</style></head><body>${svg}</body></html>`
}

function assertPngDimensions(path, expectedSize) {
  const png = readFileSync(path)
  if (png.subarray(1, 4).toString() !== 'PNG') throw new Error(`invalid_png:${path}`)
  if (png.readUInt32BE(16) !== expectedSize || png.readUInt32BE(20) !== expectedSize) {
    throw new Error(`invalid_icon_dimensions:${path}`)
  }
}

export function renderIcons({ browserPath = findBrowser() } = {}) {
  const source = readFileSync(new URL('../assets/icon-master.svg', import.meta.url), 'utf8')
  const workDir = mkdtempSync(join(tmpdir(), 'leshine-icons-'))

  try {
    for (const size of SIZES) {
      const browserSize = size === 16 ? 256 : 512
      const htmlPath = join(workDir, `icon-${size}.html`)
      const outputPath = resolve(`assets/icon-${size}.png`)
      writeFileSync(htmlPath, renderDocument(size <= 32 ? compactSvg(source) : source, browserSize))
      execFileSync(browserPath, [
        '--headless=new',
        '--disable-gpu',
        '--hide-scrollbars',
        `--force-device-scale-factor=${size / browserSize}`,
        '--run-all-compositor-stages-before-draw',
        '--virtual-time-budget=500',
        `--window-size=${browserSize},${browserSize}`,
        `--user-data-dir=${join(workDir, `profile-${size}`)}`,
        `--screenshot=${outputPath}`,
        pathToFileURL(htmlPath).href,
      ], { stdio: 'ignore' })
      assertPngDimensions(outputPath, size)
    }
  } finally {
    rmSync(workDir, { recursive: true, force: true })
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) renderIcons()
