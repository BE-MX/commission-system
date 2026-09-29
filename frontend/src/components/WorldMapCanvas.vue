<template>
  <div class="world-map" aria-hidden="true">
    <canvas ref="mapRef" />
    <canvas ref="motionRef" />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import landContours from '@/assets/world-land.json'

const mapRef = ref(null)
const motionRef = ref(null)
let dispose = () => {}

// Natural Earth 1:110m land, public domain; source and processing in DESIGN.md.
// Market regions are rough lon/lat hulls; their edges get feathered, so precision is not needed.
const GLOW_REGIONS = [
  [[-172, 76], [-75, 80], [-60, 62], [-52, 47], [-78, 22], [-100, 22], [-125, 28], [-170, 56]],
  [[-16, 35], [-16, 62], [4, 76], [34, 76], [46, 68], [42, 44], [28, 35], [10, 36]],
  [[26, 42], [45, 42], [62, 38], [62, 22], [56, 12], [43, 11], [32, 29], [26, 31]],
  [[104, -12], [162, -12], [162, -50], [104, -50]],
]
// Neighbours that fall inside the feathered hulls: Africa (Mediterranean and Red Sea coasts) and
// Mexico/Caribbean (North America glows only for the US and Canada), carved out along their borders.
const EXCLUDED_REGIONS = [
  [[-18, 36], [-5.5, 35.9], [10, 37.6], [11.5, 33], [32.3, 31.4], [32.6, 29.8], [35.6, 23], [38.6, 17.8], [43.4, 12.4], [52, 11.8], [52, -36], [-18, -36]],
  [[-130, 32.6], [-117.1, 32.6], [-114.8, 32.5], [-111, 31.3], [-108.2, 31.3], [-106.4, 31.8], [-104.5, 29.6], [-101.4, 29.8], [-99.5, 27.5], [-97.2, 25.9], [-90, 24.3], [-80, 23.4], [-72, 21.5], [-60, 16], [-60, 0], [-130, 0]],
]

const DESTINATIONS = [
  { name: '北美', lon: -100, lat: 45 },
  { name: '欧洲', lon: 10, lat: 50 },
  { name: '中东', lon: 50, lat: 25 },
  { name: '澳洲', lon: 135, lat: -25 },
]
const ORIGIN = { name: '青岛', lon: 120.383, lat: 36.067 }

onMounted(() => {
  const canvas = mapRef.value
  const motion = motionRef.value
  const ctx = canvas.getContext('2d')
  const fx = motion.getContext('2d')
  if (!ctx || !fx) return
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  const compact = window.matchMedia('(max-width: 1023px)')
  const palette = getComputedStyle(canvas)
  const gold = palette.getPropertyValue('--login-gold').trim()
  const light = palette.getPropertyValue('--login-gold-light').trim()
  let width = 0, height = 0, dpr = 1, frame = 0, previous = null, elapsed = 0
  let routes = []
  let grainTile = null, resizeTimer = 0
  let origin = { x: 0, y: 0 }

  function point(location) {
    const scale = Math.min((width - 40) / 360, (height - 48) / 155)
    return { x: width / 2 + location.lon * scale, y: height / 2 + (10 - location.lat) * scale }
  }

  function dot(context, x, y, radius) {
    context.beginPath()
    context.arc(x, y, radius, 0, Math.PI * 2)
    context.fill()
  }

  function tracePolygons(context, polygons) {
    context.beginPath()
    for (const polygon of polygons) {
      polygon.forEach(([lon, lat], index) => {
        const p = point({ lon, lat })
        if (index === 0) context.moveTo(p.x, p.y)
        else context.lineTo(p.x, p.y)
      })
      context.closePath()
    }
  }

  function layer() {
    const surface = document.createElement('canvas')
    surface.width = canvas.width
    surface.height = canvas.height
    const context = surface.getContext('2d')
    context.setTransform(dpr, 0, 0, dpr, 0, 0)
    return { surface, context }
  }

  function grain() {
    const surface = document.createElement('canvas')
    surface.width = surface.height = 96
    const context = surface.getContext('2d')
    const noise = context.createImageData(96, 96)
    for (let i = 0; i < noise.data.length; i += 4) {
      const v = Math.random() < 0.5 ? 0 : 255
      noise.data[i] = noise.data[i + 1] = noise.data[i + 2] = v
      noise.data[i + 3] = Math.random() * 22
    }
    context.putImageData(noise, 0, 0)
    return surface
  }

  function glow(context, x, y, radius, alpha) {
    const gradient = context.createRadialGradient(x, y, 0, x, y, radius)
    gradient.addColorStop(0, light)
    gradient.addColorStop(0.3, gold)
    gradient.addColorStop(1, 'transparent')
    context.fillStyle = gradient
    context.globalAlpha = alpha
    dot(context, x, y, radius)
  }

  // Feathered hulls: draw the shape off-canvas and keep only its shadow, the one blur every canvas engine has.
  function regionMask(context, feather, polygons = GLOW_REGIONS) {
    const shift = width + feather * 4
    context.save()
    context.translate(-shift, 0)
    context.shadowOffsetX = shift * dpr
    context.shadowBlur = feather * dpr
    context.shadowColor = light
    context.fillStyle = light
    tracePolygons(context, polygons)
    context.fill()
    context.restore()
  }

  function sample(route, t) {
    const u = 1 - t
    return {
      x: u * u * origin.x + 2 * u * t * route.control.x + t * t * route.end.x,
      y: u * u * origin.y + 2 * u * t * route.control.y + t * t * route.end.y,
    }
  }

  function drawMap() {
    ctx.clearRect(0, 0, width, height)
    const unit = point({ lon: 1, lat: 0 }).x - point({ lon: 0, lat: 0 }).x
    // Land body: lit tint, inner rim, contour rings and grain, then light pooled around the markets.
    tracePolygons(ctx, landContours)
    ctx.save()
    ctx.clip()
    // Key light from the upper left keeps the tint from reading as one flat slab.
    const top = point({ lon: -180, lat: 80 }), bottom = point({ lon: 180, lat: -55 })
    const body = ctx.createLinearGradient(top.x, top.y, bottom.x * 0.55, bottom.y)
    body.addColorStop(0, light)
    body.addColorStop(0.45, gold)
    body.addColorStop(1, gold)
    ctx.fillStyle = body
    ctx.globalAlpha = 0.16
    ctx.fillRect(0, 0, width, height)
    const falloff = ctx.createLinearGradient(top.x, top.y, bottom.x * 0.55, bottom.y)
    falloff.addColorStop(0, 'rgba(0, 0, 0, 0)')
    falloff.addColorStop(1, 'rgba(0, 0, 0, 0.16)')
    ctx.fillStyle = falloff
    ctx.globalAlpha = 1
    ctx.fillRect(0, 0, width, height)
    // Inner rim: a faint glow just inside every coast lifts each continent like a raised plate.
    tracePolygons(ctx, landContours)
    ctx.lineJoin = 'round'
    ctx.strokeStyle = gold
    ctx.shadowColor = gold
    ctx.lineWidth = unit * 4
    ctx.shadowBlur = unit * 8 * dpr
    ctx.globalAlpha = 0.07
    ctx.stroke()
    ctx.lineWidth = unit * 1.2
    ctx.shadowBlur = unit * 2.5 * dpr
    ctx.globalAlpha = 0.22
    ctx.stroke()
    ctx.shadowBlur = 0
    // Contour rings: stroke-then-erase leaves a hairline at each offset; the land clip keeps the inner one.
    const rings = layer()
    const r = rings.context
    r.lineJoin = 'round'
    r.strokeStyle = gold
    for (let step = 4; step >= 1; step--) {
      tracePolygons(r, landContours)
      r.globalCompositeOperation = 'source-over'
      r.globalAlpha = 0.45 * (1 - (step - 1) / 4)
      r.lineWidth = unit * step * 2.2 + 0.8
      r.stroke()
      r.globalCompositeOperation = 'destination-out'
      r.globalAlpha = 1
      r.lineWidth = unit * step * 2.2 - 0.8
      r.stroke()
    }
    ctx.globalAlpha = 0.22
    ctx.drawImage(rings.surface, 0, 0, width, height)
    // Film grain breaks up the digital flatness without adding a visible pattern.
    grainTile ??= grain()
    ctx.fillStyle = ctx.createPattern(grainTile, 'repeat')
    ctx.globalAlpha = 0.28
    ctx.fillRect(0, 0, width, height)
    ctx.globalCompositeOperation = 'lighter'
    for (const location of DESTINATIONS) {
      const { x, y } = point(location)
      glow(ctx, x, y, unit * 34, 0.22)
    }
    glow(ctx, point(ORIGIN).x, point(ORIGIN).y, unit * 42, 0.26)
    const lift = layer()
    regionMask(lift.context, unit * 7)
    lift.context.globalCompositeOperation = 'destination-out'
    regionMask(lift.context, unit * 1.2, EXCLUDED_REGIONS)
    ctx.globalCompositeOperation = 'source-over'
    ctx.globalAlpha = 0.1
    ctx.drawImage(lift.surface, 0, 0, width, height)
    ctx.restore()
    tracePolygons(ctx, landContours)
    ctx.strokeStyle = gold
    ctx.lineWidth = 0.7
    ctx.globalAlpha = 0.3
    ctx.stroke()
    // Market halo: coastline light that only survives inside the feathered region hulls.
    const halo = layer()
    const h = halo.context
    h.lineJoin = 'round'
    // Bloom: wide faint passes first so light falls off gradually, as if shining up out of the map.
    tracePolygons(h, landContours)
    h.strokeStyle = gold
    h.shadowColor = gold
    h.lineWidth = 1.2
    for (const [blur, alpha] of [[20, 0.9], [9, 0.6], [3, 0.45]]) {
      h.shadowBlur = unit * blur * dpr
      h.globalAlpha = alpha
      h.stroke()
    }
    h.shadowBlur = unit * 0.8 * dpr
    h.shadowColor = light
    h.strokeStyle = light
    h.lineWidth = 1
    h.globalAlpha = 0.8
    h.stroke()
    const mask = layer()
    regionMask(mask.context, unit * 6)
    mask.context.globalCompositeOperation = 'destination-out'
    regionMask(mask.context, unit * 1.2, EXCLUDED_REGIONS)
    h.shadowBlur = 0
    h.setTransform(1, 0, 0, 1, 0, 0)
    h.globalCompositeOperation = 'destination-in'
    h.globalAlpha = 1
    h.drawImage(mask.surface, 0, 0)
    ctx.globalCompositeOperation = 'lighter'
    ctx.globalAlpha = 1
    ctx.drawImage(halo.surface, 0, 0, width, height)
    ctx.globalCompositeOperation = 'source-over'
    origin = point(ORIGIN)
    routes = DESTINATIONS.map(location => {
      const end = point(location)
      return { end, control: { x: (origin.x + end.x) / 2, y: Math.min(origin.y, end.y) - Math.min(65, Math.abs(origin.x - end.x) * 0.2) } }
    })
    ctx.strokeStyle = gold
    ctx.globalAlpha = 0.2
    ctx.lineWidth = 0.8
    for (const route of routes) {
      ctx.beginPath()
      ctx.moveTo(origin.x, origin.y)
      ctx.quadraticCurveTo(route.control.x, route.control.y, route.end.x, route.end.y)
      ctx.stroke()
    }
    for (const location of [...DESTINATIONS, ORIGIN]) {
      const { x, y } = point(location)
      const isOrigin = location === ORIGIN
      if (isOrigin) {
        const glow = ctx.createRadialGradient(x, y, 0, x, y, 34)
        glow.addColorStop(0, light)
        glow.addColorStop(0.25, gold)
        glow.addColorStop(1, 'transparent')
        ctx.fillStyle = glow
        ctx.globalAlpha = 0.38
        dot(ctx, x, y, 34)
        ctx.strokeStyle = light
        ctx.lineWidth = 1
        ctx.globalAlpha = 0.55
        ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.stroke()
      } else {
        ctx.globalAlpha = 0.1
        dot(ctx, x, y, 10)
      }
      ctx.globalAlpha = isOrigin ? 1 : 0.8
      ctx.fillStyle = light
      dot(ctx, x, y, isOrigin ? 4.5 : 2)
      ctx.globalAlpha = isOrigin ? 0.95 : 0.65
      ctx.font = isOrigin ? '600 12px "Microsoft YaHei", sans-serif' : '11px "Microsoft YaHei", sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(location.name, x, y + (isOrigin ? 32 : 19))
      ctx.fillStyle = gold
    }
    ctx.globalAlpha = 1
  }

  function drawMotion() {
    fx.clearRect(0, 0, width, height)
    fx.fillStyle = light
    routes.forEach((route, index) => {
      // Fixed start/control/end points; timing is independent of display refresh rate.
      const phase = (elapsed / 6500 + index * 0.25) % 1
      for (let tail = 7; tail >= 0; tail--) {
        const t = phase - tail * 0.008
        if (t < 0) continue
        const p = sample(route, t)
        fx.globalAlpha = (1 - tail / 8) * Math.min(1, phase * 12, (1 - phase) * 12) * 0.85
        dot(fx, p.x, p.y, tail === 0 ? 2 : 1.2)
      }
    })
    // Two staggered rings keep Qingdao visibly active without a flashing beacon.
    fx.strokeStyle = light
    fx.lineWidth = 1.3
    for (let ring = 0; ring < 2; ring++) {
      const phase = (elapsed / 3600 + ring * 0.5) % 1
      fx.globalAlpha = 0.5 * (1 - phase) ** 2
      fx.beginPath()
      fx.arc(origin.x, origin.y, 10 + phase * 28, 0, Math.PI * 2)
      fx.stroke()
    }
    fx.globalAlpha = 0.9
    dot(fx, origin.x, origin.y, 4.8 + Math.sin(elapsed / 1400) * 0.6)
    fx.globalAlpha = 1
  }

  function animate(time) {
    frame = requestAnimationFrame(animate)
    if (previous === null) previous = time
    const delta = time - previous
    if (delta < 1000 / 30) return
    elapsed += Math.min(delta, 100)
    previous = time
    drawMotion()
  }

  function syncMotion() {
    cancelAnimationFrame(frame)
    frame = 0
    previous = null
    fx.clearRect(0, 0, width, height)
    // Small screens keep the same composition as a still, saving battery behind the form.
    if (!document.hidden && !reduced.matches && !compact.matches && width > 0 && height > 0) {
      frame = requestAnimationFrame(animate)
    }
  }

  function resize() {
    const bounds = canvas.parentElement.getBoundingClientRect()
    width = Math.max(0, bounds.width)
    height = Math.max(0, bounds.height)
    dpr = Math.min(window.devicePixelRatio || 1, 2)
    for (const [surface, context] of [[canvas, ctx], [motion, fx]]) {
      surface.width = Math.round(width * dpr)
      surface.height = Math.round(height * dpr)
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    if (width > 40 && height > 48) drawMap()
    syncMotion()
  }

  // The base map costs several full-size blur passes, so redraw once the size settles; CSS stretches the old frame meanwhile.
  const observer = new ResizeObserver(() => {
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(resize, 120)
  })
  observer.observe(canvas.parentElement)
  reduced.addEventListener('change', syncMotion)
  compact.addEventListener('change', syncMotion)
  document.addEventListener('visibilitychange', syncMotion)
  resize()
  dispose = () => {
    cancelAnimationFrame(frame)
    clearTimeout(resizeTimer)
    observer.disconnect()
    reduced.removeEventListener('change', syncMotion)
    compact.removeEventListener('change', syncMotion)
    document.removeEventListener('visibilitychange', syncMotion)
  }
})
onUnmounted(() => dispose())
</script>

<style scoped>
.world-map, canvas { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
</style>
