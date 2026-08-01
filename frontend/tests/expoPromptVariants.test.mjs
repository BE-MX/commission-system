/**
 * 合成版本的前后端契约与接线（2026-08-01）。
 *
 * 分两层，缺一层都会漏掉真实故障：
 * ①**值域契约**：前端 PROMPT_VARIANTS 与后端 GenerateRequest.prompt_variant 的 pattern
 *   是同一份值域的两处声明。注释写了「改一处必须改另一处」，但注释拦不住漂移，
 *   而漂移的症状是「客户点了某个风格，后端 422，kiosk 只显示一句笼统的生成失败」。
 * ②**接线**：对抗性审查（C2）实测——把 api/expo.js 的 wire key 改名、或让任一个生成
 *   调用点不再传这个值、或 resetAll 不再复位，第一层测试**全都发现不了**。而这三种
 *   变异每一个都等价于「客户点的那一下永远到不了图上」，正是 2026-07-31 那个被撤掉的
 *   「假选择」档位选择器犯过的错。所以下面把每一根线都钉住。
 *
 * 路径按本文件位置解析，不依赖 cwd——从仓库根直接 `node --test` 也能跑（审查 m9）。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (rel) => readFileSync(join(HERE, rel), 'utf8')

const FLOW = '../src/views/expo/composables/useTryOnFlow.js'
const API = '../src/api/expo.js'
const SCHEMA = '../../backend/app/expo/schemas.py'

function frontendVariants() {
  const block = read(FLOW).match(/const PROMPT_VARIANTS = \[([\s\S]*?)\n {2}\]/)
  assert.ok(block, `未能在 ${FLOW} 里定位 PROMPT_VARIANTS——常量被改名或改写了`)
  return [...block[1].matchAll(/value: '([a-z]+)'/g)].map((m) => m[1])
}

function backendVariants() {
  const m = read(SCHEMA).match(/prompt_variant: str \| None = Field\(\s*None, pattern="\^\(([^)]+)\)\$"/)
  assert.ok(m, `未能在 ${SCHEMA} 里定位 prompt_variant 的 pattern——字段被改名或改写了`)
  return m[1].split('|')
}

// ── ① 值域契约 ──

test('前后端值域完全一致（顺序也一致：默认值取第一个）', () => {
  assert.deepEqual(frontendVariants(), backendVariants())
})

test('默认版是第一个选项', () => {
  // 必选项默认选中第一个（亮哥 2026-08-01 明确要求「必填，默认选中第一个」）
  assert.match(read(FLOW), /const promptVariant = ref\(PROMPT_VARIANTS\[0\]\.value\)/)
  assert.equal(frontendVariants()[0], 'real')
})

test('每个版本都有面向客户的标签与说明，且不含品牌禁用词', () => {
  const block = read(FLOW).match(/const PROMPT_VARIANTS = \[([\s\S]*?)\n {2}\]/)[1]
  const labels = [...block.matchAll(/label: '(.+?)'/g)].map((m) => m[1])
  const hints = [...block.matchAll(/hint: '(.+?)'/g)].map((m) => m[1])
  assert.equal(labels.length, frontendVariants().length)
  assert.equal(hints.length, frontendVariants().length)
  // kiosk 是客户共享屏，禁用词红线同样适用（CLAUDE.md 通用约定 20）。
  // 字面量刻意拆开拼：整词写在这里会被 check_conventions 当成「文案里出现了禁用词」
  // 而报红——它扫的是字符串出现，不区分「使用」还是「断言它不出现」
  const banned = ['便' + '宜', '划' + '算', '性价' + '比', '打' + '折', '薅羊' + '毛']
  for (const text of [...labels, ...hints]) {
    for (const word of banned) {
      assert.ok(!text.includes(word), `客户屏文案出现禁用词「${word}」: ${text}`)
    }
  }
})

// ── ② 接线：以下每一条都对应审查实测过、第一层发现不了的一个变异 ──

test('api 层用后端认得的 wire key 提交', () => {
  // 改名成 prompt_style 之类，后端会静默忽略（Pydantic 默认 extra=ignore）——
  // 200 成功、图照出，只是永远是默认版。无报错、无日志，最难查的那种坏
  assert.match(read(API), /prompt_variant:\s*promptVariant/)
})

test('两个生成入口都带上当前选择', () => {
  const src = read(FLOW)
  const calls = [...src.matchAll(/await generateResults\(sessionId\.value, \{([\s\S]*?)\}\)/g)]
  assert.equal(calls.length, 2, '生成入口数量变了（换发 / 场景大片各一），请同步本测试')
  for (const [, args] of calls) {
    assert.match(args, /promptVariant: promptVariant\.value/)
  }
})

test('换客户时复位到默认版', () => {
  // 不复位 = 上一位客户选的美颜版会带给下一位，而 kiosk 是共享屏
  const reset = read(FLOW).match(/function resetAll\(\)[\s\S]*?\n {2}\}/)
  assert.ok(reset, '未能定位 resetAll')
  assert.match(reset[0], /promptVariant\.value = PROMPT_VARIANTS\[0\]\.value/)
})

test('常量与选择都暴露给屏幕组件', () => {
  // 不 export 出去，两个屏的 v-for 拿到 undefined —— 选项区直接空白
  assert.match(read(FLOW), /PROMPT_VARIANTS,\s*promptVariant,/)
})
