import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { paintWorldMap } from '../src/components/worldMapPainter.js'

const source = readFileSync(new URL('../src/components/WorldMapCanvas.vue', import.meta.url), 'utf8')
const landContours = JSON.parse(readFileSync(new URL('../src/assets/world-land.json', import.meta.url), 'utf8'))
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')

// A 2D context that accepts every canvas call and remembers the ones the tests read back.
function fakeContext() {
  const seen = { clears: 0, arcs: [], texts: [], rects: [], sources: [] }
  const api = {
    clearRect() { seen.clears++; seen.arcs = [] },
    arc(...args) { seen.arcs.push(args) },
    fillText(...args) { seen.texts.push(args) },
    rect(...args) { seen.rects.push(args) },
    drawImage(image) { seen.sources.push(image) },
    createRadialGradient: () => ({ addColorStop() {} }),
    createLinearGradient: () => ({ addColorStop() {} }),
    createPattern: () => ({}),
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
    measureText: () => ({ width: 24 }),
  }
  return new Proxy(api, {
    get: (target, key) => key in seen ? seen[key] : key in target ? target[key] : () => {},
    set: (target, key, value) => { target[key] = value; return true },
  })
}

function fakeCanvas(extra = {}) {
  const context = fakeContext()
  return { width: 0, height: 0, style: {}, getContext: () => context, context, ...extra }
}

function listeners() {
  return { handlers: new Map(),
    addEventListener(type, cb) { this.handlers.set(cb, type) },
    removeEventListener(_, cb) { this.handlers.delete(cb) },
    emit(type, event) { for (const [cb, name] of [...this.handlers]) if (name === type) cb(event) },
  }
}

// The painter builds its off-screen layers through the global document.
globalThis.document = { createElement: () => fakeCanvas() }

function mountMap({ reduced = false, compact = false, hidden = false, fine = true, avoid = null } = {}) {
  const bounds = { left: 0, top: 0, width: 720, height: 300 }
  const root = { style: {}, getBoundingClientRect: () => bounds }
  const surfaces = [0, 1].map(() => fakeCanvas({ parentElement: root, getBoundingClientRect: () => bounds }))
  const media = matches => ({ ...listeners(), matches, change(value) { this.matches = value; this.emit('change') } })
  const reducedMedia = media(reduced), compactMedia = media(compact), fineMedia = media(fine)
  const created = []
  const document = { ...listeners(), hidden, documentElement: listeners(),
    createElement: () => { created.push(fakeCanvas()); return created.at(-1) } }
  const window = { ...listeners(), devicePixelRatio: 3, innerWidth: 1600, innerHeight: 900, scrollX: 0, scrollY: 0,
    matchMedia: query => query.includes('reduced') ? reducedMedia : query.includes('max-width') ? compactMedia : fineMedia }
  let refIndex = 0, nextId = 0, mounted, unmounted, resize, disconnected = false
  const frames = new Map()
  vm.runInNewContext(script, {
    landContours, paintWorldMap,
    ref: () => ({ value: surfaces[refIndex++] }),
    defineProps: () => ({ avoid }),
    onMounted: cb => { mounted = cb }, onUnmounted: cb => { unmounted = cb },
    window, document,
    getComputedStyle: () => ({ getPropertyValue: name => name === '--login-gold' ? '#d4af6e' : '#f2dfb0' }),
    requestAnimationFrame: cb => { frames.set(++nextId, cb); return nextId },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: cb => { cb(); return 1 }, clearTimeout() {},
    ResizeObserver: class {
      constructor(cb) { resize = cb }
      observe() {}
      disconnect() { disconnected = true }
    },
  })
  mounted()
  let clock = 0
  const tick = time => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(cb => cb(time)) }
  return { contexts: surfaces.map(surface => surface.context), surfaces, root, frames, reducedMedia, compactMedia, document, window, bounds, resize, tick,
    // The component's own off-screen canvases, in creation order: coast glow, light scratch, glow sprite.
    scratch: created[1],
    // Advance the clock in display frames of `each` ms up to `time`.
    runTo(time, each = 10) { for (; clock <= time; clock += each) tick(clock) },
    veil() {
      const { maskImage: value, webkitMaskImage: prefixed } = surfaces[0].style
      assert.equal(prefixed, value, 'older Chromium only reads the prefixed property')
      return value ? Number(value.match(/transparent ([\d.]+)px/)[1]) : null
    },
    unmount() { unmounted(); assert.ok(disconnected) },
  }
}

const originOf = scene => scene.contexts[0].arcs.find(arc => arc[2] === 4.5)
const beaconRings = (scene, core) => scene.contexts[1].arcs.filter(arc => arc[0] === core[0] && arc[1] === core[1] && arc[2] > 10 && arc[2] <= 38)

test('the still map is painted once while everything on top of it animates; DPR is capped', () => {
  const scene = mountMap()
  const paints = scene.contexts[0].clears
  scene.runTo(5000)
  assert.equal(scene.contexts[0].clears, paints)
  assert.ok(scene.contexts[1].clears > 100)
  assert.equal(scene.surfaces[0].width, 1440)
  scene.unmount()
})

test('the opening wave uncovers the map from Qingdao, then removes its veil', () => {
  const scene = mountMap()
  assert.equal(scene.veil(), 0, 'the finished map never flashes before the opening')
  scene.runTo(400)
  const early = scene.veil()
  scene.runTo(1200)
  assert.ok(early > 0 && scene.veil() > early)
  scene.runTo(2100)
  assert.equal(scene.veil(), null)
  scene.unmount()
})

test('reduced motion and compact screens show the whole map at once and run no loop', () => {
  for (const options of [{ reduced: true }, { compact: true }]) {
    const scene = mountMap(options)
    assert.equal(scene.frames.size, 0)
    assert.equal(scene.veil(), null)
    assert.ok(originOf(scene), 'static map remains visible')
    // Turning motion back on later goes straight to the ambient loop, without replaying the opening.
    scene.reducedMedia.change(false)
    scene.compactMedia.change(false)
    assert.equal(scene.frames.size, 1)
    assert.equal(scene.veil(), null)
    scene.unmount()
  }
})

test('a tab opened in the background waits, and plays the opening once it is seen', () => {
  const scene = mountMap({ hidden: true })
  assert.equal(scene.frames.size, 0)
  assert.equal(scene.veil(), 0)
  scene.document.hidden = false
  scene.document.emit('visibilitychange')
  assert.equal(scene.frames.size, 1)
  scene.runTo(2100)
  assert.equal(scene.veil(), null)
  scene.unmount()
})

test('live preference changes and visibility pause and resume one loop; unmount cleans up', () => {
  const scene = mountMap()
  scene.reducedMedia.change(true)
  assert.equal(scene.frames.size, 0)
  scene.reducedMedia.change(false)
  assert.equal(scene.frames.size, 1)
  scene.compactMedia.change(true)
  assert.equal(scene.frames.size, 0)
  scene.compactMedia.change(false)
  scene.document.hidden = true
  scene.document.emit('visibilitychange')
  assert.equal(scene.frames.size, 0)
  scene.document.hidden = false
  scene.document.emit('visibilitychange')
  assert.equal(scene.frames.size, 1)
  scene.unmount()
  assert.equal(scene.frames.size, 0)
  const left = [scene.document, scene.document.documentElement, scene.window, scene.reducedMedia, scene.compactMedia]
  assert.equal(left.reduce((sum, target) => sum + target.handlers.size, 0), 0)
})

test('the loop idles at 30fps and follows the display during the opening and under the pointer', () => {
  const scene = mountMap()
  const during = (from, to) => { scene.runTo(from); const before = scene.contexts[1].clears; scene.runTo(to); return scene.contexts[1].clears - before }
  assert.ok(during(0, 1000) >= 45, 'opening is not throttled')
  const idle = during(4000, 5000)
  assert.ok(idle >= 28 && idle <= 36, `idle frames per second: ${idle}`)
  scene.window.emit('pointermove', { clientX: 300, clientY: 150, pointerType: 'mouse' })
  assert.ok(during(5010, 5400) >= 18, 'pointer movement lifts the cap')
  const resting = during(8000, 9000)
  assert.ok(resting >= 28 && resting <= 36, `a pointer resting on the map goes back to idle: ${resting}`)
  scene.unmount()
})

test('route positions depend on elapsed time instead of refresh rate', () => {
  // 16 ms and 25 ms displays share no frame times before 1200 ms, so only elapsed time can make them agree.
  const scenes = [mountMap(), mountMap()]
  for (let time = 0; time <= 1200; time += 16) scenes[0].tick(time)
  for (let time = 0; time <= 1200; time += 25) scenes[1].tick(time)
  assert.ok(scenes[0].contexts[1].arcs.length > 3)
  assert.deepEqual(scenes[0].contexts[1].arcs, scenes[1].contexts[1].arcs)
  scenes.forEach(scene => scene.unmount())
})

test('moving lights are composited from the coast glow, each inside its own box', () => {
  const scene = mountMap()
  scene.runTo(600)
  assert.ok(scene.contexts[1].sources.includes(scene.scratch), 'the opening wave lights the coast it passes')
  scene.runTo(5200)
  const before = scene.scratch.context.rects.length
  scene.window.emit('pointermove', { clientX: 300, clientY: 150, pointerType: 'mouse' })
  scene.runTo(5400)
  const boxes = scene.scratch.context.rects.slice(before).filter(([left, top]) => left === 130 && top === 0)
  assert.ok(boxes.length > 0, 'the pointer light is clipped to its 170px radius, not the whole canvas')
  assert.ok(boxes.every(([, , width, height]) => width === 340 && height === 300))
  scene.unmount()
})

test('a machine that cannot keep up skips the rest of the opening and stays on the cheap path', () => {
  const scene = mountMap()
  scene.runTo(1000, 60)
  assert.equal(scene.veil(), null, 'the map is shown at once instead of crawling open')
  scene.window.emit('pointermove', { clientX: 300, clientY: 150, pointerType: 'mouse' })
  const before = scene.contexts[1].clears
  scene.runTo(2000, 10)
  const frames = scene.contexts[1].clears - before
  assert.ok(frames <= 36, `locked to idle rate even under the pointer: ${frames}`)
  assert.equal(scene.root.style.transform, 'translate3d(0px, 0px, 0)')
  scene.unmount()
})

test('resize redraws the map and restarts only one animation loop', () => {
  const scene = mountMap()
  const paints = scene.contexts[0].clears
  // ResizeObserver reports once on observe(): same size, so nothing is repainted mid-opening.
  scene.resize()
  assert.equal(scene.contexts[0].clears, paints)
  scene.bounds.width = 500
  scene.resize()
  assert.equal(scene.contexts[0].clears, paints + 1)
  assert.equal(scene.surfaces[0].width, 1000)
  assert.equal(scene.frames.size, 1)
  scene.unmount()
})

test('Qingdao has a larger static beacon and expanding rings centered on the origin', () => {
  const scene = mountMap()
  const core = originOf(scene)
  assert.ok(core, 'origin core remains visible in the static layer')
  scene.runTo(5000)
  const rings = beaconRings(scene, core)
  assert.equal(rings.length, 2)
  scene.runTo(5100)
  assert.ok(beaconRings(scene, core).every((arc, index) => arc[2] > rings[index][2]))
  scene.reducedMedia.change(true)
  assert.equal(scene.contexts[1].arcs.length, 0)
  assert.ok(scene.contexts[0].arcs.includes(core))
  scene.unmount()
})

test('a comet that reaches its market leaves a ripple on that node', () => {
  const scene = mountMap()
  const markets = scene.contexts[0].arcs.filter(arc => arc[2] === 2)
  assert.equal(markets.length, 4)
  scene.runTo(1900)
  const ripples = scene.contexts[1].arcs.filter(arc => arc[2] > 3 && markets.some(node => node[0] === arc[0] && node[1] === arc[1]))
  assert.ok(ripples.length >= 1)
  scene.unmount()
})

test('the map slides against a mouse pointer and ignores touch and coarse pointers', () => {
  const rest = 'translate3d(0px, 0px, 0)'
  const moved = options => {
    const scene = mountMap(options.mount)
    scene.runTo(3300)
    scene.window.emit('pointermove', { clientX: 300, clientY: 150, pointerType: options.type })
    scene.runTo(3800)
    const transform = scene.root.style.transform
    scene.unmount()
    return transform
  }
  assert.notEqual(moved({ type: 'mouse' }), rest)
  assert.equal(moved({ type: 'touch' }), rest)
  assert.equal(moved({ type: 'mouse', mount: { fine: false } }), rest)
})

test('market labels move out of the way of the brand copy', () => {
  const paint = blocks => {
    const context = fakeContext()
    paintWorldMap(context, { land: landContours, width: 720, height: 300, dpr: 1, gold: '#d4af6e', light: '#f2dfb0', blocks })
    return Object.fromEntries(context.texts.map(([name, x, y]) => [name, { x, y }]))
  }
  const open = paint([])
  const spot = open['北美']
  const crowded = paint([{ left: spot.x - 30, right: spot.x + 30, top: spot.y - 14, bottom: spot.y + 6 }])
  assert.notDeepEqual(crowded['北美'], spot)
  assert.deepEqual(crowded['青岛'], open['青岛'])
  assert.equal(Object.keys(crowded).length, 5, 'every label is still drawn')
})

test('the map reads the copy position from layout and quiets itself behind it', () => {
  const open = mountMap()
  const spot = open.contexts[0].texts.find(([name]) => name === '北美')
  assert.equal(open.contexts[0].rects.length, 0, 'nothing is erased when no copy lies over the map')
  open.unmount()
  // A line of copy sitting on the default label position, caught mid-entrance: only its layout box counts.
  const line = { offsetLeft: spot[1] - 20, offsetTop: spot[2] - 12, offsetWidth: 40, offsetHeight: 14, offsetParent: null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 1, bottom: 1, width: 1, height: 1 }) }
  const scene = mountMap({ avoid: () => ({ children: [line] }) })
  const moved = scene.contexts[0].texts.find(([name]) => name === '北美')
  assert.notDeepEqual(moved.slice(1, 3), spot.slice(1, 3))
  assert.deepEqual(scene.contexts[0].rects, [[spot[1] - 30, spot[2] - 22, 60, 34]])
  scene.unmount()
})
