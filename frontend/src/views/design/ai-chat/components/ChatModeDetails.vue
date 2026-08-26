<template>
  <el-drawer :model-value="open" class="chat-mode-drawer" :title="mode?.title || '对话方式说明'" size="min(560px, 100vw)" append-to-body :destroy-on-close="true" @update:model-value="$emit('update:open', $event)">
    <template v-if="mode">
      <p class="mode-description">{{ mode.description }}</p>
      <dl class="mode-facts">
        <dt>类型</dt><dd>{{ mode.kind === 'skill' ? 'Skill 文件 · 方案对话适配版' : 'Prompt · 内置规则文件' }}</dd>
        <dt>生效范围</dt><dd>本会话持续生效；更换方式请新建对话。</dd>
        <dt>文件</dt><dd>{{ mode.filename }}</dd>
        <dt>版本</dt><dd>{{ mode.version?.slice(0, 12) || '尚未加载' }}</dd>
      </dl>
      <p v-if="mode.kind === 'skill'" class="mode-note">保留盲区梳理、逐题访谈和理解检验，不执行 Git、写文件或其他编码工具。原始文件另行保留，当前加载的是网页适配版。</p>
    </template>
    <p v-if="loading" role="status">正在读取规则文件…</p>
    <p v-else-if="error" role="alert">{{ error }} <el-button text @click="$emit('retry')">重试</el-button></p>
    <details v-else-if="content" class="mode-content">
      <summary>展开规则原文</summary>
      <div class="markdown-body" v-html="rendered" />
    </details>
  </el-drawer>
</template>

<script setup>
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
const props = defineProps({ open: Boolean, mode: Object, content: String, loading: Boolean, error: String })
defineEmits(['update:open', 'retry'])
const rendered = computed(() => DOMPurify.sanitize(marked.parse(props.content || '')))
</script>

<style scoped>
.mode-description { color: var(--text-primary); line-height: 1.6; }
.mode-facts { display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 14px 12px; font-size: 13px; line-height: 1.6; }
.mode-facts dt { color: var(--text-secondary); }
.mode-facts dd { margin: 0; overflow-wrap: anywhere; }
.mode-note { padding: 12px; border-radius: 10px; background: var(--color-gold-soft); color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.mode-content { margin-top: 24px; }
.mode-content summary { min-height: 44px; cursor: pointer; color: var(--color-primary); }
.markdown-body { overflow-wrap: anywhere; line-height: 1.8; font-size: 14px; }
.markdown-body :deep(pre) { overflow-x: auto; }
.markdown-body :deep(table) { display: block; overflow-x: auto; }
</style>
