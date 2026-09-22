<template>
  <div class="battle-page">
    <header class="battle-header"><div><h2>{{ report?.name || '临时战报' }}</h2><p>目标有方向，业绩有依据，复盘到每一笔订单。</p></div><div class="battle-actions"><GlassButton left-icon="Refresh" :loading="loading" @click="refresh">刷新</GlassButton><GlassButton v-permission="'battle_report:admin'" variant="primary" left-icon="Plus" @click="openSettings(false)">新建战报</GlassButton></div></header>
    <div class="battle-actions battle-picker"><el-select v-model="selectedId" placeholder="选择战报" aria-label="选择战报" @change="changeReport"><el-option v-for="item in reports" :key="item.id" :label="`${item.name} · ${stageLabels[item.stage]}`" :value="item.id" /></el-select><el-checkbox v-model="archived" @change="loadReports()">查看归档</el-checkbox><el-select v-if="report" v-model="team" clearable placeholder="全部可查看业务组" aria-label="业务组筛选" @change="changeTeam"><el-option v-for="item in teams" :key="item" :label="item" :value="item" /></el-select></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="report" class="battle-meta"><el-tag size="small" effect="plain">{{ stageLabels[report.stage] }}</el-tag><span>{{ report.start_date }} — {{ report.end_date }} · USD</span><span>核算日期 · 订单 GMV · 活动小组</span></div>
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
        <el-tab-pane label="战报总览" name="overview"><ReportOverview v-if="overview" :data="overview" @team="chooseTeam" @review="review" /></el-tab-pane>
        <el-tab-pane label="每日复盘" name="daily"><ReportDaily v-if="tab === 'daily'" :key="`${report.id}:${team}:${refreshKey}`" :report="report" :team="team" :selection="selection" /></el-tab-pane>
        <el-tab-pane label="目标填报" name="targets"><ReportTargets v-if="tab === 'targets'" :report="report" :team="team" @saved="refresh" /></el-tab-pane>
      </el-tabs>
      <el-empty v-else-if="!loading" :description="error ? '暂时无法读取战报，请重试' : '暂无可查看的战报，管理员可新建战报并邀请业务员参与'" />
    </div>
    <footer v-if="overview" class="battle-footer"><span>计算时间：{{ formatBeijingDateTime(overview.calculated_at) }}（北京时间）</span><span>源同步时间未知 · 以当前业务镜像数据为准</span></footer>
    <ReportSettings v-model="settingsVisible" :report="editingReport" @saved="settingsSaved" />
    <ReportPosters v-if="postersVisible && report" v-model="postersVisible" :report="report" @saved="refresh" />
    <DetailDrawer v-model="auditsVisible" title="战报修改记录" :loading="auditsLoading"><el-alert v-if="auditError" type="error" :title="auditError" :closable="false" /><article v-for="item in audits" :key="item.id" class="battle-audit"><h4>{{ auditLabels[item.action] || item.action }} · {{ formatBeijingDateTime(item.created_at) }}</h4><p>操作人 ID：{{ item.actor_id }} · {{ item.reason || '常规操作' }}</p><details><summary>查看修改前后内容</summary><p>修改前</p><pre>{{ JSON.stringify(item.before, null, 2) }}</pre><p>修改后</p><pre>{{ JSON.stringify(item.after, null, 2) }}</pre></details></article><el-pagination v-model:current-page="auditPage" :total="auditTotal" :page-size="20" layout="prev, pager, next" @current-change="loadAudits" /></DetailDrawer>
  </div>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
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

const reports = ref([]), report = ref(null), overview = ref(null), selectedId = ref(null), archived = ref(false)
const postersVisible = ref(false)
const team = ref(''), tab = ref('overview'), selection = ref({}), loading = ref(false), busy = ref(false), error = ref(''), refreshKey = ref(0)
const settingsVisible = ref(false), editingReport = ref(null), auditsVisible = ref(false), auditsLoading = ref(false), auditError = ref(''), audits = ref([]), auditPage = ref(1), auditTotal = ref(0)
const auditLabels = { create: '创建战报', configure: '更正设置', targets: '修改目标', publish: '发布', archive: '归档', restore: '恢复', poster_config: '海报与群推送设置' }
const teams = computed(() => [...new Set(report.value?.members.map(m => m.team) || [])])
let request = 0, listRequest = 0, auditRequest = 0
async function loadReports(preferred) {
  const token = ++listRequest; ++request; loading.value = true; report.value = null; overview.value = null
  try {
    const result = await battleReportApi.list({ archived: archived.value })
    if (token !== listRequest) return
    reports.value = result.items
    selectedId.value = reports.value.some(r => r.id === preferred) ? preferred : reports.value[0]?.id || null
    team.value = ''; selection.value = {}; error.value = ''
    if (selectedId.value) await loadReport()
  } catch (e) { if (token === listRequest) error.value = errorText(e) }
  finally { if (token === listRequest) loading.value = false }
}
async function loadReport() {
  if (!selectedId.value) return
  const token = ++request, id = selectedId.value; loading.value = true
  try {
    const [detail, data] = await Promise.all([battleReportApi.get(id), battleReportApi.overview(id, { team: team.value || undefined })])
    if (token !== request) return
    report.value = detail; overview.value = data; error.value = ''
  } catch (e) { if (token === request) error.value = `数据未更新：${errorText(e)}` }
  finally { if (token === request) loading.value = false }
}
function changeReport() { report.value = null; overview.value = null; team.value = ''; selection.value = {}; return loadReport() }
function changeTeam() { overview.value = null; selection.value = {}; return loadReport() }
function chooseTeam(value) { team.value = value; changeTeam() }
function review(value) { selection.value = value; tab.value = 'daily' }
function refresh() { refreshKey.value++; return selectedId.value ? loadReport() : loadReports() }
function openSettings(edit) { editingReport.value = edit ? report.value : null; settingsVisible.value = true }
async function settingsSaved(id) { archived.value = false; refreshKey.value++; await loadReports(id) }
async function transition(action) {
  if (busy.value) return
  busy.value = true
  try { const id = report.value.id; await battleReportApi.state(id, { action, version: report.value.version }); msgSuccess(auditLabels[action]); archived.value = action === 'archive'; await loadReports(id) }
  catch (e) { error.value = errorText(e) } finally { busy.value = false }
}
async function openAudits() { audits.value = []; auditPage.value = 1; auditsVisible.value = true; await loadAudits() }
async function loadAudits() {
  const token = ++auditRequest; auditsLoading.value = true; auditError.value = ''
  try { const result = await battleReportApi.audits(report.value.id, { page: auditPage.value }); if (token === auditRequest) { audits.value = result.items; auditTotal.value = result.total } }
  catch (e) { if (token === auditRequest) auditError.value = errorText(e) }
  finally { if (token === auditRequest) auditsLoading.value = false }
}
onMounted(() => loadReports())
onUnmounted(() => { request++; listRequest++; auditRequest++ })
</script>
<style src="./battle-report.css"></style>
