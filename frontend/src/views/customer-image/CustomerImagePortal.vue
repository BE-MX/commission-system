<script setup>
import * as publicApi from '@/api/customerImagePublic'
import { clearInviteToken } from './inviteSession.js'
import CustomerProductCatalog from './CustomerProductCatalog.vue'
import CustomerProductEditor from './CustomerProductEditor.vue'
import LanguageSwitcher from './components/LanguageSwitcher.vue'
import { useCustomerImagePortal } from './composables/useCustomerImagePortal'
import { provideCustomerImageI18n } from './i18n.js'

const { t, tm } = provideCustomerImageI18n()

function downloadFilename(generation) {
  const product = generation?.product_name || t('download.productFallback')
  return `${product}-${t('download.suffix')}-${generation?.id}.png`
}

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
  clearInvite: clearInviteToken,
  downloadFilename,
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
    <LanguageSwitcher />

    <div v-if="state.view === 'loading'" class="page-state" role="status" aria-live="polite">
      <span class="state-mark">Le</span>
      <h1>{{ t('portal.loading.title') }}</h1>
      <p>{{ t('portal.loading.detail') }}</p>
    </div>

    <div v-else-if="state.view === 'invalid'" class="page-state invalid" role="alert">
      <span class="state-mark">!</span>
      <h1>{{ t('portal.invalid.title') }}</h1>
      <p>{{ tm(state.notice) || t('portal.invalid.detail') }}</p>
      <strong>{{ t('portal.contactManager') }}</strong>
    </div>

    <div v-else-if="state.view === 'empty'" class="page-state">
      <span class="state-mark">0</span>
      <h1>{{ t('portal.empty.title') }}</h1>
      <p>{{ t('portal.empty.detail') }}</p>
      <strong>{{ t('portal.contactManager') }}</strong>
    </div>

    <div v-else-if="state.view === 'error'" class="page-state" role="alert">
      <span class="state-mark">!</span>
      <h1>{{ t('portal.error.title') }}</h1>
      <p>{{ tm(state.error) }}</p>
      <button type="button" @click="bootstrap">{{ t('portal.retry') }}</button>
    </div>

    <template v-else>
      <header class="topbar">
        <div class="brand">
          <span class="brand-mark" aria-hidden="true">Le</span>
          <div class="brand-copy">
            <small>{{ t('portal.brand.kicker') }}</small>
            <strong>{{ t('portal.brand.subtitle') }}</strong>
          </div>
        </div>
        <div class="topbar-status">
          <span v-if="state.context?.customer_display_name" class="customer">{{ state.context.customer_display_name }}</span>
          <span class="status-pill"><span class="dot" aria-hidden="true" />{{ t('portal.exclusiveChannel') }}</span>
        </div>
      </header>

      <CustomerProductCatalog
        v-if="state.view === 'catalog'"
        :products="state.products"
        :cover-urls="assets.coverUrls"
        :customer-name="state.context?.customer_display_name"
        @select="chooseProduct"
      />

      <CustomerProductEditor
        v-else-if="selectedProduct"
        :product="selectedProduct"
        :products="state.products"
        :cover-urls="assets.coverUrls"
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
        @select-product="chooseProduct"
        @update-requirement="updateRequirement"
        @update-selection="updateSelection"
        @upload-logo="replaceLogo"
      />
    </template>
  </div>
</template>

<style scoped>
.customer-portal {
  /* 品牌五色色谱（严格取自色板，全部颜色由这五个色号派生） */
  --cip-fantasy: #F7F3ED;
  --cip-vanilla: #EFD8D6;
  --cip-sand: #C2C6B9;
  --cip-rose: #DBA1A2;
  --cip-tobago: #422B23;
  --cip-ink: var(--cip-tobago);
  --cip-muted: color-mix(in srgb, var(--cip-tobago) 60%, var(--cip-fantasy));
  --cip-faint: color-mix(in srgb, var(--cip-tobago) 42%, var(--cip-fantasy));
  --cip-canvas: var(--cip-fantasy);
  --cip-surface: color-mix(in srgb, var(--cip-fantasy) 40%, #fff);
  --cip-surface-subtle: color-mix(in srgb, var(--cip-fantasy) 76%, #fff);
  --cip-border: color-mix(in srgb, var(--cip-tobago) 13%, var(--cip-fantasy));
  --cip-border-strong: color-mix(in srgb, var(--cip-tobago) 26%, var(--cip-fantasy));
  --cip-accent: var(--cip-tobago);
  --cip-accent-hover: color-mix(in srgb, var(--cip-tobago) 84%, var(--cip-rose));
  --cip-accent-strong: color-mix(in srgb, var(--cip-rose) 58%, var(--cip-tobago));
  --cip-accent-soft: var(--cip-vanilla);
  --cip-accent-soft-hover: color-mix(in srgb, var(--cip-vanilla) 78%, var(--cip-rose));
  --cip-highlight: var(--cip-rose);
  --cip-on-accent: var(--cip-fantasy);
  --cip-focus: color-mix(in srgb, var(--cip-rose) 30%, transparent);
  --cip-danger: color-mix(in srgb, var(--cip-rose) 56%, var(--cip-tobago));
  --cip-danger-soft: color-mix(in srgb, var(--cip-vanilla) 58%, #fff);
  --cip-success: color-mix(in srgb, var(--cip-sand) 46%, var(--cip-tobago));
  --cip-success-soft: color-mix(in srgb, var(--cip-sand) 34%, var(--cip-fantasy));
  --cip-shadow: color-mix(in srgb, var(--cip-tobago) 9%, transparent);
  --cip-font-display: Georgia, 'Songti SC', 'Noto Serif SC', 'STSong', serif;
  min-height: 100vh;
  color: var(--cip-ink);
  background: var(--cip-canvas);
  font-family: var(--font-body, 'DM Sans', system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif);
}
.topbar {
  position: sticky;
  z-index: 10;
  top: 0;
  display: flex;
  min-height: 72px;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 154px 0 28px;
  border-bottom: 1px solid var(--cip-border);
  background: color-mix(in srgb, var(--cip-surface) 90%, transparent);
  backdrop-filter: blur(14px);
}
.brand { display: flex; min-width: 0; align-items: center; gap: 12px; }
.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  flex: 0 0 40px;
  border-radius: 13px;
  color: var(--cip-fantasy);
  background: var(--cip-tobago);
  font-family: var(--cip-font-display);
  font-size: 17px;
  font-style: italic;
  box-shadow: 0 6px 18px var(--cip-shadow);
}
.brand-copy { min-width: 0; }
.brand-copy small {
  display: block;
  color: var(--cip-faint);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .22em;
}
.brand-copy strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--cip-ink);
  font-family: var(--cip-font-display);
  font-size: 18px;
  font-weight: 500;
  letter-spacing: .02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-status { display: flex; align-items: center; gap: 14px; }
.customer { color: var(--cip-muted); font-size: 12px; }
.status-pill {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  border: 1px solid var(--cip-border);
  border-radius: 999px;
  color: var(--cip-muted);
  background: var(--cip-surface);
  font-size: 11px;
}
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--cip-sand);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cip-sand) 30%, transparent);
}
.page-state { display: grid; min-height: 100vh; place-items: center; align-content: center; gap: 10px; padding: 24px; text-align: center; }
.state-mark {
  display: grid;
  width: 54px;
  height: 54px;
  place-items: center;
  border: 1px solid var(--cip-border);
  border-radius: 18px;
  color: var(--cip-accent-strong);
  background: var(--cip-accent-soft);
  font-family: var(--cip-font-display);
  font-size: 19px;
  font-weight: 700;
}
.page-state h1 { margin: 10px 0 0; font-family: var(--cip-font-display); font-size: 26px; font-weight: 500; letter-spacing: .01em; }
.page-state p { max-width: 440px; margin: 0; color: var(--cip-muted); line-height: 1.75; }
.page-state strong { margin-top: 8px; color: var(--cip-accent-strong); font-size: 13px; }
.page-state button { min-height: 44px; margin-top: 10px; padding: 0 22px; cursor: pointer; border: 0; border-radius: 999px; color: var(--cip-on-accent); background: var(--cip-accent); font-weight: 700; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.page-state button:active { transform: scale(.98); }
@media (hover: hover) and (pointer: fine) { .page-state button:hover { background: var(--cip-accent-hover); } }
@media (max-width: 760px) {
  .topbar { min-height: 60px; padding: 0 118px 0 14px; }
  .brand-mark { width: 34px; height: 34px; flex-basis: 34px; border-radius: 11px; font-size: 14px; }
  .brand-copy strong { font-size: 16px; }
  .topbar-status { display: none; }
}
@media (prefers-reduced-motion: reduce) { .page-state button { transition: none; } .page-state button:active { transform: none; } }
</style>
