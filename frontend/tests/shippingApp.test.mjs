import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const root = new URL('../public/shipping-app/', import.meta.url)
const source = fs.readFileSync(new URL('../standalone-apps.js', root), 'utf8')
function boot(path) {
  const nodes = [], events = {}
  const viewport = { content: 'width=device-width, initial-scale=1.0' }
  const document = {
    title: '莱莎方舟平台',
    querySelector: selector => selector.includes('viewport') ? viewport : nodes[0],
    querySelectorAll: () => [...nodes],
    createElement: tag => ({ tag, attrs: {}, setAttribute(key, value) { this.attrs[key] = value }, remove() { nodes.splice(nodes.indexOf(this), 1) } }),
    head: { appendChild: node => nodes.push(node) },
  }
  const window = { location: { href: 'https://leshine.cloud' + path }, addEventListener: (name, fn) => { events[name] = fn } }
  vm.runInNewContext(source, { document, window, URL })
  return { nodes, viewport, document, go(path) { window.location.href = 'https://leshine.cloud' + path; events['ark:route-ready']() } }
}
test('scan and dedicated login retain install metadata, unrelated routes do not inherit it', () => {
  const app = boot('/shipping/scan')
  assert.equal(app.nodes.length, 7)
  app.go('/login?redirect=%2Fshipping%2Fscan')
  assert.equal(app.nodes.length, 7)
  assert.equal(app.document.title, '莱莎出库检验')
  assert.equal(app.viewport.content.split('viewport-fit').length, 2)
  app.go('/inventory')
  assert.equal(app.nodes.length, 0)
  assert.equal(app.viewport.content, 'width=device-width, initial-scale=1.0')
  app.go('/shipping/scan')
  assert.equal(app.nodes.length, 7)
})
test('initial login supports installation; ordinary login and misleading redirects do not', () => {
  assert.equal(boot('/login?redirect=%2Fshipping%2Fscan').nodes.length, 7)
  assert.equal(boot('/login?redirect=%2Fshipping%2Fscan%3Fsource%3Dhome%23top').nodes.length, 7)
  for (const path of ['/login', '/shipping/scanner', '/login?redirect=https://evil.test/shipping/scan', '/expo/kiosk']) {
    assert.equal(boot(path).nodes.length, 0)
  }
})
test('manifest opens the scan page, covers login, and declares real PNG dimensions', () => {
  const manifest = JSON.parse(fs.readFileSync(new URL('manifest.webmanifest', root)))
  assert.equal(manifest.start_url, '/shipping/scan')
  assert.equal(manifest.id, '/shipping/scan')
  assert.equal(manifest.display, 'standalone')
  assert.ok('/login'.startsWith(manifest.scope))
  for (const size of [180, 192, 512]) {
    const png = fs.readFileSync(new URL(`icon-${size}.png`, root))
    assert.equal(png.readUInt32BE(16), size)
    assert.equal(png.readUInt32BE(20), size)
    if (size !== 180) assert.ok(manifest.icons.some(icon => icon.sizes === `${size}x${size}`))
  }
})


test('FX install metadata survives login and replaces shipping metadata on SPA transitions', () => {
  const app = boot('/fx-settlement')
  assert.equal(app.nodes.find(node => node.attrs.rel === 'manifest').attrs.href, '/fx-app/manifest.webmanifest')
  app.go('/login?redirect=%2Ffx-settlement%3Fsource%3Dhome')
  assert.equal(app.document.title, '结汇决策助手')
  assert.equal(app.nodes.length, 7)
  app.go('/shipping/scan')
  assert.equal(app.nodes.find(node => node.attrs.rel === 'manifest').attrs.href, '/shipping-app/manifest.webmanifest')
  app.go('/fx-settlement')
  assert.equal(app.nodes.find(node => node.attrs.rel === 'manifest').attrs.href, '/fx-app/manifest.webmanifest')
  app.go('/login')
  assert.equal(app.nodes.length, 0)
  assert.equal(app.viewport.content, 'width=device-width, initial-scale=1.0')
  for (const path of ['/fx-settlement-other', '/login?redirect=https://evil.test/fx-settlement', '/invoice/fx-settlement']) assert.equal(boot(path).nodes.length, 0)
})

test('FX manifest has its own identity and PNG icons', () => {
  const fxRoot = new URL('../public/fx-app/', import.meta.url)
  const manifest = JSON.parse(fs.readFileSync(new URL('manifest.webmanifest', fxRoot)))
  assert.equal(manifest.id, '/fx-settlement')
  assert.equal(manifest.start_url, '/fx-settlement')
  assert.equal(manifest.display, 'standalone')
  assert.equal(manifest.scope, '/')
  for (const size of [180, 192, 512]) {
    const png = fs.readFileSync(new URL(`icon-${size}.png`, fxRoot))
    assert.equal(png.readUInt32BE(16), size)
    assert.equal(png.readUInt32BE(20), size)
  }
})
