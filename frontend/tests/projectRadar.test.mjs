import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const page = readFileSync(new URL('../src/views/insight/ProjectRadar.vue', import.meta.url), 'utf8')
const detail = readFileSync(new URL('../src/views/insight/components/ProjectRadarDetail.vue', import.meta.url), 'utf8')
const publicPage = readFileSync(new URL('../src/views/insight/ProjectRadarPublicDetail.vue', import.meta.url), 'utf8')
const composable = readFileSync(new URL('../src/views/insight/composables/useProjectRadar.js', import.meta.url), 'utf8')
const navigation = readFileSync(new URL('../src/config/navigation.js', import.meta.url), 'utf8')
const router = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')

test('radar list renders data with standard table and loading only error status', () => {
  assert.match(page, /<ListPageStatus v-if="errorMessage"/)
  assert.doesNotMatch(page, /<ListPageStatus v-if="hasData \|\| errorMessage"/)
  assert.match(page, /class="radar-table list-table"/)
  assert.match(page, /v-sticky-scrollbar/)
  assert.match(page, /border class="radar-table list-table"/)
})

test('capture uses committed filters and persistent job polling', () => {
  assert.match(composable, /pageSize: 20/)
  assert.match(composable, /await listState\.handleSearch\(\)/)
  for (const status of ['completed', 'partial', 'failed', 'awaiting_choice']) assert.ok(composable.includes(`'${status}'`))
  assert.match(composable, /onBeforeUnmount\(stopPolling\)/)
})

test('signed detail is public and read-only while authenticated edits close unread on close', () => {
  assert.match(router, /ProjectRadarPublicDetail/)
  assert.match(router, /meta: \{ title: '项目雷达详情', public: true \}/)
  assert.match(publicPage, /<ProjectRadarDetail v-else-if="item" :item="item" read-only \/>/)
  assert.match(page, /mark_read: true/)
  assert.match(detail, /grid-template-columns: minmax\(0, 1fr\)/)
  assert.match(navigation, /path: '\/insight\/project-radar'/)
})
