<template>
  <section class="qualification-panel">
    <el-alert type="info" title="开发资格决定是否值得继续开发；研究质量审核只确认材料是否可用。审核通过不会改变客户归属。" :closable="false" />
    <div ref="panelRef" class="table-card">
      <FilterBar  class="toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value" @search="handleSearch" @reset="handleReset"><el-input v-model="searchForm.keyword" placeholder="搜索待审核客户" clearable class="filter-w-lg"   />
</FilterBar>
      <!-- 操作行：TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>
      <ListPageStatus v-if="listPageState.hasData.value" :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="fetchList" />
<el-table v-loading="loading" :data="list" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" row-key="research_task_id" @sort-change="listPageState.handleSortChange($event.order ? { sort_field: $event.prop, sort_order: $event.order === 'ascending' ? 'asc' : 'desc' } : {})" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('customer')" prop="customer_name" label="客户" min-width="180" show-overflow-tooltip />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('scope')" prop="scope_label" label="开发方向" min-width="160" show-overflow-tooltip />
        <el-table-column sortable="custom" prop="match_score" v-if="visibleKeys.includes('match-score')" label="目标匹配分" min-width="120"><template #default="{ row }">{{ row.match_score ?? '未评估' }}</template></el-table-column>
        <el-table-column sortable="custom" prop="updated_at" v-if="visibleKeys.includes('updated')" label="研究更新" min-width="170"><template #default="{ row }">{{ formatBeijingDateTime(row.updated_at, { seconds: false }) }}</template></el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="150" max-width="180" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="inspect(row)">{{ row.can_review ? '审阅并决定' : '查看受限原因' }}</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </div>
    <DetailDrawer class="customer-hub-drawer" v-model="visible" title="开发资格审核" width="760px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <div v-loading="context.loading" class="review-body">
        <el-alert v-if="context.error" type="error" title="审核依据加载失败，请重新加载后再决定。" :closable="false"><el-button link @click="reload">重新加载</el-button></el-alert>
        <template v-else-if="context.data">
          <h2>{{ context.data.customer_name }}</h2><p>开发方向：{{ context.data.scope_label || '当前可见范围' }} · 目标匹配分：{{ context.data.match_score ?? '未评估' }}</p>
          <p v-if="context.data.previous_reason">上次结论原因：{{ context.data.previous_reason }}</p>
          <ResearchSummary :detail="context.data" />
          <el-alert v-if="!context.data.can_review" type="warning" :title="context.data.blocked_reason" :closable="false" />
          <el-form label-position="top" v-else :disabled="saving" class="decision-form">
            <el-form-item label="开发决定"><el-radio-group v-model="form.decision"><el-radio-button value="approve">值得开发</el-radio-button><el-radio-button value="defer">暂缓开发</el-radio-button><el-radio-button value="supplement">补充证据</el-radio-button><el-radio-button value="reject">不适合</el-radio-button></el-radio-group></el-form-item>
            <el-form-item label="判断理由（必填）"><el-input v-model="form.reason" type="textarea" :rows="3" placeholder="结合需求适配、供应商现状或风险，说明判断依据" /></el-form-item>
            <el-form-item v-if="needsDate" label="重新评估时间（北京时间，必填）"><el-date-picker v-model="form.reviewAfter" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
            <p class="hint">来源、目标范围和证据快照由方舟自动记录。</p>
          </el-form>
          <el-alert v-if="saveError" type="error" title="提交失败，内容已保留。如研究或已有结论发生变化，请重新加载依据后再决定。" :closable="false"><el-button link :disabled="saving" @click="reload">重新加载依据</el-button></el-alert>
        </template>
      </div>
      <template #footer><GlassButton variant="ghost" :disabled="saving" @click="visible = false">关闭</GlassButton><GlassButton v-any-permission="['sales_automation:write','sales_automation:admin']" variant="primary" :loading="saving" :disabled="!canSubmit || saving" @click="save">提交决定</GlassButton></template>
    </DetailDrawer>
  </section>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { listQualificationQueue, getQualificationContext, submitQualificationDecision } from '@/api/customerHub'
import { formatBeijingDateTime, parseApiDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { createLatestResource } from './customerHubResources'
import { createSearchJobIdempotencyKey } from './customerHubController'
import { useOperationsList } from './composables/useOperationsList'
import ResearchSummary from './ResearchSummary.vue'
const visible = ref(false), saving = ref(false), saveError = ref(null), taskId = ref(null), requestKey = ref('')
const context = reactive(createLatestResource(getQualificationContext))
const form = reactive({ decision: 'approve', reason: '', reviewAfter: '' })
const listPageState = useOperationsList(listQualificationQueue, { searchForm: { keyword: '' } })
const { loading, list, total, page, pageSize, searchForm, error, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = listPageState
// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'customer', label: '客户' },
  { key: 'scope', label: '开发方向' },
  { key: 'match-score', label: '目标匹配分' },
  { key: 'updated', label: '研究更新' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('qualification-panel', columnDefs)
const hasActiveFilters = computed(() => Boolean(searchForm.keyword))
const needsDate = computed(() => ['defer', 'supplement'].includes(form.decision))
const canSubmit = computed(() => !context.loading && !context.error && context.data?.can_review && context.data?.research_task_id === taskId.value && form.reason.trim() && (!needsDate.value || (parseApiDateTime(form.reviewAfter)?.getTime() || 0) > Date.now()))
watch(form, () => { requestKey.value = createSearchJobIdempotencyKey() }, { flush: 'sync' })
async function reload() { if (saving.value) return; saveError.value = null; requestKey.value = createSearchJobIdempotencyKey(); await context.load(taskId.value) }
async function inspect(row) { if (saving.value) return; taskId.value = row.research_task_id; Object.assign(form, { decision: 'approve', reason: '', reviewAfter: '' }); visible.value = true; await reload() }
async function save() {
  if (!canSubmit.value || saving.value) return
  saving.value = true; saveError.value = null
  try {
    await submitQualificationDecision(taskId.value, { decision: form.decision, reason: form.reason.trim(), review_after: needsDate.value ? `${form.reviewAfter}+08:00` : null, context_hash: context.data.context_hash, expected_current_review_id: context.data.current_review_id, request_key: requestKey.value })
    visible.value = false; msgSuccess('开发资格决定已记录'); await listPageState.refreshUpdate()
  } catch (error) { saveError.value = error }
  finally { saving.value = false }
}
defineExpose({ refresh: listPageState.refreshUpdate })
</script>
<style scoped>.qualification-panel { display: grid; gap: 14px; }.review-body { min-height: 160px; }.review-body h2 { margin: 0; font-size: 17px; }.review-body p { color: var(--text-secondary); line-height: 1.6; }.decision-form { margin-top: 20px; }.decision-form :deep(.el-date-editor) { width: 100%; }.hint { color: var(--text-muted); font-size: 12px; }</style>
