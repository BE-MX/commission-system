// Package/routing labels must never be mistaken for tracking numbers.
export function validWaybillBarcode(value) {
  const number = String(value || '').trim().replace(/\s/g, '').toUpperCase()
  if (/^(JD|2L)/.test(number)) return ''
  return /^(\d{10}|\d{12}|\d{15}|1Z[A-Z0-9]{16}|SF\d{13})$/.test(number) ? number : ''
}
let decoderModule
async function decoder() { return decoderModule ||= import('@zxing/library') }

// Pure pixel entry point also allows regression tests without a browser/camera.
export async function decodeWaybillPixels({ data, width, height }) {
  const { RGBLuminanceSource, HybridBinarizer, BinaryBitmap, Code128Reader, BitArray } = await decoder()
  const luminance = new Uint8ClampedArray(width * height)
  for (let i = 0; i < luminance.length; i++) luminance[i] = (data[i * 4] + 2 * data[i * 4 + 1] + data[i * 4 + 2]) / 4
  for (const rotated of [false, true]) {
    const w = rotated ? height : width, h = rotated ? width : height
    const pixels = rotated ? new Uint8ClampedArray(luminance.length) : luminance
    if (rotated) for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) pixels[x * height + height - y - 1] = luminance[y * width + x]
    const bitmap = new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(pixels, w, h)))
    const reader = new Code128Reader()
    for (let rowIndex = 1; rowIndex < 20; rowIndex++) {
      const y = Math.floor(h * rowIndex / 20)
      let row
      try { row = bitmap.getBlackRow(y, new BitArray(w)) } catch { continue } // Blank/low contrast row.
      const ranges = [[0, w]]
      for (let attempt = 0; ranges.length && attempt < 5; attempt++) {
        const [left, right] = ranges.shift()
        if (right - left < 60) continue
        const segment = new BitArray(w)
        for (let x = left; x < right; x++) if (row.get(x)) segment.set(x)
        try {
          let result, reversed = false
          try { result = reader.decodeRow(y, segment, new Map()) }
          catch { segment.reverse(); reversed = true; result = reader.decodeRow(y, segment, new Map()) }
          const accepted = validWaybillBarcode(result.getText())
          if (accepted) return accepted
          const positions = result.getResultPoints().map(point => reversed ? w - 1 - point.getX() : point.getX())
          // Search either side of a rejected JD/2L code as well as other rows.
          const start = Math.max(left, Math.floor(Math.min(...positions)) - 40)
          const end = Math.min(right, Math.ceil(Math.max(...positions)) + 40)
          ranges.push([left, start], [end, right])
        } catch { /* A normal non-barcode row; keep scanning. */ }
      }
    }
  }
  return ''
}
export async function readWaybillBarcode(image) {
  if (globalThis.BarcodeDetector) {
    try {
      const results = await new BarcodeDetector({ formats: ['code_128', 'code_39', 'itf'] }).detect(image)
      const accepted = results.map(item => validWaybillBarcode(item.rawValue)).find(Boolean)
      if (accepted) return accepted
    } catch (error) { console.debug('Native barcode detector unavailable', error.name) }
  }
  let canvas
  try {
    const width = image.videoWidth || image.width, height = image.videoHeight || image.height
    const scale = Math.min(1, 1920 / Math.max(width, height))
    canvas = document.createElement('canvas'); canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale)
    const context = canvas.getContext('2d', { willReadFrequently: true })
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    return await decodeWaybillPixels(context.getImageData(0, 0, canvas.width, canvas.height))
  } catch (error) {
    console.warn('Barcode decoding failed; OCR remains available', error.name)
    return ''
  } finally { if (canvas) canvas.width = canvas.height = 0 }
}
