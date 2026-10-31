<template>
  <section ref="panelRef" class="table-card">
    <h3>已承接记录</h3>
    <FilterBar class="toolbar" :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset">
      <el-input v-model="searchForm.source" clearable class="filter-w-sm" placeholder="来源系统" />
      <el-input v-model="searchForm.tenant" clearable class="filter-w-md" placeholder="来源账号" />
      <el-select v-model="searchForm.role" clearable class="filter-w-sm" placeholder="全部责任性质"><el-option v-for="(label, key) in recordRoles" :key="key" :label="label" :value="key" /></el-select>
      <el-select v-model="searchForm.object_type" clearable class="filter-w-md" placeholder="全部对象类型"><el-option v-for="(label, key) in recordKinds" :key="key" :label="label" :value="key" /></el-select>
    </FilterBar>
    <div class="action-bar">
      <GlassButton v-permission="'commerce_migration:admin'" variant="primary" left-icon="Check" :loading="activation.pending.value" :disabled="!selected.length || loading || !!errorMessage || activation.uncertain.value" @click="openActivation">核对并放行所选责任</GlassButton>
      <span>已选 {{ selected.length }} 条待放行责任</span>
      <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columns" :fullscreen="isFullscreen" :loading="loading" @refresh="fetchList" @fullscreen="toggleFullscreen" />
    </div>
    <ListPageStatus :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
    <el-table ref="table" :data="list" v-loading="loading" row-key="id" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" @selection-change="selected = $event" v-sticky-scrollbar>
      <el-table-column type="selection" :selectable="selectable" min-width="52" />
      <el-table-column v-for="column in columns.filter(row => visibleKeys.includes(row.key))" :key="column.key" :prop="column.key" :label="column.label" :min-width="column.width || 140" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="column.key === 'object_type'">{{ recordKinds[row.object_type] || row.object_type }}</span>
          <StatusBadge v-else-if="column.key === 'role'" :type="row.role === 'opening' ? 'warning' : 'info'">{{ recordRoles[row.role] || row.role }}</StatusBadge>
          <StatusBadge v-else-if="column.key === 'current_state'" :type="row.current_state === 'opening' ? 'warning' : 'success'">{{ stateLabel(row) }}</StatusBadge>
          <span v-else-if="column.key === 'created_at'">{{ formatBeijingDateTime(row.created_at) }}</span>
          <span v-else>{{ row[column.key] ?? '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="140" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="showDetail(row)">核验依据</GlassButton></template></el-table-column>
      <template #empty><el-empty v-if="!errorMessage" description="尚无承接记录，可先选择已核验清单" :image-size="96" /></template>
    </el-table>
    <el-pagination class="pager" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    <DetailDrawer v-model="detailOpen" title="承接核验依据" width="760px">
      <ListPageStatus :error="detail.errorMessage.value" :loading="detail.loading.value" :has-data="detail.hasData.value" :paged="false" @retry="detail.load()" />
      <template v-if="detail.data.value">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="来源记录">{{ detail.data.value.record.id }} · {{ recordKinds[detail.data.value.record.object_type] || detail.data.value.record.object_type }}</el-descriptions-item>
          <el-descriptions-item label="原身份">{{ detail.data.value.record.source }} / {{ detail.data.value.record.tenant }} / {{ detail.data.value.record.external_id }}</el-descriptions-item>
          <el-descriptions-item label="批次">{{ detail.data.value.record.batch_key }}</el-descriptions-item>
          <el-descriptions-item label="切换业务日">{{ detail.data.value.batch.cutover_date }}</el-descriptions-item>
          <el-descriptions-item label="核验依据">{{ detail.data.value.batch.review_reference }}</el-descriptions-item>
          <el-descriptions-item label="源文件摘要">{{ detail.data.value.batch.evidence_sha256 }}</el-descriptions-item>
          <el-descriptions-item label="承接时间（北京时间）">{{ formatBeijingDateTime(detail.data.value.record.created_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="action-bar"><GlassButton left-icon="Download" :disabled="!!detail.error.value" @click="downloadEvidence">下载核验依据与结果</GlassButton></div>
        <el-collapse><el-collapse-item title="原始核验事实"><pre class="evidence-json">{{ JSON.stringify(detail.data.value.record.snapshot, null, 2) }}</pre></el-collapse-item></el-collapse>
      </template>
    </DetailDrawer>
    <el-dialog v-model="activationOpen" title="核对责任并放行" width="760px" :show-close="!activation.pending.value && !activation.uncertain.value" :close-on-click-modal="false" :close-on-press-escape="!activation.pending.value && !activation.uncertain.value">
      <p>核对所选完整订单与生产责任。放行将建立当前待供货预占，历史发货、验收和领料不重复过账。</p>
      <p v-if="activation.pending.value" role="status">正在核对或处理当前请求…</p>
      <el-alert v-if="activation.failure.value" :title="activation.failure.value" type="error" :closable="false" show-icon />
      <el-alert v-if="activation.uncertain.value" title="结果未确认，已保留原请求及全部版本。请重试当前放行请求核对结果。" type="warning" :closable="false" show-icon />
      <template v-if="activation.review.value">
        <p>切换业务日：{{ activation.review.value.command.business_date }}</p>
        <el-table :data="activation.review.value.descriptions" border class="list-table" v-sticky-scrollbar>
          <el-table-column prop="name" label="待放行单据" min-width="180" />
          <el-table-column label="类型" min-width="100"><template #default="{ row }">{{ row.kind === 'order' ? '完整订单' : '生产责任' }}</template></el-table-column>
          <el-table-column label="放行后状态" min-width="140"><template #default="{ row }">{{ orderStates[row.source_status]?.label || '本地生产' }}</template></el-table-column>
        </el-table>
        <el-alert v-if="activation.review.value.report.can_activate" title="所选期末责任核对通过，可放行继续办理" type="success" :closable="false" show-icon />
        <el-table v-else :data="activation.review.value.report.conflicts" border class="list-table" v-sticky-scrollbar><el-table-column prop="message" label="尚需完成的责任" min-width="280" /></el-table>
      </template>
      <el-alert v-if="activation.result.value" title="已放行。后续收款、生产验收和发货使用正常业务入口。" type="success" :closable="false" show-icon />
      <template #footer><div class="dialog-footer">
        <GlassButton :disabled="activation.pending.value || activation.uncertain.value" @click="activationOpen = false">返回</GlassButton>
        <GlassButton v-if="!activation.result.value" :disabled="activation.pending.value || activation.uncertain.value" @click="reviewSelected">重新核对</GlassButton>
        <GlassButton v-permission="'commerce_migration:admin'" variant="primary" :loading="activation.pending.value" :disabled="!activation.review.value?.report.can_activate || !!activation.result.value" @click="activate">{{ activation.uncertain.value ? '重试当前放行请求' : '放行所选责任' }}</GlassButton>
      </div></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { ref, watch } from 'vue'
import { getMigrationRecords, getMigrationRecord, prepareMigrationActivation, activateMigration } from '@/api/commerceMigration'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import { useAsyncResource } from '@/composables/useAsyncResource'
import TableTools from '@/components/TableTools.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { downloadBlob } from '@/utils/download'
import { orderStates } from '@/views/invoice/native/labels'
import { recordKinds, recordRoles } from './labels'
import { useMigrationActivation } from './useMigrationActivation'
const state = useListPage(async (params, { signal }) => {
  const query = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== ''))
  const { data } = await getMigrationRecords(query, { signal, suppressToast: true })
  if (!Array.isArray(data?.items) || typeof data.total !== 'number') throw new Error('承接记录返回不完整，请重试')
  return data
}, { searchForm: { source: '', tenant: '', role: '', object_type: '' } })
const { list, loading, errorMessage, hasData, dataPage, searchForm, hasPendingSearch, page, pageSize, total, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = state
const columns = [{ key: 'id', label: '来源记录', width: 110 }, { key: 'external_id', label: '原身份' },
  { key: 'object_type', label: '对象类型' }, { key: 'role', label: '责任性质', width: 110 }, { key: 'current_state', label: '当前状态' },
  { key: 'source', label: '来源系统', width: 110 }, { key: 'tenant', label: '来源账号' }, { key: 'batch_key', label: '承接批次' },
  { key: 'created_at', label: '承接时间（北京时间）', width: 190 }]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView('commerce-migration', columns)
const selected = ref([]), table = ref(), detailOpen = ref(false), activationOpen = ref(false)
const activation = useMigrationActivation({ prepare: prepareMigrationActivation, activate: activateMigration })
const detail = useAsyncResource(async (id, { signal }) => (await getMigrationRecord(id, { signal, suppressToast: true })).data)
const selectable = row => !loading.value && !errorMessage.value && !activation.pending.value && !activation.uncertain.value
  && row.role === 'opening' && ['order_binding', 'production_opening'].includes(row.object_type) && row.current_state === 'opening'
const stateLabel = row => row.current_state === 'local' ? '已放行' : orderStates[row.current_state]?.label || (row.role === 'archive' ? '已归档' : '已承接')
watch(list, () => { selected.value = []; table.value?.clearSelection() })
watch(detailOpen, open => { if (!open) detail.cancel() })
function showDetail(row) { detail.clear(); detailOpen.value = true; detail.load(row.id) }
async function openActivation() { if (!selected.value.length || activation.pending.value || activation.uncertain.value) return; activation.clear(); activationOpen.value = true; await reviewSelected() }
async function reviewSelected() { await activation.prepare(selected.value.map(row => row.id)) }
async function activate() { if (await activation.activate()) { msgSuccess('放行责任'); await fetchList() } }
function downloadEvidence() {
  downloadBlob({ data: new Blob([JSON.stringify(detail.data.value, null, 2)], { type: 'application/json' }) }, `migration-record-${detail.data.value.record.id}.json`)
}
defineExpose({ refresh: fetchList })
</script>
<style scoped>
.evidence-json { max-height: 520px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; color: var(--text-secondary); }
</style>
