<script setup>
import CustomerLogoUpload from './components/CustomerLogoUpload.vue'
import GenerationHistory from './components/GenerationHistory.vue'
import GenerationPreview from './components/GenerationPreview.vue'
import ProductOptionGroup from './components/ProductOptionGroup.vue'
import { useCustomerImageI18n } from './i18n.js'
import { MOBILE_FLOW_TEMPLATE } from './layout.js'

defineProps({
  product: { type: Object, required: true },
  products: { type: Array, default: () => [] },
  coverUrls: { type: Object, default: () => ({}) },
  canGoBack: { type: Boolean, default: false },
  coverUrl: { type: String, default: '' },
  logoUrl: { type: String, default: '' },
  uploadingLogo: { type: Boolean, default: false },
  selections: { type: Object, default: () => ({}) },
  requirement: { type: String, default: '' },
  quota: { type: Object, default: () => ({ total: 0, used: 0, remaining: 0 }) },
  generations: { type: Array, default: () => [] },
  generationUrls: { type: Object, default: () => ({}) },
  previewGeneration: { type: Object, default: null },
  generationMessage: { type: Object, default: null },
  generateEnabled: { type: Boolean, default: false },
  generateHint: { type: Object, default: null },
  submitting: { type: Boolean, default: false },
  error: { type: Object, default: null },
  notice: { type: Object, default: null },
  resultAnnouncement: { type: Object, default: null },
})

defineEmits(['back', 'download', 'generate', 'select-generation', 'select-product', 'update-requirement', 'update-selection', 'upload-logo'])

const { t, tm } = useCustomerImageI18n()
</script>

<template>
  <main class="workbench">
    <div class="workbench-grid" :style="{ '--customer-mobile-flow': MOBILE_FLOW_TEMPLATE }">
      <aside class="product-rail" data-mobile-step="1">
        <div class="flow-products">
          <button v-if="canGoBack" type="button" class="back" :disabled="submitting" @click="$emit('back')">‹ {{ t('editor.allProducts') }}</button>
          <div class="rail-heading">
            <span class="eyebrow">{{ t('editor.styleEyebrow') }}</span>
            <h2>{{ t('editor.selectProduct') }}</h2>
            <p>{{ t('editor.selectProductDetail') }}</p>
          </div>
          <div class="product-list" :aria-label="t('catalog.products.label')">
            <button
              v-for="(item, index) in products"
              :key="item.id"
              type="button"
              class="product-card"
              :class="{ active: item.id === product.id }"
              :disabled="submitting"
              @click="$emit('select-product', item)"
            >
              <span class="num">{{ String(index + 1).padStart(2, '0') }}</span>
              <img v-if="coverUrls[item.id]" :src="coverUrls[item.id]" :alt="item.name">
              <span v-else class="thumb-fallback" aria-hidden="true">{{ item.category || t('catalog.product.fallback') }}</span>
              <span class="product-copy">
                <strong>{{ item.name }}</strong>
                <small>{{ item.category }}</small>
              </span>
              <span class="arrow" aria-hidden="true">↗</span>
            </button>
          </div>
        </div>
        <div class="divider" />
        <div class="flow-history">
          <GenerationHistory
            :generations="generations"
            :generation-urls="generationUrls"
            :selected-id="previewGeneration?.id"
            @select="$emit('select-generation', $event)"
          />
        </div>
      </aside>

      <section class="preview-column flow-preview" data-mobile-step="2">
        <GenerationPreview
          :product="product"
          :cover-url="coverUrl"
          :generation="previewGeneration"
          :result-url="generationUrls[previewGeneration?.id] || ''"
          :message="generationMessage"
          @download="$emit('download', $event)"
        />
      </section>

      <aside class="control-panel" data-mobile-step="3">
        <div class="control-heading">
          <span class="eyebrow">{{ t('editor.customizeEyebrow') }}</span>
          <h2>{{ t('editor.customize') }}</h2>
        </div>
        <div class="flow-logo">
          <CustomerLogoUpload :logo-url="logoUrl" :uploading="uploadingLogo" :disabled="submitting" @upload="$emit('upload-logo', $event)" />
        </div>
        <section class="control-section flow-options" aria-labelledby="options-title">
          <div class="section-heading">
            <span class="badge">B</span>
            <div>
              <h2 id="options-title">{{ t('editor.options.title') }}</h2>
              <p>{{ t('editor.options.detail') }}</p>
            </div>
          </div>
          <ProductOptionGroup
            v-for="option in product.options || []"
            :key="option.key"
            :option="option"
            :model-value="selections[option.key]"
            :disabled="submitting"
            @update:model-value="$emit('update-selection', option.key, $event)"
          />
        </section>
        <section class="control-section flow-requirement">
          <div class="section-heading">
            <span class="badge">C</span>
            <div>
              <h2 id="requirement-label">{{ t('editor.requirement.title') }}</h2>
              <p>{{ t('editor.requirement.detail') }}</p>
            </div>
          </div>
          <textarea
            id="customer-requirement"
            aria-labelledby="requirement-label"
            :value="requirement"
            :disabled="submitting"
            maxlength="500"
            rows="4"
            :placeholder="t('editor.requirement.placeholder')"
            @input="$emit('update-requirement', $event.target.value)"
          />
          <small class="count">{{ requirement.length }} / 500</small>
          <div class="generate-feedback" aria-live="polite">
            <p v-if="error" class="feedback error" role="alert">{{ tm(error) }}</p>
            <p v-else-if="notice" class="feedback notice" role="status">{{ tm(notice) }}</p>
            <p v-if="generateHint" class="hint">{{ tm(generateHint) }}</p>
          </div>
        </section>

        <div class="flow-spacer mobile-action-spacer" aria-hidden="true" />
        <div class="generate-block">
          <div class="quota-line" :aria-label="t('editor.quota.label')">
            <span>{{ t('editor.quota.label') }}</span>
            <strong>{{ quota.remaining }}</strong>
            <small>/ {{ quota.total }}</small>
          </div>
          <button
            type="button"
            class="generate"
            :disabled="!generateEnabled"
            @click="$emit('generate')"
          >
            {{ submitting ? t('editor.submitting') : t('editor.generate') }}
          </button>
          <p class="quota-copy">{{ t('quota.copy', { count: quota.remaining }) }}</p>
        </div>

        <span class="sr-only" aria-live="polite">{{ tm(resultAnnouncement) }}</span>
      </aside>
    </div>
  </main>
</template>

<style scoped>
.workbench { width: min(1480px, calc(100% - 36px)); margin: 0 auto; padding: 22px 0 42px; }
.workbench-grid { display: grid; min-height: calc(100vh - 136px); grid-template-columns: 272px minmax(0, 1fr) 352px; gap: 16px; }
.product-rail, .control-panel, .preview-column { min-width: 0; border: 1px solid var(--cip-border); border-radius: 20px; background: var(--cip-surface); }
.product-rail, .control-panel { align-self: start; display: grid; gap: 18px; max-height: calc(100vh - 116px); padding: 20px; overflow-y: auto; }
.preview-column { padding: 20px; }
.divider { height: 1px; background: var(--cip-border); }
.eyebrow { color: var(--cip-faint); font-size: 9px; font-weight: 700; letter-spacing: .2em; }
.rail-heading h2, .control-heading h2 { margin: 6px 0 0; color: var(--cip-ink); font-family: var(--cip-font-display); font-size: 22px; font-weight: 500; }
.rail-heading p { margin: 8px 0 0; color: var(--cip-muted); font-size: 12px; line-height: 1.65; }
.back { justify-self: start; min-height: 44px; margin: -8px 0 -4px; padding: 0 4px; cursor: pointer; border: 0; color: var(--cip-muted); background: transparent; font-size: 13px; }
.back:disabled { cursor: not-allowed; opacity: .5; }
.product-list { display: grid; gap: 8px; }
.product-card {
  display: grid;
  width: 100%;
  min-height: 44px;
  grid-template-columns: 24px 52px minmax(0, 1fr) 14px;
  align-items: center;
  gap: 10px;
  padding: 8px;
  cursor: pointer;
  border: 1px solid transparent;
  border-radius: 14px;
  color: var(--cip-ink);
  background: transparent;
  text-align: left;
  transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1);
}
.product-card:active { transform: scale(.98); }
.product-card:disabled { cursor: not-allowed; opacity: .55; }
.product-card.active { border-color: var(--cip-border-strong); background: var(--cip-surface-subtle); box-shadow: 0 8px 22px var(--cip-shadow); }
.product-card .num { align-self: start; padding-top: 3px; color: var(--cip-faint); font-size: 9px; }
.product-card img, .thumb-fallback { width: 52px; height: 52px; border-radius: 10px; }
.product-card img { object-fit: cover; }
.thumb-fallback { display: grid; place-items: center; color: var(--cip-accent-strong); background: var(--cip-accent-soft); font-size: 10px; }
.product-copy { min-width: 0; }
.product-copy strong, .product-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.product-copy strong { font-size: 12px; }
.product-copy small { margin-top: 4px; color: var(--cip-muted); font-size: 10px; }
.product-card .arrow { color: var(--cip-accent-strong); font-size: 15px; }
.control-heading h2 { margin: 6px 0 0; }
.control-section { display: grid; gap: 14px; padding-top: 18px; border-top: 1px solid var(--cip-border); }
.section-heading { display: flex; gap: 10px; align-items: flex-start; }
.badge { display: grid; width: 26px; height: 26px; place-items: center; flex: 0 0 26px; border-radius: 50%; color: var(--cip-accent-strong); background: var(--cip-accent-soft); font-size: 11px; font-weight: 700; }
.section-heading h2 { margin: 3px 0 0; color: var(--cip-ink); font-size: 15px; }
.section-heading p { margin: 4px 0 0; color: var(--cip-muted); font-size: 12px; }
textarea { box-sizing: border-box; width: 100%; min-height: 104px; resize: vertical; padding: 11px 12px; border: 1px solid var(--cip-border); border-radius: 12px; outline: none; color: var(--cip-ink); background: var(--cip-surface-subtle); font: inherit; font-size: 13px; line-height: 1.6; }
textarea:disabled { cursor: not-allowed; opacity: .62; }
textarea:focus { border-color: var(--cip-highlight); box-shadow: 0 0 0 3px var(--cip-focus); }
.count { justify-self: end; margin-top: -10px; color: var(--cip-faint); font-size: 10px; }
.generate-block { position: sticky; bottom: 0; display: grid; gap: 10px; margin: 4px -20px 0; padding: 12px 20px 0; border-top: 1px solid var(--cip-border); background: var(--cip-surface); }
.generate-feedback { display: grid; gap: 8px; }
.quota-line { display: flex; align-items: baseline; justify-content: center; gap: 6px; color: var(--cip-muted); }
.quota-line span, .quota-line small { font-size: 11px; }
.quota-line strong { color: var(--cip-accent-strong); font-family: var(--cip-font-display); font-size: 22px; font-weight: 500; }
.generate { min-height: 50px; cursor: pointer; border: 0; border-radius: 999px; color: var(--cip-on-accent); background: var(--cip-accent); font-size: 14px; font-weight: 700; letter-spacing: .02em; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1), opacity 180ms ease; }
.generate:active:not(:disabled) { transform: scale(.98); }
.generate:disabled { cursor: not-allowed; opacity: .45; }
.feedback, .hint, .quota-copy { margin: 0; font-size: 11px; line-height: 1.55; }
.feedback { padding: 9px 12px; border-radius: 10px; }
.feedback.error { color: var(--cip-danger); background: var(--cip-danger-soft); }
.feedback.notice { color: var(--cip-success); background: var(--cip-success-soft); }
.hint, .quota-copy { color: var(--cip-muted); text-align: center; }
.mobile-action-spacer { display: none; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (hover: hover) and (pointer: fine) {
  .generate:not(:disabled):hover { background: var(--cip-accent-hover); }
  .back:not(:disabled):hover { color: var(--cip-ink); }
  .product-card:not(:disabled):hover { background: var(--cip-surface-subtle); }
}
@media (max-width: 1120px) and (min-width: 761px) { .workbench-grid { grid-template-columns: 240px minmax(0, 1fr) 304px; } }
@media (max-width: 760px) {
  .workbench { --customer-mobile-cta-height: 118px; width: 100%; min-height: 100dvh; padding: 0; }
  .workbench-grid { display: grid; min-height: 0; grid-template-areas: var(--customer-mobile-flow); grid-template-columns: minmax(0, 1fr); gap: 10px; padding: 10px; }
  .product-rail, .control-panel { display: contents; }
  .product-rail > .divider, .control-panel > .divider { display: none; }
  .flow-products, .flow-logo, .flow-options, .flow-requirement, .flow-history { min-width: 0; padding: 16px; border: 1px solid var(--cip-border); border-radius: 16px; background: var(--cip-surface); }
  .flow-products { grid-area: products; display: grid; gap: 12px; }
  .flow-logo { grid-area: logo; }
  .flow-options { grid-area: options; padding-top: 16px; border-top: 1px solid var(--cip-border); }
  .flow-requirement { grid-area: requirement; padding-top: 16px; border-top: 1px solid var(--cip-border); }
  .flow-preview { grid-area: preview; }
  .flow-history { grid-area: history; }
  .flow-spacer { grid-area: spacer; }
  .flow-products .product-list { display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; }
  .flow-products .product-card { min-width: 196px; }
  .preview-column { width: auto; max-height: none; overflow: visible; border-radius: 16px; }
  .mobile-action-spacer { display: block; height: calc(var(--customer-mobile-cta-height) + env(safe-area-inset-bottom)); }
  textarea { scroll-margin-bottom: calc(var(--customer-mobile-cta-height) + env(safe-area-inset-bottom)); scroll-padding-bottom: calc(var(--customer-mobile-cta-height) + env(safe-area-inset-bottom)); }
  .generate-block { position: fixed; z-index: 4; right: 10px; bottom: 0; left: 10px; box-sizing: border-box; min-height: calc(var(--customer-mobile-cta-height) + env(safe-area-inset-bottom)); align-content: center; margin: 0; padding: 10px 12px calc(10px + env(safe-area-inset-bottom)); border: 1px solid var(--cip-border); border-bottom: 0; border-radius: 18px 18px 0 0; background: var(--cip-surface); box-shadow: 0 -10px 30px var(--cip-shadow); }
}
@media (prefers-reduced-motion: reduce) {
  .generate, .product-card { transition: none; }
  .generate:active:not(:disabled), .product-card:active { transform: none; }
}
</style>
