import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { MOBILE_FLOW_TEMPLATE, mobileFlowAreas } from '../src/views/customer-image/layout.js'

const editor = readFileSync(
  new URL('../src/views/customer-image/CustomerProductEditor.vue', import.meta.url),
  'utf8',
)

test('mobile flow is product rail then logo parameters requirement result and history', () => {
  assert.deepEqual(mobileFlowAreas(), ['products', 'logo', 'options', 'requirement', 'preview', 'history', 'spacer'])
  assert.equal(MOBILE_FLOW_TEMPLATE, '"products" "logo" "options" "requirement" "preview" "history" "spacer"')
})

test('one responsive DOM tree maps each customer section to its executable grid area', () => {
  const expected = {
    products: "t\\('editor\\.selectProduct'\\)",
    logo: 'CustomerLogoUpload',
    options: 'ProductOptionGroup',
    requirement: 'customer-requirement',
    preview: 'GenerationPreview',
    history: 'GenerationHistory',
    spacer: 'mobile-action-spacer',
  }
  for (const [area, content] of Object.entries(expected)) {
    const matches = [...editor.matchAll(new RegExp(`class="[^"]*flow-${area}[^"]*"[\\s\\S]*?${content}`, 'g'))]
    assert.equal(matches.length, 1, `${area} must map one DOM section without duplication`)
  }
  assert.match(editor, /grid-template-areas:\s*var\(--customer-mobile-flow\)/)
  assert.match(editor, /display:\s*contents/)
})
