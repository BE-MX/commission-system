<template>
  <canvas
    ref="canvasRef"
    :style="{
      position: 'absolute',
      top: 0,
      left: 0,
      width: '100%',
      height: '100%',
      zIndex: 0
    }"
  />
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const canvasRef = ref(null)
const particles = ref([])
const ripples = ref([])
const stars = ref([])
let animRef = 0
let lastSpawnTime = 0
let lastRippleTime = 0

// 大陆多边形数据
const CONTINENTS = [
  // North America
  [[-155,65],[-140,70],[-120,72],[-100,70],[-90,65],[-80,60],[-70,55],[-60,50],[-55,45],[-50,40],[-80,30],[-100,25],[-110,30],[-120,35],[-130,40],[-140,50],[-150,55],[-155,65]],
  // South America
  [[-80,10],[-70,0],[-60,-10],[-55,-20],[-55,-30],[-60,-40],[-65,-50],[-70,-55],[-75,-50],[-75,-40],[-75,-30],[-75,-20],[-75,-10],[-78,0],[-80,10]],
  // Europe
  [[-10,35],[0,40],[10,45],[20,50],[30,55],[40,60],[45,65],[40,70],[30,70],[20,65],[10,60],[0,55],[-10,50],[-10,45],[-10,40],[-10,35]],
  // Africa
  [[-15,35],[0,35],[15,35],[30,32],[40,25],[45,15],[40,5],[35,-5],[30,-15],[25,-25],[20,-30],[15,-35],[10,-30],[5,-20],[0,-10],[-5,0],[-10,10],[-15,20],[-15,30],[-15,35]],
  // Middle East
  [[35,25],[45,30],[55,35],[60,30],[65,25],[60,20],[55,15],[50,15],[45,20],[40,22],[35,25]],
  // Asia
  [[60,70],[80,75],[100,75],[120,72],[140,65],[150,60],[160,55],[170,50],[170,40],[160,30],[150,25],[140,20],[130,15],[120,10],[110,5],[100,0],[90,5],[80,10],[70,15],[65,20],[60,25],[55,30],[55,40],[55,50],[60,60],[60,70]],
  // Australia
  [[115,-15],[125,-15],[135,-18],[145,-25],[150,-30],[150,-35],[145,-38],[140,-40],[130,-38],[120,-35],[115,-30],[115,-25],[115,-20],[115,-15]],
  // India
  [[70,8],[80,8],[88,10],[92,15],[90,22],[85,25],[80,22],[75,18],[72,12],[70,8]]
]

// 目标城市
const DESTINATIONS = [
  { name: '北美', color: '#00d4ff', lat: 45, lon: -100 },
  { name: '欧洲', color: '#d4af6e', lat: 50, lon: 10 },
  { name: '中东', color: '#ff9f43', lat: 25, lon: 50 },
  { name: '澳洲', color: '#54d468', lat: -25, lon: 135 }
]

// 青岛坐标
const qingdaoLon = 120.383
const qingdaoLat = 36.067

// 点在多边形内判断
function pointInPolygon(x, y, polygon) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1]
    const xj = polygon[j][0], yj = polygon[j][1]
    const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)
    if (intersect) inside = !inside
  }
  return inside
}

function isLand(lon, lat) {
  return CONTINENTS.some(poly => pointInPolygon(lon, lat, poly))
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  let width = 0
  let height = 0
  const dpr = Math.min(window.devicePixelRatio || 1, 2)

  function resize() {
    width = canvas.offsetWidth
    height = canvas.offsetHeight
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)

    // 初始化星星
    stars.value = []
    for (let i = 0; i < 80; i++) {
      stars.value.push({
        x: Math.random() * width,
        y: Math.random() * height,
        size: Math.random() * 1.5 + 0.3,
        twinkle: Math.random() * Math.PI * 2,
        speed: Math.random() * 0.02 + 0.005
      })
    }
  }

  resize()

  function getMapParams() {
    const cx = width * 0.40
    const cy = height * 0.5
    const scale = Math.min(width, height) * 0.0028
    return { cx, cy, scale }
  }

  function drawDotMatrix() {
    const { cx, cy, scale } = getMapParams()
    const spacing = 6
    const dotSize = 1.2

    for (let y = 0; y < height; y += spacing) {
      for (let x = 0; x < width; x += spacing) {
        const lon = (x - cx) / scale
        const lat = (cy - y) / scale

        if (lon < -180 || lon > 180 || lat < -60 || lat > 85) continue

        const dLon = lon - qingdaoLon
        const dLat = lat - qingdaoLat
        const dist = Math.sqrt(dLon * dLon + dLat * dLat)

        const land = isLand(lon, lat)
        if (land) {
          let highlight = false
          let destColor = ''
          for (const dest of DESTINATIONS) {
            const ddLon = lon - dest.lon
            const ddLat = lat - dest.lat
            const dd = Math.sqrt(ddLon * ddLon + ddLat * ddLat)
            if (dd < 12) {
              highlight = true
              destColor = dest.color
              break
            }
          }

          if (highlight && destColor) {
            ctx.fillStyle = destColor
            ctx.globalAlpha = 0.35
          } else if (dist < 8) {
            ctx.fillStyle = '#ff6b6b'
            ctx.globalAlpha = 0.45
          } else {
            ctx.fillStyle = '#d4af6e'
            ctx.globalAlpha = 0.18
          }
          ctx.beginPath()
          ctx.arc(x, y, dotSize, 0, Math.PI * 2)
          ctx.fill()
          ctx.globalAlpha = 1
        } else {
          ctx.fillStyle = '#00d4ff'
          ctx.globalAlpha = 0.04
          ctx.beginPath()
          ctx.arc(x, y, dotSize * 0.7, 0, Math.PI * 2)
          ctx.fill()
          ctx.globalAlpha = 1
        }
      }
    }
  }

  function drawGrid() {
    const { cx, cy, scale } = getMapParams()
    ctx.strokeStyle = 'rgba(0, 212, 255, 0.03)'
    ctx.lineWidth = 1

    for (let lon = -180; lon <= 180; lon += 30) {
      const x = cx + lon * scale
      ctx.beginPath()
      ctx.moveTo(x, 0)
      ctx.lineTo(x, height)
      ctx.stroke()
    }
    for (let lat = -60; lat <= 80; lat += 20) {
      const y = cy - lat * scale
      ctx.beginPath()
      ctx.moveTo(0, y)
      ctx.lineTo(width, y)
      ctx.stroke()
    }
  }

  function drawStars(time) {
    for (const star of stars.value) {
      const alpha = 0.2 + 0.25 * Math.sin(time * star.speed + star.twinkle)
      ctx.fillStyle = `rgba(255, 255, 255, ${alpha})`
      ctx.beginPath()
      ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  function drawQingdaoGlow(time) {
    const { cx, cy, scale } = getMapParams()
    const qx = cx + qingdaoLon * scale
    const qy = cy - qingdaoLat * scale

    const pulse = 2.5 + 1.5 * Math.sin(time * 0.002)

    const gradient = ctx.createRadialGradient(qx, qy, 0, qx, qy, 25)
    gradient.addColorStop(0, 'rgba(255, 107, 107, 0.6)')
    gradient.addColorStop(0.3, 'rgba(255, 107, 107, 0.2)')
    gradient.addColorStop(1, 'rgba(255, 107, 107, 0)')
    ctx.fillStyle = gradient
    ctx.beginPath()
    ctx.arc(qx, qy, 25, 0, Math.PI * 2)
    ctx.fill()

    ctx.fillStyle = '#ff6b6b'
    ctx.shadowColor = '#ff6b6b'
    ctx.shadowBlur = 15
    ctx.beginPath()
    ctx.arc(qx, qy, pulse, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0

    ctx.fillStyle = 'rgba(255, 107, 107, 0.9)'
    ctx.font = '12px Inter, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('青岛', qx, qy + 22)
  }

  function drawDestinations() {
    const { cx, cy, scale } = getMapParams()
    for (const dest of DESTINATIONS) {
      const dx = cx + dest.lon * scale
      const dy = cy - dest.lat * scale

      const gradient = ctx.createRadialGradient(dx, dy, 0, dx, dy, 18)
      gradient.addColorStop(0, dest.color + '40')
      gradient.addColorStop(1, dest.color + '00')
      ctx.fillStyle = gradient
      ctx.beginPath()
      ctx.arc(dx, dy, 18, 0, Math.PI * 2)
      ctx.fill()

      ctx.fillStyle = dest.color
      ctx.shadowColor = dest.color
      ctx.shadowBlur = 10
      ctx.beginPath()
      ctx.arc(dx, dy, 3, 0, Math.PI * 2)
      ctx.fill()
      ctx.shadowBlur = 0

      ctx.fillStyle = dest.color + 'cc'
      ctx.font = '11px Inter, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(dest.name, dx, dy + 18)
    }
  }

  function spawnParticles(time) {
    if (time - lastSpawnTime < 400) return
    lastSpawnTime = time

    const { cx, cy, scale } = getMapParams()
    const qx = cx + qingdaoLon * scale
    const qy = cy - qingdaoLat * scale

    if (particles.value.length >= 50) return

    for (const dest of DESTINATIONS) {
      if (Math.random() > 0.6) continue
      const destX = cx + dest.lon * scale
      const destY = cy - dest.lat * scale
      particles.value.push({
        x: qx,
        y: qy,
        destX,
        destY,
        progress: 0,
        speed: 0.003 + Math.random() * 0.004,
        color: dest.color,
        trail: [],
        curveOffset: (Math.random() - 0.5) * 40
      })
    }
  }

  function updateParticles() {
    for (let i = particles.value.length - 1; i >= 0; i--) {
      const p = particles.value[i]
      p.progress += p.speed

      const t = p.progress
      const midX = (p.x + p.destX) / 2 + p.curveOffset
      const midY = (p.y + p.destY) / 2 - Math.abs(p.curveOffset) * 0.5

      const nx = (1 - t) * (1 - t) * p.x + 2 * (1 - t) * t * midX + t * t * p.destX
      const ny = (1 - t) * (1 - t) * p.y + 2 * (1 - t) * t * midY + t * t * p.destY

      p.trail.push({ x: nx, y: ny, opacity: 0.6 })
      if (p.trail.length > 10) p.trail.shift()

      p.x = nx
      p.y = ny

      if (p.progress >= 1) {
        particles.value.splice(i, 1)
      }
    }
  }

  function drawParticles() {
    for (const p of particles.value) {
      for (let i = 0; i < p.trail.length; i++) {
        const t = p.trail[i]
        const alpha = (t.opacity * (i + 1) / p.trail.length) * 0.5
        ctx.fillStyle = p.color + Math.floor(alpha * 255).toString(16).padStart(2, '0')
        const size = 1 + (i / p.trail.length) * 1.5
        ctx.beginPath()
        ctx.arc(t.x, t.y, size, 0, Math.PI * 2)
        ctx.fill()
      }

      ctx.fillStyle = p.color
      ctx.shadowColor = p.color
      ctx.shadowBlur = 8
      ctx.beginPath()
      ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2)
      ctx.fill()
      ctx.shadowBlur = 0
    }
  }

  function spawnRipple(time) {
    if (time - lastRippleTime < 4000) return
    lastRippleTime = time

    const { cx, cy, scale } = getMapParams()
    const qx = cx + qingdaoLon * scale
    const qy = cy - qingdaoLat * scale

    ripples.value.push({
      x: qx,
      y: qy,
      radius: 0,
      opacity: 0.6,
      maxRadius: 80
    })
  }

  function updateRipples() {
    for (let i = ripples.value.length - 1; i >= 0; i--) {
      const r = ripples.value[i]
      r.radius += 1.2
      r.opacity = 0.6 * (1 - r.radius / r.maxRadius)
      if (r.radius >= r.maxRadius) {
        ripples.value.splice(i, 1)
      }
    }
  }

  function drawRipples() {
    for (const r of ripples.value) {
      ctx.strokeStyle = `rgba(255, 107, 107, ${r.opacity})`
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.arc(r.x, r.y, r.radius, 0, Math.PI * 2)
      ctx.stroke()
    }
  }

  function animate(time) {
    ctx.clearRect(0, 0, width, height)

    ctx.fillStyle = '#0a0a0f'
    ctx.fillRect(0, 0, width, height)

    drawGrid()
    drawStars(time)
    drawDotMatrix()
    drawDestinations()

    spawnParticles(time)
    updateParticles()
    drawParticles()

    spawnRipple(time)
    updateRipples()
    drawRipples()

    drawQingdaoGlow(time)

    animRef = requestAnimationFrame(animate)
  }

  animRef = requestAnimationFrame(animate)

  const handleResize = () => {
    resize()
  }
  window.addEventListener('resize', handleResize)

  onUnmounted(() => {
    cancelAnimationFrame(animRef)
    window.removeEventListener('resize', handleResize)
  })
})
</script>
