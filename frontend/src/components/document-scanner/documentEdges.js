import { area, cross, isValidQuad } from './documentQuad.js'

const clamp = (value, min, max) => Math.min(max, Math.max(min, value))
const luma = (r, g, b) => (77 * r + 150 * g + 29 * b) / 256

function convexHull(points) {
  const sorted = points.slice().sort(([x1, y1], [x2, y2]) => x1 - x2 || y1 - y2)
  function half(sequence) {
    const hull = []
    for (const point of sequence) {
      while (hull.length >= 2 && cross(hull.at(-2), hull.at(-1), point) <= 0) hull.pop()
      hull.push(point)
    }
    return hull.slice(0, -1)
  }
  return [...half(sorted), ...half(sorted.reverse())]
}

function fitQuad(hull) {
  if (hull.length < 4) return null
  while (hull.length > 4) {
    const costs = hull.map((point, i) => {
      const before = hull[(i + hull.length - 1) % hull.length]
      const after = hull[(i + 1) % hull.length]
      return cross(before, point, after)
    })
    hull.splice(costs.indexOf(Math.min(...costs)), 1)
  }
  const start = hull.reduce((best, point, i) => (
    point[0] + point[1] < hull[best][0] + hull[best][1] ? i : best
  ), 0)
  return [...hull.slice(start), ...hull.slice(0, start)]
}

function imageChannels({ width, height, data }) {
  const gray = new Uint8Array(width * height)
  const redGreen = new Int16Array(gray.length)
  const blueGreen = new Int16Array(gray.length)
  for (let i = 0; i < gray.length; i++) {
    const offset = i * 4
    gray[i] = luma(data[offset], data[offset + 1], data[offset + 2])
    redGreen[i] = data[offset] - data[offset + 1]
    blueGreen[i] = data[offset + 2] - data[offset + 1]
  }
  return [gray, redGreen, blueGreen]
}

function gradientMap([gray, redGreen, blueGreen], width, height) {
  const gradient = new Uint8Array(gray.length)
  const sobel = (channel, i) => {
    const nw = channel[i - width - 1]
    const ne = channel[i - width + 1]
    const sw = channel[i + width - 1]
    const se = channel[i + width + 1]
    const gx = ne + se - nw - sw + 2 * (channel[i + 1] - channel[i - 1])
    const gy = sw + se - nw - ne + 2 * (channel[i + width] - channel[i - width])
    return Math.abs(gx) + Math.abs(gy)
  }
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x
      gradient[i] = Math.min(255, Math.max(sobel(gray, i), sobel(redGreen, i) * 1.3, sobel(blueGreen, i) * 1.3) / 4)
    }
  }
  return gradient
}

// Follow edge components with a small gap tolerance. Keep only the two extreme pixels
// per row of each component, which preserves its convex hull.
function edgeContours(edges, width, height, threshold) {
  const visited = new Uint8Array(edges.length)
  const queue = new Int32Array(edges.length)
  const left = new Int32Array(height)
  const right = new Int32Array(height)
  const contours = []
  for (let start = 0; start < edges.length; start++) {
    if (edges[start] < threshold || visited[start]) continue
    let size = 1
    let minX = width
    let maxX = 0
    let minY = height
    let maxY = 0
    queue[0] = start
    visited[start] = 1
    for (let head = 0; head < size; head++) {
      const index = queue[head]
      const x = index % width
      const y = (index / width) | 0
      minX = Math.min(minX, x)
      maxX = Math.max(maxX, x)
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y)
      for (let ny = Math.max(1, y - 2); ny <= Math.min(height - 2, y + 2); ny++) {
        for (let nx = Math.max(1, x - 2); nx <= Math.min(width - 2, x + 2); nx++) {
          const neighbor = ny * width + nx
          if (visited[neighbor] || edges[neighbor] < threshold) continue
          visited[neighbor] = 1
          queue[size++] = neighbor
        }
      }
    }
    if (size < 64 || (maxX - minX) * (maxY - minY) < edges.length * 0.11) continue
    left.fill(width, minY, maxY + 1)
    right.fill(-1, minY, maxY + 1)
    for (let i = 0; i < size; i++) {
      const x = queue[i] % width
      const y = (queue[i] / width) | 0
      left[y] = Math.min(left[y], x)
      right[y] = Math.max(right[y], x)
    }
    const points = []
    for (let y = minY; y <= maxY; y++) {
      if (right[y] < 0) continue
      points.push([left[y], y])
      if (left[y] !== right[y]) points.push([right[y], y])
    }
    contours.push(points)
  }
  return contours
}

function edgeSupport(edges, width, height, [ax, ay], [bx, by], threshold) {
  let supported = 0
  const samples = 36
  for (let i = 1; i < samples; i++) {
    const x = Math.round(ax + (bx - ax) * i / samples)
    const y = Math.round(ay + (by - ay) * i / samples)
    let strongest = 0
    for (let ny = Math.max(0, y - 3); ny <= Math.min(height - 1, y + 3); ny++) {
      for (let nx = Math.max(0, x - 3); nx <= Math.min(width - 1, x + 3); nx++) {
        strongest = Math.max(strongest, edges[ny * width + nx])
      }
    }
    if (strongest >= threshold) supported++
  }
  return supported / (samples - 1)
}

// Ink lines have an intensity peak but similar colors on both sides.
// A paper edge separates two regions several pixels away from the edge.
function paperBoundarySupport({ width, height, data }, [ax, ay], [bx, by]) {
  const length = Math.hypot(bx - ax, by - ay)
  const nx = (ay - by) / length
  const ny = (bx - ax) / length
  const differences = []
  for (let sample = 0; sample < 16; sample++) {
    const t = 0.12 + sample * 0.76 / 15
    const x = ax + (bx - ax) * t
    const y = ay + (by - ay) * t
    const delta = [0, 0, 0]
    let count = 0
    for (const gap of [4, 7]) {
      const px = Math.round(x + nx * gap)
      const py = Math.round(y + ny * gap)
      const qx = Math.round(x - nx * gap)
      const qy = Math.round(y - ny * gap)
      if (Math.min(px, qx, py, qy) < 0 || Math.max(px, qx) >= width || Math.max(py, qy) >= height) continue
      const inside = (py * width + px) * 4
      const outside = (qy * width + qx) * 4
      for (let channel = 0; channel < 3; channel++) {
        delta[channel] += data[inside + channel] - data[outside + channel]
      }
      count++
    }
    if (count) differences.push(delta.map(value => value / count))
  }
  if (differences.length < 10) return 0
  const medians = [0, 1, 2].map(channel => {
    const values = differences.map(delta => delta[channel]).sort((a, b) => a - b)
    return values[Math.floor(values.length / 2)]
  })
  const strengths = medians.map(Math.abs)
  const dominant = strengths.indexOf(Math.max(...strengths))
  const polarity = Math.sign(medians[dominant])
  return differences.filter(delta => delta[dominant] * polarity >= 9).length / 16
}

function splitLevels(channel) {
  const histogram = new Uint32Array(511)
  let total = 0
  for (const level of channel) {
    histogram[level + 255]++
    total += level
  }
  let selection = null
  let maxVariance = 0
  let count = 0
  let sum = 0
  for (let i = 0; i < histogram.length; i++) {
    if (!histogram[i]) continue
    const level = i - 255
    count += histogram[i]
    sum += level * histogram[i]
    const remaining = channel.length - count
    if (!remaining || Math.min(count, remaining) < channel.length * 0.075) continue
    const distance = (total - sum) / remaining - sum / count
    const variance = count * remaining * distance ** 2
    if (distance < 12 || variance <= maxVariance) continue
    selection = level
    maxVariance = variance
  }
  return selection
}

function regionQuads(channel, width, height) {
  const split = splitLevels(channel)
  if (split == null) return []
  // Both sides of the split are traversed in the same pass. A page may be
  // darker or lighter than the desk, or differ mainly in color.
  const groups = new Uint8Array(channel.length)
  for (let i = 0; i < channel.length; i++) groups[i] = channel[i] <= split ? 1 : 2
  const queue = new Int32Array(channel.length)
  const left = new Int32Array(height)
  const right = new Int32Array(height)
  const quads = []
  for (let i = 0; i < groups.length; i++) {
    const region = groups[i]
    if (!region) continue
    let size = 1
    queue[0] = i
    groups[i] = 0
    let frameContact = 0
    let minY = height
    let maxY = 0
    const add = index => {
      if (groups[index] !== region) return
      groups[index] = 0
      queue[size++] = index
    }
    for (let head = 0; head < size; head++) {
      const pixel = queue[head]
      const x = pixel % width
      const y = (pixel / width) | 0
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y)
      if (x === 0 || x === width - 1 || y === 0 || y === height - 1) frameContact++
      if (x > 0) add(pixel - 1)
      if (x < width - 1) add(pixel + 1)
      if (y > 0) add(pixel - width)
      if (y < height - 1) add(pixel + width)
    }
    if (size < channel.length * 0.095 || frameContact > Math.min(width, height) * 0.13) continue
    left.fill(width, minY, maxY + 1)
    right.fill(-1, minY, maxY + 1)
    for (let j = 0; j < size; j++) {
      const x = queue[j] % width
      const y = (queue[j] / width) | 0
      left[y] = Math.min(left[y], x)
      right[y] = Math.max(right[y], x)
    }
    const outer = []
    for (let y = minY; y <= maxY; y++) {
      if (right[y] < 0) continue
      outer.push([left[y], y], [right[y], y])
    }
    const quad = fitQuad(convexHull(outer))
    if (!quad) continue
    const density = size / area(quad)
    if (density >= 0.68 && density <= 1.20) quads.push(quad)
  }
  return quads
}

function lineFit(points, tangentX, tangentY) {
  if (points.length < 9) return null
  let meanX = 0
  let meanY = 0
  for (const [x, y] of points) {
    meanX += x
    meanY += y
  }
  meanX /= points.length
  meanY /= points.length
  let covariance = 0
  let variance = 0
  for (const [x, y] of points) {
    const along = (x - meanX) * tangentX + (y - meanY) * tangentY
    const across = (y - meanY) * tangentX - (x - meanX) * tangentY
    covariance += along * across
    variance += along ** 2
  }
  const slope = covariance / variance
  if (!Number.isFinite(slope) || Math.abs(slope) > 0.12) return null
  const nx = -tangentY - slope * tangentX
  const ny = tangentX - slope * tangentY
  return [nx, ny, nx * meanX + ny * meanY]
}

function sharpenCorners(quad, image, edges) {
  const { width, height } = image
  const lines = quad.map(([ax, ay], index) => {
    const [bx, by] = quad[(index + 1) % 4]
    const length = Math.hypot(bx - ax, by - ay)
    const dx = (bx - ax) / length
    const dy = (by - ay) / length
    const picks = []
    for (let sample = 0; sample < 20; sample++) {
      const t = 0.10 + sample * 0.80 / 19
      const x = ax + (bx - ax) * t
      const y = ay + (by - ay) * t
      let strongest = 13
      let best = null
      for (let offset = -4; offset <= 4; offset++) {
        const px = Math.round(x - dy * offset)
        const py = Math.round(y + dx * offset)
        if (px < 1 || py < 1 || px >= width - 1 || py >= height - 1) continue
        const weight = edges[py * width + px] - Math.abs(offset) * 2
        if (weight <= strongest) continue
        strongest = weight
        best = [px, py]
      }
      if (best) picks.push(best)
    }
    return lineFit(picks, dx, dy) || [-dy, dx, -dy * ax + dx * ay]
  })
  return lines.map(([a, b, c], index) => {
    const [d, e, f] = lines[(index + 3) % 4]
    const denominator = a * e - b * d
    if (Math.abs(denominator) < 0.15) return quad[index]
    const x = (c * e - b * f) / denominator
    const y = (a * f - c * d) / denominator
    const [qx, qy] = quad[index]
    if (Math.hypot(x - qx, y - qy) > 9) return quad[index]
    return [clamp(x, 0, width - 1), clamp(y, 0, height - 1)]
  })
}

export function detectDocument(image) {
  const { width, height } = image
  if (Math.min(width, height) < 24) return null
  const channels = imageChannels(image)
  const edges = gradientMap(channels, width, height)
  const normalize = quad => quad.map(([x, y]) => [x / (width - 1), y / (height - 1)])
  let best = null
  let bestScore = 0

  function prefer(quad, region = false, threshold = 17) {
    if (!quad) return
    const normalized = normalize(quad)
    const coverage = area(normalized)
    if (coverage < 0.11 || coverage > 0.94 || !isValidQuad(normalized)) return
    if (!region && quad.some(([x, y]) => x <= 2 || y <= 2 || x >= width - 3 || y >= height - 3)) return
    const border = quad.map((point, i) => paperBoundarySupport(image, point, quad[(i + 1) % 4]))
    if (Math.min(...border) < 0.5) return
    const edge = quad.map((point, i) => edgeSupport(edges, width, height, point, quad[(i + 1) % 4], threshold))
    const averageEdge = edge.reduce((sum, value) => sum + value, 0) / 4
    if (Math.min(...edge) < (region ? 0.29 : 0.49) || averageEdge < (region ? 0.54 : 0.68)) return
    const averageBorder = border.reduce((sum, value) => sum + value, 0) / 4
    const score = coverage * (averageEdge + averageBorder) / 2
    if (score <= bestScore) return
    best = quad
    bestScore = score
  }

  for (const channel of channels) {
    for (const quad of regionQuads(channel, width, height)) prefer(quad, true)
  }
  // Paper does not always separate at a single level, e.g. when a shadow
  // crosses the sheet. Retain contour detection for such cases.
  if (bestScore < 0.35) {
    for (const threshold of [34, 17]) {
      for (const contour of edgeContours(edges, width, height, threshold)) {
        prefer(fitQuad(convexHull(contour)), false, threshold)
      }
    }
  }
  if (!best) return null
  const refined = normalize(sharpenCorners(best, image, edges))
  return isValidQuad(refined) ? refined : normalize(best)
}
