import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/WorldMapCanvas.vue', import.meta.url), 'utf8')
const landContours = JSON.parse(readFileSync(new URL('../src/assets/world-land.json', import.meta.url), 'utf8'))
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')

function mountMap({ reduced = false, compact = false, hidden = false } = {}) {
  const contexts = [0, 1].map(() => ({
    clears: 0, arcs: [],
    clearRect() { this.clears++; this.arcs = [] },
    arc(...args) { this.arcs.push(args) },
    setTransform() {}, beginPath() {}, fill() {}, moveTo() {}, lineTo() {}, closePath() {},
    createRadialGradient() { return { addColorStop() {} } },
    quadraticCurveTo() {}, stroke() {}, fillText() {},
  }))
  const bounds = { width: 720, height: 300 }
  const surfaces = contexts.map(context => ({
    parentElement: { getBoundingClientRect: () => bounds },
    getContext: () => context,
  }))
  function media(matches) {
    return { matches, handlers: new Set(),
      addEventListener(_, cb) { this.handlers.add(cb) },
      removeEventListener(_, cb) { this.handlers.delete(cb) },
      change(value) { this.matches = value; this.handlers.forEach(cb => cb()) },
    }
  }
  const reducedMedia = media(reduced), compactMedia = media(compact)
  const document = { ...media(false), hidden }
  let refIndex = 0, nextId = 0, mounted, unmounted, resize, disconnected = false
  const frames = new Map()
  vm.runInNewContext(script, {
    landContours,
    ref: () => ({ value: surfaces[refIndex++] }),
    onMounted: cb => { mounted = cb }, onUnmounted: cb => { unmounted = cb },
    window: { devicePixelRatio: 3, matchMedia: query => query.includes('reduced') ? reducedMedia : compactMedia },
    document,
    getComputedStyle: () => ({ getPropertyValue: name => name === '--login-gold' ? '#d4af6e' : '#f2dfb0' }),
    requestAnimationFrame: cb => { frames.set(++nextId, cb); return nextId },
    cancelAnimationFrame: id => frames.delete(id),
    ResizeObserver: class {
      constructor(cb) { resize = cb }
      observe() {}
      disconnect() { disconnected = true }
    },
  })
  mounted()
  return { contexts, surfaces, frames, reducedMedia, compactMedia, document, bounds, resize,
    tick(time) { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(cb => cb(time)) },
    unmount() { unmounted(); assert.ok(disconnected) },
  }
}

test('static geography is not repainted during animation; DPR is capped', () => {
  const scene = mountMap()
  const paints = scene.contexts[0].clears
  for (let time = 0; time <= 1000; time += 10) scene.tick(time)
  assert.equal(scene.contexts[0].clears, paints)
  assert.ok(scene.contexts[1].clears > 20 && scene.contexts[1].clears <= 31)
  assert.equal(scene.surfaces[0].width, 1440)
  scene.unmount()
})

test('reduced motion, compact screens and hidden tabs do not run an animation loop', () => {
  for (const options of [{ reduced: true }, { compact: true }, { hidden: true }]) {
    const scene = mountMap(options)
    assert.equal(scene.frames.size, 0)
    assert.ok(scene.contexts[0].arcs.length > 100, 'static map remains visible')
    scene.unmount()
  }
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
  scene.document.handlers.forEach(cb => cb())
  assert.equal(scene.frames.size, 0)
  scene.document.hidden = false
  scene.document.handlers.forEach(cb => cb())
  assert.equal(scene.frames.size, 1)
  scene.unmount()
  assert.equal(scene.frames.size, 0)
  assert.equal(scene.document.handlers.size + scene.reducedMedia.handlers.size + scene.compactMedia.handlers.size, 0)
})

test('route positions depend on elapsed time instead of refresh rate', () => {
  const scenes = [mountMap(), mountMap()]
  for (let time = 0; time <= 1200; time += 10) scenes[0].tick(time)
  for (let time = 0; time <= 1200; time += 20) scenes[1].tick(time)
  assert.deepEqual(scenes[0].contexts[1].arcs, scenes[1].contexts[1].arcs)
  scenes.forEach(scene => scene.unmount())
})

test('resize redraws the map and restarts only one animation loop', () => {
  const scene = mountMap()
  const paints = scene.contexts[0].clears
  scene.bounds.width = 500
  scene.resize()
  assert.equal(scene.contexts[0].clears, paints + 1)
  assert.equal(scene.surfaces[0].width, 1000)
  assert.equal(scene.frames.size, 1)
  scene.unmount()
})

test('Qingdao has a larger static beacon and expanding rings centered on the origin', () => {
  const scene = mountMap()
  const core = scene.contexts[0].arcs.find(arc => arc[2] === 4.5)
  assert.ok(core, 'origin core remains visible in the static layer')
  scene.tick(0)
  scene.tick(100)
  const rings = scene.contexts[1].arcs.filter(arc => arc[0] === core[0] && arc[1] === core[1] && arc[2] > 10)
  assert.equal(rings.length, 2)
  scene.tick(200)
  const nextRings = scene.contexts[1].arcs.filter(arc => arc[0] === core[0] && arc[1] === core[1] && arc[2] > 10)
  assert.ok(nextRings.every((arc, index) => arc[2] > rings[index][2]))
  scene.reducedMedia.change(true)
  assert.equal(scene.contexts[1].arcs.length, 0)
  assert.ok(scene.contexts[0].arcs.includes(core))
  scene.unmount()
})
