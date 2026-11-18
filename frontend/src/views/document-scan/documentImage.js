import { distance, isValidQuad, squareToQuad } from './documentQuad.js'

const OUTPUT_EDGE = 2600

const clamp = (value, min, max) => Math.min(max, Math.max(min, value))
const luma = (r, g, b) => (77 * r + 150 * g + 29 * b) / 256

function canvasFor(width, height) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

export function canvasFrom(source, width, height, limit = OUTPUT_EDGE) {
  const scale = Math.min(1, limit / Math.max(width, height))
  const canvas = canvasFor(Math.max(1, Math.round(width * scale)), Math.max(1, Math.round(height * scale)))
  const ctx = canvas.getContext('2d', { willReadFrequently: true, alpha: false })
  ctx.fillStyle = 'white'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height)
  return canvas
}

export function readDetectionPixels(canvas, source, width, height, maxEdge, quality = 'low') {
  const scale = Math.min(1, maxEdge / Math.max(width, height))
  const w = Math.max(1, Math.round(width * scale))
  const h = Math.max(1, Math.round(height * scale))
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w
    canvas.height = h
  }
  const ctx = canvas.getContext('2d', { willReadFrequently: true, alpha: false })
  ctx.imageSmoothingQuality = quality
  ctx.drawImage(source, 0, 0, w, h)
  return ctx.getImageData(0, 0, w, h)
}

export async function readScanPhoto(file) {
  const url = URL.createObjectURL(file)
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    return canvasFrom(image, image.naturalWidth, image.naturalHeight)
  } finally {
    URL.revokeObjectURL(url)
  }
}

export function scanBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('JPEG encoding failed'))
    }, 'image/jpeg', 0.94)
  })
}

export function rectifyDocument(source, points) {
  if (!isValidQuad(points)) throw new Error('Invalid document corners')
  const { width, height, data } = source
  const quad = points.map(([x, y]) => [x * (width - 1), y * (height - 1)])
  const [a, b, c, d, e, f, g, h] = squareToQuad(quad)
  const targetWidth = Math.max(distance(quad[0], quad[1]), distance(quad[3], quad[2])) + 1
  const targetHeight = Math.max(distance(quad[0], quad[3]), distance(quad[1], quad[2])) + 1
  const scale = Math.min(1, OUTPUT_EDGE / Math.max(targetWidth, targetHeight))
  const w = Math.max(2, Math.round(targetWidth * scale))
  const hgt = Math.max(2, Math.round(targetHeight * scale))
  const output = new Uint8ClampedArray(w * hgt * 4)
  for (let y = 0; y < hgt; y++) {
    const v = y / (hgt - 1)
    for (let x = 0; x < w; x++) {
      const u = x / (w - 1)
      const divisor = g * u + h * v + 1
      const px = clamp((a * u + b * v + c) / divisor, 0, width - 1)
      const py = clamp((d * u + e * v + f) / divisor, 0, height - 1)
      const left = Math.floor(px)
      const top = Math.floor(py)
      const right = Math.min(left + 1, width - 1)
      const bottom = Math.min(top + 1, height - 1)
      const dx = px - left
      const dy = py - top
      const lt = (top * width + left) * 4
      const rt = (top * width + right) * 4
      const lb = (bottom * width + left) * 4
      const rb = (bottom * width + right) * 4
      const dest = (y * w + x) * 4
      for (let ch = 0; ch < 3; ch++) {
        const upper = data[lt + ch] * (1 - dx) + data[rt + ch] * dx
        const lower = data[lb + ch] * (1 - dx) + data[rb + ch] * dx
        output[dest + ch] = upper * (1 - dy) + lower * dy
      }
      output[dest + 3] = 255
    }
  }
  return { data: output, width: w, height: hgt }
}

function estimatePaper({ width, height, data }, tileWidth, tileHeight, columns, rows) {
  const paper = new Float32Array(columns * rows * 3)
  for (let row = 0; row < rows; row++) {
    for (let column = 0; column < columns; column++) {
      const histogram = new Uint32Array(256)
      const samples = []
      for (let y = row * tileHeight; y < Math.min(height, (row + 1) * tileHeight); y += 4) {
        for (let x = column * tileWidth; x < Math.min(width, (column + 1) * tileWidth); x += 4) {
          const i = (y * width + x) * 4
          const gray = Math.round(luma(data[i], data[i + 1], data[i + 2]))
          histogram[gray]++
          samples.push([i, gray])
        }
      }
      const quantile = fraction => {
        let count = 0
        for (let gray = 0; gray < histogram.length; gray++) {
          count += histogram[gray]
          if (count >= samples.length * fraction) return gray
        }
        return 255
      }
      const low = quantile(0.73)
      const high = quantile(0.94)
      const means = [0, 0, 0]
      let count = 0
      for (const [index, gray] of samples) {
        if (gray < low || gray > high) continue
        for (let ch = 0; ch < 3; ch++) means[ch] += data[index + ch]
        count++
      }
      const offset = (row * columns + column) * 3
      for (let ch = 0; ch < 3; ch++) paper[offset + ch] = Math.max(112, means[ch] / Math.max(1, count))
    }
  }
  return paper
}

export function applyScanEffect({ width, height, data }, effect) {
  if (effect === 'original') return data
  // Balance the color and brightness of the surrounding paper before boosting
  // ink contrast. Interpolation keeps tile boundaries invisible.
  const columns = Math.min(12, Math.ceil(width / 56))
  const rows = Math.min(12, Math.ceil(height / 56))
  const tileWidth = Math.ceil(width / columns)
  const tileHeight = Math.ceil(height / rows)
  const paper = estimatePaper({ width, height, data }, tileWidth, tileHeight, columns, rows)
  const output = new Uint8ClampedArray(data.length)
  for (let y = 0; y < height; y++) {
    const gridY = clamp(y / tileHeight - 0.5, 0, rows - 1)
    const top = Math.floor(gridY)
    const bottom = Math.min(top + 1, rows - 1)
    const dy = gridY - top
    for (let x = 0; x < width; x++) {
      const gridX = clamp(x / tileWidth - 0.5, 0, columns - 1)
      const left = Math.floor(gridX)
      const right = Math.min(left + 1, columns - 1)
      const dx = gridX - left
      const a = (top * columns + left) * 3
      const b = (top * columns + right) * 3
      const c = (bottom * columns + left) * 3
      const d = (bottom * columns + right) * 3
      const i = (y * width + x) * 4
      for (let ch = 0; ch < 3; ch++) {
        const rangeTop = paper[a + ch] * (1 - dx) + paper[b + ch] * dx
        const rangeBottom = paper[c + ch] * (1 - dx) + paper[d + ch] * dx
        const whiteLevel = (rangeTop * (1 - dy) + rangeBottom * dy) * 0.97
        output[i + ch] = 255 * (1 - 1.8 * (1 - data[i + ch] / whiteLevel))
      }
      if (effect === 'mono') {
        const gray = luma(output[i], output[i + 1], output[i + 2])
        output[i] = output[i + 1] = output[i + 2] = (gray - 135) * 2.6 + 160
      }
      output[i + 3] = 255
    }
  }
  return output
}

export function renderScan(scan, effect) {
  const canvas = canvasFor(scan.width, scan.height)
  const pixels = applyScanEffect(scan, effect)
  canvas.getContext('2d').putImageData(new ImageData(pixels, scan.width, scan.height), 0, 0)
  return canvas
}
