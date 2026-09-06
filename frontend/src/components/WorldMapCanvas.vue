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
const landPolygons = landContours.map(points => ({
  points,
  west: Math.min(...points.map(p => p[0])), east: Math.max(...points.map(p => p[0])),
  south: Math.min(...points.map(p => p[1])), north: Math.max(...points.map(p => p[1])),
}))

const DESTINATIONS = [
  { name: '北美', lon: -100, lat: 45 },
  { name: '欧洲', lon: 10, lat: 50 },
  { name: '中东', lon: 50, lat: 25 },
  { name: '澳洲', lon: 135, lat: -25 },
]
const ORIGIN = { name: '青岛', lon: 120.383, lat: 36.067 }

function isLand(lon, lat) {
  return landPolygons.some(({ points: polygon, west, east, south, north }) => {
    if (lon < west || lon > east || lat < south || lat > north) return false
    let inside = false
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const [xi, yi] = polygon[i]
      const [xj, yj] = polygon[j]
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside
    }
    return inside
  })
}

// Geographic membership never changes: calculate once, not for every frame.
const landDots = []
for (let lat = -55; lat <= 80; lat += 3) {
  for (let lon = -175; lon <= 175; lon += 3) {
    if (isLand(lon, lat)) landDots.push({ lon, lat })
  }
}

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
  let width = 0, height = 0, frame = 0, previous = null, elapsed = 0
  let routes = []
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

  function sample(route, t) {
    const u = 1 - t
    return {
      x: u * u * origin.x + 2 * u * t * route.control.x + t * t * route.end.x,
      y: u * u * origin.y + 2 * u * t * route.control.y + t * t * route.end.y,
    }
  }

  function drawMap() {
    ctx.clearRect(0, 0, width, height)
    // Coastlines and a quiet graticule make the land masses recognizable at a glance.
    ctx.strokeStyle = gold
    ctx.lineWidth = 0.6
    ctx.globalAlpha = 0.07
    for (let lon = -180; lon <= 180; lon += 30) {
      const start = point({ lon, lat: -55 }), end = point({ lon, lat: 80 })
      ctx.beginPath(); ctx.moveTo(start.x, start.y); ctx.lineTo(end.x, end.y); ctx.stroke()
    }
    for (let lat = -40; lat <= 80; lat += 20) {
      const start = point({ lon: -180, lat }), end = point({ lon: 180, lat })
      ctx.beginPath(); ctx.moveTo(start.x, start.y); ctx.lineTo(end.x, end.y); ctx.stroke()
    }
    ctx.fillStyle = gold
    ctx.lineWidth = 0.85
    for (const polygon of landContours) {
      ctx.beginPath()
      polygon.forEach(([lon, lat], index) => {
        const p = point({ lon, lat })
        if (index === 0) ctx.moveTo(p.x, p.y)
        else ctx.lineTo(p.x, p.y)
      })
      ctx.closePath()
      ctx.globalAlpha = 0.07
      ctx.fill()
      ctx.globalAlpha = 0.32
      ctx.stroke()
    }
    ctx.globalAlpha = 0.2
    for (const location of landDots) {
      const { x, y } = point(location)
      dot(ctx, x, y, width < 450 ? 0.8 : 1.1)
    }
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
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    for (const [surface, context] of [[canvas, ctx], [motion, fx]]) {
      surface.width = Math.round(width * dpr)
      surface.height = Math.round(height * dpr)
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    if (width > 40 && height > 48) drawMap()
    syncMotion()
  }

  const observer = new ResizeObserver(resize)
  observer.observe(canvas.parentElement)
  reduced.addEventListener('change', syncMotion)
  compact.addEventListener('change', syncMotion)
  document.addEventListener('visibilitychange', syncMotion)
  resize()
  dispose = () => {
    cancelAnimationFrame(frame)
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
