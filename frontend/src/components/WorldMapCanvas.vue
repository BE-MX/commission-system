<template>
  <div class="world-map" aria-hidden="true">
    <canvas ref="mapRef" />
    <canvas ref="motionRef" />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import landContours from '@/assets/world-land.json'
import { paintWorldMap } from './worldMapPainter'

// `avoid` returns the element whose children (the brand copy) must stay readable over the map.
const props = defineProps({ avoid: { type: Function, default: null } })
const mapRef = ref(null)
const motionRef = ref(null)
let dispose = () => {}

// Opening: a light wave leaves Qingdao and uncovers the map as it travels.
const INTRO = 1900
const LOOP_START = 3200
const FIRST_FLIGHT = [1500, 1250, 1000, 800]
// Afterwards each route keeps its own pace, so arrivals never fall into a metronome.
const FLIGHT = [5200, 4300, 3500, 3100]
const REST = [1700, 2300, 1500, 2600]
const WAVE_FIRST = 7000, WAVE_EVERY = 11000, WAVE_SPAN = 3600
const IDLE_FRAME = 1000 / 30 - 4, HOT_FRAME = 12


onMounted(() => {
  const canvas = mapRef.value
  const motion = motionRef.value
  const ctx = canvas.getContext('2d')
  const fx = motion.getContext('2d')
  if (!ctx || !fx) return
  const root = canvas.parentElement
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  const compact = window.matchMedia('(max-width: 1023px)')
  const fine = window.matchMedia('(hover: hover) and (pointer: fine)')
  const palette = getComputedStyle(canvas)
  const gold = palette.getPropertyValue('--login-gold').trim()
  const light = palette.getPropertyValue('--login-gold-light').trim()
  let width = 0, height = 0, dpr = 1, frame = 0, previous = null, elapsed = 0
  let routes = []
  let resizeTimer = 0
  let origin = { x: 0, y: 0 }
  // Coast glow at CSS-pixel resolution: every moving light is this one bitmap seen through a mask.
  const coast = document.createElement('canvas'), scratch = document.createElement('canvas')
  const coastCtx = coast.getContext('2d'), mask = scratch.getContext('2d')
  const spark = sprite()
  let unit = 1, reach = 1, veiled = false, hot = true
  // `lite` is the cheap path a slow machine falls back to: no opening, no pointer effects, 30fps.
  let sized = false, lite = false, probed = 0, probeTime = 0, slowFrames = 0
  let bounds = { left: 0, top: 0 }
  const pointer = { x: 0, y: 0, seen: false }
  const torch = { x: 0, y: 0, power: 0 }
  const shift = { x: 0, y: 0 }

  // Soft round glow reused for comet heads and flares, so a frame allocates no gradients for them.
  function sprite() {
    const surface = document.createElement('canvas')
    surface.width = surface.height = 64
    const context = surface.getContext('2d')
    const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32)
    gradient.addColorStop(0, light)
    gradient.addColorStop(0.16, tint(gold, 0.7))
    gradient.addColorStop(0.5, tint(gold, 0.16))
    gradient.addColorStop(1, tint(gold, 0))
    context.fillStyle = gradient
    context.fillRect(0, 0, 64, 64)
    return surface
  }

  // Same hue at a given alpha; fading to plain `transparent` would pass through grey.
  function tint(hex, alpha) {
    const value = parseInt(hex.slice(1), 16)
    return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`
  }

  function dot(context, x, y, radius) {
    context.beginPath()
    context.arc(x, y, radius, 0, Math.PI * 2)
    context.fill()
  }

  function sample(route, t) {
    const u = 1 - t
    return {
      x: u * u * origin.x + 2 * u * t * route.control.x + t * t * route.end.x,
      y: u * u * origin.y + 2 * u * t * route.control.y + t * t * route.end.y,
    }
  }

  // Where an element sits by layout alone (offset chain), in viewport coordinates: the copy's entrance
  // and the title's float are transforms, and labels must not be placed against a box caught mid-move.
  function layoutBox(element) {
    let left = 0, top = 0
    for (let node = element; node; node = node.offsetParent) {
      left += node.offsetLeft
      top += node.offsetTop
    }
    return { left: left - window.scrollX, top: top - window.scrollY, width: element.offsetWidth, height: element.offsetHeight }
  }

  // Rectangles of the brand copy in canvas coordinates, padded so labels keep a little air.
  function keepClear() {
    const target = props.avoid?.()
    if (!target || compact.matches) return []
    return Array.from(target.children, layoutBox)
      .filter(box => box.width > 0 && box.height > 0)
      .map(box => ({
        left: box.left - bounds.left - 10, top: box.top - bounds.top - 10,
        right: box.left + box.width - bounds.left + 10, bottom: box.top + box.height - bounds.top + 10,
      }))
  }

  // The static map hides behind a radial mask while the opening wave uncovers it; one inline style per frame.
  function reveal(radius) {
    const value = radius === null ? '' : `radial-gradient(circle at ${origin.x.toFixed(1)}px ${origin.y.toFixed(1)}px, black ${Math.max(0, radius - 100).toFixed(1)}px, transparent ${radius.toFixed(1)}px)`
    canvas.style.webkitMaskImage = value
    canvas.style.maskImage = value
    veiled = radius !== null
  }

  const opening = () => reach * (1 - (1 - Math.min(1, Math.max(0, (elapsed - 120) / INTRO))) ** 1.9)

  // Where a route's comet is: in flight (path position `t`) or `landed` that many ms ago.
  function flight(index) {
    const loopFrom = LOOP_START + index * 700
    if (elapsed < loopFrom) {
      const p = (elapsed - 200 - index * 110) / FIRST_FLIGHT[index]
      if (p < 0) return null
      return p < 1 ? { t: 1 - (1 - p) ** 2.4, glow: Math.min(1, p * 12), tail: 0.24 } : { landed: (p - 1) * FIRST_FLIGHT[index] }
    }
    const p = ((elapsed - loopFrom) % (FLIGHT[index] + REST[index])) / FLIGHT[index]
    return p < 1 ? { t: p * p * (3 - 2 * p), glow: Math.min(1, p * 10, (1 - p) * 14), tail: 0.2 } : { landed: (p - 1) * FLIGHT[index] }
  }

  // Tapered tail of short strokes behind a glowing head.
  function comet(route, state) {
    const head = sample(route, state.t)
    let from = head
    fx.strokeStyle = light
    for (let step = 1; step <= 14; step++) {
      const t = state.t - (step / 14) * state.tail
      if (t < 0) break
      const to = sample(route, t)
      const keep = 1 - step / 15
      fx.globalAlpha = state.glow * keep ** 1.5 * 0.9
      fx.lineWidth = 0.5 + keep * 2.1
      fx.beginPath()
      fx.moveTo(from.x, from.y)
      fx.lineTo(to.x, to.y)
      fx.stroke()
      from = to
    }
    fx.globalAlpha = state.glow * 0.9
    fx.drawImage(spark, head.x - 15, head.y - 15, 30, 30)
    fx.globalAlpha = state.glow
    dot(fx, head.x, head.y, 1.7)
  }

  function circle(x, y, radius, alpha, lineWidth) {
    fx.globalAlpha = alpha
    fx.lineWidth = lineWidth
    fx.beginPath()
    fx.arc(x, y, radius, 0, Math.PI * 2)
    fx.stroke()
  }

  function drawMotion() {
    fx.clearRect(0, 0, width, height)
    fx.fillStyle = light
    fx.strokeStyle = light
    // Lights are [x, y, inner radius, outer radius, peak position, strength]; coasts glow where they fall.
    const lights = []
    const wave = (radius, band, strength) => lights.push([origin.x, origin.y, Math.max(0, radius - band), radius + band * 0.3, 0.74, strength])

    if (elapsed < 120 + INTRO) {
      const radius = opening(), fade = 1 - radius / reach
      reveal(radius + 24)
      wave(radius, 170, 1)
      circle(origin.x, origin.y, radius, 0.18 * fade, 1)
    } else if (veiled) reveal(null)
    if (elapsed < 700) {
      // Ignition: Qingdao flares once before the wave leaves.
      const p = elapsed / 700, size = 40 + p * 170
      fx.globalAlpha = (1 - p) ** 2
      fx.drawImage(spark, origin.x - size / 2, origin.y - size / 2, size, size)
    }
    // Every so often the wave goes out again, quieter, so the map keeps breathing after the opening.
    const since = (elapsed - WAVE_FIRST) % WAVE_EVERY
    if (!lite && elapsed >= WAVE_FIRST && since < WAVE_SPAN) {
      const p = since / WAVE_SPAN, strength = Math.min(1, p * 8) * (1 - p) ** 1.2
      const radius = reach * (1 - (1 - p) ** 1.7)
      wave(radius, 130, 0.8 * strength)
      circle(origin.x, origin.y, radius, 0.14 * strength, 1)
    }

    routes.forEach((route, index) => {
      const state = flight(index)
      if (!state) return
      if (state.landed === undefined) return comet(route, state)
      const p = state.landed / 1400
      if (p >= 1) return
      // Arrival: a ripple on the node, a flash, and that market's coast swelling with light.
      const swell = p < 0.14 ? p / 0.14 : (1 - (p - 0.14) / 0.86) ** 1.6
      lights.push([route.end.x, route.end.y, 0, unit * 30, 0, 0.8 * swell])
      circle(route.end.x, route.end.y, 3 + p * 20, 0.6 * (1 - p) ** 2, 1)
      const size = 26 + p * 14
      fx.globalAlpha = 0.8 * (1 - p) ** 3
      fx.drawImage(spark, route.end.x - size / 2, route.end.y - size / 2, size, size)
    })

    // Two staggered rings keep Qingdao visibly active without a flashing beacon.
    const calm = Math.min(1, elapsed / 600)
    for (let ring = 0; ring < 2; ring++) {
      const phase = (elapsed / 3600 + ring * 0.5) % 1
      circle(origin.x, origin.y, 10 + phase * 28, 0.5 * (1 - phase) ** 2 * calm, 1.3)
    }
    fx.globalAlpha = 0.9
    dot(fx, origin.x, origin.y, 4.8 + Math.sin(elapsed / 1400) * 0.6)

    if (torch.power > 0.02) {
      // The pointer carries a light: coasts near it brighten, with a faint warm pool underneath.
      lights.push([torch.x, torch.y, 0, 170, 0, torch.power])
      fx.globalAlpha = 0.06 * torch.power
      fx.drawImage(spark, torch.x - 140, torch.y - 140, 280, 280)
    }

    // Each light is composited inside its own bounding box, so a pulse or the torch costs a small blit
    // rather than the whole canvas; it goes behind the comets and rings already drawn this frame.
    fx.globalCompositeOperation = 'destination-over'
    fx.globalAlpha = 1
    for (const [x, y, inner, outer, peak, strength] of lights) {
      const left = Math.max(0, Math.floor(x - outer)), top = Math.max(0, Math.floor(y - outer))
      const w = Math.min(coast.width, Math.ceil(x + outer)) - left, h = Math.min(coast.height, Math.ceil(y + outer)) - top
      if (w <= 0 || h <= 0) continue
      const gradient = mask.createRadialGradient(x, y, inner, x, y, outer)
      if (peak > 0) gradient.addColorStop(0, 'rgba(0, 0, 0, 0)')
      gradient.addColorStop(peak, `rgba(0, 0, 0, ${strength.toFixed(3)})`)
      gradient.addColorStop(1, 'rgba(0, 0, 0, 0)')
      mask.save()
      mask.beginPath()
      mask.rect(left, top, w, h)
      mask.clip()
      mask.clearRect(left, top, w, h)
      mask.fillStyle = gradient
      mask.fillRect(left, top, w, h)
      mask.globalCompositeOperation = 'source-in'
      mask.drawImage(coast, left, top, w, h, left, top, w, h)
      mask.restore()
      fx.drawImage(scratch, left, top, w, h, left, top, w, h)
    }
    fx.globalCompositeOperation = 'source-over'
  }

  // Pointer light and parallax ease toward their targets at a rate independent of frame rate.
  // Returns whether anything is still moving, which keeps the loop at full frame rate; a pointer resting
  // on the map keeps its light but lets the loop fall back to idle.
  function follow(delta) {
    const live = pointer.seen && fine.matches && !lite
    const x = pointer.x - bounds.left - shift.x, y = pointer.y - bounds.top - shift.y
    const over = live && x > -40 && x < width + 40 && y > -40 && y < height + 40
    if (over) {
      // A torch that was off lands under the pointer instead of sweeping in from where it last was.
      const ease = torch.power < 0.02 ? 1 : 1 - Math.exp(-delta / 110)
      torch.x += (x - torch.x) * ease
      torch.y += (y - torch.y) * ease
    }
    torch.power += ((over ? 1 : 0) - torch.power) * (1 - Math.exp(-delta / (over ? 180 : 360)))
    // The map slides a few pixels against the pointer, which sets it behind the copy and the card.
    const targetX = live ? (0.5 - pointer.x / window.innerWidth) * 18 : 0
    const targetY = live ? (0.5 - pointer.y / window.innerHeight) * 12 : 0
    const drift = 1 - Math.exp(-delta / 280)
    shift.x += (targetX - shift.x) * drift
    shift.y += (targetY - shift.y) * drift
    slide(`translate3d(${Math.round(shift.x * 50) / 50}px, ${Math.round(shift.y * 50) / 50}px, 0)`)
    return (over && Math.abs(x - torch.x) + Math.abs(y - torch.y) > 0.3)
      || Math.abs((over ? 1 : 0) - torch.power) > 0.004
      || Math.abs(targetX - shift.x) + Math.abs(targetY - shift.y) > 0.05
  }

  function slide(value) {
    if (root.style.transform !== value) root.style.transform = value
  }

  function animate(time) {
    frame = requestAnimationFrame(animate)
    if (previous === null) previous = time
    const delta = time - previous
    // Idle runs at 30fps; the opening and pointer movement follow the display.
    if (delta > 0 && delta < (hot ? HOT_FRAME : IDLE_FRAME)) return
    const passed = Math.min(delta, 100)
    elapsed += passed
    previous = time
    // Slow-machine check: the first frames carry page start-up work and are skipped. After that, four frames
    // slower than 20fps, or twelve that cannot average 25fps, finish the opening at once and keep the cheap
    // path; counting slow frames (not one long gap) keeps a single hitch on a fast machine from tripping it.
    if (!lite && elapsed < 120 + INTRO && delta > 0 && ++probed > 3) {
      probeTime += Math.min(delta, 250)
      if (delta > 50) slowFrames++
      if (slowFrames >= 4 || (probed === 15 && probeTime / 12 > 40)) {
        lite = true
        elapsed = 120 + INTRO
      }
    }
    const moving = follow(passed)
    hot = !lite && (moving || elapsed < LOOP_START)
    drawMotion()
  }

  function syncMotion() {
    cancelAnimationFrame(frame)
    frame = 0
    previous = null
    hot = !lite
    fx.clearRect(0, 0, width, height)
    // Small screens and reduced motion keep the same composition as a still: no opening, nothing follows the pointer.
    const still = reduced.matches || compact.matches
    if (still) {
      elapsed = Math.max(elapsed, LOOP_START)
      torch.power = shift.x = shift.y = 0
      slide('')
      reveal(null)
    } else if (width > 0 && height > 0 && elapsed < 120 + INTRO) {
      // Veil the map before its first paint so the opening never flashes the finished picture.
      reveal(opening())
    }
    if (!document.hidden && !still && width > 0 && height > 0) {
      frame = requestAnimationFrame(animate)
    }
  }

  function measure() {
    const rect = root.getBoundingClientRect()
    bounds = { left: rect.left - shift.x, top: rect.top - shift.y }
    return rect
  }

  function resize() {
    const rect = measure()
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    // ResizeObserver reports once as soon as it observes; repainting then would stall the opening for nothing.
    if (sized && rect.width === width && rect.height === height && ratio === dpr) return
    sized = true
    width = Math.max(0, rect.width)
    height = Math.max(0, rect.height)
    dpr = ratio
    for (const [surface, context] of [[canvas, ctx], [motion, fx]]) {
      surface.width = Math.round(width * dpr)
      surface.height = Math.round(height * dpr)
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    if (width > 40 && height > 48) {
      const blocks = keepClear()
      coast.width = scratch.width = Math.round(width)
      coast.height = scratch.height = Math.round(height)
      ;({ unit, origin, reach, routes } = paintWorldMap(ctx, { land: landContours, width, height, dpr, gold, light, blocks, glowCtx: coastCtx }))
    }
    syncMotion()
  }

  function track(event) {
    if (event.pointerType === 'touch') return
    pointer.x = event.clientX
    pointer.y = event.clientY
    pointer.seen = true
  }
  function release() { pointer.seen = false }

  // The base map costs several full-size blur passes, so redraw once the size settles; CSS stretches the old frame meanwhile.
  const observer = new ResizeObserver(() => {
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(resize, 120)
  })
  observer.observe(root)
  reduced.addEventListener('change', syncMotion)
  compact.addEventListener('change', syncMotion)
  document.addEventListener('visibilitychange', syncMotion)
  window.addEventListener('pointermove', track, { passive: true })
  window.addEventListener('scroll', measure, { passive: true })
  window.addEventListener('resize', measure, { passive: true })
  document.documentElement.addEventListener('pointerleave', release)
  resize()
  dispose = () => {
    cancelAnimationFrame(frame)
    clearTimeout(resizeTimer)
    observer.disconnect()
    reduced.removeEventListener('change', syncMotion)
    compact.removeEventListener('change', syncMotion)
    document.removeEventListener('visibilitychange', syncMotion)
    window.removeEventListener('pointermove', track)
    window.removeEventListener('scroll', measure)
    window.removeEventListener('resize', measure)
    document.documentElement.removeEventListener('pointerleave', release)
  }
})
onUnmounted(() => dispose())
</script>

<style scoped>
.world-map, canvas { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
</style>
