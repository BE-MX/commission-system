import test from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, defineComponent, h } from 'vue'

import {
  CUSTOMER_IMAGE_LOCALE_KEY,
  customerImageMessage,
  normalizeCustomerImageLocale,
  provideCustomerImageI18n,
  readCustomerImageLocale,
  translateCustomerImage,
  useCustomerImageI18n,
  writeCustomerImageLocale,
} from '../src/views/customer-image/i18n.js'

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

test('creates stable message descriptors', () => {
  assert.deepEqual(customerImageMessage('status.completed', { product: 'Box' }), {
    key: 'status.completed',
    params: { product: 'Box' },
  })
  assert.deepEqual(customerImageMessage('portal.retry'), { key: 'portal.retry', params: {} })
})

test('contains bilingual fixed UI copy for every portal surface', () => {
  const keys = [
    'portal.loading.title', 'portal.invalid.title', 'portal.empty.title', 'portal.error.title',
    'portal.retry', 'portal.brand.subtitle', 'portal.exclusiveChannel',
    'language.label', 'language.english', 'language.chinese',
    'catalog.eyebrow', 'catalog.title', 'catalog.titleForCustomer', 'catalog.intro',
    'catalog.search.label', 'catalog.search.placeholder', 'catalog.categories.label',
    'catalog.category.all', 'catalog.products.label', 'catalog.product.fallback',
    'catalog.product.descriptionFallback', 'catalog.product.designNow', 'catalog.empty.title',
    'catalog.empty.detail', 'catalog.empty.showAll',
    'editor.allProducts', 'editor.selectProduct', 'editor.selectProductDetail',
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
    'errors.rateLimited', 'errors.uploadTooLarge', 'errors.uploadInvalid', 'errors.quotaExhausted',
    'errors.settingsChanged', 'errors.logoRequired', 'errors.serviceUnavailable',
    'errors.logoUploadFailed', 'errors.settingsRefreshFailed', 'errors.generationConflict',
    'errors.generationFailed', 'errors.pageLoadFailed',
    'settings.logoUpdated', 'settings.updated', 'download.productFallback', 'download.suffix',
  ]

  for (const key of keys) {
    assert.notEqual(translateCustomerImage('en', key), key, `missing English: ${key}`)
    assert.notEqual(translateCustomerImage('zh-CN', key), key, `missing Chinese: ${key}`)
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
