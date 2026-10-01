<template>
  <div class="usage-list">
    <div class="list-toolbar">
      <div>
        <strong>生成用量</strong>
        <span>按任务核对运行状态、Token 用量和预估成本。</span>
      </div>
    </div>

    <section ref="panelRef" class="table-card">
      <!-- 操作行：本页无页级主操作，仅 TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="load()"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listResource.hasData.value" :paged="true" :error="listResource.errorMessage.value" :loading="loading" :has-data="true" :data-page="listResource.dataPage.value" @retry="load()" />
      <el-table v-loading="loading" :data="generations" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <template #empty><ListPageStatus :paged="true" :error="listResource.errorMessage.value" :loading="loading" @retry="load()"><el-empty v-if="listResource.isEmpty.value" :image-size="96" description="暂无数据" /></ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('task')" prop="id" label="任务" min-width="90">
          <template #default="{ row }">#{{ row.id }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('product')" prop="product_name" label="产品" min-width="170" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('invite')" prop="invite_id" label="邀请" min-width="90">
          <template #default="{ row }">#{{ row.invite_id }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="110">
          <template #default="{ row }"><StatusBadge :type="statusType[row.status] || 'info'" effect="plain">{{ statusLabel[row.status] || row.status }}</StatusBadge></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('tokens')" label="Token" min-width="150">
          <template #default="{ row }">{{ formatNumber(row.total_tokens) }} <small>（入 {{ formatNumber(row.input_tokens) }} / 出 {{ formatNumber(row.output_tokens) }}）</small></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('cost')" label="预估成本" min-width="120">
          <template #default="{ row }">{{ formatCost(row.estimated_cost_microusd) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('created-at')" label="创建时间" min-width="170">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('error')" prop="error_message" label="异常" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.error_message || '-' }}</template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="generationPage"
        v-model:page-size="generationPageSize"
        :total="generationTotal"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @current-change="load"
        @size-change="changeSize"
      />
    </section>
  </div>
</template>

<script setup>
import { formatMoney } from '../../../utils/money.js'

import { onMounted, ref } from 'vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { formatBeijingDateTime } from '@/utils/datetime'

const props = defineProps({ state: { type: Object, required: true } })
const { generations, generationPage, generationPageSize, generationTotal } = props.state
const listResource = props.state.generationsResource
const loading = listResource.loading
const statusLabel = { queued: '排队中', running: '生成中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const statusType = { queued: 'info', running: 'warning', succeeded: 'success', failed: 'danger', cancelled: 'info' }
const formatDate = value => formatBeijingDateTime(value)
const formatNumber = value => Number(value || 0).toLocaleString('zh-CN')
const formatCost = value => value == null ? '-' : formatMoney(Number(value) / 1_000_000, { precision: 4, currency: 'USD', currencyDisplay: 'narrowSymbol' })

// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节）
const columnDefs = [
  { key: 'task', label: '任务' },
  { key: 'product', label: '产品' },
  { key: 'invite', label: '邀请' },
  { key: 'status', label: '状态' },
  { key: 'tokens', label: 'Token' },
  { key: 'cost', label: '预估成本' },
  { key: 'created-at', label: '创建时间' },
  { key: 'error', label: '异常' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('customer-image-usage', columnDefs)

function load(page = generationPage.value) { return listResource.handlePageChange(page) }
function changeSize(size) { return listResource.handleSizeChange(size) }

onMounted(load)
</script>

<style scoped>
.usage-list { min-width: 0; }
.list-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 64px; }
.list-toolbar div { display: grid; gap: 3px; }
.list-toolbar span, small { color: var(--el-text-color-secondary); font-size: 13px; }
</style>
