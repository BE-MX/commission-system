<template>
  <section class="mode-bar" aria-label="当前对话方式">
    <div class="mode-row">
      <span>当前方式：<strong>{{ mode.title }}</strong></span>
      <div class="mode-actions">
        <button type="button" :disabled="loading || !!error" @click="$emit('details')">查看说明</button>
        <button v-if="!locked" type="button" :disabled="disabled" aria-label="移除当前对话方式" @click="$emit('remove')">×</button>
      </div>
    </div>
    <div v-if="mode.kind === 'skill'" class="mode-file">
      <el-icon aria-hidden="true"><Document /></el-icon>
      <button type="button" :disabled="loading || !!error" @click="$emit('details')">{{ mode.filename }}</button>
      <span v-if="!error" role="status">{{ loading ? '加载中…' : '已加载' }}</span>
    </div>
    <p v-else-if="loading" role="status">正在加载对话规则…</p>
    <p v-if="error" class="mode-error" role="alert">{{ error }} <button type="button" :disabled="disabled" @click="$emit('retry')">重试</button></p>
    <p v-else-if="mode.id === 'talent' && !locked">每次只聊一个问题，可随时停下并继续。结果用于自我探索，不是心理诊断。</p>
  </section>
</template>

<script setup>
import { Document } from '@element-plus/icons-vue'
defineProps({ mode: { type: Object, required: true }, loading: Boolean, error: String, locked: Boolean, disabled: Boolean })
defineEmits(['details', 'remove', 'retry'])
</script>

<style scoped>
.mode-bar { width: min(100%, 820px); margin: 0 auto 8px; color: var(--text-secondary); font-size: 12px; }
.mode-row, .mode-file, .mode-actions { display: flex; align-items: center; gap: 8px; min-width: 0; }
.mode-row { justify-content: space-between; }
.mode-row strong { color: var(--color-primary); }
.mode-actions { flex-shrink: 0; }
.mode-bar button { min-height: 44px; min-width: 44px; padding: 0 8px; border: 0; background: transparent; color: var(--color-primary); font: inherit; cursor: pointer; }
.mode-bar button:disabled { opacity: .55; cursor: not-allowed; }
.mode-bar button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.mode-file button { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.mode-file > span { flex-shrink: 0; }
.mode-bar p { margin: 2px 0; line-height: 1.5; }
.mode-error { color: var(--color-danger); }
</style>
