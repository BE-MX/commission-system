<template>
  <div>
    <div class="page-header"><h2>双路线核对</h2></div>
    <ListPageStatus :error="status.errorMessage.value" :loading="status.loading.value" :has-data="status.hasData.value" :paged="false" @retry="status.load()" />
    <ResponsiveDescriptions v-if="status.data.value" :column="3" border>
      <el-descriptions-item label="覆盖状态">{{ shadowLabel(status.data.value.coverage) }}</el-descriptions-item>
      <el-descriptions-item label="待导出凭证">{{ status.data.value.pending_outbox }}</el-descriptions-item>
      <el-descriptions-item label="未知结果观察">{{ status.data.value.unknown_observations }}</el-descriptions-item>
    </ResponsiveDescriptions>
    <div class="table-card">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset"><el-input v-model="searchForm.dataset_id" class="filter-w-md" clearable placeholder="数据集 ID" aria-label="数据集 ID" /><el-input v-model="searchForm.invoice_id" class="filter-w-sm" clearable placeholder="订单 ID" aria-label="订单 ID" /></FilterBar>
      <div class="action-bar"><GlassButton v-permission="'commerce_shadow:write'" left-icon="Plus" :disabled="status.data.value?.enabled !== true" @click="openRun">排队核对</GlassButton><GlassButton left-icon="Refresh" :loading="loading" @click="refresh">刷新</GlassButton></div>
      <p class="transport-help">任务排队后，由管理员导出输入，在隔离环境运行，再导入结果回执。未完成执行时保持待处理。</p>
      <el-alert v-if="transportError" :title="transportError" type="error" :closable="false" />
      <input ref="receiptFile" type="file" accept="application/json,.json" hidden aria-label="导入隔离核对回执" @change="importReceiptFile" />
      <el-tabs v-model="tab" @tab-change="changeTab"><el-tab-pane label="核对任务" name="runs" /><el-tab-pane label="差异复核" name="differences" /></el-tabs>
      <ListPageStatus :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table :data="list" v-loading="loading" border class="list-table" v-sticky-scrollbar>
        <el-table-column prop="id" label="编号" min-width="90" />
        <el-table-column v-if="tab === 'runs'" prop="dataset_id" label="数据集" min-width="150" />
        <el-table-column v-if="tab === 'runs'" label="核对状态" min-width="130"><template #default="{ row }"><StatusBadge :type="row.status === 'consistent' ? 'success' : 'warning'">{{ shadowLabel(row.status) }}</StatusBadge></template></el-table-column>
        <el-table-column v-if="tab === 'runs'" label="覆盖与水位" min-width="260"><template #default="{ row }">{{ shadowLabel(row.coverage?.state) }}<small class="watermark">观察 {{ row.coverage?.observed_through ?? '—' }} / 导出 {{ row.coverage?.exported_through ?? '—' }} / 应用 {{ row.coverage?.applied_through ?? '—' }}</small></template></el-table-column>
        <el-table-column v-if="tab === 'differences'" label="源对象" min-width="140"><template #default="{ row }">{{ row.invoice_id ? `订单 ${row.invoice_id}` : row.payment_id ? `付款 ${row.payment_id}` : row.local_customer_id ? `客户 ${row.local_customer_id}` : '待核验' }}</template></el-table-column>
        <el-table-column v-if="tab === 'differences'" prop="observation_id" label="源观察" min-width="110" />
        <el-table-column v-if="tab === 'differences'" prop="field" label="差异字段" min-width="140" />
        <el-table-column v-if="tab === 'differences'" label="正式预期 / 独立实际" min-width="250"><template #default="{ row }"><pre>{{ display(row.expected) }}</pre><pre>{{ display(row.actual) }}</pre></template></el-table-column>
        <el-table-column v-if="tab === 'differences'" label="复核状态" min-width="100"><template #default="{ row }">{{ reviewLabels[row.classification] || row.classification }}</template></el-table-column>
        <el-table-column label="操作" min-width="270" class-name="table-action-column"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="showDetail(row)">证据详情</GlassButton><template v-if="tab === 'runs'"><GlassButton v-permission="'commerce_shadow:admin'" variant="link" left-icon="Download" :disabled="transportBusy" @click="exportInput(row)">导出输入</GlassButton><GlassButton v-permission="'commerce_shadow:admin'" variant="link" left-icon="Upload" :disabled="transportBusy" @click="chooseReceipt(row)">导入回执</GlassButton></template><GlassButton v-if="tab === 'differences'" v-permission="'commerce_shadow:admin'" variant="link" left-icon="Edit" @click="openReview(row)">复核</GlassButton></template></el-table-column>
        <template #empty><el-empty v-if="!errorMessage" description="暂无核对记录" /></template>
      </el-table>
      <el-pagination class="pager" :current-page="page" :page-size="pageSize" :total="total" layout="total, sizes, prev, pager, next" :page-sizes="[20, 50, 100]" @size-change="handleSizeChange" @current-change="handlePageChange" />
    </div>
    <DetailDrawer v-model="detailOpen" title="核对证据" width="760px" :loading="detail.loading.value">
      <ListPageStatus :error="detail.errorMessage.value" :loading="detail.loading.value" :has-data="detail.hasData.value" :paged="false" @retry="detail.load()" />
      <template v-if="selected"><ResponsiveDescriptions :column="2" border><el-descriptions-item label="数据用途">独立对比 · 不计正式账</el-descriptions-item><el-descriptions-item label="源观察">{{ selected.observation_id ?? selected.through_observation_id }}</el-descriptions-item><el-descriptions-item label="源订单">{{ selected.invoice_id ?? (selected.invoice_ids?.join(', ') || '—') }}</el-descriptions-item><el-descriptions-item label="付款 / 本地客户">{{ selected.payment_id ?? selected.payment_ids?.join(', ') ?? '—' }} / {{ selected.local_customer_id ?? selected.local_customer_ids?.join(', ') ?? '—' }}</el-descriptions-item><el-descriptions-item label="数据集">{{ selected.dataset_id ?? '见所属核对任务' }}</el-descriptions-item></ResponsiveDescriptions><h3>覆盖与依赖</h3><pre>{{ display(selected.coverage || {}) }}</pre><h3>正式预期</h3><pre>{{ display(selected.expected || {}) }}</pre><h3>独立计算结果</h3><pre>{{ display(selected.actual || detail.data.value?.results || {}) }}</pre></template>
    </DetailDrawer>
    <el-dialog v-model="runOpen" title="排队独立核对" width="480px" :show-close="!runCommand.pending.value" :close-on-click-modal="!runCommand.pending.value">
      <el-form label-position="top" :disabled="runCommand.pending.value"><el-form-item label="数据集 ID"><el-input v-model="runForm.dataset_id" /></el-form-item><el-form-item label="订单 ID（逗号分隔，可留空）"><el-input v-model="runForm.invoice_ids" /></el-form-item><el-form-item label="付款 ID（纯预收可填写）"><el-input v-model="runForm.payment_ids" /></el-form-item><el-form-item label="本地客户 ID（纯预收可填写）"><el-input v-model="runForm.local_customer_ids" /></el-form-item><el-form-item label="截至源观察 ID"><el-input v-model="runForm.through_observation_id" inputmode="numeric" /></el-form-item></el-form>
      <p>使用已核验的一致检查点与完整责任闭包；缺少依赖会保留为覆盖不足。</p>
      <el-alert v-if="runCommand.failure.value" :title="runCommand.failure.value" type="error" :closable="false" />
      <template #footer><GlassButton :disabled="runCommand.pending.value" @click="runOpen = false">返回</GlassButton><GlassButton v-permission="'commerce_shadow:write'" variant="primary" :loading="runCommand.pending.value" @click="submitRun">排队核对</GlassButton></template>
    </el-dialog>
    <el-dialog v-model="reviewOpen" title="差异复核" width="480px" :show-close="!reviewCommand.pending.value" :close-on-click-modal="!reviewCommand.pending.value">
      <el-form label-position="top" :disabled="reviewCommand.pending.value"><el-form-item label="分类"><el-select v-model="reviewForm.classification"><el-option value="explained" label="已解释" /><el-option value="fixed" label="已修复" /></el-select></el-form-item><el-form-item label="事实依据（至少5字）"><el-input v-model="reviewForm.evidence" type="textarea" maxlength="3000" /></el-form-item></el-form>
      <p>复核保留原差异与数值，不会改写正式账或把数值差异变成一致。</p>
      <el-alert v-if="reviewCommand.failure.value" :title="reviewCommand.failure.value" type="error" :closable="false" />
      <template #footer><GlassButton :disabled="reviewCommand.pending.value" @click="reviewOpen = false">返回</GlassButton><GlassButton v-permission="'commerce_shadow:admin'" variant="primary" :loading="reviewCommand.pending.value" @click="submitReview">保存复核</GlassButton></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, onActivated, onDeactivated, ref } from 'vue'
import { getShadowStatus, getShadowRuns, getShadowDifferences, getShadowRun, queueShadowRun, reviewShadowDifference, exportShadowInput, importShadowReceipts } from '@/api/commerceShadow'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { msgSuccess } from '@/utils/feedback'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { shadowLabel } from './routeState'
import { shadowReplayPayload } from './shadowRequest'
import { downloadBlob } from '@/utils/download'
const tab = ref('runs'), appliedTab = ref('runs')
const status = useAsyncResource(async (_, { signal }) => (await getShadowStatus({ signal, suppressToast: true })).data)
const state = useListPage(async (params, { signal }) => {
  const query = { ...params, invoice_id: String(params.invoice_id || '').trim() || undefined }
  return (await (appliedTab.value === 'runs' ? getShadowRuns : getShadowDifferences)(query, { signal, suppressToast: true })).data
}, { searchForm: { dataset_id: '', invoice_id: '' } })
const { list, loading, errorMessage, hasData, hasPendingSearch, dataPage, page, pageSize, total, searchForm, handleSearch, handleReset, handlePageChange, handleSizeChange, fetchList } = state
function changeTab() { appliedTab.value = tab.value; state.list.value = []; state.total.value = 0; handleSearch() }
function refresh() { status.load(); fetchList() }
const receiptFile = ref(null), transportBusy = ref(false), transportError = ref('')
let importRunId = null, transportEpoch = 0, transportController = null
function chooseReceipt(row) { if (!transportBusy.value) { importRunId = row.id; receiptFile.value.value = ''; receiptFile.value.click() } }
async function transfer(operation) {
  if (transportBusy.value) return
  const epoch = ++transportEpoch
  transportController = new AbortController()
  transportBusy.value = true; transportError.value = ''
  try { await operation(transportController.signal, () => epoch === transportEpoch) }
  catch (error) { if (epoch === transportEpoch) transportError.value = typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error.message || '核对文件处理失败，请重新读取原任务' }
  finally { if (epoch === transportEpoch) transportBusy.value = false }
}
async function exportInput(row) {
  const id = row.id
  await transfer(async (signal, current) => {
    const result = await exportShadowInput(id, { signal, suppressToast: true })
    if (current()) downloadBlob({ data: new Blob([JSON.stringify(result.data, null, 2)], { type: 'application/json' }) }, `comparison-${id}-input.json`)
  })
}
async function importReceiptFile(event) {
  const file = event.target.files?.[0], id = importRunId
  event.target.value = ''; importRunId = null
  if (!file || !id) return
  await transfer(async (signal, current) => {
    if (file.size > 10 * 1024 * 1024) throw new Error('核对回执不能超过10MB')
    let body
    try { body = JSON.parse(await file.text()) }
    catch { throw new Error('无法读取JSON回执，请选择隔离执行生成的结果文件') }
    if (!current()) return
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('回执须为隔离执行生成的JSON对象')
    if (body.run_id !== id) throw new Error('回执不属于当前核对任务')
    await importShadowReceipts(id, body, { signal, suppressToast: true })
    if (current()) { msgSuccess('导入核对回执'); refresh() }
  })
}
const reviewLabels = { open: '待复核', explained: '已解释', fixed: '已修复' }, display = value => JSON.stringify(value, null, 2)
const detail = useAsyncResource(async (id, { signal }) => (await getShadowRun(id, { signal, suppressToast: true })).data)
const detailOpen = ref(false), selectedDifference = ref(null)
const selected = computed(() => selectedDifference.value || detail.data.value)
function showDetail(row) { selectedDifference.value = tab.value === 'differences' ? row : null; detail.clear(); detailOpen.value = true; detail.load(row.run_id || row.id) }
const runOpen = ref(false), reviewOpen = ref(false), runCommand = useNativeCommand(), reviewCommand = useNativeCommand()
const runForm = ref({}), reviewForm = ref({}), reviewedId = ref(null)
function openRun() { runForm.value = { dataset_id: searchForm.dataset_id, invoice_ids: searchForm.invoice_id, payment_ids: '', local_customer_ids: '', through_observation_id: '' }; runCommand.reset(); runOpen.value = true }
function openReview(row) { reviewedId.value = row.id; reviewForm.value = { classification: 'explained', evidence: '' }; reviewCommand.reset(); reviewOpen.value = true }
async function submitRun() {
  const result = await runCommand.run({ payload: () => shadowReplayPayload(runForm.value), send: queueShadowRun })
  if (result.ok) { msgSuccess('核对任务已排队'); runOpen.value = false; refresh() }
}
async function submitReview() {
  const result = await reviewCommand.run({ payload: () => { if (reviewForm.value.evidence.trim().length < 5) throw new Error('请填写至少5字事实依据'); return { ...reviewForm.value, evidence: reviewForm.value.evidence.trim() } }, send: body => reviewShadowDifference(reviewedId.value, { classification: body.classification, evidence: body.evidence }) })
  if (result.ok) { msgSuccess('保存差异复核'); reviewOpen.value = false; state.refreshUpdate() }
}
onActivated(refresh)
onDeactivated(() => { detailOpen.value = false; runOpen.value = false; reviewOpen.value = false; state.cancel(); detail.clear(); status.clear(); transportEpoch++; transportController?.abort(); transportBusy.value = false; importRunId = null })
</script>
<style scoped>pre { white-space: pre-wrap; overflow-wrap: anywhere; margin: 5px 0; color: var(--text-secondary); font-size: 12px; } .watermark { display: block; color: var(--text-secondary); } p { color: var(--text-secondary); }</style>
