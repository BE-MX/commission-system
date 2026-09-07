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
.prompt-picker { width: min(88vw, 640px); flex: none; margin-top: 12px; }
.picker-title { color: var(--xk-gold-dim); font-size: 12px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.picker-title button { background: transparent; border: 0; color: var(--xk-gold); padding: 8px 12px; cursor: pointer; }
.picker-options { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; }
.picker-option { flex: 1 0 120px; max-width: 240px; display: flex; flex-direction: column; justify-content: center; gap: 4px; border: 1px solid var(--xk-gold-line); background: var(--xk-ink); border-radius: 12px; padding: 10px 14px; color: var(--xk-paper); cursor: pointer; overflow-wrap: anywhere; }
.picker-option.selected { border-color: var(--xk-gold); color: var(--xk-gold-hi); }
.picker-option small { color: var(--xk-mut); font-size: 10px; }
.picker-error { color: var(--xk-gold-hi); font-size: 13px; padding: 8px 0; }
.picker-option:focus-visible, .picker-title button:focus-visible { outline: 2px solid var(--xk-gold-hi); outline-offset: 2px; }
</style>
