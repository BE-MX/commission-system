<script setup>
import CustomerLogoUpload from './components/CustomerLogoUpload.vue'
import GenerationHistory from './components/GenerationHistory.vue'
import GenerationPreview from './components/GenerationPreview.vue'
import ProductOptionGroup from './components/ProductOptionGroup.vue'

defineProps({
  product: { type: Object, required: true },
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
  generationMessage: { type: String, default: '' },
  generateEnabled: { type: Boolean, default: false },
  generateHint: { type: String, default: '' },
  submitting: { type: Boolean, default: false },
  error: { type: String, default: '' },
  notice: { type: String, default: '' },
})

defineEmits(['back', 'download', 'generate', 'select-generation', 'update-requirement', 'update-selection', 'upload-logo'])
</script>

<template>
  <main class="editor-shell">
    <header class="editor-header">
      <button v-if="canGoBack" type="button" class="back" @click="$emit('back')">← 选择其他产品</button>
      <div class="title">
        <small>{{ product.category }}</small>
        <h1>{{ product.name }}</h1>
      </div>
      <div class="quota" aria-label="生成额度">
        <span>剩余额度</span>
        <strong>{{ quota.remaining }}</strong>
        <small>/ {{ quota.total }}</small>
      </div>
    </header>

    <div class="editor-grid">
      <aside class="settings-panel" data-mobile-step="1">
        <CustomerLogoUpload :logo-url="logoUrl" :uploading="uploadingLogo" @upload="$emit('upload-logo', $event)" />
        <div class="divider" />
        <section class="options-section" aria-labelledby="options-title">
          <div class="section-heading">
            <span>2</span>
            <div>
              <h2 id="options-title">确认产品参数</h2>
              <p>已为您预设标准选项</p>
            </div>
          </div>
          <ProductOptionGroup
            v-for="option in product.options || []"
            :key="option.key"
            :option="option"
            :model-value="selections[option.key]"
            @update:model-value="$emit('update-selection', option.key, $event)"
          />
        </section>
      </aside>

      <section class="preview-column" data-mobile-step="2">
        <GenerationPreview
          :product="product"
          :cover-url="coverUrl"
          :generation="previewGeneration"
          :result-url="generationUrls[previewGeneration?.id] || ''"
          :message="generationMessage"
          @download="$emit('download', $event)"
        />
      </section>

      <aside class="action-panel" data-mobile-step="3">
        <section class="requirement-section">
          <div class="section-heading">
            <span>3</span>
            <div>
              <h2>补充要求</h2>
              <p>可选，最多 500 字</p>
            </div>
          </div>
          <textarea
            :value="requirement"
            maxlength="500"
            rows="4"
            placeholder="例如：LOGO 稍微缩小，整体更简洁"
            @input="$emit('update-requirement', $event.target.value)"
          />
          <small class="count">{{ requirement.length }} / 500</small>
        </section>

        <div class="generate-block">
          <p v-if="error" class="feedback error" role="alert">{{ error }}</p>
          <p v-else-if="notice" class="feedback notice" role="status">{{ notice }}</p>
          <p v-if="generateHint" class="hint">{{ generateHint }}</p>
          <button
            type="button"
            class="generate"
            :disabled="!generateEnabled"
            @click="$emit('generate')"
          >
            {{ submitting ? '正在提交…' : '生成新的效果图' }}
          </button>
          <p class="quota-copy">本次生成将使用 1 次额度，剩余 {{ quota.remaining }} 次</p>
        </div>

        <div class="divider" />
        <GenerationHistory
          :generations="generations"
          :generation-urls="generationUrls"
          :selected-id="previewGeneration?.id"
          @select="$emit('select-generation', $event)"
        />
      </aside>
    </div>
  </main>
</template>

<style scoped>
.editor-shell { width: min(1460px, calc(100% - 32px)); margin: 0 auto; padding: 18px 0 34px; }
.editor-header { display: grid; min-height: 68px; grid-template-columns: 260px minmax(0, 1fr) 320px; align-items: center; gap: 16px; }
.back { justify-self: start; min-height: 44px; padding: 0 12px; cursor: pointer; border: 0; color: var(--cip-muted); background: transparent; }
.title { min-width: 0; }
.title small { color: var(--cip-accent-strong); font-size: 10px; }
h1 { margin: 3px 0 0; overflow: hidden; color: var(--cip-ink); font-size: 19px; text-overflow: ellipsis; white-space: nowrap; }
.quota { justify-self: end; display: flex; min-height: 44px; align-items: baseline; gap: 5px; color: var(--cip-muted); }
.quota span, .quota small { font-size: 11px; }
.quota strong { color: var(--cip-accent-strong); font-size: 22px; }
.editor-grid { display: grid; min-height: calc(100vh - 120px); grid-template-columns: 260px minmax(0, 1fr) 320px; gap: 16px; }
.settings-panel, .preview-column, .action-panel { min-width: 0; border: 1px solid var(--cip-border); border-radius: 16px; background: var(--cip-surface); }
.settings-panel, .action-panel { padding: 18px; }
.settings-panel { align-self: start; display: grid; gap: 18px; max-height: calc(100vh - 108px); overflow-y: auto; }
.preview-column { padding: 18px; }
.action-panel { align-self: start; display: grid; gap: 18px; max-height: calc(100vh - 108px); overflow-y: auto; }
.divider { height: 1px; background: var(--cip-border); }
.options-section, .requirement-section { display: grid; gap: 18px; }
.section-heading { display: flex; gap: 10px; align-items: flex-start; }
.section-heading > span { display: grid; width: 28px; height: 28px; place-items: center; flex: 0 0 28px; border-radius: 50%; color: var(--cip-accent-strong); background: var(--cip-accent-soft); font-weight: 700; }
.section-heading h2 { margin: 2px 0 0; color: var(--cip-ink); font-size: 15px; }
.section-heading p { margin: 4px 0 0; color: var(--cip-muted); font-size: 12px; }
textarea { box-sizing: border-box; width: 100%; min-height: 104px; resize: vertical; padding: 11px 12px; border: 1px solid var(--cip-border); border-radius: 10px; outline: none; color: var(--cip-ink); background: var(--cip-surface-subtle); font: inherit; font-size: 13px; line-height: 1.55; }
textarea:focus { border-color: var(--cip-accent); box-shadow: 0 0 0 3px var(--cip-focus); }
.count { justify-self: end; margin-top: -12px; color: var(--cip-muted); font-size: 10px; }
.generate-block { display: grid; gap: 9px; }
.generate { min-height: 48px; cursor: pointer; border: 0; border-radius: 11px; color: var(--cip-on-accent); background: var(--cip-accent); font-size: 14px; font-weight: 750; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1), opacity 180ms ease; }
.generate:active:not(:disabled) { transform: scale(.98); }
.generate:disabled { cursor: not-allowed; opacity: .45; }
.feedback, .hint, .quota-copy { margin: 0; font-size: 11px; line-height: 1.5; }
.feedback { padding: 9px 10px; border-radius: 8px; }
.feedback.error { color: var(--cip-danger); background: var(--cip-danger-soft); }
.feedback.notice { color: var(--cip-success); background: var(--cip-success-soft); }
.hint, .quota-copy { color: var(--cip-muted); text-align: center; }
@media (hover: hover) and (pointer: fine) { .generate:not(:disabled):hover { background: var(--cip-accent-hover); } .back:hover { color: var(--cip-ink); } }
@media (max-width: 1080px) and (min-width: 761px) { .editor-header, .editor-grid { grid-template-columns: 240px minmax(0, 1fr) 280px; } }
@media (max-width: 760px) {
  .editor-shell { width: 100%; padding: 0 0 calc(104px + env(safe-area-inset-bottom)); }
  .editor-header { position: sticky; z-index: 3; top: 0; display: grid; min-height: 62px; grid-template-columns: auto minmax(0, 1fr) auto; gap: 5px; padding: 0 10px; border-bottom: 1px solid var(--cip-border); background: var(--cip-surface); }
  .title small { display: none; }
  .title h1 { font-size: 15px; }
  .quota span, .quota small { display: none; }
  .quota strong { font-size: 18px; }
  .editor-grid { display: flex; min-height: 0; flex-direction: column; gap: 10px; padding: 10px; }
  [data-mobile-step="1"] { order: 2; }
  [data-mobile-step="2"] { order: 1; }
  [data-mobile-step="3"] { order: 3; }
  .settings-panel, .preview-column, .action-panel { width: auto; max-height: none; overflow: visible; border-radius: 14px; }
  .action-panel { padding-bottom: 18px; }
  .generate-block { position: sticky; z-index: 2; bottom: calc(8px + env(safe-area-inset-bottom)); padding: 10px; border: 1px solid var(--cip-border); border-radius: 12px; background: var(--cip-surface); box-shadow: 0 8px 26px var(--cip-shadow); }
}
@media (prefers-reduced-motion: reduce) { .generate { transition: none; } .generate:active:not(:disabled) { transform: none; } }
</style>
