<template>
  <section class="client-library" :aria-busy="loading">
    <div v-if="loading" class="library-loading">
      <span class="loading-mark">L</span>
      <strong>正在准备客户视图…</strong>
      <p>读取该客户实际可见的已发布素材</p>
    </div>

    <div v-else-if="error" class="library-loading empty-library">
      <span class="loading-mark">!</span>
      <strong>客户视图加载失败</strong>
      <p>{{ error }}</p>
    </div>

    <template v-else-if="customer">
      <header class="preview-topbar">
        <div class="brand-lockup">
          <img src="/logo.webp" alt="LeShine Hair" />
          <span><strong>CONTENT</strong><small>HUB</small></span>
        </div>
        <div class="portal-label">
          <span>PRIVATE COLLECTION</span>
          <strong>{{ customer.customer_name }}</strong>
        </div>
        <div class="preview-badge"><span /> 客户视角预览</div>
      </header>

      <div class="library-content">
        <section class="collection-head">
          <div class="collection-identity">
            <div class="collection-logo">{{ initials(customer.customer_name) }}</div>
            <div>
              <div class="breadcrumb">PRIVATE COLLECTION <span>/</span> {{ customer.customer_name.toUpperCase() }}</div>
              <h1>{{ customer.customer_name }} Content Library</h1>
              <p>Browse and download your product photos and videos from one private collection.</p>
            </div>
          </div>
          <div class="summary-card">
            <div><span>STATUS</span><strong>{{ status.label }}</strong></div>
            <div><span>ASSETS</span><strong>{{ customer.asset_count }}</strong></div>
            <div><span>UPDATED</span><strong>{{ formatPortalDate(customer.updated_at) }}</strong></div>
          </div>
        </section>

        <section class="library-stats" :aria-label="`${customer.customer_name} 素材统计`">
          <div><strong>{{ customer.image_count }}</strong><span>Photos</span></div>
          <div><strong>{{ customer.video_count }}</strong><span>Videos</span></div>
          <div><strong>{{ customer.published_batch_count }}</strong><span>Deliveries</span></div>
          <div><strong>{{ customer.asset_count }}</strong><span>Assets</span></div>
        </section>

        <div v-if="customer.status === 'disabled'" class="notice-bar disabled-notice">
          <div><span class="notice-check">!</span><span><strong>This client portal is disabled.</strong> The client cannot sign in or view any material.</span></div>
          <span class="notice-private">ACCESS BLOCKED</span>
        </div>

        <div v-else class="notice-bar">
          <div><span class="notice-check">✓</span><span><strong>{{ customer.published_batch_count }} published deliveries.</strong> Everything below is visible to this client.</span></div>
          <span class="notice-private">PRIVATE · SECURE</span>
        </div>

        <section v-if="customer.status !== 'disabled'" class="sku-finder" aria-label="筛选客户素材">
          <div class="finder-heading">
            <div><span class="eyebrow">FIND YOUR MATERIALS</span><h2>Browse the client library</h2></div>
            <label class="search-field"><span>⌕</span><input v-model="search" aria-label="搜索素材" placeholder="Search file name" /></label>
          </div>
          <div class="finder-row">
            <span>Media</span>
            <div class="finder-options" role="tablist" aria-label="素材类型">
              <button v-for="option in mediaOptions" :key="option.value" type="button" :class="{ active: mediaType === option.value }" @click="mediaType = option.value">{{ option.label }}</button>
            </div>
          </div>
        </section>

        <div v-if="customer.status === 'disabled'" class="empty-state disabled-state">
          <span>!</span>
          <h3>Client access is currently disabled.</h3>
          <p>Enable the portal account before the client can sign in and see published materials.</p>
        </div>

        <div v-else-if="filteredBatches.length" class="sku-library">
          <section v-for="(batch, index) in filteredBatches" :key="batch.id" class="sku-section">
            <header class="sku-heading">
              <div>
                <span>{{ String(index + 1).padStart(2, '0') }} · SHOOTING DELIVERY</span>
                <h2>{{ batch.title || `拍摄交付 R${batch.revision}` }}</h2>
                <p>{{ formatPortalDate(batch.published_at) }} · {{ batch.assets.length }} assets · {{ batchAssetCount(batch, 'image') }} photos · {{ batchAssetCount(batch, 'video') }} videos</p>
              </div>
              <span v-if="batch.shoot_type" class="shoot-tag">{{ batch.shoot_type }}</span>
            </header>
            <div class="asset-gallery">
              <article v-for="(asset, assetIndex) in batch.assets" :key="asset.id" class="asset-card">
                <button v-if="asset.media_type === 'image'" class="asset-preview" type="button" :aria-label="`Open ${asset.file_name}`" @click="previewAsset = asset">
                  <img :src="asset.content_url" :alt="asset.file_name" loading="lazy" />
                </button>
                <div v-else class="asset-preview video-preview">
                  <video :src="asset.content_url" controls preload="metadata" />
                </div>
                <div class="asset-footer">
                  <span><strong>{{ asset.media_type === 'image' ? `View ${String(assetIndex + 1).padStart(2, '0')}` : 'Video' }}</strong><small>{{ formatFileSize(asset.file_size) }}</small></span>
                  <a :href="appendDownload(asset.content_url)">Download ↓</a>
                </div>
              </article>
            </div>
          </section>
        </div>

        <div v-else class="empty-state">
          <span>00</span>
          <h3>{{ batches.length ? 'No material matches this search.' : 'No published materials yet.' }}</h3>
          <p>{{ batches.length ? 'Try another file name or media type.' : 'Only approved and published files appear in the client portal.' }}</p>
          <button v-if="batches.length" type="button" @click="clearFilters">Clear filters</button>
        </div>

        <footer class="library-footer">
          <div class="brand-lockup"><img src="/logo.webp" alt="" /><span><strong>CONTENT</strong><small>HUB</small></span></div>
          <p>Private Client Content Delivery Platform</p>
          <span>© 2026 LeShine Hair</span>
        </footer>
      </div>
    </template>

    <div v-else class="library-loading empty-library">
      <span class="loading-mark">L</span>
      <strong>选择一个客户开始预览</strong>
      <p>左侧仅显示当前账号有权访问的客户门户</p>
    </div>

    <Teleport to="body">
      <div v-if="previewAsset" class="lightbox" role="dialog" aria-modal="true" :aria-label="previewAsset.file_name" @click.self="previewAsset = null">
        <button class="lightbox-close" type="button" aria-label="关闭预览" @click="previewAsset = null">×</button>
        <div class="lightbox-content">
          <img :src="previewAsset.content_url" :alt="previewAsset.file_name" />
          <div class="lightbox-caption"><span>{{ previewAsset.file_name }}</span><a :href="appendDownload(previewAsset.content_url)">Download original ↓</a></div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import {
  appendDownload,
  filterPreviewBatches,
  formatFileSize,
  formatPortalDate,
  initials,
  portalStatusMeta,
} from './portalPreviewState'

const props = defineProps({
  customer: { type: Object, default: null },
  batches: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const mediaOptions = [
  { label: 'All files', value: 'all' },
  { label: 'Photos', value: 'image' },
  { label: 'Videos', value: 'video' },
]
const search = ref('')
const mediaType = ref('all')
const previewAsset = ref(null)
const status = computed(() => portalStatusMeta(props.customer?.status))
const filteredBatches = computed(() => filterPreviewBatches(props.batches, {
  search: search.value,
  mediaType: mediaType.value,
}))

function batchAssetCount(batch, type) {
  return batch.assets.filter(asset => asset.media_type === type).length
}

function clearFilters() {
  search.value = ''
  mediaType.value = 'all'
}

watch(() => props.customer?.customer_id, () => {
  clearFilters()
  previewAsset.value = null
})
</script>

<style scoped>
.client-library { min-height: 100%; color: var(--text-primary); background: linear-gradient(145deg, var(--dash-wash-from), var(--dash-wash-mid) 54%, var(--dash-wash-to)); }
.preview-topbar { display: flex; min-height: 76px; align-items: center; justify-content: space-between; gap: 22px; padding: 12px 30px; border-bottom: 1px solid rgba(61, 51, 35, 0.12); background: rgba(255, 255, 255, 0.72); }
.brand-lockup { display: flex; align-items: center; gap: 10px; }
.brand-lockup img { width: 42px; height: 42px; border-radius: 50%; object-fit: cover; }
.brand-lockup span { display: grid; line-height: 1; letter-spacing: 0.18em; }
.brand-lockup strong { font: 800 11px var(--font-display); }
.brand-lockup small { margin-top: 5px; color: var(--color-primary); font: 700 10px var(--font-display); }
.portal-label { display: grid; gap: 4px; text-align: center; }
.portal-label span,.breadcrumb,.eyebrow,.summary-card span,.notice-private,.sku-heading>div>span { color: var(--color-gold-muted); font: 700 10px var(--font-display); letter-spacing: 0.14em; }
.portal-label strong { font: 600 14px var(--font-body); }
.preview-badge { display: flex; align-items: center; gap: 7px; padding: 8px 11px; border: 1px solid rgba(45, 159, 111, 0.18); border-radius: 999px; color: var(--color-success-text); background: var(--color-success-bg); font-size: 12px; font-weight: 700; }
.preview-badge span { width: 7px; height: 7px; border-radius: 50%; background: var(--color-success); }
.library-content { padding: 34px clamp(22px, 4vw, 56px) 40px; }
.collection-head { display: flex; align-items: center; justify-content: space-between; gap: 30px; padding-bottom: 28px; border-bottom: 1px solid rgba(61, 51, 35, 0.12); }
.collection-identity { display: flex; min-width: 0; align-items: center; gap: 18px; }
.collection-logo { display: grid; width: 72px; height: 72px; flex: 0 0 auto; place-items: center; border-radius: 50%; color: var(--text-on-dark); background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover)); box-shadow: 0 12px 30px var(--color-primary-glow); font: 700 22px var(--font-display); }
.breadcrumb span { padding: 0 5px; color: var(--text-muted); }
.collection-identity h1 { margin: 8px 0 5px; font: 600 clamp(28px, 4vw, 48px) Georgia, serif; letter-spacing: -0.025em; }
.collection-identity p { margin: 0; color: var(--text-secondary); font-size: 14px; }
.summary-card { display: flex; flex: 0 0 auto; border: 1px solid rgba(61, 51, 35, 0.12); border-radius: 4px; background: rgba(255, 255, 255, 0.58); }
.summary-card div { display: grid; min-width: 92px; gap: 7px; padding: 13px 16px; border-right: 1px solid rgba(61, 51, 35, 0.1); }
.summary-card div:last-child { border-right: 0; }
.summary-card strong { font: 600 12px var(--font-body); }
.library-stats { display: grid; grid-template-columns: repeat(4, 1fr); margin: 24px 0; border: 1px solid rgba(61, 51, 35, 0.12); background: rgba(255, 255, 255, 0.48); }
.library-stats div { display: grid; gap: 5px; padding: 18px 22px; border-right: 1px solid rgba(61, 51, 35, 0.1); }
.library-stats div:last-child { border-right: 0; }
.library-stats strong { font: 500 27px Georgia, serif; }
.library-stats span { color: var(--text-secondary); font-size: 12px; }
.notice-bar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 24px; padding: 14px 18px; border: 1px solid rgba(45, 159, 111, 0.15); background: var(--color-success-bg); font-size: 13px; }
.notice-bar>div { display: flex; align-items: center; gap: 10px; }
.notice-check { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 50%; color: var(--text-on-dark); background: var(--color-success); font-size: 12px; }
.disabled-notice { border-color: rgba(180, 58, 48, 0.17); background: var(--color-danger-bg); }
.disabled-notice .notice-check { background: var(--color-danger); }
.sku-finder { margin-bottom: 34px; padding: 24px; border: 1px solid rgba(61, 51, 35, 0.12); background: rgba(255, 255, 255, 0.52); }
.finder-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; padding-bottom: 20px; }
.finder-heading h2 { margin: 7px 0 0; font: 500 24px Georgia, serif; }
.search-field { display: flex; width: min(320px, 100%); align-items: center; gap: 8px; border-bottom: 1px solid var(--border-hover); }
.search-field span { color: var(--text-secondary); font-size: 20px; }
.search-field input { width: 100%; height: 38px; border: 0; outline: 0; color: var(--text-primary); background: transparent; }
.finder-row { display: flex; align-items: center; gap: 20px; padding-top: 16px; border-top: 1px solid rgba(61, 51, 35, 0.1); }
.finder-row>span { width: 62px; color: var(--text-secondary); font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; }
.finder-options { display: flex; flex-wrap: wrap; gap: 7px; }
.finder-options button { padding: 8px 13px; border: 1px solid rgba(61, 51, 35, 0.14); border-radius: 999px; color: var(--text-secondary); background: transparent; cursor: pointer; font-size: 12px; transition: color 180ms ease, background 180ms ease, border-color 180ms ease; }
.finder-options button.active { border-color: var(--text-primary); color: var(--text-on-dark); background: var(--text-primary); }
.sku-section { margin-bottom: 42px; }
.sku-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 15px; padding-bottom: 13px; border-bottom: 1px solid rgba(61, 51, 35, 0.14); }
.sku-heading h2 { margin: 6px 0 4px; font: 500 27px Georgia, serif; }
.sku-heading p { margin: 0; color: var(--text-secondary); font-size: 12px; }
.shoot-tag { padding: 7px 10px; border: 1px solid rgba(61, 51, 35, 0.12); border-radius: 999px; color: var(--text-secondary); background: rgba(255, 255, 255, 0.52); font-size: 11px; }
.asset-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 14px; }
.asset-card { overflow: hidden; border: 1px solid rgba(255, 255, 255, 0.88); background: rgba(255, 255, 255, 0.68); box-shadow: 0 9px 28px rgba(117, 79, 24, 0.1); transition: transform 220ms var(--ease-out-strong), box-shadow 220ms var(--ease-out-strong); }
.asset-preview { display: block; width: 100%; aspect-ratio: 4 / 3; overflow: hidden; border: 0; padding: 0; background: var(--border-color); cursor: zoom-in; }
.asset-preview img,.asset-preview video { width: 100%; height: 100%; object-fit: cover; transition: transform 320ms var(--ease-out-strong); }
.video-preview { cursor: default; }
.asset-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 13px; }
.asset-footer>span { display: grid; min-width: 0; gap: 3px; }
.asset-footer strong { font-size: 12px; }
.asset-footer small { color: var(--text-secondary); font-size: 10px; }
.asset-footer a,.lightbox-caption a { flex: 0 0 auto; color: var(--color-primary-hover); font-size: 11px; font-weight: 700; text-decoration: none; }
.empty-state { padding: 70px 24px; border: 1px dashed rgba(61, 51, 35, 0.18); text-align: center; }
.empty-state>span { color: var(--color-primary); font: 500 38px Georgia, serif; }
.empty-state h3 { margin: 12px 0 5px; font: 500 23px Georgia, serif; }
.empty-state p { margin: 0; color: var(--text-secondary); }
.empty-state button { margin-top: 18px; padding: 9px 14px; border: 1px solid var(--border-hover); border-radius: 999px; background: transparent; cursor: pointer; }
.library-footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 48px; padding-top: 22px; border-top: 1px solid rgba(61, 51, 35, 0.12); color: var(--text-secondary); font-size: 11px; }
.library-footer .brand-lockup img { width: 34px; height: 34px; }
.library-loading { display: grid; min-height: 560px; place-content: center; justify-items: center; padding: 40px; text-align: center; }
.loading-mark { display: grid; width: 74px; height: 74px; place-items: center; margin-bottom: 18px; border-radius: 50%; color: var(--text-on-dark); background: linear-gradient(135deg, var(--color-primary), var(--color-gold)); box-shadow: 0 14px 34px var(--color-primary-glow); font: 600 35px Georgia, serif; }
.library-loading strong { font: 500 25px Georgia, serif; }
.library-loading p { margin: 7px 0 0; color: var(--text-secondary); }
.lightbox { position: fixed; z-index: 3000; inset: 0; display: grid; place-items: center; padding: 34px; background: rgba(16, 14, 12, 0.9); }
.lightbox-close { position: absolute; top: 18px; right: 24px; border: 0; color: var(--text-on-dark); background: transparent; cursor: pointer; font-size: 36px; }
.lightbox-content { max-width: min(1100px, 94vw); }
.lightbox-content img { display: block; max-width: 100%; max-height: 82vh; object-fit: contain; }
.lightbox-caption { display: flex; justify-content: space-between; gap: 20px; padding: 12px 2px 0; color: var(--text-on-dark); }
.lightbox-caption a { color: var(--color-gold); }
@media (hover: hover) and (pointer: fine) { .asset-card:hover { transform: translateY(-2px); box-shadow: 0 14px 34px rgba(117, 79, 24, 0.16); }.asset-card:hover .asset-preview img { transform: scale(1.025); } }
@media (max-width: 980px) { .collection-head { align-items: flex-start; flex-direction: column; }.summary-card { width: 100%; }.summary-card div { flex: 1; }.preview-topbar { padding-inline: 20px; }.preview-badge { display: none; } }
@media (max-width: 700px) { .library-content { padding: 24px 16px 32px; }.portal-label { text-align: right; }.collection-identity { align-items: flex-start; }.collection-logo { width: 56px; height: 56px; }.collection-identity h1 { font-size: 29px; }.summary-card { display: grid; grid-template-columns: repeat(3, 1fr); }.summary-card div { min-width: 0; padding: 11px 9px; }.library-stats { grid-template-columns: repeat(2, 1fr); }.library-stats div:nth-child(2) { border-right: 0; }.library-stats div:nth-child(-n+2) { border-bottom: 1px solid rgba(61, 51, 35, 0.1); }.notice-private { display: none; }.finder-heading { align-items: stretch; flex-direction: column; }.search-field { width: 100%; }.finder-row { align-items: flex-start; flex-direction: column; gap: 10px; }.finder-row>span { width: auto; }.asset-gallery { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }.asset-footer { align-items: flex-start; flex-direction: column; }.library-footer { align-items: flex-start; flex-direction: column; } }
</style>
