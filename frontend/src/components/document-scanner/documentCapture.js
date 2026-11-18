import { canvasFrom, renderScan, scanBlob } from './documentImage.js'

export async function encodeCapture(source, rectified, effect, maxBytes, isCurrent) {
  const scanCanvas = renderScan(rectified, effect)
  let originalCanvas
  try {
    const scan = await scanBlob(scanCanvas, 0.90)
    if (!isCurrent()) return null
    if (scan.size > maxBytes) throw new RangeError('Scan exceeds limit')

    originalCanvas = canvasFrom(source, source.width, source.height, 2560)
    let original = await scanBlob(originalCanvas, 0.85)
    if (original.size + scan.size > maxBytes) original = await scanBlob(originalCanvas, 0.65)
    if (original.size + scan.size > maxBytes && isCurrent()) {
      originalCanvas.width = originalCanvas.height = 0
      originalCanvas = canvasFrom(source, source.width, source.height, 1600)
      original = await scanBlob(originalCanvas, 0.65)
    }

    return { scan, original: original.size + scan.size <= maxBytes ? original : null }
  } finally {
    scanCanvas.width = scanCanvas.height = 0
    if (originalCanvas) originalCanvas.width = originalCanvas.height = 0
  }
}
