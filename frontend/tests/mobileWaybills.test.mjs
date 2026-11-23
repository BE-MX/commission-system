import test from 'node:test'
import assert from 'node:assert/strict'
import { Code128Reader } from '@zxing/library'
import { validWaybillBarcode, decodeWaybillPixels } from '../src/components/document-scanner/waybillBarcode.js'
import { canSubmitPreview, previewFingerprint } from '../src/views/shipping/composables/mobileWaybillState.js'

function fixture(texts) {
  const width = 1100, height = texts.length * 100
  const data = new Uint8ClampedArray(width * height * 4).fill(255)
  for (const [index, text] of texts.entries()) {
    const codes = [104, ...Array.from(text, char => char.charCodeAt(0) - 32)]
    codes.push((104 + codes.slice(1).reduce((sum, value, i) => sum + value * (i + 1), 0)) % 103, 106)
    let x = 30
    for (const code of codes) {
      const pattern = Code128Reader.CODE_PATTERNS[code]
      for (let part = 0; part < pattern.length; part++) {
        const size = pattern[part] * 3
        if (part % 2 === 0) for (let y = index * 100 + 15; y < index * 100 + 85; y++) for (let offset = 0; offset < size; offset++) {
          const position = (y * width + x + offset) * 4
          data[position] = data[position + 1] = data[position + 2] = 0
        }
        x += size
      }
    }
  }
  return { data, width, height }
}
test('reject package and routing barcodes, retain DHL tracking', () => {
  assert.equal(validWaybillBarcode('JD1234567890'), '')
  assert.equal(validWaybillBarcode('2L1234567890'), '')
  assert.equal(validWaybillBarcode('1234567890'), '1234567890')
})
test('real Code128 pixels decode without native BarcodeDetector', async () => {
  assert.equal(await decodeWaybillPixels(fixture(['1234567890'])), '1234567890')
})
test('JD and 2L labels do not mask a valid tracking label', async () => {
  assert.equal(await decodeWaybillPixels(fixture(['JD1234567890', '2L1234567890', '1234567890'])), '1234567890')
})
test('country warning requires confirmation and every signed field invalidates preview', () => {
  const form = { waybill_no: '1234567890', carrier: 'DHL', recipient_country: 'US', recipient_name: 'Alice' }
  const fingerprint = previewFingerprint(form)
  const preview = { preview_token: 'signed', format_valid: true, can_submit: true, existing: { blocked: false }, warnings: [{ code: 'country', requires_confirmation: true }] }
  assert.equal(canSubmitPreview(preview, fingerprint, form, 'photo', []), false)
  assert.equal(canSubmitPreview(preview, fingerprint, form, 'photo', ['country']), true)
  for (const field of ['waybill_no', 'carrier', 'recipient_country', 'recipient_name']) assert.equal(canSubmitPreview(preview, fingerprint, { ...form, [field]: 'changed' }, 'photo', ['country']), false)
  assert.equal(canSubmitPreview({ ...preview, existing: { blocked: true } }, fingerprint, form, 'photo', ['country']), false)
  assert.equal(canSubmitPreview(preview, fingerprint, form, '', ['country']), false)
})

test('a routing barcode beside the waybill does not hide it', async () => {
  const left = fixture(['JD1234567890']), right = fixture(['1234567890'])
  const width = left.width + right.width, height = left.height, data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) {
    data.set(left.data.subarray(y * left.width * 4, (y + 1) * left.width * 4), y * width * 4)
    data.set(right.data.subarray(y * right.width * 4, (y + 1) * right.width * 4), (y * width + left.width) * 4)
  }
  assert.equal(await decodeWaybillPixels({ data, width, height }), '1234567890')
})

test('rotated Code128 image is decoded on Safari fallback', async () => {
  const original = fixture(['1234567890'])
  const width = original.height, height = original.width, data = new Uint8ClampedArray(original.data.length)
  for (let y = 0; y < original.height; y++) for (let x = 0; x < original.width; x++) data.set(original.data.subarray((y * original.width + x) * 4, (y * original.width + x) * 4 + 4), (x * width + width - y - 1) * 4)
  assert.equal(await decodeWaybillPixels({ data, width, height }), '1234567890')
})
