<template>
  <div class="usage-list">
    <div class="list-toolbar">
      <div>
        <strong>生成用量</strong>
        <span>按任务核对运行状态、Token 用量和预估成本。</span>
      </div>
      <GlassButton variant="outline" left-icon="Refresh" :loading="loading" @click="load()">刷新</GlassButton>
    </div>

    <el-table v-loading="loading" :data="generations" empty-text="暂无生成记录">
      <el-table-column prop="id" label="任务" width="90">
        <template #default="{ row }">#{{ row.id }}</template>
      </el-table-column>
      <el-table-column prop="product_name" label="产品" min-width="170" show-overflow-tooltip />
      <el-table-column prop="invite_id" label="邀请" width="90">
        <template #default="{ row }">#{{ row.invite_id }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }"><el-tag :type="statusType[row.status] || 'info'" effect="plain">{{ statusLabel[row.status] || row.status }}</el-tag></template>
      </el-table-column>
      <el-table-column label="Token" min-width="150">
        <template #default="{ row }">{{ formatNumber(row.total_tokens) }} <small>（入 {{ formatNumber(row.input_tokens) }} / 出 {{ formatNumber(row.output_tokens) }}）</small></template>
      </el-table-column>
      <el-table-column label="预估成本" width="120">
        <template #default="{ row }">{{ formatCost(row.estimated_cost_microusd) }}</template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="170">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="error_message" label="异常" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ row.error_message || '-' }}</template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="generationPage"
      v-model:page-size="generationPageSize"
      :total="generationTotal"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @current-change="load"
      @size-change="changeSize"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'

const props = defineProps({ state: { type: Object, required: true } })
const { generations, generationPage, generationPageSize, generationTotal } = props.state
const loading = ref(false)
const statusLabel = { queued: '排队中', running: '生成中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const statusType = { queued: 'info', running: 'warning', succeeded: 'success', failed: 'danger', cancelled: 'info' }
const formatDate = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
const formatNumber = value => Number(value || 0).toLocaleString('zh-CN')
const formatCost = value => value == null ? '-' : `$${(Number(value) / 1_000_000).toFixed(4)}`

async function load(page = generationPage.value) {
  loading.value = true
  try { await props.state.loadGenerations(page, generationPageSize.value) } finally { loading.value = false }
}
async function changeSize(size) {
  loading.value = true
  try { await props.state.loadGenerations(1, size) } finally { loading.value = false }
}

onMounted(load)
</script>

<style scoped>
.usage-list { min-width: 0; }
.list-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 64px; }
.list-toolbar div { display: grid; gap: 3px; }
.list-toolbar span, small { color: var(--el-text-color-secondary); font-size: 13px; }
.el-pagination { justify-content: flex-end; margin-top: 16px; }
:deep(.glass-button:not(.glass-button--link)) { min-height: 44px; }
@media (max-width: 720px) { .el-pagination { justify-content: flex-start; overflow-x: auto; } }
</style>
