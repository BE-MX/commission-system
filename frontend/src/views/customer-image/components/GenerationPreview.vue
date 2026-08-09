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
      <div>
        <span>实时预览</span>
        <h2 id="preview-title">{{ product?.name || '产品效果图' }}</h2>
      </div>
      <button
        v-if="generation?.status === 'succeeded' && resultUrl"
        type="button"
        class="download"
        @click="$emit('download', generation)"
      >
        下载
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

    <p v-if="generation?.status === 'queued'" class="keep-copy">已提交，可以关闭页面，结果会保留在这里</p>
    <p v-else-if="generation?.status === 'running'" class="keep-copy">正在生成，通常需要几十秒到数分钟</p>
  </section>
</template>

<style scoped>
.preview-panel { display: grid; min-height: 0; gap: 14px; }
.preview-heading { display: flex; min-height: 44px; align-items: center; justify-content: space-between; gap: 12px; }
.preview-heading span { color: var(--cip-muted); font-size: 11px; }
h2 { margin: 3px 0 0; color: var(--cip-ink); font-size: 16px; }
.download { min-height: 44px; padding: 0 16px; cursor: pointer; border: 1px solid var(--cip-accent); border-radius: 10px; color: var(--cip-accent-strong); background: var(--cip-accent-soft); font-weight: 650; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.download:active { transform: scale(.98); }
.preview-stage { position: relative; display: grid; min-height: 420px; place-items: center; overflow: hidden; border: 1px solid var(--cip-border); border-radius: 18px; background: var(--cip-canvas); }
.preview-stage img { width: 100%; height: 100%; max-height: 66vh; object-fit: contain; }
.preview-stage img.reference { opacity: .86; }
.generated-result { animation: result-arrive 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.placeholder { color: var(--cip-muted); font-size: 13px; }
.status-overlay { position: absolute; inset: auto 18px 18px; padding: 14px; border: 1px solid var(--cip-border); border-radius: 12px; background: var(--cip-surface); box-shadow: 0 8px 24px var(--cip-shadow); }
.status-overlay strong { color: var(--cip-ink); font-size: 13px; }
.status-overlay p, .keep-copy { margin: 6px 0 0; color: var(--cip-muted); font-size: 12px; line-height: 1.55; }
.status-dot { display: inline-block; width: 8px; height: 8px; margin-right: 7px; border-radius: 50%; background: var(--cip-accent); }
.status-dot[data-status="failed"] { background: var(--cip-danger); }
@media (hover: hover) and (pointer: fine) { .download:hover { background: var(--cip-accent-soft-hover); } }
@keyframes result-arrive { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 760px) { .preview-stage { min-height: 310px; } }
@media (prefers-reduced-motion: reduce) { .download { transition: none; } .download:active { transform: none; } .generated-result { animation: none; } }
</style>
