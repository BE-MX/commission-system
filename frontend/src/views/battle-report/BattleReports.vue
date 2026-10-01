<template>
  <div class="battle-page">
    <header class="battle-header"><div><h2>{{ report?.name || '临时战报' }}</h2><p>目标有方向，业绩有依据，复盘到每一笔订单。</p></div><div class="battle-actions"><GlassButton left-icon="Refresh" :loading="loading" @click="refresh">刷新</GlassButton><GlassButton v-permission="'battle_report:admin'" variant="primary" left-icon="Plus" @click="openSettings(false)">新建战报</GlassButton></div></header>
    <div class="battle-actions battle-picker"><el-select v-model="selectedId" placeholder="选择战报" aria-label="选择战报" @change="changeReport"><el-option v-for="item in reports" :key="item.id" :label="`${item.name} · ${stageLabels[item.stage]}`" :value="item.id" /></el-select><el-checkbox v-model="archived" @change="loadReports()">查看归档</el-checkbox><el-select v-if="report" v-model="team" clearable placeholder="全部可查看业务组" aria-label="业务组筛选" @change="changeTeam"><el-option v-for="item in teams" :key="item" :label="item" :value="item" /></el-select></div>
    <ListPageStatus v-if="selectorResource.error.value || selectorResource.loading.value" :paged="false" :error="selectorResource.errorMessage.value" :loading="selectorResource.loading.value" :has-data="selectorResource.hasData.value" @retry="loadReports()" />
    <ListPageStatus v-if="selectedId" :paged="false" :error="detailResource.errorMessage.value" :loading="detailResource.loading.value" :has-data="detailResource.hasData.value" @retry="loadReport"><el-empty v-if="!report" description="暂无战报详情" :image-size="96" /></ListPageStatus>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="report" class="battle-meta"><StatusBadge size="small" effect="plain">{{ stageLabels[report.stage] }}</StatusBadge><span>{{ report.start_date }} — {{ report.end_date }} · USD</span><span>核算日期 · 订单 GMV · 活动小组</span></div>
    <div v-if="report" class="battle-actions battle-manage">
      <GlassButton v-permission="'battle_report:admin'" :disabled="report.status === 'archived' || busy" left-icon="Setting" @click="openSettings(true)">战报设置</GlassButton>
      <GlassButton v-if="report.status === 'draft'" v-permission="'battle_report:admin'" variant="primary" :loading="busy" @click="transition('publish')">发布战报</GlassButton>
      <GlassButton v-if="report.status === 'published'" v-permission="'battle_report:admin'" :loading="busy" @click="transition('archive')">归档战报</GlassButton>
      <GlassButton v-if="report.status === 'archived'" v-permission="'battle_report:admin'" :loading="busy" @click="transition('restore')">恢复战报</GlassButton>
      <GlassButton v-permission="'battle_report:admin'" left-icon="Clock" @click="openAudits">修改记录</GlassButton>
      <GlassButton v-permission="'battle_report:admin'" left-icon="Picture" @click="postersVisible = true">战报海报</GlassButton>
    </div>
    <el-alert v-if="report?.status === 'draft'" type="info" :closable="false" title="当前为草稿，仅管理员可查看。核对名单和日期后发布，参与人即可填报目标。" />
    <div v-loading="loading" class="battle-content">
      <el-tabs v-if="report" v-model="tab">
        <el-tab-pane label="战报总览" name="overview"><ListPageStatus :paged="false" :error="overviewResource.errorMessage.value" :loading="overviewResource.loading.value" :has-data="overviewResource.hasData.value" @retry="loadOverview"><el-empty v-if="!overview" description="暂无战报汇总" :image-size="96" /></ListPageStatus><ReportOverview v-if="overview" :data="overview" @team="chooseTeam" @review="review" /></el-tab-pane>
        <el-tab-pane label="每日复盘" name="daily"><ReportDaily v-if="tab === 'daily'" :key="`${report.id}:${team}:${refreshKey}`" :report="report" :team="team" :selection="selection" /></el-tab-pane>
        <el-tab-pane label="目标填报" name="targets"><ReportTargets v-if="tab === 'targets'" :report="report" :team="team" @saved="refresh" /></el-tab-pane>
      </el-tabs>
      <el-empty v-else-if="!loading && !selectorResource.error.value && !detailResource.error.value" :description="error ? '暂时无法读取战报，请重试' : '暂无可查看的战报，管理员可新建战报并邀请业务员参与'" />
    </div>
    <footer v-if="overview" class="battle-footer"><span>计算时间：{{ formatBeijingDateTime(overview.calculated_at) }}（北京时间）</span><span>源同步时间未知 · 以当前业务镜像数据为准</span></footer>
    <ReportSettings v-model="settingsVisible" :report="editingReport" @saved="settingsSaved" />
    <ReportPosters v-if="postersVisible && report" v-model="postersVisible" :report="report" @saved="refresh" />
    <DetailDrawer v-model="auditsVisible" title="战报修改记录" :loading="auditsLoading"><ListPageStatus :error="auditError" :loading="auditsLoading" :has-data="auditState.hasData.value" :data-page="auditState.dataPage.value" @retry="loadAudits" /><el-empty v-if="auditState.isEmpty.value" description="暂无修改记录" /><article v-for="item in audits" :key="item.id" class="battle-audit"><h4>{{ auditLabels[item.action] || item.action }} · {{ formatBeijingDateTime(item.created_at) }}</h4><p>操作人 ID：{{ item.actor_id }} · {{ item.reason || '常规操作' }}</p><details><summary>查看修改前后内容</summary><p>修改前</p><pre>{{ JSON.stringify(item.before, null, 2) }}</pre><p>修改后</p><pre>{{ JSON.stringify(item.after, null, 2) }}</pre></details></article><el-pagination class="pager" :page-sizes="[20, 50, 100]" v-model:current-page="auditPage" v-model:page-size="auditPageSize" :total="auditTotal" layout="total, sizes, prev, pager, next" @current-change="changeAuditPage" @size-change="changeAuditSize" /></DetailDrawer>
  </div>
</template>
<script setup>
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useListPage } from '@/composables/useListPage'
import { watchListResourceScope } from '@/composables/useListResourceScope'

import { computed, onMounted, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { battleReportApi } from '@/api/battleReport'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import ReportOverview from './components/ReportOverview.vue'
import ReportDaily from './components/ReportDaily.vue'
import ReportTargets from './components/ReportTargets.vue'
import ReportSettings from './components/ReportSettings.vue'
import ReportPosters from './components/ReportPosters.vue'
import { errorText, stageLabels } from './helpers'

const selectorResource = useAsyncResource(async (params, { signal }) => (await battleReportApi.list(params, { signal, suppressToast: true })).items || [], { initialData: [] })
const detailResource = useAsyncResource(async (id, { signal }) => battleReportApi.get(id, { signal, suppressToast: true }))
const overviewResource = useAsyncResource(async ({ id, team }, { signal }) => battleReportApi.overview(id, { team: team || undefined }, { signal, suppressToast: true }))
const reports = selectorResource.data, report = detailResource.data, overview = overviewResource.data
const selectedId = ref(null), archived = ref(false)
const loading = computed(() => selectorResource.loading.value || detailResource.loading.value || overviewResource.loading.value)
const postersVisible = ref(false)
const team = ref(''), tab = ref('overview'), selection = ref({}), busy = ref(false), error = ref(''), refreshKey = ref(0)
const settingsVisible = ref(false), editingReport = ref(null), auditsVisible = ref(false)
const auditState = useListPage(async ({ reportId, ...params }, { signal }) => reportId ? await battleReportApi.audits(reportId, params, { signal, suppressToast: true }) : { items: [], total: 0 },
  { searchForm: { reportId: null }, immediate: false })
watchListResourceScope(auditState, ['reportId'])
const { list: audits, loading: auditsLoading, errorMessage: auditError, page: auditPage, pageSize: auditPageSize, total: auditTotal, fetchList: loadAudits, handlePageChange: changeAuditPage, handleSizeChange: changeAuditSize } = auditState
const auditLabels = { create: '创建战报', configure: '更正设置', targets: '修改目标', publish: '发布', archive: '归档', restore: '恢复', poster_config: '海报与群推送设置' }
const teams = computed(() => [...new Set(report.value?.members.map(m => m.team) || [])])
let listScope = null, scopeVersion = 0
async function loadReports(preferred = selectedId.value) {
  if (listScope !== archived.value) {
    listScope = archived.value; selectorResource.clear(); detailResource.clear(); overviewResource.clear()
    scopeVersion++; selectedId.value = null; team.value = ''; selection.value = {}; error.value = ''
  }
  const scope = scopeVersion
  const ok = await selectorResource.load({ archived: archived.value })
  if (!ok) return false
  if (scope !== scopeVersion) return true
  const nextId = reports.value.some(item => item.id === preferred) ? preferred : reports.value[0]?.id || null
  if (nextId !== selectedId.value) {
    selectedId.value = nextId; return changeReport()
  }
  return loadReport()
}
function loadOverview() {
  if (!selectedId.value) return Promise.resolve(false)
  return overviewResource.load({ id: selectedId.value, team: team.value })
}
function loadReport() {
  if (!selectedId.value) return Promise.resolve(false)
  return Promise.all([detailResource.load(selectedId.value), loadOverview()])
}
function changeReport() {
  scopeVersion++; detailResource.clear(); overviewResource.clear(); team.value = ''; selection.value = {}; error.value = ''
  return loadReport()
}
function changeTeam() { overviewResource.clear(); selection.value = {}; return loadOverview() }
function chooseTeam(value) { team.value = value; changeTeam() }
function review(value) { selection.value = value; tab.value = 'daily' }
function refresh() { refreshKey.value++; return selectorResource.error.value || !selectedId.value ? loadReports() : loadReport() }
function openSettings(edit) { editingReport.value = edit ? report.value : null; settingsVisible.value = true }
async function settingsSaved(id) { archived.value = false; refreshKey.value++; await loadReports(id) }
async function transition(action) {
  if (busy.value || !report.value || detailResource.error.value || loading.value) return
  const id = report.value.id, version = report.value.version, scope = scopeVersion
  busy.value = true
  try {
    await battleReportApi.state(id, { action, version }); msgSuccess(auditLabels[action])
    if (scope === scopeVersion) { archived.value = action === 'archive'; await loadReports(id) }
  } catch (e) { if (scope === scopeVersion) error.value = errorText(e) }
  finally { busy.value = false }
}
function openAudits() { auditsVisible.value = true }
watch(() => [auditsVisible.value, report.value?.id], ([open, id]) => {
  auditState.searchForm.reportId = open ? id ?? null : null
  auditState.handleSearch()
}, { flush: 'sync' })

onMounted(() => loadReports())

</script>
<style src="./battle-report.css"></style>
