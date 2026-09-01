const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const sheetPath = path.resolve(__dirname, '../components/domestic-sheet/domestic-sheet.wxml')

test('special badge uses the stable order category code', function () {
  const source = fs.readFileSync(sheetPath, 'utf8')

  assert.match(source, /wx:if="\{\{item\.order_category === 'special'\}\}"/)
  assert.doesNotMatch(
    source,
    /order_type_label\s*===\s*['"]特单['"]/
  )
})
