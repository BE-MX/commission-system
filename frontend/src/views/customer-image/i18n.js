import { inject, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'

export const CUSTOMER_IMAGE_LOCALE_KEY = 'ark_customer_image_locale'
export const CUSTOMER_IMAGE_LOCALES = ['en', 'zh-CN']

const CUSTOMER_IMAGE_I18N_KEY = Symbol('customer-image-i18n')

const MESSAGES = {
  en: {
    'portal.loading.title': 'Loading your product design studio…',
    'portal.loading.detail': 'We’ll be ready shortly.',
    'portal.invalid.title': 'This link is no longer valid',
    'portal.invalid.detail': 'Please contact your account manager for a new private access link.',
    'portal.contactManager': 'Contact your account manager',
    'portal.empty.title': 'No products are available to design',
    'portal.empty.detail': 'Please ask your account manager to add products to this invitation.',
    'portal.error.title': 'We can’t load this page right now',
    'portal.retry': 'Reload',
    'portal.brand.kicker': 'LESHINE STUDIO',
    'portal.brand.subtitle': 'LeShine Product Visuals',
    'portal.exclusiveChannel': 'Private customization channel',

    'language.label': 'Choose language',
    'language.english': 'English',
    'language.chinese': 'Chinese',

    'catalog.eyebrow': '01 / STYLE · YOUR PRODUCT VISUALS',
    'catalog.title': 'Choose a product to design',
    'catalog.titleForCustomer': '{name}, choose a product to design',
    'catalog.intro': 'Choose a product, upload your logo, and confirm the preset options to generate a visual.',
    'catalog.search.label': 'Search',
    'catalog.search.placeholder': 'Search product names',
    'catalog.categories.label': 'Product categories',
    'catalog.category.all': 'All',
    'catalog.products.label': 'Product list',
    'catalog.product.fallback': 'Product',
    'catalog.product.descriptionFallback': 'Upload your brand logo to quickly preview it on this product.',
    'catalog.product.designNow': 'Design now',
    'catalog.empty.title': 'No matching products found',
    'catalog.empty.detail': 'Try another keyword or category.',
    'catalog.empty.showAll': 'View all products',

    'editor.allProducts': 'All products',
    'editor.selectProduct': 'Choose a product',
    'editor.selectProductDetail': 'Switching products keeps your uploaded logo and previous results.',
    'editor.customize': 'Customize your product',
    'editor.options.title': 'Confirm product options',
    'editor.options.detail': 'Standard options have been preset for you.',
    'editor.requirement.title': 'Additional requests',
    'editor.requirement.detail': 'Optional, up to 500 characters',
    'editor.requirement.placeholder': 'For example: make the logo slightly smaller and keep the layout minimal',
    'editor.quota.label': 'Credits remaining',
    'editor.generate': 'Generate visual',
    'editor.submitting': 'Submitting…',

    'upload.title': 'Upload your brand logo',
    'upload.detail': 'PNG / JPG / WEBP; it will be used to generate your product visual.',
    'upload.previewAlt': 'Uploaded brand logo',
    'upload.uploading': 'Uploading…',
    'upload.replace': 'Replace logo',
    'upload.choose': 'Upload your brand logo',
    'upload.replaceDetail': 'New generations will use the latest logo.',
    'upload.chooseDetail': 'Your upload is saved automatically for this invitation.',
    'upload.required': 'Upload your brand logo first.',

    'options.required': 'Required',
    'options.yes': 'Yes',
    'options.no': 'No',

    'quota.copy': 'This generation uses 1 credit. {count} remaining.',
    'quota.logoRequired': 'Upload your brand logo first.',
    'quota.optionsRequired': 'Complete all required options.',
    'quota.exhausted': 'This invitation has no generation credits left. You can still view and download previous results.',
    'quota.submitting': 'Submitting, please wait.',

    'generation.queued.detail': 'Your request is queued and will begin shortly.',
    'generation.running.detail': 'Your product visual is being generated.',
    'generation.succeeded.detail': 'Your product visual is ready.',
    'generation.failed.detail': 'This generation could not be completed. Please try again.',
    'generation.processing.detail': 'Your request is being processed.',
    'generation.completed.announcement': '{product} visual is ready.',

    'preview.eyebrow': 'CUSTOM PREVIEW',
    'preview.titleFallback': 'Product visual',
    'preview.download': 'Download visual',
    'preview.resultAlt': 'Generated visual for {product}',
    'preview.referenceAlt': 'Reference image for {product}',
    'preview.placeholder': 'Choose a product to view its reference image.',
    'preview.failed': 'Not completed',
    'preview.running': 'Generating',
    'preview.queued': 'Waiting to generate',
    'preview.queuedNote': 'Submitted. You may close this page; the result will remain here.',
    'preview.runningNote': 'Generating now. This usually takes from tens of seconds to a few minutes.',
    'preview.live': 'Live preview',
    'preview.signature': 'AI generated · LeShine private customization',

    'history.title': 'Previous visuals',
    'history.empty': 'Your generated results will remain here and can be viewed while this invitation is valid.',
    'history.status.queued': 'Submitted',
    'history.status.running': 'Generating',
    'history.status.succeeded': 'Completed',
    'history.status.failed': 'Not completed',
    'history.status.processing': 'Processing',

    'errors.invalidLink': 'This link is no longer valid. Please contact your account manager for a new one.',
    'errors.rateLimited': 'Too many requests. Please wait one minute and try again.',
    'errors.uploadTooLarge': 'The logo image is too large. Compress it and upload again.',
    'errors.uploadInvalid': 'We could not read this logo. Please use a PNG, JPG, or WebP image.',
    'errors.quotaExhausted': 'This invitation has no generation credits left. You can still view and download previous results.',
    'errors.settingsChanged': 'Product settings were updated. Select the options again before generating.',
    'errors.logoRequired': 'Upload your brand logo first.',
    'errors.serviceUnavailable': 'The image service is temporarily unavailable. Your settings are saved; please try again later.',
    'errors.logoUploadFailed': 'Logo upload failed. Check the image and try again.',
    'errors.settingsRefreshFailed': 'Product settings could not be refreshed. Check your connection and try again.',
    'errors.generationConflict': 'Check your credits and logo, then try again.',
    'errors.generationFailed': 'The image service is temporarily unavailable. Your settings are saved; please try again later.',
    'errors.pageLoadFailed': 'This page could not be loaded. Check your connection and try again.',

    'settings.logoUpdated': 'Your logo was updated. You can continue choosing options.',
    'settings.updated': 'Product settings were updated. Confirm the latest options before generating again.',
    'download.productFallback': 'product-visual',
    'download.suffix': 'visual',
  },
  'zh-CN': {
    'portal.loading.title': '正在加载产品效果图工作台…',
    'portal.loading.detail': '马上就好',
    'portal.invalid.title': '此链接已失效',
    'portal.invalid.detail': '请联系您的业务经理重新获取专属访问链接。',
    'portal.contactManager': '联系您的业务经理',
    'portal.empty.title': '当前没有可设计的产品',
    'portal.empty.detail': '请联系您的业务经理为此邀请添加产品。',
    'portal.error.title': '页面暂时无法加载',
    'portal.retry': '重新加载',
    'portal.brand.kicker': 'LESHINE STUDIO',
    'portal.brand.subtitle': '莱莎产品效果图',
    'portal.exclusiveChannel': '专属定制通道',

    'language.label': '选择语言',
    'language.english': '英语',
    'language.chinese': '中文',

    'catalog.eyebrow': '01 / STYLE · 专属产品效果图',
    'catalog.title': '选择要设计的产品',
    'catalog.titleForCustomer': '{name}，选择要设计的产品',
    'catalog.intro': '选好产品后，上传 LOGO 并确认预设参数即可生成。',
    'catalog.search.label': '搜索',
    'catalog.search.placeholder': '搜索产品名称',
    'catalog.categories.label': '产品分类',
    'catalog.category.all': '全部',
    'catalog.products.label': '产品列表',
    'catalog.product.fallback': '产品',
    'catalog.product.descriptionFallback': '上传品牌 LOGO，快速查看产品应用效果。',
    'catalog.product.designNow': '立即设计',
    'catalog.empty.title': '没有找到匹配的产品',
    'catalog.empty.detail': '换个关键词或分类试试。',
    'catalog.empty.showAll': '查看全部产品',

    'editor.allProducts': '全部产品',
    'editor.selectProduct': '选择产品',
    'editor.selectProductDetail': '切换产品会保留已上传的 LOGO 与历史结果。',
    'editor.customize': '定制你的产品',
    'editor.options.title': '确认产品参数',
    'editor.options.detail': '已为您预设标准选项',
    'editor.requirement.title': '补充要求',
    'editor.requirement.detail': '可选，最多 500 字',
    'editor.requirement.placeholder': '例如：LOGO 稍微缩小，整体更简洁',
    'editor.quota.label': '剩余额度',
    'editor.generate': '生成效果图',
    'editor.submitting': '正在提交…',

    'upload.title': '上传品牌 LOGO',
    'upload.detail': 'PNG / JPG / WEBP，将用于生成产品效果图',
    'upload.previewAlt': '已上传的品牌 LOGO',
    'upload.uploading': '正在上传…',
    'upload.replace': '更换 LOGO',
    'upload.choose': '点击上传品牌 LOGO',
    'upload.replaceDetail': '替换后新生成将使用最新 LOGO',
    'upload.chooseDetail': '上传后自动保存到本次邀请',
    'upload.required': '请先上传品牌 LOGO',

    'options.required': '必选',
    'options.yes': '是',
    'options.no': '否',

    'quota.copy': '本次生成将使用 1 次额度，剩余 {count} 次',
    'quota.logoRequired': '请先上传品牌 LOGO',
    'quota.optionsRequired': '请完成必选参数',
    'quota.exhausted': '本次邀请的生成额度已用完，历史结果仍可查看下载',
    'quota.submitting': '正在提交，请稍候',

    'generation.queued.detail': '请求已进入队列，即将开始生成。',
    'generation.running.detail': '正在生成产品效果图。',
    'generation.succeeded.detail': '产品效果图已生成。',
    'generation.failed.detail': '本次生成未完成，请重试。',
    'generation.processing.detail': '正在处理本次请求。',
    'generation.completed.announcement': '{product} 效果图已生成',

    'preview.eyebrow': '定制预览',
    'preview.titleFallback': '产品效果图',
    'preview.download': '下载效果图',
    'preview.resultAlt': '{product}生成效果图',
    'preview.referenceAlt': '{product}参考图',
    'preview.placeholder': '选择产品后查看参考图',
    'preview.failed': '本次未完成',
    'preview.running': '正在生成',
    'preview.queued': '等待生成',
    'preview.queuedNote': '已提交，可以关闭页面，结果会保留在这里',
    'preview.runningNote': '正在生成，通常需要几十秒到数分钟',
    'preview.live': '实时预览',
    'preview.signature': 'AI 生成 · 莱莎专属定制',

    'history.title': '历史效果图',
    'history.empty': '生成结果会保留在这里，邀请有效期内可随时查看。',
    'history.status.queued': '已提交',
    'history.status.running': '生成中',
    'history.status.succeeded': '已完成',
    'history.status.failed': '未完成',
    'history.status.processing': '处理中',

    'errors.invalidLink': '此链接已失效，请联系您的业务经理重新获取。',
    'errors.rateLimited': '操作过于频繁，请稍候一分钟再试',
    'errors.uploadTooLarge': 'LOGO 图片过大，请压缩后重新上传',
    'errors.uploadInvalid': 'LOGO 图片无法识别，请更换 PNG、JPG 或 WebP 图片',
    'errors.quotaExhausted': '本次邀请的生成额度已用完，历史结果仍可查看下载',
    'errors.settingsChanged': '产品设置已更新，请重新选择参数后生成',
    'errors.logoRequired': '请先上传品牌 LOGO',
    'errors.serviceUnavailable': '生图服务暂时不可用，本次设置已保留，请稍后重试',
    'errors.logoUploadFailed': 'LOGO 上传失败，请检查图片后重试',
    'errors.settingsRefreshFailed': '产品设置更新失败，请检查网络后重试',
    'errors.generationConflict': '请确认额度和 LOGO 后重试',
    'errors.generationFailed': '生图服务暂时不可用，本次设置已保留，请稍后重试',
    'errors.pageLoadFailed': '页面暂时无法加载，请检查网络后重试',

    'settings.logoUpdated': 'LOGO 已更新，可以继续选择参数。',
    'settings.updated': '产品设置已更新，请确认最新参数后再次生成',
    'download.productFallback': '产品效果图',
    'download.suffix': '效果图',
  },
}

export function normalizeCustomerImageLocale(value) {
  return CUSTOMER_IMAGE_LOCALES.includes(value) ? value : 'en'
}

export function readCustomerImageLocale(storage) {
  try {
    return normalizeCustomerImageLocale(storage?.getItem(CUSTOMER_IMAGE_LOCALE_KEY))
  } catch {
    return 'en'
  }
}

export function writeCustomerImageLocale(storage, locale) {
  try {
    storage?.setItem(CUSTOMER_IMAGE_LOCALE_KEY, normalizeCustomerImageLocale(locale))
  } catch {
    // Locale persistence must never interrupt the generation workflow.
  }
}

export function customerImageMessage(key, params = {}) {
  return { key, params }
}

export function translateCustomerImage(locale, key, params = {}, messages = MESSAGES) {
  const template = messages[normalizeCustomerImageLocale(locale)]?.[key]
    ?? messages.en?.[key]
    ?? key
  return template.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''))
}

function browserStorage() {
  try {
    return globalThis.localStorage
  } catch {
    return undefined
  }
}

export function provideCustomerImageI18n(storage = browserStorage()) {
  const locale = ref(readCustomerImageLocale(storage))
  let previousDocumentLanguage
  let mounted = false

  function syncDocumentLanguage(value) {
    if (mounted && globalThis.document?.documentElement) {
      globalThis.document.documentElement.lang = value
    }
  }

  function setLocale(value) {
    locale.value = normalizeCustomerImageLocale(value)
    writeCustomerImageLocale(storage, locale.value)
  }

  const i18n = {
    locale,
    setLocale,
    t: (key, params = {}) => translateCustomerImage(locale.value, key, params),
    tm: descriptor => descriptor
      ? translateCustomerImage(locale.value, descriptor.key, descriptor.params)
      : '',
  }

  provide(CUSTOMER_IMAGE_I18N_KEY, i18n)
  watch(locale, syncDocumentLanguage, { flush: 'sync' })

  onMounted(() => {
    if (!globalThis.document?.documentElement) return
    previousDocumentLanguage = globalThis.document.documentElement.lang
    mounted = true
    syncDocumentLanguage(locale.value)
  })

  onBeforeUnmount(() => {
    if (mounted && globalThis.document?.documentElement) {
      globalThis.document.documentElement.lang = previousDocumentLanguage
    }
    mounted = false
  })

  return i18n
}

export function useCustomerImageI18n() {
  const i18n = inject(CUSTOMER_IMAGE_I18N_KEY, null)
  if (!i18n) {
    throw new Error('useCustomerImageI18n() requires provideCustomerImageI18n() in a parent component')
  }
  return i18n
}
