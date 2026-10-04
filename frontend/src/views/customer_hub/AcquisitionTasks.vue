<template>
  <div class="workflow customer-hub">
    <el-alert v-if="profileLoadError" type="error" title="获客模型加载失败，未打开编辑器，避免覆盖现有配置。" :closable="false" show-icon><template #default><el-button link type="primary" @click="openProfile">重试</el-button></template></el-alert>
    <el-alert v-else-if="workflowError" type="error" title="操作失败，请检查字段或权限后重试。" :closable="false" show-icon />
    <!-- 主操作经共享面板 actions 插槽注入（Action Bar Spec）：页头只留标题与描述 -->
    <CustomerHubWorkspace :key="refreshKey" kind="acquisition" @view-results="openResults">
      <template #actions>
        <GlassButton v-permission="'sales_automation:admin'" variant="secondary" left-icon="Setting" :loading="profileLoading" @click="openProfile">配置获客模型</GlassButton>
        <GlassButton v-any-permission="['sales_automation:write','sales_automation:admin']" variant="primary" left-icon="Plus" @click="openJobDialog">创建获客任务</GlassButton>
      </template>
    </CustomerHubWorkspace>
    <el-dialog class="customer-hub-dialog" v-model="jobDialog" title="创建获客任务" width="640px"><el-form label-position="top"><el-form-item label="任务名称"><el-input v-model="job.name" /></el-form-item><el-form-item label="自动获客数量（每次 1–20）"><el-input-number v-model="job.target_count" :min="1" :max="20" /></el-form-item><el-form-item label="国家（逗号分隔）"><el-input v-model="job.countries" /></el-form-item></el-form><template #footer><GlassButton variant="ghost" @click="jobDialog = false">取消</GlassButton><GlassButton variant="primary" :loading="workflowLoading" @click="submitJob">创建</GlassButton></template></el-dialog>
    <el-dialog class="customer-hub-dialog" v-model="profileDialog" title="配置获客模型" width="760px"><el-form label-position="top" class="profile-form"><el-form-item label="公司名称"><el-input v-model="form.company_name" /></el-form-item><el-form-item label="公司网站"><el-input v-model="form.company_website" /></el-form-item><ListField v-model="form.products" label="产品" /><ListField v-model="form.competitive_advantages" label="竞争优势" /><ListField v-model="form.target_countries" label="目标国家" /><ListField v-model="form.target_industries" label="目标行业" /><ListField v-model="form.target_roles" label="目标角色" /><ListField v-model="form.exclusions" label="排除条件" /><el-form-item label="默认触达语言"><el-input v-model="form.default_outreach_language" /></el-form-item><el-form-item label="策略版本"><el-input v-model="form.policy_version" /></el-form-item><el-form-item label="策略 JSON" class="span-two"><el-input v-model="form.policyText" type="textarea" :rows="6" /></el-form-item></el-form><template #footer><GlassButton variant="ghost" @click="profileDialog = false">取消</GlassButton><GlassButton v-permission="'sales_automation:admin'" variant="primary" :loading="workflowLoading" @click="submitProfile">保存</GlassButton></template></el-dialog>
    <el-dialog class="customer-hub-dialog" v-model="resultsDialog" :title="`任务结果 · ${resultsJob?.name || ''}`" width="760px">
<ListPageStatus v-if="resultsState.hasData.value" :error="resultsError" :loading="resultsLoading" :has-data="true" :data-page="resultsState.dataPage.value" @retry="loadResults" />
      <div ref="resultsPanelRef" class="table-card results-panel">
        <div class="action-bar">
          <TableTools v-model:visible-keys="resultsVisibleKeys" v-model:density="resultsDensity" :columns="resultsColumnDefs" :loading="resultsLoading" :fullscreen="resultsIsFullscreen" @refresh="loadResults" @fullscreen="toggleResultsFullscreen" />
        </div>
        <el-table v-loading="resultsLoading" :data="results" border class="list-table" :class="resultsDensityClass" :max-height="resultsIsFullscreen ? undefined : 520" @sort-change="resultsState.handleSortChange($event.order ? { sort_field: $event.prop, sort_order: $event.order === 'ascending' ? 'asc' : 'desc' } : {})" v-sticky-scrollbar>
<template #empty><ListPageStatus :error="resultsError" :loading="resultsLoading" @retry="loadResults"><el-empty description="该任务没有产出候选客户；若任务已完成仍为空，请检查执行端日志或调整后重新创建任务。" /></ListPageStatus></template>
          <el-table-column sortable="custom" prop="customer_id" v-if="resultsVisibleKeys.includes('customer')" label="客户" min-width="110"><template #default="{ row }">#{{ row.customer_id }}</template></el-table-column>
          <el-table-column sortable="custom" v-if="resultsVisibleKeys.includes('rank')" prop="best_rank" label="排名" min-width="80" />
          <el-table-column sortable="custom" prop="best_score" v-if="resultsVisibleKeys.includes('score')" label="匹配分" min-width="100"><template #default="{ row }">{{ row.best_score }}</template></el-table-column>
          <el-table-column sortable="custom" prop="result_status" v-if="resultsVisibleKeys.includes('status')" label="结果状态" min-width="120"><template #default="{ row }"><StatusBadge size="small">{{ searchResultStatusLabel(row.result_status) }}</StatusBadge></template></el-table-column>
          <el-table-column sortable="custom" prop="created_at" v-if="resultsVisibleKeys.includes('created')" label="入档时间" min-width="170"><template #default="{ row }">{{ formatResultDate(row.created_at) }}</template></el-table-column>
        </el-table>
        <el-pagination v-model:current-page="resultsPage" v-model:page-size="resultsPageSize" :page-sizes="[20, 50, 100]" :total="resultsTotal" layout="total, sizes, prev, pager, next" class="pager" @current-change="handlePageChange" @size-change="handleSizeChange" />
      </div>

    </el-dialog>
  </div>
</template>
<script setup>
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useListPage } from '@/composables/useListPage'
import { watchListResourceScope } from '@/composables/useListResourceScope'

import { computed, defineComponent, h, reactive, ref } from 'vue'
import { ElFormItem, ElInput } from 'element-plus'
import { msgError, msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { listSearchJobResults } from '@/api/customerHub'
import CustomerHubWorkspace from './CustomerHubWorkspace.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { useAcquisitionWorkflows } from './composables/useCustomerHub'
import { buildAcquisitionProfilePayload, buildSearchJobPayload, createSearchJobDraft, searchResultStatusLabel, shouldOpenProfileEditor } from './customerHubController'
const { workflowLoading, workflowError, loadProfile, saveProfile, createJob } = useAcquisitionWorkflows()
const refreshKey = ref(0), jobDialog = ref(false), profileDialog = ref(false), profileLoading = ref(false), profileLoadError = ref(false)
const job = reactive(createSearchJobDraft())
const form = reactive({ company_name: '', company_website: '', products: [], competitive_advantages: [], target_countries: [], target_industries: [], target_roles: [], exclusions: [], default_outreach_language: 'en', policy_version: '', policyText: '{}' })
const split = value => value.split(',').map(item => item.trim()).filter(Boolean)
async function openProfile() { profileLoading.value = true; profileLoadError.value = false; const result = await loadProfile(); profileLoading.value = false; if (!shouldOpenProfileEditor(result)) { profileLoadError.value = true; return } const p = result.data || {}; Object.assign(form, { company_name: p.company_name || '', company_website: p.company_website || '', products: p.products || [], competitive_advantages: p.advantages || [], target_countries: p.target_countries || [], target_industries: p.target_industries || [], target_roles: p.target_roles || [], exclusions: p.exclusions || [], default_outreach_language: p.default_language || 'en', policy_version: p.policy_version || '', policyText: JSON.stringify(p.policy_json || {}, null, 2) }); profileDialog.value = true }
function openJobDialog() { Object.assign(job, createSearchJobDraft()); jobDialog.value = true }
async function submitJob() { if (await createJob(buildSearchJobPayload(job))) { jobDialog.value = false; Object.assign(job, createSearchJobDraft()); refreshKey.value++; msgSuccess('创建获客任务') } }
async function submitProfile() { let policy_json; try { policy_json = JSON.parse(form.policyText) } catch { msgError('策略 JSON 格式错误'); return } if (await saveProfile(buildAcquisitionProfilePayload({ ...form, policy_json }))) { profileDialog.value = false; msgSuccess('保存获客模型') } }
const resultsDialog = ref(false), resultsJob = ref(null)
const resultsState = useListPage(async ({ jobId, ...params }, { signal }) => (await listSearchJobResults(jobId, params, { signal, suppressToast: true })).data,
  { searchForm: { jobId: null }, immediate: false })
watchListResourceScope(resultsState, ['jobId'])
const { list: results, loading: resultsLoading, errorMessage: resultsError, total: resultsTotal, page: resultsPage, pageSize: resultsPageSize, handlePageChange, handleSizeChange, fetchList: loadResults } = resultsState
const resultsColumnDefs = [
  { key: 'customer', label: '客户' }, { key: 'rank', label: '排名' },
  { key: 'score', label: '匹配分' }, { key: 'status', label: '结果状态' },
  { key: 'created', label: '入档时间' },
]
const {
  density: resultsDensity, densityClass: resultsDensityClass,
  visibleKeys: resultsVisibleKeys, panelRef: resultsPanelRef,
  isFullscreen: resultsIsFullscreen, toggleFullscreen: toggleResultsFullscreen,
} = useTableView('acquisition-results', resultsColumnDefs)
const formatResultDate = value => value ? formatBeijingDateTime(value) : '—'
function openResults(row) {
  resultsJob.value = row
  resultsDialog.value = true
  resultsState.searchForm.jobId = row.job_id
  return resultsState.handleSearch()
}

</script>
<style scoped>
.workflow { display: grid; gap: 12px; }.actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }.profile-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }.span-two { grid-column: 1 / -1; }@media (max-width: 768px) { .profile-form { grid-template-columns: 1fr; }.span-two { grid-column: auto; } }
.results-panel:fullscreen { overflow: auto; }
</style>
