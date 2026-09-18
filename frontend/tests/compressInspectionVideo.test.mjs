import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../src/views/shipping/composables/compressInspectionVideo.js', import.meta.url), 'utf8').replaceAll('export ', '')
const flush = () => new Promise(resolve => setImmediate(resolve))

function setup({ closeHangs = false, stalled = false, playDenied = false } = {}) {
  const timeouts = new Map(), intervals = new Map(), events = new Map()
  let nextId = 0, now = 0, loaded = false, currentTime = 0, recorder
  const stats = { plays: 0, stopped: 0, revoked: 0, disconnected: 0 }
  const track = { stop() { stats.stopped++ } }
  const stream = { getTracks: () => [track], addTrack() {} }
  const video = {
    duration: 5, videoWidth: 1920, videoHeight: 1080, seeking: false,
    get currentTime() { return currentTime },
    set currentTime(value) { currentTime = value; queueMicrotask(() => video.onseeked?.()) },
    play() {
      stats.plays++
      if (playDenied) return Promise.reject(new Error('NotAllowedError'))
      if (!loaded) { loaded = true; queueMicrotask(() => video.onloadeddata?.()) }
      else if (!stalled) queueMicrotask(() => { currentTime = 5; video.onended?.() })
      return Promise.resolve()
    },
    pause() {}, removeAttribute() {}, load() {},
  }
  class AudioContext {
    state = 'running'
    resume() { return Promise.resolve() }
    close() { return closeHangs ? new Promise(() => {}) : Promise.resolve() }
    createMediaElementSource() { return { connect() {}, disconnect() { stats.disconnected++ } } }
    createMediaStreamDestination() { return { stream: { getAudioTracks: () => [track], getTracks: () => [track] }, disconnect() {} } }
  }
  class MediaRecorder {
    static isTypeSupported() { return true }
    state = 'inactive'
    constructor() { recorder = this }
    start() { this.state = 'recording' }
    stop() {
      this.state = 'inactive'
      this.ondataavailable?.({ data: new Blob(['encoded']) })
      this.onstop?.()
    }
  }
  const context = vm.createContext({
    AudioContext, MediaRecorder, Blob, File, console,
    Date: { now: () => now },
    document: {
      hidden: false,
      createElement: tag => tag === 'video' ? video : { captureStream: () => stream, getContext: () => ({ drawImage() {} }) },
      addEventListener: (name, fn) => events.set(name, fn), removeEventListener: name => events.delete(name),
    },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() { stats.revoked++ } },
    setTimeout: (fn, ms) => { const id = ++nextId; timeouts.set(id, { fn, ms }); return id },
    clearTimeout: id => timeouts.delete(id),
    setInterval: fn => { const id = ++nextId; intervals.set(id, fn); return id },
    clearInterval: id => intervals.delete(id),
  })
  vm.runInContext(source + '\nthis.compress = compressInspectionVideo', context)
  const file = new File(['original video content'], 'capture.mov', { type: 'video/quicktime' })
  return { context, video, stats, timeouts, intervals, events, file, advance: ms => { now += ms }, get recorder() { return recorder } }
}

test('starts playback before waiting for decoded data (Safari may not preload it)', async () => {
  const h = setup()
  const task = h.context.compress(h.file)
  assert.equal(h.stats.plays, 1, 'play must be requested in the original input/click event')
  const result = await task
  assert.equal(result.type, 'video/mp4')
  assert.equal(await result.text(), 'encoded')
  assert.equal(h.stats.revoked, 1)
  assert.equal(h.timeouts.size, 0)
  assert.equal(h.intervals.size, 0)
})

test('a pending AudioContext.close cannot hide an error or prevent cleanup', async () => {
  const h = setup({ closeHangs: true, playDenied: true })
  let error
  const task = h.context.compress(h.file).catch(e => { error = e })
  await flush()
  // Also exercise the old loading-timeout path without waiting 15 seconds.
  for (const timer of [...h.timeouts.values()]) timer.fn()
  await flush()
  assert.ok(error, 'compression must settle even if close never settles')
  assert.equal(h.stats.revoked, 1)
  assert.equal(h.events.size, 0)
  assert.equal(h.stats.stopped, 1, 'stop the audio track even before captureStream exists')
  await task
})

test('stalled playback exits promptly instead of waiting for the full video timeout', async () => {
  const h = setup({ stalled: true })
  let error
  const task = h.context.compress(h.file).catch(e => { error = e })
  await flush()
  assert.equal(h.recorder?.state, 'recording')
  h.advance(11000)
  for (const tick of [...h.intervals.values()]) tick()
  await flush()
  assert.match(error?.message || '', /停滞/)
  assert.equal(h.intervals.size, 0)
  assert.equal(h.stats.stopped, 1)
  await task
})

test('aborting compression releases recorder, tracks and listeners', async () => {
  const h = setup({ stalled: true }), controller = new AbortController()
  const task = h.context.compress(h.file, { signal: controller.signal })
  await flush()
  controller.abort()
  await assert.rejects(task, /取消/)
  assert.equal(h.stats.revoked, 1)
  assert.equal(h.intervals.size, 0)
  assert.equal(h.events.size, 0)
})
