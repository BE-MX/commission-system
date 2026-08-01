/**
 * 合成版本值域的前后端契约（2026-08-01）。
 *
 * 前端 useTryOnFlow.PROMPT_VARIANTS 与后端 GenerateRequest.prompt_variant 的 pattern
 * 是同一份值域的两处声明，注释写了「改一处必须改另一处」——但注释拦不住漂移，
 * 而漂移的症状是「客户点了某个风格，后端 422，kiosk 只显示一句笼统的生成失败」。
 * 这个测试直接读两边的源码比对，让漂移在 CI/本地立刻可见。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const FLOW = 'src/views/expo/composables/useTryOnFlow.js'
const SCHEMA = '../backend/app/expo/schemas.py'

function frontendVariants() {
  const src = readFileSync(FLOW, 'utf8')
  const block = src.match(/const PROMPT_VARIANTS = \[([\s\S]*?)\n {2}\]/)
  assert.ok(block, `未能在 ${FLOW} 里定位 PROMPT_VARIANTS——常量被改名或改写了`)
  return [...block[1].matchAll(/value: '([a-z]+)'/g)].map((m) => m[1])
}

function backendVariants() {
  const src = readFileSync(SCHEMA, 'utf8')
  const m = src.match(/prompt_variant: str \| None = Field\(\s*None, pattern="\^\(([^)]+)\)\$"/)
  assert.ok(m, `未能在 ${SCHEMA} 里定位 prompt_variant 的 pattern——字段被改名或改写了`)
  return m[1].split('|')
}

test('前后端值域完全一致（顺序也一致：默认值取第一个）', () => {
  assert.deepEqual(frontendVariants(), backendVariants())
})

test('默认版是第一个选项', () => {
  const src = readFileSync(FLOW, 'utf8')
  // 必选项默认选中第一个（亮哥 2026-08-01 明确要求「必填，默认选中第一个」）
  assert.match(src, /const promptVariant = ref\(PROMPT_VARIANTS\[0\]\.value\)/)
  assert.equal(frontendVariants()[0], 'real')
})

test('每个版本都有面向客户的标签与说明', () => {
  const src = readFileSync(FLOW, 'utf8')
  const block = src.match(/const PROMPT_VARIANTS = \[([\s\S]*?)\n {2}\]/)[1]
  const labels = [...block.matchAll(/label: '(.+?)'/g)].map((m) => m[1])
  const hints = [...block.matchAll(/hint: '(.+?)'/g)].map((m) => m[1])
  assert.equal(labels.length, frontendVariants().length)
  assert.equal(hints.length, frontendVariants().length)
  // kiosk 是客户共享屏，禁用词红线同样适用（CLAUDE.md 通用约定 20）
  for (const text of [...labels, ...hints]) {
    for (const banned of ['便宜', '划算', '性价比', '打折', '薅羊毛']) {
      assert.ok(!text.includes(banned), `客户屏文案出现禁用词「${banned}」: ${text}`)
    }
  }
})
