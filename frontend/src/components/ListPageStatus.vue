<template>
  <div v-if="error" class="list-page-status">
    <el-alert :title="hasData ? '数据更新失败' : '列表加载失败'" :type="hasData ? 'warning' : 'error'" :closable="false" show-icon>
      <p v-if="hasData">当前显示上次成功加载的结果<span v-if="paged">（第 {{ dataPage }} 页）</span>，可能已过期。</p>
      <p>{{ error }}</p>
      <GlassButton :left-icon="Refresh" :loading="loading" @click="$emit('retry')">重试加载</GlassButton>
    </el-alert>
  </div>
  <p v-else-if="loading" class="list-page-loading" role="status">正在加载…</p>
  <slot v-else />
</template>

<script setup>
import { Refresh } from '@element-plus/icons-vue'
import GlassButton from './GlassButton.vue'

defineProps({
  error: { type: String, default: '' },
  loading: Boolean,
  hasData: Boolean,
  paged: { type: Boolean, default: true },
  dataPage: { type: Number, default: 1 },
})
defineEmits(['retry'])
</script>

<style scoped>
.list-page-status { padding: 12px 14px; text-align: left; }
.list-page-status p { margin: 0 0 8px; overflow-wrap: anywhere; }
.list-page-loading { padding: 20px; color: var(--text-secondary); }
</style>
