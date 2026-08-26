import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRenderer, defineComponent, h } from 'vue'

import {
  CUSTOMER_IMAGE_LOCALE_KEY,
  CUSTOMER_IMAGE_MESSAGES,
  customerImageMessage,
  normalizeCustomerImageLocale,
  provideCustomerImageI18n,
  readCustomerImageLocale,
  translateCustomerImage,
  useCustomerImageI18n,
  writeCustomerImageLocale,
} from '../src/views/customer-image/i18n.js'

function read(relativePath) {
  try {
    return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
  } catch {
    return ''
  }
}

const languageSwitcherSource = read('../src/views/customer-image/components/LanguageSwitcher.vue')
const portalSource = read('../src/views/customer-image/CustomerImagePortal.vue')
const fixedCopySources = {
  catalog: read('../src/views/customer-image/CustomerProductCatalog.vue'),
  editor: read('../src/views/customer-image/CustomerProductEditor.vue'),
  logo: read('../src/views/customer-image/components/CustomerLogoUpload.vue'),
  options: read('../src/views/customer-image/components/ProductOptionGroup.vue'),
  preview: read('../src/views/customer-image/components/GenerationPreview.vue'),
  history: read('../src/views/customer-image/components/GenerationHistory.vue'),
}

test('normalizes missing and unsupported locales to English', () => {
  assert.equal(CUSTOMER_IMAGE_LOCALE_KEY, 'ark_customer_image_locale')
  assert.equal(normalizeCustomerImageLocale(undefined), 'en')
  assert.equal(normalizeCustomerImageLocale('en'), 'en')
  assert.equal(normalizeCustomerImageLocale('zh-CN'), 'zh-CN')
  assert.equal(normalizeCustomerImageLocale('fr'), 'en')
})

test('reads locale safely and falls back when storage is unavailable', () => {
  assert.equal(readCustomerImageLocale({ getItem: () => null }), 'en')
  assert.equal(readCustomerImageLocale({ getItem: () => 'zh-CN' }), 'zh-CN')
  assert.equal(readCustomerImageLocale({ getItem: () => 'broken' }), 'en')
  assert.equal(readCustomerImageLocale({ getItem: () => { throw new Error('denied') } }), 'en')
  assert.equal(readCustomerImageLocale(undefined), 'en')
})

test('writes normalized locale without exposing storage failures', () => {
  const writes = []
  assert.doesNotThrow(() => writeCustomerImageLocale({
    setItem(key, value) { writes.push([key, value]) },
  }, 'zh-CN'))
  assert.deepEqual(writes, [[CUSTOMER_IMAGE_LOCALE_KEY, 'zh-CN']])

  assert.doesNotThrow(() => writeCustomerImageLocale({
    setItem() { throw new Error('quota exceeded') },
  }, 'en'))
  assert.doesNotThrow(() => writeCustomerImageLocale(undefined, 'en'))
})

test('translates, interpolates, and falls back through English to the key', () => {
  assert.equal(
    translateCustomerImage('en', 'quota.copy', { count: 3 }),
    'This generation uses 1 credit. 3 remaining.',
  )
  assert.equal(
    translateCustomerImage('zh-CN', 'quota.copy', { count: 3 }),
    '本次生成将使用 1 次额度，剩余 3 次',
  )
  assert.equal(
    translateCustomerImage('zh-CN', 'generation.completed.announcement', { product: 'Box' }),
    'Box 效果图已生成',
  )
  assert.equal(translateCustomerImage('fr', 'portal.loading.title'), 'Loading your product design studio…')
  assert.equal(translateCustomerImage('zh-CN', 'missing.message'), 'missing.message')
})

test('falls back to English when a supported locale is missing a message', () => {
  const messages = {
    en: { 'fallback.greeting': 'Hello, {name}.' },
    'zh-CN': {},
  }

  assert.equal(
    translateCustomerImage('zh-CN', 'fallback.greeting', { name: 'Mia' }, messages),
    'Hello, Mia.',
  )
})

test('creates stable message descriptors', () => {
  assert.deepEqual(customerImageMessage('status.completed', { product: 'Box' }), {
    key: 'status.completed',
    params: { product: 'Box' },
  })
  assert.deepEqual(customerImageMessage('portal.retry'), { key: 'portal.retry', params: {} })
})

test('contains bilingual fixed UI copy for every portal surface', () => {
  const keys = [
    'portal.loading.title', 'portal.loading.detail', 'portal.invalid.title', 'portal.invalid.detail',
    'portal.contactManager', 'portal.empty.title', 'portal.empty.detail', 'portal.error.title',
    'portal.retry', 'portal.brand.kicker', 'portal.brand.subtitle', 'portal.exclusiveChannel',
    'language.label', 'language.english', 'language.chinese',
    'catalog.eyebrow', 'catalog.title', 'catalog.titleForCustomer', 'catalog.intro',
    'catalog.search.label', 'catalog.search.placeholder', 'catalog.categories.label',
    'catalog.category.all', 'catalog.products.label', 'catalog.product.fallback',
    'catalog.product.descriptionFallback', 'catalog.product.designNow', 'catalog.empty.title',
    'catalog.empty.detail', 'catalog.empty.showAll',
    'editor.allProducts', 'editor.styleEyebrow', 'editor.customizeEyebrow',
    'editor.selectProduct', 'editor.selectProductDetail',
    'editor.customize', 'editor.options.title', 'editor.options.detail',
    'editor.requirement.title', 'editor.requirement.detail', 'editor.requirement.placeholder',
    'editor.quota.label', 'editor.generate', 'editor.submitting',
    'upload.title', 'upload.detail', 'upload.previewAlt', 'upload.uploading',
    'upload.replace', 'upload.choose', 'upload.replaceDetail', 'upload.chooseDetail', 'upload.required',
    'options.required', 'options.yes', 'options.no',
    'quota.copy', 'quota.logoRequired', 'quota.optionsRequired', 'quota.exhausted', 'quota.submitting',
    'generation.queued.detail', 'generation.running.detail', 'generation.succeeded.detail',
    'generation.failed.detail', 'generation.processing.detail', 'generation.completed.announcement',
    'preview.eyebrow', 'preview.titleFallback', 'preview.download', 'preview.resultAlt',
    'preview.referenceAlt', 'preview.placeholder', 'preview.failed', 'preview.running',
    'preview.queued', 'preview.queuedNote', 'preview.runningNote', 'preview.live', 'preview.signature',
    'history.title', 'history.empty', 'history.status.queued', 'history.status.running',
    'history.status.succeeded', 'history.status.failed', 'history.status.processing',
    'errors.invalidLink', 'errors.rateLimited', 'errors.uploadTooLarge', 'errors.uploadInvalid',
    'errors.quotaExhausted', 'errors.settingsChanged', 'errors.logoRequired', 'errors.serviceUnavailable',
    'errors.logoUploadFailed', 'errors.settingsRefreshFailed', 'errors.generationConflict',
    'errors.generationFailed', 'errors.pageLoadFailed',
    'settings.logoUpdated', 'settings.updated', 'download.productFallback', 'download.suffix',
  ]

  const messages = CUSTOMER_IMAGE_MESSAGES
  assert.ok(messages, 'the production catalog must be directly inspectable')
  assert.equal(Object.isFrozen(messages), true, 'the catalog root must be read-only')
  assert.equal(keys.length, 104)

  for (const locale of ['en', 'zh-CN']) {
    assert.equal(Object.isFrozen(messages[locale]), true, `${locale} catalog must be read-only`)
    assert.deepEqual(Object.keys(messages[locale]).sort(), [...keys].sort(), `${locale} keys`)
    for (const [key, value] of Object.entries(messages[locale])) {
      assert.equal(typeof value, 'string', `${locale}.${key} must be a string`)
      assert.notEqual(value.trim(), '', `${locale}.${key} must not be empty`)
    }
  }
})

test('provides one reactive locale and restores the document language on unmount', async () => {
  const writes = []
  const storage = {
    getItem: () => 'zh-CN',
    setItem: (key, value) => writes.push([key, value]),
  }
  const originalDocument = globalThis.document
  globalThis.document = { documentElement: { lang: 'fr' } }

  let injected
  const Child = defineComponent({
    setup() {
      injected = useCustomerImageI18n()
      return () => h('span', injected.t('portal.retry'))
    },
  })
  const Root = defineComponent({
    setup() {
      provideCustomerImageI18n(storage)
      return () => h(Child)
    },
  })
  const renderer = createRenderer({
    patchProp() {},
    insert(child, parent) { parent.children ??= []; parent.children.push(child) },
    remove() {},
    createElement: type => ({ type, children: [] }),
    createText: text => ({ text }),
    createComment: text => ({ comment: text }),
    setText(node, text) { node.text = text },
    setElementText(node, text) { node.text = text },
    parentNode: () => null,
    nextSibling: () => null,
  })
  const app = renderer.createApp(Root)

  try {
    app.mount({ children: [] })
    assert.equal(injected.locale.value, 'zh-CN')
    assert.equal(globalThis.document.documentElement.lang, 'zh-CN')
    assert.equal(injected.tm(customerImageMessage('portal.retry')), '重新加载')

    injected.setLocale('en')
    assert.equal(injected.locale.value, 'en')
    assert.equal(globalThis.document.documentElement.lang, 'en')
    assert.deepEqual(writes, [[CUSTOMER_IMAGE_LOCALE_KEY, 'en']])

    app.unmount()
    assert.equal(globalThis.document.documentElement.lang, 'fr')
  } finally {
    globalThis.document = originalDocument
  }
})

test('requires an installed provider', () => {
  const errors = []
  const originalError = console.error
  console.error = (...args) => errors.push(args)
  const Root = defineComponent({
    setup() {
      assert.throws(() => useCustomerImageI18n(), /provideCustomerImageI18n/)
      return () => h('div')
    },
  })
  const renderer = createRenderer({
    patchProp() {}, insert() {}, remove() {}, createElement: type => ({ type }),
    createText: text => ({ text }), createComment: text => ({ comment: text }),
    setText() {}, setElementText() {}, parentNode: () => null, nextSibling: () => null,
  })

  try {
    renderer.createApp(Root).mount({})
  } finally {
    console.error = originalError
  }
})

test('language switcher is a native accessible two-language control', () => {
  assert.ok(languageSwitcherSource, 'missing LanguageSwitcher.vue')
  assert.match(languageSwitcherSource, /useCustomerImageI18n/)
  assert.match(languageSwitcherSource, /:aria-label="t\('language\.label'\)"/)
  assert.match(languageSwitcherSource, /value:\s*'en'[\s\S]*?labelKey:\s*'language\.english'[\s\S]*?shortLabel:\s*'EN'/)
  assert.match(languageSwitcherSource, /value:\s*'zh-CN'[\s\S]*?labelKey:\s*'language\.chinese'[\s\S]*?shortLabel:\s*'中文'/)
  assert.match(languageSwitcherSource, /v-for="option in languageOptions"/)
  assert.match(languageSwitcherSource, /:key="option\.value"/)
  assert.match(languageSwitcherSource, /:aria-label="t\(option\.labelKey\)"/)
  assert.match(languageSwitcherSource, /:aria-pressed="locale === option\.value"/)
  assert.match(languageSwitcherSource, /@click="setLocale\(option\.value\)"/)
  assert.match(languageSwitcherSource, /\{\{\s*option\.shortLabel\s*\}\}/)
  assert.match(languageSwitcherSource, /min-height:\s*44px/)
})

test('language switcher motion is bounded and pointer-aware', () => {
  assert.match(languageSwitcherSource, /transition:\s*transform\s+160ms\s+cubic-bezier\(0\.23,\s*1,\s*0\.32,\s*1\)/)
  assert.match(languageSwitcherSource, /:active[\s\S]*?transform:\s*scale\(\.97\)/)
  assert.match(languageSwitcherSource, /@media\s*\(hover:\s*hover\)\s*and\s*\(pointer:\s*fine\)/)
  assert.match(languageSwitcherSource, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?transform:\s*none/)
  assert.match(languageSwitcherSource, /outline:\s*3px\s+solid\s+var\(--cip-accent-strong\)/)
  assert.match(languageSwitcherSource, /outline-offset:\s*2px/)
  assert.match(languageSwitcherSource, /top:\s*max\(5px,\s*env\(safe-area-inset-top\)\)/)
  assert.match(languageSwitcherSource, /right:\s*max\(8px,\s*env\(safe-area-inset-right\)\)/)
  assert.doesNotMatch(languageSwitcherSource, /transition:\s*all/)
})

test('portal installs i18n before its hook and keeps the switcher outside every state branch', () => {
  const provider = portalSource.indexOf('provideCustomerImageI18n()')
  const portalHook = portalSource.indexOf('useCustomerImagePortal({')
  const switcher = portalSource.indexOf('<LanguageSwitcher')
  const firstStateBranch = portalSource.indexOf('v-if="state.view')

  assert.ok(provider >= 0, 'portal must install customer image i18n')
  assert.ok(portalHook > provider, 'i18n provider must be installed before the portal hook')
  assert.ok(switcher >= 0 && switcher < firstStateBranch, 'switcher must remain outside state branches')
  assert.match(portalSource, /const\s*\{\s*t,\s*tm\s*\}\s*=\s*provideCustomerImageI18n\(\)/)
  assert.match(portalSource, /<LanguageSwitcher\s*\/?>/)
  assert.match(portalSource, /tm\(state\.(?:notice|error)\)/)
})

test('portal shell copy is fully catalog-driven', () => {
  for (const key of [
    'portal.loading.title', 'portal.loading.detail', 'portal.invalid.title', 'portal.invalid.detail',
    'portal.contactManager', 'portal.empty.title', 'portal.empty.detail', 'portal.error.title',
    'portal.retry', 'portal.brand.kicker', 'portal.brand.subtitle', 'portal.exclusiveChannel',
  ]) assert.match(portalSource, new RegExp(`t\\(['"]${key.replaceAll('.', '\\.')}`), `missing ${key}`)

  const withoutLanguageLabel = portalSource.replaceAll('中文', '')
  for (const copy of [
    '正在加载产品效果图工作台', '马上就好', '此链接已失效', '请联系您的业务经理',
    '联系您的业务经理', '当前没有可设计的产品', '页面暂时无法加载', '重新加载',
    '莱莎产品效果图', '专属定制通道',
  ]) assert.equal(withoutLanguageLabel.includes(copy), false, `portal shell still hard-codes ${copy}`)
})

test('all six customer surfaces consume the shared i18n provider without fixed Chinese copy', () => {
  for (const [name, source] of Object.entries(fixedCopySources)) {
    assert.ok(source, `missing ${name} source`)
    assert.match(source, /useCustomerImageI18n\(\)/, `${name} must consume the portal locale`)
    assert.match(source, /\bt\(/, `${name} must translate fixed copy`)
    assert.doesNotMatch(source, /[\u3400-\u9fff]/u, `${name} still contains fixed Chinese copy`)
  }

  assert.match(fixedCopySources.editor, /\btm\(error\)/)
  assert.match(fixedCopySources.editor, /\btm\(notice\)/)
  assert.match(fixedCopySources.editor, /\btm\(generateHint\)/)
  assert.match(fixedCopySources.editor, /\btm\(resultAnnouncement\)/)
  assert.match(fixedCopySources.preview, /\btm\(message\)/)
})

test('catalog uses a locale-independent category sentinel and never translates business data', () => {
  const source = fixedCopySources.catalog
  assert.match(source, /const\s+ALL_CATEGORIES\s*=\s*['"]__all__['"]/)
  assert.match(source, /t\('catalog\.category\.all'\)/)
  assert.match(source, /product\.name/)
  assert.match(source, /product\.category/)
  assert.match(source, /product\.description/)
  assert.doesNotMatch(source, /t\(\s*product\.(?:name|category|description)/)
})

test('editor descriptor props keep the descriptor contract and business labels stay raw', () => {
  const editor = fixedCopySources.editor
  for (const prop of ['generationMessage', 'generateHint', 'error', 'notice', 'resultAnnouncement']) {
    assert.match(editor, new RegExp(`${prop}: \\{ type: Object`), `${prop} must accept a descriptor`)
  }

  const options = fixedCopySources.options
  assert.match(options, /\{\{\s*option\.label\s*\}\}/)
  assert.match(options, /\{\{\s*value\.label\s*\}\}/)
  assert.match(options, /\{\{\s*value\.pantone_code\s*\}\}/)
  assert.doesNotMatch(options, /t\(\s*(?:option|value)\.(?:label|pantone_code)/)
  assert.match(fixedCopySources.history, /\{\{\s*generation\.product_name\s*\}\}/)
  assert.doesNotMatch(fixedCopySources.history, /t\(\s*generation\.product_name/)
})

test('editor section markers translate and historical results announce their own product', () => {
  assert.match(fixedCopySources.editor, /t\('editor\.styleEyebrow'\)/)
  assert.match(fixedCopySources.editor, /t\('editor\.customizeEyebrow'\)/)
  assert.equal(CUSTOMER_IMAGE_MESSAGES.en['editor.styleEyebrow'], '01 / STYLE')
  assert.equal(CUSTOMER_IMAGE_MESSAGES['zh-CN']['editor.styleEyebrow'], '01 / 选择产品')

  assert.match(fixedCopySources.preview, /generation\?\.product_name\s*\|\|\s*product\?\.name/)
  assert.match(fixedCopySources.preview, /preview\.resultAlt[\s\S]*generation\?\.product_name/)
})
