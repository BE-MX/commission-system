import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/views/layout/MainLayout.vue', import.meta.url), 'utf8')

function openingTag(className) {
  const classIndex = source.indexOf(`class="${className}"`)
  if (classIndex === -1) return ''
  const start = source.lastIndexOf('<', classIndex)
  const end = source.indexOf('>', classIndex)
  return source.slice(start, end + 1)
}

function cssBlock(header) {
  const start = source.indexOf(header)
  const openingBrace = source.indexOf('{', start)
  let depth = 0
  for (let index = openingBrace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    if (source[index] === '}') depth -= 1
    if (depth === 0) return source.slice(start, index + 1)
  }
  return ''
}

test('mobile navigation starts closed without overwriting the desktop preference', () => {
  assert.match(source, /matchMedia\?\.\('\(max-width: 640px\)'\)/)
  assert.match(source, /const isNarrow = ref\(mobileQuery\?\.matches \?\? false\)/)
  assert.match(source, /const desktopCollapse = ref\(false\)/)
  assert.match(source, /const mobileNavigationOpen = ref\(false\)/)
  assert.match(source, /get:\s*\(\)\s*=>\s*isNarrow\.value \|\| desktopCollapse\.value/)
  assert.match(source, /if \(!isNarrow\.value\) desktopCollapse\.value = value/)
  assert.match(source, /mobileQuery\?\.addEventListener\('change', onNarrowChange\)/)
  assert.match(source, /mobileQuery\?\.removeEventListener\('change', onNarrowChange\)/)
})

test('mobile layout opens a navigation drawer and reserves the full content width', () => {
  const toggle = openingTag('collapse-toggle')
  assert.doesNotMatch(toggle, /v-if="!isNarrow"/)
  assert.match(toggle, /mobileNavigationOpen = true/)
  assert.match(toggle, /:aria-expanded=/)
  assert.match(source, /<SidebarNavigation v-if="!isNarrow"/)
  assert.match(source, /<el-drawer v-else v-model="mobileNavigationOpen" direction="ltr"/)
  assert.match(source, /watch\(\(\) => route\.fullPath, \(\) => \{ mobileNavigationOpen\.value = false \}\)/)

  const mobileStyles = cssBlock('@media (max-width: 640px)')
  assert.match(mobileStyles, /\.header\s*\{\s*padding:\s*0 10px;/)
  assert.match(mobileStyles, /\.main-content\s*\{\s*padding:\s*12px 10px;/)
  assert.match(source, /\.right-container\s*\{[\s\S]*?min-width:\s*0;/)
})
