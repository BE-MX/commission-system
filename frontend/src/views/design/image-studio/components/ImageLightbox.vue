<template>
  <Transition name="lightbox">
    <div
      v-if="asset"
      ref="lightboxDialog"
      class="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="查看生成原图"
      tabindex="-1"
      @click.self="emit('close')"
      @keydown="onDialogKeydown"
    >
      <div class="lightbox-panel">
        <button type="button" class="close-button" aria-label="关闭大图" @click="emit('close')">
          <el-icon><Close /></el-icon>
        </button>
        <img v-if="url" :src="url" alt="生成结果原图" />
        <div v-else class="lightbox-loading"><el-icon class="is-loading"><Loading /></el-icon><span>正在读取原图…</span></div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { Close, Loading } from '@element-plus/icons-vue'
import { focusDialog, restoreDialogFocus, trapDialogFocus } from '../state'

const props = defineProps({ asset: { type: Object, default: null }, url: { type: String, default: null } })
const emit = defineEmits(['close'])
const lightboxDialog = ref(null)
let restoreTarget = null

function onDialogKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  trapDialogFocus(event, lightboxDialog.value)
}
watch(() => props.asset, async (value, previous) => {
  if (value && !previous) {
    restoreTarget = document.activeElement
    await nextTick()
    focusDialog(lightboxDialog.value)
  } else if (previous) {
    await nextTick()
    restoreDialogFocus(restoreTarget)
    restoreTarget = null
  }
})
</script>

<style scoped>
.lightbox { position: fixed; z-index: 2200; inset: 0; display: grid; place-items: center; padding: 24px; background: var(--sidebar-glass-to); }
.lightbox-panel { position: relative; display: grid; max-width: min(94vw, 1280px); max-height: 92vh; place-items: center; }
.lightbox img { display: block; max-width: 100%; max-height: 90vh; border-radius: var(--dash-card-radius); object-fit: contain; }
.close-button { position: absolute; z-index: 1; top: 10px; right: 10px; display: grid; width: 38px; height: 38px; place-items: center; border: 1px solid var(--dash-glass-dark-border); border-radius: 50%; background: var(--sidebar-glass-from); color: var(--text-on-dark); cursor: pointer; }
.lightbox-loading { display: flex; align-items: center; gap: 10px; color: var(--text-on-dark); }
.lightbox-enter-active, .lightbox-leave-active { transition: opacity 220ms cubic-bezier(0.23, 1, 0.32, 1); }
.lightbox-enter-active .lightbox-panel { transition: transform 220ms cubic-bezier(0.23, 1, 0.32, 1); }
.lightbox-enter-from, .lightbox-leave-to { opacity: 0; }
.lightbox-enter-from .lightbox-panel { transform: scale(0.97); }
@media (hover: hover) and (pointer: fine) { .close-button:hover { opacity: 0.82; } }
@media (prefers-reduced-motion: reduce) {
  .lightbox-enter-active, .lightbox-leave-active { transition: opacity 160ms linear; }
  .lightbox-enter-active .lightbox-panel { transition: opacity 160ms linear; }
  .lightbox-enter-from .lightbox-panel { transform: none; opacity: 0; }
}
</style>
