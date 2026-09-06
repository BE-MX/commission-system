<template>
  <section class="workbench" aria-label="客户待办">
    <div v-if="!customerId" class="summary-grid">
      <button v-for="card in cards" :key="card.value" type="button" class="summary-card" :class="{ selected: searchForm.view === card.value }" :aria-pressed="searchForm.view === card.value" @click="selectView(card.value)">
        <span>{{ card.label }}</span><strong>{{ loading || !summary ? '—' : summary[card.value] }}</strong>
      </button>
    </div>
    <p v-if="!customerId" class="hint">按行动计数，同一客户可有多个待办，卡片可能重叠。待首触以方舟已归档的对外沟通记录为准。所有时间均为北京时间。</p>
    <div class="toolbar">
      <el-input v-if="!customerId" v-model="searchForm.keyword" clearable aria-label="搜索待办客户" placeholder="搜索客户名称或编号" @keyup.enter="handleSearch" @clear="handleSearch" />
      <el-select v-model="searchForm.scope" aria-label="待办归属范围" @change="handleSearch"><el-option label="我的待办" value="mine" /><el-option label="可见协作待办" value="visible" /></el-select>
      <el-select v-model="searchForm.view" aria-label="待办时间筛选" @change="handleSearch"><el-option v-for="item in views" :key="item.value" :label="item.label" :value="item.value" /></el-select>
      <GlassButton variant="secondary" left-icon="Refresh" :loading="loading" @click="fetchList">刷新</GlassButton>
    </div>
    <el-alert v-if="error" type="error" title="待办加载失败，请检查权限或网络后刷新。" :closable="false" show-icon />
    <div v-else v-loading="loading" class="action-list" :aria-busy="loading">
      <article v-for="row in list" :key="row.action_id" class="action-row">
        <div class="row-main">
          <button v-if="!customerId" v-permission="'customer:read'" class="customer-link" type="button" @click="$emit('open-customer', row.customer_id)">{{ row.customer_name }}</button>
          <span v-if="!customerId && !canOpenCustomer" class="customer-name">{{ row.customer_name }}</span>
          <h3>{{ row.next_action || actionLabels[row.action_type] || row.action_type }}</h3>
          <p>{{ row.reason || '按当前客户状态安排跟进' }}</p>
          <p v-if="row.opportunity_title" class="hint">关联机会：{{ row.opportunity_title }}</p>
          <div class="meta"><span>{{ row.owner_name }}</span><span>{{ channelLabels[row.channel] || '渠道待定' }}</span><span>{{ statusLabel(row.effective_status) }}</span><span>{{ priorityLabels[row.priority] || row.priority }}</span></div>
        </div>
        <div class="row-action"><span>{{ row.effective_due_at ? formatBeijingDateTime(row.effective_due_at, { seconds: false }) : '待安排时间' }}</span><GlassButton v-any-permission="['customer_radar:write','customer:admin']" variant="primary" :disabled="!row.can_operate" @click="editor.open(row)">{{ row.effective_status === 'pending' ? '处理待办' : '评价建议' }}</GlassButton></div>
      </article>
      <el-empty v-if="!loading && !list.length" description="当前筛选下没有待办，可切换范围或时间查看" :image-size="72" />
    </div>
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    <ActionEditor ref="editor" @saved="saved" />
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { listWorkbench } from '@/api/customerHub'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useOperationsList } from './composables/useOperationsList'
import { actionLabels, channelLabels, statusLabel } from './operationsPresentation'
import ActionEditor from './ActionEditor.vue'
const props = defineProps({ customerId: { type: Number, default: null } })
const emit = defineEmits(['open-customer', 'saved'])
const editor = ref(null)
const auth = useAuthStore()
const canOpenCustomer = computed(() => auth.hasPermission('customer:read'))
const cards = [{ value: 'first_contact', label: '待首触' }, { value: 'today', label: '今日到期' }, { value: 'overdue', label: '逾期' }, { value: 'high_priority', label: '高优先级待跟进' }, { value: 'completed', label: '今日完成' }]
const views = [{ value: 'focus', label: '现在要处理' }, ...cards, { value: 'unscheduled', label: '待安排时间' }, { value: 'upcoming', label: '后续跟进' }, { value: 'snoozed', label: '延后未到期' }, { value: 'all', label: '全部行动' }]
const priorityLabels = { urgent: '紧急', high: '高优先级', normal: '普通', low: '低优先级' }
const { loading, list, total, page, pageSize, searchForm, error, summary, fetchList, handleSearch, handlePageChange, handleSizeChange } = useOperationsList(
  params => listWorkbench({ ...params, ...(props.customerId ? { customer_id: props.customerId } : {}) }),
  { searchForm: { keyword: '', scope: props.customerId ? 'visible' : 'mine', view: 'focus' } },
)
watch(() => props.customerId, handleSearch)
function selectView(view) { searchForm.view = view; handleSearch() }
async function saved() { await fetchList(); emit('saved') }
defineExpose({ refresh: fetchList })
</script>
<style scoped>
.workbench { display: grid; gap: 14px; }.summary-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }.summary-card { font: inherit; min-width: 0; display: grid; gap: 12px; text-align: left; padding: 18px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); color: var(--text-secondary); cursor: pointer; }.summary-card strong { font-family: var(--font-display); font-variant-numeric: tabular-nums; color: var(--text-primary); font-size: 28px; }.summary-card.selected { border-color: var(--color-primary); background: var(--toolbar-bg); }.summary-card:focus-visible, .customer-link:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }.hint { margin: 0; font-size: 12px; line-height: 1.6; color: var(--text-muted); }.toolbar { display: flex; gap: 10px; flex-wrap: wrap; }.toolbar :deep(.el-input) { flex: 1; min-width: 180px; }.toolbar :deep(.el-select) { width: 180px; }.action-list { min-height: 120px; border: 1px solid var(--border-color); border-radius: var(--card-radius); overflow: hidden; background: var(--card-bg); }.action-row { display: flex; gap: 20px; justify-content: space-between; padding: 18px; border-bottom: 1px solid var(--border-color); }.action-row:last-child { border-bottom: 0; }.row-main { min-width: 0; }.customer-link { overflow-wrap: anywhere; text-align: left; border: 0; background: transparent; padding: 0; color: var(--color-primary); font: inherit; cursor: pointer; }.action-row h3 { margin: 8px 0; font-size: 15px; line-height: 1.5; overflow-wrap: anywhere; }.action-row p { margin: 6px 0; color: var(--text-secondary); line-height: 1.6; }.meta { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--text-muted); }.row-action { display: grid; align-content: center; justify-items: end; gap: 12px; flex-shrink: 0; font-size: 12px; color: var(--text-secondary); }.el-pagination { overflow-x: auto; }
@media(max-width: 768px) { .summary-grid { grid-template-columns: repeat(2, 1fr); }.summary-card { padding: 12px; }.summary-card:last-child { grid-column: 1 / -1; }.action-row { flex-direction: column; gap: 12px; }.row-action { display: flex; justify-content: space-between; align-items: center; }.toolbar :deep(.el-select) { flex: 1; min-width: 140px; } }
</style>
