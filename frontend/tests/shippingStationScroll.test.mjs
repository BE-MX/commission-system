import { test } from 'node:test'
import assert from 'node:assert/strict'
import { captureStationScroll, restoredStationScroll } from '../src/views/shipping/composables/stationScroll.js'

const card = (id, top, height = 280) => ({ dataset: { itemId: id }, getBoundingClientRect: () => ({ top, bottom: top + height }) })

test('refresh restores the same product at the same screen position after rows above it change', () => {
  const before = [card('A', -400), card('B', 143), card('C', 439)]
  const position = captureStationScroll(before, 1800, 130, 844)
  assert.deepEqual(position, { scrollY: 1800, itemId: 'B', itemTop: 143 })
  const after = [card('new', -200), card('B', 319), card('C', 650)]
  assert.equal(restoredStationScroll(position, after, 1800), 1976)
})

test('refresh falls back to the old scroll position when the product is removed', () => {
  const position = captureStationScroll([card('A', 160)], 2400, 130, 844)
  assert.equal(restoredStationScroll(position, [card('B', 180)], 2400), 2400)
})

test('refresh at the order header or with no products keeps the exact viewport position', () => {
  const position = captureStationScroll([], 325, 130, 844)
  assert.deepEqual(position, { scrollY: 325, itemId: undefined, itemTop: undefined })
  assert.equal(restoredStationScroll(position, [card('A', 360)], 325), 325)
})

test('refresh at the top stays at the top even when the first product is visible', () => {
  const position = captureStationScroll([card('A', 700)], 0, 130, 844)
  assert.deepEqual(position, { scrollY: 0 })
  assert.equal(restoredStationScroll(position, [card('A', 830)], 0), 0)
})

test('a product below the viewport does not drag the current header position', () => {
  const position = captureStationScroll([card('A', 900)], 200, 130, 844)
  assert.deepEqual(position, { scrollY: 200, itemId: undefined, itemTop: undefined })
  assert.equal(restoredStationScroll(position, [card('A', 1020)], 200), 200)
})
