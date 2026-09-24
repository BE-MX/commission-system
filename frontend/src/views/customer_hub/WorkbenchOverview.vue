<template>
  <section class="workbench-overview lg-card">
    <div class="overview-cards">
      <button
        v-for="card in mapped.cards"
        :key="card.key"
        type="button"
        class="overview-card"
        @click="$emit('select-view', card.toView)"
      >
        <span class="card-label">{{ card.label }}</span>
        <span class="card-value">{{ card.value }}</span>
        <span class="card-hint">{{ card.hint }}</span>
      </button>
    </div>
    <div class="overview-status">
      <div v-if="!mapped.scans" class="scans-empty">今日尚未评估（规则扫描与 AI 分析分开统计）</div>
      <template v-else>
        <div v-for="row in mapped.scansRows" :key="row.key" class="scans-row">
          <span class="scans-label">{{ row.label }}</span>
          <span>应检 {{ row.expected ?? '—' }}</span>
          <span>完成 {{ row.completed ?? '—' }}</span>
          <span v-if="row.skipped != null">跳过 {{ row.skipped }}</span>
          <span class="scans-failed">失败 {{ row.failed ?? '—' }}</span>
        </div>
      </template>
      <div class="watermark-row">
        <span v-for="item in mapped.watermarks" :key="item.source" class="watermark-item">
          {{ item.source }}
          <el-tag size="small" :type="item.status === 'fresh' ? 'success' : 'warning'">
            {{ WATERMARK_STATUS_LABELS[item.status] || item.status }}
          </el-tag>
          <span v-if="item.syncedThrough" class="watermark-time">{{ item.syncedThrough }}</span>
        </span>
        <span v-if="!mapped.watermarks.length" class="watermark-empty">暂无来源同步水位</span>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getWorkbenchOverview } from '@/api/customerHub'
import { mapWorkbenchOverview, WATERMARK_STATUS_LABELS } from './customerWorkspaceController'

defineEmits(['select-view'])
const mapped = ref({ cards: [], scans: null, scansRows: [], watermarks: [], generatedAt: null })

async function refresh() {
  try {
    const response = await getWorkbenchOverview({ customer_scope: 'primary', action_scope: 'mine' })
    mapped.value = mapWorkbenchOverview(response.data)
  } catch {
    mapped.value = { cards: [], scans: null, scansRows: [], watermarks: [], generatedAt: null }
  }
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<style scoped>
.workbench-overview { display: grid; gap: 12px; padding: 16px; }
.overview-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.overview-card {
  display: grid; gap: 4px; padding: 12px; text-align: left;
  border: 1px solid var(--border-color); border-radius: var(--card-radius, 10px);
  background: var(--card-bg); cursor: pointer; color: var(--text-primary);
}
.overview-card:hover { border-color: var(--color-primary); }
.card-label { color: var(--text-secondary); font-size: 12px; }
.card-value { font-size: 22px; font-weight: 600; }
.card-hint { color: var(--text-muted); font-size: 12px; }
.overview-status { display: grid; gap: 6px; font-size: 12px; color: var(--text-secondary); }
.scans-row { display: flex; gap: 12px; flex-wrap: wrap; }
.scans-label { min-width: 88px; color: var(--text-primary); }
.scans-failed { color: var(--color-danger); }
.watermark-row { display: flex; gap: 12px; flex-wrap: wrap; }
.watermark-item { display: inline-flex; align-items: center; gap: 4px; }
.watermark-time { color: var(--text-muted); }
.scans-empty, .watermark-empty { color: var(--text-muted); }
@media (max-width: 768px) {
  .overview-cards { grid-template-columns: repeat(2, 1fr); }
}
</style>
