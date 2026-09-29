<template>
  <canvas ref="canvasRef" class="ark-wake" aria-hidden="true" />
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'

// The title is the ship: it holds still on screen while space streams past it to the left.
// `limit` is the element whose right edge the course line must not cross (the brand panel).
const props = defineProps({ anchor: { type: Object, default: null }, limit: { type: Object, default: null } })
const canvasRef = ref(null)

const SHIP_SPEED = 90 // px/s the scene flows past the ark
const EMIT_RATE = 70 // wake particles per second: fine dust inside the light tail, not the headline
const TRACK_SECONDS = 4.5
const DUST_COUNT = 26
const AHEAD = 220
// Nozzle rails as fractions of the glyph height: most particles ride one, which reads as filament streams.
const NOZZLES = [-0.26, -0.1, 0.04, 0.18, 0.3] // course line drawn ahead of the title

const rand = (min, max) => min + Math.random() * (max - min)
// Sum of three uniforms: cheap bell curve in [-1, 1] so the wake stays dense at its core.
const bell = () => (Math.random() + Math.random() + Math.random() - 1.5) / 1.5

function rgb(hex) {
  const value = parseInt(hex.replace('#', ''), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

let dispose = () => {}

function start(anchor, canvas, limit) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return () => {}
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  const compact = window.matchMedia('(max-width: 1023px)')
  const palette = getComputedStyle(canvas)
  const light = rgb(palette.getPropertyValue('--login-gold-light').trim())
  const gold = rgb(palette.getPropertyValue('--login-gold').trim())
  let width = 0, height = 0, dpr = 1, frame = 0, previous = null, clock = 0, emitDebt = 0, resizeTimer = 0
  let particles = [], track = [], dust = []

  const mix = t => light.map((channel, i) => Math.round(channel + (gold[i] - channel) * t))
  const color = (t, alpha) => `rgba(${mix(t).join(', ')}, ${alpha})`
  // Per-particle strokes pick from a fixed ramp and vary globalAlpha, so a frame allocates no strings or gradients.
  const ramp = Array.from({ length: 16 }, (_, i) => `rgb(${mix(i / 15).join(', ')})`)

  // Emitter at the trailing edge of the first glyph, in canvas coordinates; read live so the float carries it.
  function engine() {
    const box = canvas.getBoundingClientRect()
    const text = anchor.getBoundingClientRect()
    return { x: text.left - box.left + 4, y: text.top - box.top + text.height * 0.54, h: text.height, right: text.right - box.left }
  }

  // Distant dust only lives behind the ship, so it never scatters over the copy.
  function spawnDust(x, e) {
    return { x, y: e.y + bell() * height * 0.4, speed: rand(0.12, 0.5) * SHIP_SPEED, size: rand(0.5, 1.1), alpha: rand(0.12, 0.4) }
  }

  function seedDust(e) {
    dust = Array.from({ length: DUST_COUNT }, () => spawnDust(rand(0, e.x), e))
  }

  function step(dt, e) {
    clock += dt
    for (emitDebt += EMIT_RATE * dt; emitDebt >= 1; emitDebt--) {
      // World velocity starts backward and decays to rest, so on screen particles burst out then settle to ship speed.
      const rail = Math.random() < 0.7 ? NOZZLES[Math.floor(Math.random() * NOZZLES.length)] + bell() * 0.015 : bell() * 0.3
      particles.push({
        x: e.x + rand(-2, 3), y: e.y + rail * e.h, u: -rand(0.3, 1.2) * SHIP_SPEED, vy: rail * 26 + bell() * 5,
        age: 0, life: rand(1.6, 3), size: Math.random() < 0.04 ? rand(0.9, 1.2) : rand(0.3, 0.75), seed: rand(0, Math.PI * 2),
      })
    }
    const drag = Math.exp(-1.1 * dt)
    particles = particles.filter(p => {
      p.age += dt
      p.u *= drag
      p.vy = p.vy * drag + Math.sin(p.age * 2.2 + p.seed) * 9 * dt
      p.x += (p.u - SHIP_SPEED) * dt
      p.y += p.vy * dt
      return p.age < p.life && p.x > -20
    })
    track.push({ x: e.x, y: e.y, t: clock })
    while (track.length && clock - track[0].t > TRACK_SECONDS) track.shift()
    for (const d of dust) {
      d.x -= d.speed * dt
      if (d.x < -4) Object.assign(d, spawnDust(e.x - 12, e))
    }
  }

  function draw(e) {
    ctx.clearRect(0, 0, width, height)
    ctx.globalCompositeOperation = 'lighter'
    ctx.lineCap = 'round'
    const flow = (clock * SHIP_SPEED) % 36

    // Lane: two edges widening behind the ship plus a dashed course ahead, markers streaming backward.
    for (const side of [-1, 1]) {
      // Gentle flare: the lane opens slowly with distance, curving rather than splaying.
      const offset = x => side * (e.h * 0.62 + ((e.x - x) / e.x) ** 1.6 * e.h * 1.1)
      const edge = ctx.createLinearGradient(0, 0, e.x, 0)
      edge.addColorStop(0, color(1, 0))
      edge.addColorStop(1, color(1, 0.16))
      ctx.strokeStyle = edge
      ctx.lineWidth = 0.8
      ctx.beginPath()
      for (let x = e.x - 6; x > -8; x -= 8) ctx.lineTo(x, e.y + offset(x))
      ctx.stroke()
      ctx.lineWidth = 1.2
      for (let x = e.x - 18 - flow; x > 0; x -= 36) {
        ctx.strokeStyle = color(0.3, 0.3 * (x / e.x) ** 1.5)
        ctx.beginPath()
        ctx.moveTo(x, e.y + offset(x))
        ctx.lineTo(x - 7, e.y + offset(x - 7))
        ctx.stroke()
      }
    }
    const start = e.right + 18, end = Math.min(width - 8, e.right + AHEAD)
    ctx.lineWidth = 1
    for (let x = end - ((36 - flow) % 36); x > start; x -= 36) {
      const reach = (x - start) / (end - start)
      ctx.strokeStyle = color(0.2, 0.34 * Math.sin(Math.PI * reach) ** 0.8)
      ctx.beginPath()
      ctx.moveTo(x, e.y)
      ctx.lineTo(x - 10, e.y)
      ctx.stroke()
    }

    // Track: where the ark has actually been, receding at ship speed; the title's float leaves a gentle wave.
    if (track.length > 1) {
      const path = () => {
        ctx.beginPath()
        for (let i = track.length - 1; i >= 0; i--) {
          const p = track[i]
          const x = p.x - (clock - p.t) * SHIP_SPEED
          if (i === track.length - 1) ctx.moveTo(x, p.y)
          else ctx.lineTo(x, p.y)
        }
      }
      const tail = track[0].x - (clock - track[0].t) * SHIP_SPEED
      for (const [lineWidth, alpha, tone] of [[6, 0.05, 0.6], [2, 0.14, 0.3], [0.8, 0.42, 0]]) {
        const fade = ctx.createLinearGradient(tail, 0, e.x, 0)
        fade.addColorStop(0, color(tone, 0))
        fade.addColorStop(0.7, color(tone, alpha * 0.55))
        fade.addColorStop(1, color(tone, alpha))
        ctx.strokeStyle = fade
        ctx.lineWidth = lineWidth
        path()
        ctx.stroke()
      }
    }

    ctx.lineWidth = 1
    for (const d of dust) {
      ctx.strokeStyle = color(0.5, d.alpha * Math.max(0, Math.min(1, (e.x - d.x) / 40)))
      ctx.lineWidth = d.size
      ctx.beginPath()
      ctx.moveTo(d.x, d.y)
      ctx.lineTo(d.x + d.speed * 0.05, d.y)
      ctx.stroke()
    }

    // Light tail: the headline of the wake. Radial gradients stretched along the course, with the outer circle
    // pulled behind the engine, give an egg-shaped plume that is brightest at the ark and trails off backward.
    const reach = Math.max(e.x, e.h * 3)
    for (const [spread, alpha, stops] of [[0.5, 0.4, [[0, 0], [0.2, 0.25], [0.55, 0.8], [1, 1]]], [0.13, 0.55, [[0, 0], [0.4, 0.3], [1, 0.8]]]]) {
      const r = e.h * spread
      ctx.save()
      ctx.translate(e.x + 6, e.y)
      ctx.scale(reach / (r * 1.8), 1)
      const plume = ctx.createRadialGradient(0, 0, 0, -r * 0.9, 0, r)
      stops.forEach(([at, tone], i) => plume.addColorStop(at, color(tone, i === stops.length - 1 ? 0 : alpha * (1 - at) ** 1.3)))
      ctx.fillStyle = plume
      ctx.beginPath()
      ctx.arc(-r * 0.9, 0, r, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }

    // Wake dust: hair-thin streaks riding inside the tail, brighter at the head and tapering toward the engine.
    for (const p of particles) {
      const t = p.age / p.life
      const alpha = Math.min(1, t * 12) * (1 - t) ** 1.6 * 0.5
      const dx = -(p.u - SHIP_SPEED) * 0.05, dy = -p.vy * 0.05
      ctx.strokeStyle = ramp[Math.min(15, Math.round(t * 1.6 * 15))]
      ctx.lineWidth = p.size
      ctx.globalAlpha = alpha
      ctx.beginPath()
      ctx.moveTo(p.x, p.y)
      ctx.lineTo(p.x + dx, p.y + dy)
      ctx.stroke()
      ctx.globalAlpha = alpha * 0.35
      ctx.beginPath()
      ctx.moveTo(p.x + dx, p.y + dy)
      ctx.lineTo(p.x + dx * 2.2, p.y + dy * 2.2)
      ctx.stroke()
    }
    ctx.globalAlpha = 1

    // Engine glow, stretched along the course and flickering faintly.
    ctx.save()
    ctx.translate(e.x, e.y)
    ctx.scale(2.6, 1)
    const radius = e.h * 0.55
    const core = ctx.createRadialGradient(0, 0, 0, 0, 0, radius)
    core.addColorStop(0, color(0, 0.34 + Math.sin(clock * 9) * 0.03))
    core.addColorStop(0.4, color(0.6, 0.12))
    core.addColorStop(1, color(1, 0))
    ctx.fillStyle = core
    ctx.beginPath()
    ctx.arc(0, 0, radius, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()

    // Feather every edge so the wake dissolves into the map instead of ending in a box.
    ctx.globalCompositeOperation = 'destination-in'
    const across = ctx.createLinearGradient(0, 0, width, 0)
    across.addColorStop(0, 'rgba(0, 0, 0, 0)')
    across.addColorStop(Math.min(0.9, e.x * 0.4 / width), 'rgba(0, 0, 0, 1)')
    across.addColorStop(Math.max(0.1, (width - 60) / width), 'rgba(0, 0, 0, 1)')
    across.addColorStop(1, 'rgba(0, 0, 0, 0)')
    ctx.fillStyle = across
    ctx.fillRect(0, 0, width, height)
    const vertical = ctx.createLinearGradient(0, 0, 0, height)
    vertical.addColorStop(0, 'rgba(0, 0, 0, 0)')
    vertical.addColorStop(0.3, 'rgba(0, 0, 0, 1)')
    vertical.addColorStop(0.7, 'rgba(0, 0, 0, 1)')
    vertical.addColorStop(1, 'rgba(0, 0, 0, 0)')
    ctx.fillStyle = vertical
    ctx.fillRect(0, 0, width, height)
    ctx.globalCompositeOperation = 'source-over'
  }

  function animate(time) {
    frame = requestAnimationFrame(animate)
    if (previous === null) previous = time
    const delta = time - previous
    // Slack under 1000/30 so 60/120 Hz frames land on an even cadence instead of occasionally skipping one.
    if (delta < 1000 / 30 - 4) return
    previous = time
    const e = engine()
    step(Math.min(delta, 100) / 1000, e)
    draw(e)
  }

  // Run the simulation ahead so the wake is already full on the first frame (and for the reduced-motion still).
  function prewarm() {
    particles = []
    track = []
    clock = 0
    const e = engine()
    seedDust(e)
    for (let i = 0; i < 90; i++) step(1 / 30, e)
    draw(e)
  }

  function sync() {
    cancelAnimationFrame(frame)
    frame = 0
    previous = null
    if (!document.hidden && !reduced.matches && !compact.matches && width > 0) frame = requestAnimationFrame(animate)
  }

  // Layout position (offset chain) ignores transforms, so the entrance slide and the float don't skew the band.
  function box(el) {
    let x = 0, y = 0
    for (let node = el; node && node !== canvas.parentElement; node = node.offsetParent) {
      x += node.offsetLeft
      y += node.offsetTop
    }
    return { x, y, w: el.offsetWidth, h: el.offsetHeight }
  }

  function layout() {
    const text = box(anchor)
    if (compact.matches || !text.w) {
      width = 0
      canvas.hidden = true
      sync()
      return
    }
    const bound = limit ? box(limit) : null
    const nextWidth = Math.round(Math.min(text.x + text.w + AHEAD, bound ? bound.x + bound.w - 8 : Infinity))
    const nextHeight = Math.round(Math.max(300, text.h * 4.6))
    canvas.style.top = `${Math.round(text.y + text.h / 2 - nextHeight / 2)}px`
    const sameSize = !canvas.hidden && nextWidth === width && nextHeight === height
    canvas.hidden = false
    // Height-only page changes (and the observer's initial report) keep the running wake instead of resetting it.
    if (!sameSize) {
      width = nextWidth
      height = nextHeight
      Object.assign(canvas.style, { width: `${width}px`, height: `${height}px` })
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      prewarm()
    }
    sync()
  }

  const observer = new ResizeObserver(() => {
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(layout, 120)
  })
  observer.observe(canvas.parentElement)
  reduced.addEventListener('change', sync)
  compact.addEventListener('change', layout)
  document.addEventListener('visibilitychange', sync)
  layout()
  return () => {
    cancelAnimationFrame(frame)
    clearTimeout(resizeTimer)
    observer.disconnect()
    reduced.removeEventListener('change', sync)
    compact.removeEventListener('change', layout)
    document.removeEventListener('visibilitychange', sync)
  }
}

// The anchor ref is filled in by the parent after its own render, so start once both elements exist.
watch([() => props.anchor, () => props.limit, canvasRef], ([anchor, limit, canvas]) => {
  dispose()
  dispose = anchor && canvas ? start(anchor, canvas, limit) : () => {}
}, { flush: 'post' })
onUnmounted(() => dispose())
</script>

<style scoped>
.ark-wake {
  position: absolute; left: 0; pointer-events: none; mix-blend-mode: screen;
  animation: ark-wake-in 600ms cubic-bezier(0.23, 1, 0.32, 1) both;
}
@keyframes ark-wake-in { from { opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .ark-wake { animation: none; }
}
</style>
