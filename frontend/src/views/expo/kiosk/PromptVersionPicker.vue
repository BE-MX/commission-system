<template>
  <div class="prompt-picker">
    <div class="picker-title">出图风格 <button :disabled="flow.promptVersionsLoading.value" @click="flow.loadPromptVersions()">{{ flow.promptVersionsLoading.value ? '加载中…' : '刷新' }}</button></div>
    <div v-if="flow.promptVersionsError.value" class="picker-error" role="alert">{{ flow.promptVersionsError.value }}</div>
    <div class="picker-options" role="group" aria-label="出图风格">
      <button v-for="version in flow.promptVersions.value" :key="version.id" class="picker-option"
        :aria-pressed="flow.promptVersionId.value === version.id"
        :class="{ selected: flow.promptVersionId.value === version.id }"
        :disabled="flow.promptVersionsLoading.value"
        @click="flow.promptVersionId.value = version.id; flow.touch()">
        <span>{{ version.name }}</span><small v-if="version.hint">{{ version.hint }}</small>
      </button>
    </div>
  </div>
</template>

<script setup>
import { inject, onMounted, onBeforeUnmount } from 'vue'
const flow = inject('tryonFlow')
function refresh() { flow.loadPromptVersions() }
onMounted(() => { refresh(); window.addEventListener('focus', refresh) })
onBeforeUnmount(() => window.removeEventListener('focus', refresh))
</script>

<style scoped>
.prompt-picker { width: min(100%, 760px); flex: none; padding-top: 10px; border-top: 1px solid var(--xk-gold-line); }
.picker-title { color: var(--xk-gold-dim); font-size: 14px; display: flex; justify-content: space-between; align-items: center; }
.picker-title button { background: transparent; border: 0; color: var(--xk-gold); min-height: 48px; padding: 8px 12px; cursor: pointer; }
.picker-options { display: flex; gap: 8px; overflow-x: auto; padding: 4px 3px 6px; }
.picker-option { flex: 1 0 120px; min-height: 54px; display: flex; flex-direction: column; justify-content: center; gap: 4px; border: 1px solid var(--xk-gold-line); background: transparent; border-radius: 7px; padding: 9px 14px; color: var(--xk-paper); cursor: pointer; overflow-wrap: anywhere; }
.picker-option.selected { border-color: var(--xk-gold); background: var(--xk-selected); }
.picker-option small { color: var(--xk-mut); font-size: 12px; }
.picker-error { color: var(--xk-warn); font-size: 14px; padding: 8px 0; }
.picker-option:disabled { opacity: 0.5; }
@media (max-height: 700px) { .prompt-picker { padding-top: 2px; } .picker-title button { min-height: 36px; } }
@media (max-width: 600px) { .picker-option { flex-basis: calc((100% - 16px) / 3); min-width: 88px; padding: 9px 8px; } }
</style>
