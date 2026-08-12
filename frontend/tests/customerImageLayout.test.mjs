import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function read(relativePath) {
  try {
    return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
  } catch {
    return ''
  }
}

const files = {
  portal: read('../src/views/customer-image/CustomerImagePortal.vue'),
  catalog: read('../src/views/customer-image/CustomerProductCatalog.vue'),
  editor: read('../src/views/customer-image/CustomerProductEditor.vue'),
  composable: read('../src/views/customer-image/composables/useCustomerImagePortal.js'),
  logo: read('../src/views/customer-image/components/CustomerLogoUpload.vue'),
  options: read('../src/views/customer-image/components/ProductOptionGroup.vue'),
  history: read('../src/views/customer-image/components/GenerationHistory.vue'),
  preview: read('../src/views/customer-image/components/GenerationPreview.vue'),
}

test('portal replaces the bootstrap shell while preserving the secure route helpers', () => {
  const router = read('../src/router/index.js')
  assert.ok(files.portal, 'missing customer portal')
  assert.match(router, /CustomerImagePortal\.vue/)
  assert.match(router, /captureCustomerImageRouteToken/)
  assert.match(router, /bypassCustomerImageRoute/)
  assert.doesNotMatch(router, /CustomerImageRouteShell/)
})

test('catalog is a bounded search and category flow with real image cards and one command', () => {
  assert.ok(files.catalog)
  assert.match(files.catalog, /search/i)
  assert.match(files.catalog, /category|分类/)
  assert.match(files.catalog, /aspect-ratio/)
  assert.match(files.catalog, /立即设计/)
  assert.match(files.catalog, /coverUrls/)
})

test('editor owns desktop three tracks and mobile ordered flow with a safe-area action', () => {
  assert.ok(files.editor)
  assert.match(files.editor, /272px\s+minmax\(0,\s*1fr\)\s+352px/)
  assert.match(files.editor, /@media\s*\(max-width:\s*760px\)/)
  assert.match(files.editor, /env\(safe-area-inset-bottom/)
  assert.match(files.editor, /data-mobile-step|mobile-step/)
  assert.match(files.portal, /position:\s*sticky/)
  assert.match(files.editor, /position:\s*fixed/)
  assert.match(files.editor, /100dvh/)
  assert.match(files.editor, /mobile-action-spacer/)
})

test('desktop workbench keeps products and history left, preview center, and controls right', () => {
  const left = files.editor.match(/<aside class="product-rail"[\s\S]*?<\/aside>/)?.[0] || ''
  const center = files.editor.match(/<section class="[^"]*preview-column[^"]*"[\s\S]*?<\/section>/)?.[0] || ''
  const right = files.editor.match(/<aside class="control-panel"[\s\S]*?<\/aside>/)?.[0] || ''
  assert.match(left, /选择产品/)
  assert.match(left, /product-card/)
  assert.match(left, /GenerationHistory/)
  assert.match(center, /GenerationPreview/)
  assert.match(right, /CustomerLogoUpload/)
  assert.match(right, /ProductOptionGroup/)
  assert.match(right, /customer-requirement/)
  assert.match(right, /generate-block/)
})

test('customer controls cover logo color boolean requirement quota history preview and download', () => {
  assert.match(files.logo, /type="file"/)
  assert.match(files.logo, /image\/\*/)
  assert.match(files.options, /single_choice/)
  assert.match(files.options, /color_hex/)
  assert.match(files.options, /el-switch/)
  assert.match(files.editor, /maxlength="500"|:maxlength="500"/)
  assert.match(files.editor, /aria-labelledby="requirement-label"/)
  assert.match(files.editor, /剩余额度/)
  assert.match(files.history, /generation/i)
  assert.match(files.preview, /下载/)
})

test('submission lock reaches every mutable editor control', () => {
  assert.match(files.editor, /:disabled="submitting"[^>]*@click="\$emit\('back'\)/)
  assert.match(files.editor, /CustomerLogoUpload[\s\S]*:disabled="submitting"/)
  assert.match(files.editor, /ProductOptionGroup[\s\S]*:disabled="submitting"/)
  assert.match(files.editor, /id="customer-requirement"[\s\S]*:disabled="submitting"/)
  assert.match(files.editor, /generate-feedback/)
  assert.match(files.editor, /scroll-padding-bottom|scroll-margin-bottom/)
})

test('portal data flow uses registered wrappers polling idempotency and blob cleanup', () => {
  assert.match(files.composable, /Promise\.all/)
  assert.match(files.composable, /createGeneration/)
  assert.match(files.composable, /requestId/)
  assert.match(files.composable, /hasActiveGenerations/)
  assert.match(files.composable, /setTimeout/)
  assert.match(files.composable, /assets\.(?:clear|dispose)\(|clearAssets\(|revoke/)
  assert.doesNotMatch(files.composable, /axios\.create|from ['"]axios['"]/)
})

test('UI exposes actionable safe states without internal prompt or provider controls', () => {
  const combined = Object.values(files).join('\n')
  for (const copy of [
    '请先上传品牌 LOGO',
    '可以关闭页面',
    '几十秒到数分钟',
    '此链接已失效',
    '联系您的业务经理',
  ]) assert.ok(combined.includes(copy), `missing ${copy}`)
  assert.doesNotMatch(combined, /Provider|provider_id|prompt_snapshot|pricing_snapshot|storage_path/)
  assert.doesNotMatch(combined, /自由提示词|模型选择|质量选择/)
})

test('motion is bounded accessible and every customer action has a 44px target', () => {
  const combined = Object.values(files).join('\n')
  assert.match(combined, /min-height:\s*44px/)
  assert.match(combined, /prefers-reduced-motion:\s*reduce/)
  assert.match(combined, /result-arrive[\s\S]*180ms/)
  assert.match(combined, /cubic-bezier\(0\.23,\s*1,\s*0\.32,\s*1\)/)
  assert.doesNotMatch(combined, /transition:\s*all/)
  assert.doesNotMatch(combined, /\bease-in\b/)
  assert.doesNotMatch(combined, /scale\(0\)/)
})

test('customer portal source files stay below the 500-line split boundary', () => {
  for (const [name, source] of Object.entries(files)) {
    assert.ok(source, `missing ${name}`)
    assert.ok(source.split(/\r?\n/).length <= 500, `${name} exceeds 500 lines`)
  }
})
