<script setup>
import * as publicApi from '@/api/customerImagePublic'
import CustomerProductCatalog from './CustomerProductCatalog.vue'
import CustomerProductEditor from './CustomerProductEditor.vue'
import { useCustomerImagePortal } from './composables/useCustomerImagePortal'

const {
  state,
  assets,
  selectedProduct,
  previewGeneration,
  generationMessage,
  generateEnabled,
  generateHint,
  backToCatalog,
  bootstrap,
  chooseProduct,
  downloadGeneration,
  replaceLogo,
  selectGeneration,
  submitGeneration,
  updateRequirement,
  updateSelection,
} = useCustomerImagePortal({
  api: publicApi,
  scrollResultIntoView() {
    requestAnimationFrame(() => {
      document.getElementById('customer-generation-result')?.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        block: 'start',
      })
    })
  },
})
</script>

<template>
  <div class="customer-portal">
    <div v-if="state.view === 'loading'" class="page-state" role="status" aria-live="polite">
      <span class="state-mark">AI</span>
      <h1>正在加载产品效果图工作台…</h1>
      <p>马上就好</p>
    </div>

    <div v-else-if="state.view === 'invalid'" class="page-state invalid" role="alert">
      <span class="state-mark">!</span>
      <h1>此链接已失效</h1>
      <p>{{ state.notice || '请联系您的业务经理重新获取专属访问链接。' }}</p>
      <strong>联系您的业务经理</strong>
    </div>

    <div v-else-if="state.view === 'empty'" class="page-state">
      <span class="state-mark">0</span>
      <h1>当前没有可设计的产品</h1>
      <p>请联系您的业务经理为此邀请添加产品。</p>
      <strong>联系您的业务经理</strong>
    </div>

    <div v-else-if="state.view === 'error'" class="page-state" role="alert">
      <span class="state-mark">!</span>
      <h1>页面暂时无法加载</h1>
      <p>{{ state.error }}</p>
      <button type="button" @click="bootstrap">重新加载</button>
    </div>

    <CustomerProductCatalog
      v-else-if="state.view === 'catalog'"
      :products="state.products"
      :cover-urls="assets.coverUrls"
      :customer-name="state.context?.customer_display_name"
      @select="chooseProduct"
    />

    <CustomerProductEditor
      v-else-if="selectedProduct"
      :product="selectedProduct"
      :can-go-back="state.products.length > 1"
      :cover-url="assets.coverUrls[selectedProduct.id] || ''"
      :logo-url="assets.logoUrl.value"
      :uploading-logo="state.uploadingLogo"
      :selections="state.selections"
      :requirement="state.requirement"
      :quota="state.quota"
      :generations="state.generations"
      :generation-urls="assets.generationUrls"
      :preview-generation="previewGeneration"
      :generation-message="generationMessage"
      :generate-enabled="generateEnabled"
      :generate-hint="generateHint"
      :submitting="state.submitting"
      :error="state.error"
      :notice="state.notice"
      :result-announcement="state.resultAnnouncement"
      @back="backToCatalog"
      @download="downloadGeneration"
      @generate="submitGeneration"
      @select-generation="selectGeneration"
      @update-requirement="updateRequirement"
      @update-selection="updateSelection"
      @upload-logo="replaceLogo"
    />
  </div>
</template>

<style scoped>
.customer-portal {
  --cip-accent: var(--color-primary);
  --cip-accent-hover: var(--color-primary-hover);
  --cip-accent-strong: var(--color-gold-muted);
  --cip-accent-soft: var(--color-primary-light);
  --cip-accent-soft-hover: var(--color-gold-soft);
  --cip-on-accent: var(--color-white);
  --cip-ink: var(--text-primary);
  --cip-muted: var(--text-secondary);
  --cip-border: var(--border-color);
  --cip-border-strong: var(--border-color-strong, var(--border-color));
  --cip-surface: var(--bg-primary);
  --cip-surface-subtle: var(--bg-secondary);
  --cip-canvas: var(--bg-page);
  --cip-focus: var(--color-primary-glow);
  --cip-danger: var(--color-danger-text);
  --cip-danger-soft: var(--color-danger-bg);
  --cip-success: var(--color-success-text);
  --cip-success-soft: var(--color-success-bg);
  --cip-shadow: var(--shadow-color, rgba(32, 40, 52, .08));
  min-height: 100vh;
  color: var(--cip-ink);
  background: var(--cip-canvas);
  font-family: var(--font-body);
}
.page-state { display: grid; min-height: 100vh; place-items: center; align-content: center; gap: 10px; padding: 24px; text-align: center; }
.state-mark { display: grid; width: 52px; height: 52px; place-items: center; border-radius: 16px; color: var(--cip-accent-strong); background: var(--cip-accent-soft); font-weight: 800; }
.page-state h1 { margin: 8px 0 0; font-size: 24px; }
.page-state p { max-width: 440px; margin: 0; color: var(--cip-muted); line-height: 1.65; }
.page-state strong { margin-top: 8px; color: var(--cip-accent-strong); font-size: 13px; }
.page-state button { min-height: 44px; margin-top: 8px; padding: 0 18px; cursor: pointer; border: 0; border-radius: 10px; color: var(--cip-on-accent); background: var(--cip-accent); font-weight: 700; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.page-state button:active { transform: scale(.98); }
@media (hover: hover) and (pointer: fine) { .page-state button:hover { background: var(--cip-accent-hover); } }
@media (prefers-reduced-motion: reduce) { .page-state button { transition: none; } .page-state button:active { transform: none; } }
</style>
