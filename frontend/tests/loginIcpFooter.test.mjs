import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/views/auth/LoginPage.vue', import.meta.url),
  'utf8',
)

test('login page exposes the ICP registration and organizer on every viewport', () => {
  const formSideIndex = source.indexOf('class="form-side')
  const filingIndex = source.indexOf('aria-label="网站备案信息"')

  assert.ok(formSideIndex >= 0, 'login form area should exist')
  assert.ok(filingIndex > formSideIndex, 'filing information should live in the always-visible form area')
  assert.match(source, />\s*鲁ICP备2023012060号-3\s*<\/a>/)
  assert.match(source, />\s*鄄城莱莎发制品有限公司\s*<\/span>/)
})

test('ICP registration opens the MIIT site safely in a new tab', () => {
  assert.match(
    source,
    /<a\s+href="https:\/\/beian\.miit\.gov\.cn\/"\s+target="_blank"\s+rel="noopener noreferrer"/,
  )
})

test('filing footer is pinned below the form and adapts on narrow screens', () => {
  assert.match(
    source,
    /\.site-filing\s*\{[\s\S]*?position:\s*absolute;[\s\S]*?bottom:\s*18px;/,
  )
  assert.match(source, /@media \(max-width:\s*640px\)\s*\{[\s\S]*?\.site-filing\s*\{[\s\S]*?flex-wrap:\s*wrap;/)
})
