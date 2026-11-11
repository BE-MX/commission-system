// Paints the still world map of the login page: land, market coasts, routes, nodes and labels.
// Plain canvas work with no component state; WorldMapCanvas.vue animates on top of what this returns.

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

let grainTile = null

// `blocks` are rectangles of copy lying over the map: labels stay out of them and the map is quieted behind them.
// `glowCtx` receives every coast's glow at CSS-pixel size.
export function paintWorldMap(ctx, { land, width, height, dpr, gold, light, blocks = [], glowCtx = null }) {
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
    surface.width = Math.round(width * dpr)
    surface.height = Math.round(height * dpr)
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

  // First free spot around a node: below, above, either side, then further out with a hairline leader.
  function place(x, y, labelWidth, drop, blocks) {
    const spots = [
      { x, y: y + drop, align: 'center' },
      { x, y: y - 11, align: 'center' },
      { x: x + 10, y: y + 4, align: 'left' },
      { x: x - 10, y: y + 4, align: 'right' },
      // Still covered: step further out above and below, joined to the node by a hairline.
      ...[1, 2, 3, 4].flatMap(step => [
        { x, y: y - 10 - step * 24, align: 'center', lead: -5 },
        { x, y: y + drop + step * 24, align: 'center', lead: 5 },
      ]),
    ]
    const free = spot => {
      const left = spot.align === 'center' ? spot.x - labelWidth / 2 : spot.align === 'left' ? spot.x : spot.x - labelWidth
      return !blocks.some(b => left < b.right && left + labelWidth > b.left && spot.y - 11 < b.bottom && spot.y + 3 > b.top)
    }
    return spots.find(free) ?? spots[0]
  }

  ctx.clearRect(0, 0, width, height)
  const unit = point({ lon: 1, lat: 0 }).x - point({ lon: 0, lat: 0 }).x
  // Land body: lit tint, inner rim, contour rings and grain, then light pooled around the markets.
  tracePolygons(ctx, land)
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
  tracePolygons(ctx, land)
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
    tracePolygons(r, land)
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
  tracePolygons(ctx, land)
  ctx.strokeStyle = gold
  ctx.lineWidth = 0.7
  ctx.globalAlpha = 0.3
  ctx.stroke()
  // Market halo: coastline light that only survives inside the feathered region hulls.
  const halo = layer()
  const h = halo.context
  h.lineJoin = 'round'
  // Bloom: wide faint passes first so light falls off gradually, as if shining up out of the map.
  tracePolygons(h, land)
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
  // Before the markets are cut out, keep every coast's glow for the moving lights.
  if (glowCtx) {
    glowCtx.drawImage(halo.surface, 0, 0, Math.round(width), Math.round(height))
    // A little of the land itself, so a passing light lifts the plains as well as the shoreline.
    tracePolygons(glowCtx, land)
    glowCtx.fillStyle = gold
    glowCtx.globalAlpha = 0.2
    glowCtx.fill()
  }
  const markets = layer()
  regionMask(markets.context, unit * 6)
  markets.context.globalCompositeOperation = 'destination-out'
  regionMask(markets.context, unit * 1.2, EXCLUDED_REGIONS)
  h.shadowBlur = 0
  h.setTransform(1, 0, 0, 1, 0, 0)
  h.globalCompositeOperation = 'destination-in'
  h.globalAlpha = 1
  h.drawImage(markets.surface, 0, 0)
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = 1
  ctx.drawImage(halo.surface, 0, 0, width, height)
  ctx.globalCompositeOperation = 'source-over'
  const origin = point(ORIGIN)
  const reach = Math.hypot(Math.max(origin.x, width - origin.x), Math.max(origin.y, height - origin.y))
  const routes = DESTINATIONS.map(location => {
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
    ctx.font = isOrigin ? '600 12px "Microsoft YaHei", sans-serif' : '11px "Microsoft YaHei", sans-serif'
    const spot = place(x, y, ctx.measureText(location.name).width, isOrigin ? 32 : 19, blocks)
    if (spot.lead) {
      ctx.strokeStyle = light
      ctx.lineWidth = 0.6
      ctx.globalAlpha = 0.3
      ctx.beginPath()
      ctx.moveTo(x, y + spot.lead)
      ctx.lineTo(x, spot.y + (spot.lead < 0 ? 5 : -12))
      ctx.stroke()
    }
    ctx.globalAlpha = isOrigin ? 0.95 : 0.65
    ctx.textAlign = spot.align
    ctx.fillText(location.name, spot.x, spot.y)
    ctx.fillStyle = gold
  }
  ctx.globalAlpha = 1
  // Quiet the map right behind each line of copy so small type stays readable. Only the feathered shadow
  // of the rectangles lands on the canvas, erasing part of the paint; moving lights and the wake are untouched.
  if (blocks.length) {
    const away = width + 400
    ctx.save()
    ctx.globalCompositeOperation = 'destination-out'
    ctx.translate(-away, 0)
    ctx.shadowOffsetX = away * dpr
    ctx.shadowBlur = 18 * dpr
    ctx.shadowColor = 'rgba(0, 0, 0, 0.62)'
    ctx.fillStyle = 'rgba(0, 0, 0, 1)'
    ctx.beginPath()
    for (const block of blocks) ctx.rect(block.left, block.top, block.right - block.left, block.bottom - block.top)
    ctx.fill()
    ctx.restore()
  }
  return { unit, origin, reach, routes }
}
