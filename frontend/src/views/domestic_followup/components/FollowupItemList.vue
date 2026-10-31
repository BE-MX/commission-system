<template>
  <div class="item-list">
    <div class="item-list-head">
      <span class="item-list-title">{{ title }}</span>
      <GlassButton variant="link" left-icon="Plus" @click="$emit('add')">添加</GlassButton>
    </div>
    <p v-if="!rows.length" class="item-empty">无</p>
    <div v-for="(row, index) in rows" :key="index" class="item-row">
      <el-input v-model="row.text" type="textarea" autosize maxlength="1000" />
      <div v-if="kind !== 'content'" class="item-meta">
        <el-select v-model="row.category" class="item-category">
          <el-option v-for="v in categories" :key="v" :value="v" :label="v" />
        </el-select>
        <el-checkbox v-model="row.severity" true-value="紧急" false-value="一般" size="small">紧急</el-checkbox>
        <el-checkbox v-model="row.record_only" size="small">仅记录，不跟进</el-checkbox>
      </div>
      <div class="item-tail">
        <StatusBadge v-if="row.origin === 'ai_inferred'" value="AI 推断" size="small" />
        <GlassButton variant="link" left-icon="Delete" @click="rows.splice(index, 1)">删除</GlassButton>
      </div>
    </div>
  </div>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'

defineProps({
  title: { type: String, required: true },
  kind: { type: String, required: true },
  rows: { type: Array, required: true },
  categories: { type: Array, default: () => [] },
})
defineEmits(['add'])
</script>

<style scoped>
.item-list { margin-bottom: 12px; }
.item-list-head { display: flex; align-items: center; justify-content: space-between; }
.item-list-title { font-weight: 600; }
.item-empty { margin: 4px 0; color: var(--text-secondary); font-size: 12px; }
.item-row { display: flex; flex-direction: column; gap: 6px; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
.item-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.item-category { width: 160px; }
.item-tail { display: flex; justify-content: space-between; align-items: center; }
</style>
