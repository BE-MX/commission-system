<template>
  <Teleport to="body">
    <transition name="modal">
      <div v-if="version" class="preview-mask" @pointerdown.self="emit('close')">
        <div class="preview" role="dialog" :aria-label="`预览 ${title}`">
          <header class="preview-head">
            <div class="preview-title">
              <span class="mono preview-ver">v{{ version.version_no }}</span>
              <span>{{ title }}</span>
            </div>
            <div class="preview-actions">
              <button class="btn btn-sm" type="button" @click="download">下载</button>
              <button class="preview-close" type="button" aria-label="关闭" @click="emit('close')">
                <svg viewBox="0 0 14 14" width="13" height="13"><path d="M2 2l10 10M12 2 2 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
              </button>
            </div>
          </header>
          <div class="preview-body">
            <div v-if="loading" class="preview-loading"><span class="spinner"></span></div>
            <template v-else>
              <img v-if="kind === 'image'" :src="url" class="preview-img" :alt="title" />
              <iframe v-else-if="kind === 'pdf'" :src="url" class="preview-frame" title="PDF 预览"></iframe>
              <MarkdownView v-else-if="kind === 'md'" :source="text" class="preview-md" />
              <pre v-else-if="kind === 'text'" class="preview-text">{{ text }}</pre>
              <div v-else class="preview-none">
                该类型不支持在线预览，请下载查看
                <button class="btn" type="button" @click="download">下载文件</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import MarkdownView from './MarkdownView.vue'
import { fetchFileLink } from '../api/index.js'

const props = defineProps({
  version: { type: Object, default: null },
  title: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const loading = ref(false)
const url = ref('')
const text = ref('')

const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp']

const kind = computed(() => {
  const ext = props.version?.ext
  if (!ext) return null
  if (IMAGE_EXTS.includes(ext)) return 'image'
  if (ext === '.pdf') return 'pdf'
  if (['.md', '.markdown'].includes(ext)) return 'md'
  if (['.txt', '.log', '.csv'].includes(ext)) return 'text'
  return 'other'
})

watch(
  () => props.version,
  async (v) => {
    url.value = ''
    text.value = ''
    if (!v) return
    loading.value = true
    try {
      const link = await fetchFileLink(v.id, 'inline')
      url.value = link.url
      if (kind.value === 'md' || kind.value === 'text') {
        const resp = await fetch(link.url)
        text.value = await resp.text()
      }
    } finally {
      loading.value = false
    }
  },
  { immediate: true }
)

async function download() {
  const link = await fetchFileLink(props.version.id, 'attachment')
  const a = document.createElement('a')
  a.href = link.url
  a.download = link.download_name
  document.body.appendChild(a)
  a.click()
  a.remove()
}
</script>

<style scoped>
.preview-mask {
  position: fixed;
  inset: 0;
  z-index: 860;
  background: rgba(28, 27, 25, 0.42);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}
.preview {
  width: min(920px, 100%);
  height: min(78vh, 100%);
  background: var(--paper);
  border-radius: var(--radius-lg);
  border: 1px solid var(--hairline-strong);
  box-shadow: var(--shadow-overlay);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transform-origin: center;
}
.preview-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--hairline);
}
.preview-title { display: flex; align-items: baseline; gap: 10px; font-weight: 600; font-size: 14px; }
.preview-ver { color: var(--gold-deep); font-weight: 600; }
.preview-actions { display: flex; align-items: center; gap: 8px; }
.preview-close {
  padding: 6px;
  color: var(--ink-3);
  border-radius: var(--radius);
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .preview-close:hover { color: var(--ink); background: var(--paper-sunken); }
}
.preview-body {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
.preview-loading { display: flex; justify-content: center; padding: 80px 0; }
.preview-img { max-width: 100%; object-fit: contain; margin: auto; }
.preview-frame { flex: 1; width: 100%; border: none; }
.preview-md { padding: 28px 36px; max-width: 720px; margin: 0 auto; }
.preview-text {
  padding: 24px 28px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
.preview-none {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 80px 0;
  color: var(--ink-3);
}
.modal-enter-active { transition: opacity 180ms ease; }
.modal-enter-active .preview { transition: transform 220ms var(--ease-out), opacity 220ms var(--ease-out); }
.modal-leave-active { transition: opacity 140ms ease; }
.modal-leave-active .preview { transition: transform 140ms ease, opacity 140ms ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-from .preview { opacity: 0; transform: scale(0.96) translateY(10px); }
.modal-leave-to .preview { opacity: 0; transform: scale(0.98) translateY(6px); }
</style>
