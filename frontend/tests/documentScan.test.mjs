import assert from 'node:assert/strict'
import test from 'node:test'
import { isDocumentScanPath } from '../src/router/documentScanRoute.js'
import { detectDocument } from '../src/components/document-scanner/documentEdges.js'
import { applyScanEffect, rectifyDocument } from '../src/components/document-scanner/documentImage.js'
import { fullFrame, isValidQuad, padDetectedQuad, squareToQuad } from '../src/components/document-scanner/documentQuad.js'

const paperCorners = [[0.16, 0.19], [0.76, 0.12], [0.88, 0.78], [0.13, 0.84]]

function image(width, height, color) {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      data.set([...color(x, y), 255], (y * width + x) * 4)
    }
  }
  return { width, height, data }
}

function tiltedPaper(width, height, background, paper) {
  return image(width, height, (x, y) => {
    const inside = paperCorners.every(([ax, ay], index) => {
      const [bx, by] = paperCorners[(index + 1) % 4]
      return (bx - ax) * (y / height - ay) - (by - ay) * (x / width - ax) >= 0
    })
    if (!inside) return [background, background, background]
    const ink = x > width * 0.27 && x < width * 0.65 && y > height * 0.26 && y < height * 0.75 && y % 14 < 2
    const value = ink ? 28 : paper
    return [value, value, value]
  })
}

test('detects an angled page with horizontal printed lines in portrait and landscape photos', () => {
  for (const [width, height] of [[288, 384], [384, 244]]) {
    const detected = detectDocument(tiltedPaper(width, height, 48, 222))
    assert.ok(detected)
    for (const [index, [x, y]] of detected.entries()) {
      assert.ok(Math.hypot(x - paperCorners[index][0], y - paperCorners[index][1]) < 0.025)
    }
  }
})

test('prefers the outer edges of a pink form over its high-contrast grid', () => {
  const width = 216, height = 384
  const photo = image(width, height, (x, y) => {
    const inside = paperCorners.every(([ax, ay], index) => {
      const [bx, by] = paperCorners[(index + 1) % 4]
      return (bx - ax) * (y / height - ay) - (by - ay) * (x / width - ax) >= 0
    })
    if (!inside) return [167, 184, 151]
    const grid = x > 54 && x < 153 && y > 105 && y < 276
    if (grid && (x % 24 < 2 || y % 19 < 2 || x < 57 || x > 150 || y < 109 || y > 272)) {
      return [57, 57, 64]
    }
    return [200, 171, 189]
  })
  const detected = detectDocument(photo)
  assert.ok(detected)
  for (const [i, point] of detected.entries()) {
    assert.ok(Math.hypot(point[0] - paperCorners[i][0], point[1] - paperCorners[i][1]) < 0.026)
  }
})

test('does not report an inner grid when the complete paper is outside the frame', () => {
  const photo = image(288, 384, (x, y) => {
    const grid = x > 38 && x < 248 && y > 48 && y < 336
    return grid && (x % 26 < 2 || y % 20 < 2 || x < 41 || x > 244 || y < 52 || y > 332)
      ? [54, 49, 55]
      : [181, 165, 175]
  })
  assert.equal(detectDocument(photo), null)
})

test('falls back to manual corners when the photo has no contained four-sided page', () => {
  const noEdges = image(180, 280, () => [210, 210, 210])
  const acrossFrame = image(320, 240, (x) => x < 178 ? [200, 200, 200] : [41, 41, 41])
  assert.equal(detectDocument(noEdges), null)
  assert.equal(detectDocument(acrossFrame), null)
})

test('rejects crossed, collapsed, and out-of-bounds corners', () => {
  assert.equal(isValidQuad(fullFrame()), true)
  assert.equal(isValidQuad([[0, 0], [1, 1], [1, 0], [0, 1]]), false)
  assert.equal(isValidQuad([[0, 0], [0.99, 0], [1, 0], [0, 1]]), false)
  assert.equal(isValidQuad([[0, 0], [1.2, 0], [1, 1], [0, 1]]), false)
})

test('automatic crop leaves room for edge printing without going outside the frame', () => {
  const detected = [[0.03, 0.12], [0.92, 0.14], [0.96, 0.88], [0.02, 0.85]]
  const padded = padDetectedQuad(detected)
  assert.ok(isValidQuad(padded))
  assert.ok(padded[0][1] < detected[0][1] - 0.025)
  assert.ok(padded[2][1] > detected[2][1] + 0.025)
  assert.equal(padded[3][0], 0)
  assert.deepEqual(padDetectedQuad(fullFrame()), fullFrame())
})

test('perspective transform maps each output corner to its matching photo corner', () => {
  const [a, b, c, d, e, f, g, h] = squareToQuad(paperCorners)
  for (const [index, [u, v]] of fullFrame().entries()) {
    const scale = g * u + h * v + 1
    const [expectedX, expectedY] = paperCorners[index]
    assert.ok(Math.abs((a * u + b * v + c) / scale - expectedX) < 1e-10)
    assert.ok(Math.abs((d * u + e * v + f) / scale - expectedY) < 1e-10)
  }
})

test('rectification samples inside the selected document and keeps full-frame pixels intact', () => {
  const input = tiltedPaper(160, 222, 20, 205)
  const insetQuad = [[0.23, 0.24], [0.72, 0.19], [0.81, 0.73], [0.2, 0.79]]
  const scan = rectifyDocument(input, insetQuad)
  assert.ok(scan.width < input.width && scan.height < input.height)
  assert.ok(scan.data.filter((value, index) => index % 4 === 0 && value === 205).length > scan.width * scan.height * 0.8)
  assert.deepEqual(rectifyDocument(input, fullFrame()), input)
})

test('enhanced effect brightens a shadowed paper and black and white retains dark text', () => {
  const input = image(180, 180, (x, y) => {
    if (y === 90) return [38, 28, 31]
    return x < 60 ? [160, 151, 149] : [232, 218, 207]
  })
  const textOffset = (90 * input.width + 20) * 4
  const enhanced = applyScanEffect(input, 'enhanced')
  const mono = applyScanEffect(input, 'mono')
  assert.equal(applyScanEffect(input, 'original'), input.data)
  assert.ok(enhanced[0] > input.data[0] + 40)
  assert.ok(enhanced[textOffset] < 70)
  assert.deepEqual([...mono.subarray(0, 4)], [255, 255, 255, 255])
  assert.deepEqual([...mono.subarray(textOffset, textOffset + 4)], [0, 0, 0, 255])
})

test('enhancement neutralizes pink paper while keeping dark print and colored stamps distinct', () => {
  const photo = image(170, 190, (x, y) => {
    if (y === 90) return [100, 94, 98]
    if (x > 102 && x < 120 && y > 135 && y < 151) return [138, 65, 73]
    return x < 90 ? [175, 161, 168] : [195, 180, 187]
  })
  const pixels = applyScanEffect(photo, 'enhanced')
  const print = (90 * photo.width + 22) * 4
  const stamp = (140 * photo.width + 110) * 4
  assert.deepEqual([...pixels.subarray(0, 4)], [255, 255, 255, 255])
  assert.ok(pixels[print] < 100)
  assert.ok(pixels[stamp] - pixels[stamp + 1] > 60)
})

test('recognizes the mobile document deep link without matching other routes', () => {
  for (const path of ['/document-scan', '/document-scan/?from=mobile#scan']) {
    assert.equal(isDocumentScanPath(path), true)
  }
  for (const path of ['/document-scan-other', '/document-scan/other', '//example.com/document-scan', '/m/']) {
    assert.equal(isDocumentScanPath(path), false)
  }
})
