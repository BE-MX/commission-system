<script setup>
defineProps({
  product: { type: Object, default: null },
  coverUrl: { type: String, default: '' },
  generation: { type: Object, default: null },
  resultUrl: { type: String, default: '' },
  message: { type: String, default: '' },
})

defineEmits(['download'])
</script>

<template>
  <section id="customer-generation-result" class="preview-panel" aria-labelledby="preview-title">
    <div class="preview-heading">
      <div class="preview-title">
        <span class="eyebrow">CUSTOM PREVIEW</span>
        <h2 id="preview-title">{{ product?.name || '产品效果图' }}</h2>
      </div>
      <button
        v-if="generation?.status === 'succeeded' && resultUrl"
        type="button"
        class="download"
        @click="$emit('download', generation)"
      >
        下载效果图
      </button>
    </div>

    <div class="preview-stage">
      <img v-if="resultUrl" :src="resultUrl" :alt="`${product?.name || '产品'}生成效果图`" class="generated-result">
      <img v-else-if="coverUrl" :src="coverUrl" :alt="`${product?.name || '产品'}参考图`" class="reference">
      <div v-else class="placeholder">选择产品后查看参考图</div>
      <div v-if="generation && generation.status !== 'succeeded'" class="status-overlay" aria-live="polite">
        <span class="status-dot" :data-status="generation.status" />
        <strong>{{ generation.status === 'failed' ? '本次未完成' : generation.status === 'running' ? '正在生成' : '等待生成' }}</strong>
        <p>{{ message }}</p>
      </div>
    </div>

    <div class="stage-note">
      <span v-if="generation?.status === 'queued'">已提交，可以关闭页面，结果会保留在这里</span>
      <span v-else-if="generation?.status === 'running'">正在生成，通常需要几十秒到数分钟</span>
      <span v-else>{{ product?.category || '实时预览' }}</span>
      <span>AI 生成 · 莱莎专属定制</span>
    </div>
  </section>
</template>

<style scoped>
.preview-panel { display: grid; min-height: 0; gap: 14px; align-content: start; }
.preview-heading { display: flex; min-height: 44px; align-items: flex-end; justify-content: space-between; gap: 14px; }
.eyebrow { color: var(--cip-faint); font-size: 9px; font-weight: 700; letter-spacing: .2em; }
.preview-title { min-width: 0; }
h2 { margin: 5px 0 0; overflow: hidden; color: var(--cip-ink); font-family: var(--cip-font-display); font-size: clamp(20px, 2.4vw, 28px); font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.download { min-height: 44px; padding: 0 18px; cursor: pointer; border: 1px solid var(--cip-border-strong); border-radius: 999px; color: var(--cip-ink); background: var(--cip-accent-soft); font-weight: 650; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.download:active { transform: scale(.98); }
.preview-stage { position: relative; display: grid; min-height: 460px; place-items: center; overflow: hidden; border: 1px solid var(--cip-border); border-radius: 18px; background: var(--cip-canvas); box-shadow: 0 22px 55px var(--cip-shadow); }
.preview-stage img { width: 100%; height: 100%; max-height: 66vh; object-fit: contain; }
.preview-stage img.reference { opacity: .88; }
.generated-result { animation: result-arrive 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.placeholder { color: var(--cip-muted); font-size: 13px; }
.status-overlay { position: absolute; inset: auto 18px 18px; padding: 14px 16px; border: 1px solid var(--cip-border); border-radius: 14px; background: var(--cip-surface); box-shadow: 0 10px 28px var(--cip-shadow); }
.status-overlay strong { color: var(--cip-ink); font-size: 13px; }
.status-overlay p { margin: 6px 0 0; color: var(--cip-muted); font-size: 12px; line-height: 1.6; }
.status-dot { display: inline-block; width: 8px; height: 8px; margin-right: 7px; border-radius: 50%; background: var(--cip-highlight); }
.status-dot[data-status="failed"] { background: var(--cip-danger); }
.stage-note { display: flex; justify-content: space-between; gap: 12px; color: var(--cip-faint); font-size: 10px; letter-spacing: .04em; }
@media (hover: hover) and (pointer: fine) { .download:hover { background: var(--cip-accent-soft-hover); border-color: var(--cip-highlight); } }
@keyframes result-arrive { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 760px) {
  .preview-stage { min-height: 300px; }
  h2 { font-size: 19px; }
  .stage-note span:last-child { display: none; }
}
@media (prefers-reduced-motion: reduce) { .download { transition: none; } .download:active { transform: none; } .generated-result { animation: none; } }
</style>
