<template>
  <div class="radar-page">
    <div class="radar-aurora" aria-hidden="true"><i /><i /><i /></div>
    <header class="page-head">
      <div><h1>项目雷达</h1><p>收藏值得关注的项目，自动追踪关键更新。每天 {{ settings?.scan_time || '06:30' }} 扫描，钉钉早报只推值得看的变化。</p></div>
      <div class="page-actions"><span class="bot-hint"><i />钉钉里发给「方舟雷达」也能收录</span><GlassButton left-icon="Setting" @click="openSettings">扫描与推送设置</GlassButton></div>
    </header>

    <section v-permission="'project_radar:write'" class="capture-card">
      <form class="capture-form" @submit.prevent="submitCapture">
        <span class="capture-plus" aria-hidden="true">＋</span>
        <input v-model="captureText" type="text" aria-label="粘贴链接收录" placeholder="粘贴 GitHub、官网、X 帖子或公众号文章链接，回车收录；可一次粘贴多条">
        <GlassButton variant="primary" native-type="submit" :disabled="!captureText.trim()">收录</GlassButton>
      </form>
      <p>链接后面写的话会变成笔记，<code>#标签</code> 会随项目保存。重复链接只追加来源。</p>
    </section>

    <section class="health-strip" :class="{ 'health-strip--error': healthError }" role="status">
      <span class="health-dot" />
      <span>{{ scanText }}</span><span class="health-separator" />
      <span class="digest-time">{{ settings?.digest_time || '08:00' }}</span><span>{{ digestText }}</span>
      <GlassButton variant="link" left-icon="Refresh" @click="refresh">刷新</GlassButton>
    </section>

    <section class="list-card">
      <div class="view-tabs" role="tablist" aria-label="按状态查看">
        <button v-for="view in VIEWS" :key="view.value" type="button" role="tab" :aria-selected="filters.view === view.value" :class="{ 'has-new': view.value === 'updates' && counts.updates }" @click="changeView(view.value)">{{ view.label }}<span>{{ counts[view.value] || 0 }}</span></button>
      </div>
      <div class="filters">
        <el-input v-model="filters.keyword" class="keyword" placeholder="搜索标题、说明、笔记、标签" clearable prefix-icon="Search" @keyup.enter="search" @clear="search" />
        <el-select v-model="filters.item_type" placeholder="全部类型" clearable @change="search"><el-option v-for="type in settings?.types || []" :key="type.code" :label="type.label" :value="type.code" /></el-select>
        <el-select v-model="filters.module" placeholder="全部方舟模块" clearable @change="search"><el-option v-for="module in settings?.modules || []" :key="module.code" :label="module.label" :value="module.label" /></el-select>
        <el-select v-model="filters.read_state" placeholder="全部读取状态" clearable @change="search"><el-option label="读取正常" value="ok" /><el-option label="读取受限" value="limited" /><el-option label="读取失败" value="failed" /></el-select>
        <GlassButton left-icon="Search" :loading="loading" @click="search">查询</GlassButton>
      </div>

      <div v-if="pendingJobs.length" class="ingest-progress">
        <div v-for="job in pendingJobs" :key="job.id" class="progress-row" role="status">
          <span class="project-icon">…</span><div><b>{{ job.raw_input }}</b><div class="progress-steps"><span class="done">✓ 识别链接</span><span :class="{ doing: job.status === 'reading' }">{{ job.status === 'reading' ? '正在读取与 AI 分析…' : '等待读取…' }}</span><span>完成后原位填充</span></div></div>
        </div>
      </div>

      <ListPageStatus v-if="errorMessage" :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table v-else :data="items" v-loading="loading" border class="radar-table list-table" :row-class-name="rowClass" v-sticky-scrollbar @row-click="openDetail">
        <template #empty><el-empty :image-size="88" :description="filters.view === 'updates' ? '没有未读更新' : '这个视图下没有项目'"><GlassButton v-if="filters.view !== 'all'" @click="changeView('all')">查看全部</GlassButton></el-empty></template>
        <el-table-column label="项目" min-width="320">
          <template #default="{ row }"><div class="project-cell"><span class="project-icon" :class="`project-icon--${row.kind}`">{{ row.kind === 'repo' ? 'Git' : row.kind === 'article' ? '文' : 'Web' }}</span><div class="project-main"><div class="project-title"><b>{{ row.title }}</b><StatusBadge type="info" size="small">{{ typeLabel(row.item_type) }}</StatusBadge><StatusBadge v-if="row.unread" type="warning" size="small">{{ row.unread_update?.level === 'key' ? '关键更新' : '有更新' }}</StatusBadge><StatusBadge v-if="row.read_state !== 'ok'" type="danger" size="small">读取受限</StatusBadge></div><div class="project-path">{{ row.host }}{{ row.kind === 'repo' ? row.canonical_url.split(row.host)[1] : '' }}</div><p>{{ row.one_liner }}</p></div></div></template>
        </el-table-column>
        <el-table-column label="可用于方舟" min-width="180" class-name="radar-optional">
          <template #default="{ row }"><div class="tag-list"><StatusBadge v-for="module in row.ark_modules" :key="module.name" type="info">{{ module.name }}</StatusBadge><span v-if="!row.ark_modules.length" class="muted">—</span></div></template>
        </el-table-column>
        <el-table-column label="版本" min-width="110"><template #default="{ row }"><span v-if="row.kind === 'article'" class="muted">不追踪</span><code v-else-if="row.version">{{ row.version }}</code><span v-else class="muted">无版本</span></template></el-table-column>
        <el-table-column label="最近更新" min-width="130" class-name="radar-optional"><template #default="{ row }"><span :title="formatDateTime(row.last_updated_at)">{{ relativeTime(row.last_updated_at) }}</span><small v-if="row.unread" class="unread-text">未读</small></template></el-table-column>
        <el-table-column label="状态" min-width="100"><template #default="{ row }"><StatusBadge :type="STATUS_TYPES[row.status]">{{ STATUS[row.status] }}</StatusBadge></template></el-table-column>
        <el-table-column label="操作" min-width="82" fixed="right"><template #default="{ row }"><GlassButton variant="link" @click.stop="openDetail(row)">详情</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination v-if="total > pageSize" v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </section>

    <DetailDrawer v-model="detailVisible" :title="detail?.title || '项目详情'" :width="640" :loading="detailLoading" @closed="closeDetail">
      <ProjectRadarDetail v-if="detail" :item="detail" :types="settings?.types || []" :modules="settings?.modules || []" :read-only="!canWrite" @patch="patchDetail" />
      <template v-if="detail && canWrite" #footer><GlassButton left-icon="Refresh" @click="reanalyze">重新分析</GlassButton><span class="footer-spacer" /><GlassButton v-permission="'project_radar:write'" variant="secondary" link-tone="danger" @click="removeDetail">移出雷达</GlassButton><GlassButton variant="primary" @click="detailVisible = false">完成</GlassButton></template>
    </DetailDrawer>

    <el-dialog :model-value="Boolean(candidateJob)" title="这篇文章提到多个项目" width="640" :close-on-click-modal="false" @closed="cancelCandidates">
      <p class="dialog-note">文章本身不会追踪更新。选中的项目会单独收录，文章记为来源；未确认的名称不会自动收录。</p>
      <el-checkbox-group v-model="selectedCandidates" class="candidate-list">
        <el-checkbox v-for="(candidate, index) in candidateJob?.candidates || []" :key="`${candidate.url}-${index}`" :value="index + 1" :disabled="!candidate.confirmed"><b>{{ index + 1 }}. {{ candidate.title }}</b><p>{{ candidate.url || candidate.reason }}<span v-if="!candidate.confirmed">（未确认）</span></p></el-checkbox>
      </el-checkbox-group>
      <template #footer><GlassButton @click="selectAllCandidates">选择全部确认项</GlassButton><GlassButton variant="primary" :disabled="!selectedCandidates.length" @click="chooseCandidates">收录选中的 {{ selectedCandidates.length }} 项</GlassButton></template>
    </el-dialog>

    <el-dialog v-model="settingsVisible" title="扫描与推送设置" width="640">
      <div class="settings-form">
        <div class="setting-row"><div><b>每日扫描</b><p>只有新版本、changelog 或追踪页变化才调用 AI；修改全局时间需管理员权限。</p></div><el-time-select v-model="globalForm.scan_time" start="00:00" end="23:30" step="00:30" :disabled="!canAdmin" /></div>
        <div class="setting-row"><div><b>普通更新推送冷却</b><p>关键更新不受频率限制</p></div><el-input-number v-model="globalForm.normal_push_cooldown_days" :min="1" :max="30" :disabled="!canAdmin" /></div>
        <div v-permission="'project_radar:admin'" class="setting-action"><GlassButton @click="saveGlobal">保存全局设置</GlassButton></div>
        <div class="setting-row"><div><b>我的钉钉早报</b><p>所有更新合成一条消息，每天最多一条</p></div><el-time-select v-model="settingsForm.digest_time" start="00:00" end="23:30" step="00:30" /></div>
        <div class="setting-row"><div><b>没有更新的日子</b><p>默认不打扰；连续 7 天无推送会发送运行正常心跳</p></div><el-switch v-model="settingsForm.send_empty" active-text="发今日无更新" /></div>
        <div class="setting-row"><div><b>沉睡提醒</b><p>每周一早报附收录超过 14 天仍待看的项目</p></div><el-switch v-model="settingsForm.sleepy_reminder" /></div>
        <div class="setting-row"><div><b>GitHub Star 同步 <StatusBadge type="info">二期</StatusBadge></b><p>本期暂未开放</p></div><el-switch disabled /></div>
      </div>
      <template #footer><GlassButton @click="settingsVisible = false">取消</GlassButton><GlassButton v-permission="'project_radar:write'" variant="primary" @click="savePersonal">保存我的设置</GlassButton></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import ProjectRadarDetail from './components/ProjectRadarDetail.vue'
import { useProjectRadar } from './composables/useProjectRadar'
import {
  getRadarSubscription, patchRadarSubscription, reanalyzeRadarSubscription,
  removeRadarSubscription, saveRadarGlobalSettings, saveRadarSettings,
} from '@/api/projectRadar'
import { useAuthStore } from '@/stores/auth'
import { formatBeijingDateTime, parseApiDateTime } from '@/utils/datetime'
import { confirmDanger, msgSuccess } from '@/utils/feedback'

const VIEWS = [{ value: 'updates', label: '有新更新' }, { value: 'all', label: '全部' }, { value: 'inbox', label: '待看' }, { value: 'trying', label: '试用中' }, { value: 'adopted', label: '已采用' }, { value: 'dropped', label: '已放弃' }]
const STATUS = { inbox: '待看', trying: '试用中', adopted: '已采用', dropped: '已放弃' }
const STATUS_TYPES = { inbox: 'info', trying: 'primary', adopted: 'success', dropped: 'info' }
const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('project_radar:write'))
const canAdmin = computed(() => auth.hasPermission('project_radar:admin'))
const { listState, counts, health, settings, pendingJobs, candidateJob, selectedCandidates, refresh, loadAuxiliary, capture, chooseCandidates, cancelCandidates } = useProjectRadar()
const { loading, list: items, total, page, pageSize, searchForm: filters, errorMessage, hasData, dataPage, hasPendingSearch, fetchList, handleSearch: search, handlePageChange, handleSizeChange } = listState
const captureText = ref('')
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const settingsVisible = ref(false)
const settingsForm = reactive({ digest_time: '08:00', send_empty: false, sleepy_reminder: true })
const globalForm = reactive({ scan_time: '06:30', normal_push_cooldown_days: 7 })

const healthError = computed(() => ['failed', 'partial'].includes(health.value?.scan?.status) || health.value?.digest?.status === 'failed' || health.value?.failed_outbox_count > 0)
const scanText = computed(() => {
  const scan = health.value?.scan
  if (!scan) return `今日尚未扫描 · 每日 ${settings.value?.scan_time || '06:30'} 自动扫描`
  return `${scan.started_at?.slice(11, 16) || ''} 扫描 ${scan.success}/${scan.total} 完成${scan.failed ? ` · ${scan.failed} 项失败` : health.value?.limited_count ? ` · ${health.value.limited_count} 项读取受限` : ''}`
})
const digestText = computed(() => {
  const digest = health.value?.digest
  if (!digest) return '今日早报尚未推送'
  if (digest.status === 'failed') return '早报推送失败，请查看运行与自动化中心'
  return digest.status === 'sent' ? `早报已推送：${digest.item_count} 项更新` : '早报等待推送'
})

onMounted(loadAuxiliary)
function submitCapture() { const value = captureText.value; captureText.value = ''; capture(value) }
function changeView(view) { filters.view = view; search() }
function rowClass({ row }) { return row.unread ? 'radar-row-unread' : '' }
function typeLabel(code) { return settings.value?.types?.find(item => item.code === code)?.label || code }
function formatDateTime(value) { return value ? `${formatBeijingDateTime(value, { seconds: false })} 北京时间` : '未知' }
function relativeTime(value) {
  const date = parseApiDateTime(value)
  if (!date) return '未知'
  const hours = Math.max(0, Math.floor((Date.now() - date.getTime()) / 3600000))
  if (hours < 1) return '刚刚'
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  return days < 30 ? `${days} 天前` : formatBeijingDateTime(value, { seconds: false }).slice(0, 10)
}
async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  try { detail.value = (await getRadarSubscription(row.id)).data } finally { detailLoading.value = false }
}
async function closeDetail() {
  if (detail.value?.unread && canWrite.value) await patchRadarSubscription(detail.value.id, { mark_read: true }, { suppressToast: true })
  detail.value = null
  await refresh()
}
async function patchDetail(payload) {
  const response = await patchRadarSubscription(detail.value.id, payload)
  detail.value = response.data
  await fetchList()
}
async function reanalyze() {
  await reanalyzeRadarSubscription(detail.value.id)
  msgSuccess('正在后台重新分析，已锁定字段不会被覆盖')
  const id = detail.value.id
  setTimeout(async () => { if (detail.value?.id === id) detail.value = (await getRadarSubscription(id)).data; await refresh() }, 5000)
}
async function removeDetail() {
  const title = detail.value.title
  await confirmDanger('移出雷达', title, '只移出你的订阅，30 天内重新收录可恢复。')
  await removeRadarSubscription(detail.value.id)
  detail.value = null
  detailVisible.value = false
  msgSuccess('已移出雷达')
  await refresh()
}
function openSettings() {
  Object.assign(settingsForm, { digest_time: settings.value?.digest_time || '08:00', send_empty: settings.value?.send_empty || false, sleepy_reminder: settings.value?.sleepy_reminder ?? true })
  Object.assign(globalForm, { scan_time: settings.value?.scan_time || '06:30', normal_push_cooldown_days: settings.value?.normal_push_cooldown_days || 7 })
  settingsVisible.value = true
}
async function savePersonal() { await saveRadarSettings(settingsForm); settingsVisible.value = false; msgSuccess('设置已保存'); await loadAuxiliary() }
async function saveGlobal() { await saveRadarGlobalSettings(globalForm); msgSuccess('全局设置已保存'); await loadAuxiliary() }
function selectAllCandidates() { selectedCandidates.value = (candidateJob.value?.candidates || []).map((item, index) => item.confirmed ? index + 1 : null).filter(Boolean) }
</script>

<style scoped>
.radar-page { position: relative; min-height: 100%; padding: 22px 24px 48px; }
.radar-aurora { position: absolute; inset: 0 0 auto; height: 620px; overflow: hidden; pointer-events: none; background: linear-gradient(155deg, var(--dash-wash-from), var(--dash-wash-mid) 52%, var(--dash-wash-to)); mask-image: linear-gradient(to bottom, var(--button-text), transparent); }
.radar-aurora i { position: absolute; width: 420px; height: 420px; border-radius: 50%; background: radial-gradient(circle, var(--dash-aurora-gold), transparent 68%); }
.radar-aurora i:nth-child(1) { right: -120px; top: -180px; }
.radar-aurora i:nth-child(2) { left: -180px; top: 120px; background: radial-gradient(circle, var(--dash-aurora-amber), transparent 68%); }
.radar-aurora i:nth-child(3) { right: 20%; top: 340px; background: radial-gradient(circle, var(--dash-aurora-peach), transparent 68%); }
.page-head, .capture-card, .health-strip, .list-card { position: relative; max-width: 1500px; margin-inline: auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.page-head h1 { margin: 0; font-size: 24px; }
.page-head p { margin: 5px 0 0; color: var(--text-secondary); }
.page-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 12px; }
.bot-hint { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border-radius: 999px; background: var(--dash-glass-bg-strong); color: var(--text-secondary); font-size: 12px; }
.bot-hint i, .health-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--tag-success-text); box-shadow: 0 0 0 3px var(--tag-success-bg); }
.capture-card { padding: 14px 16px 11px; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow); }
.capture-form { display: flex; align-items: center; gap: 10px; min-height: 46px; padding: 4px 5px 4px 12px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--card-bg); transition: border-color 180ms ease, box-shadow 180ms ease; }
.capture-form:focus-within { border-color: var(--color-primary); box-shadow: 0 0 0 3px var(--color-primary-light); }
.capture-form input { flex: 1; min-width: 0; height: 36px; border: 0; outline: 0; background: transparent; color: var(--text-primary); }
.capture-plus { color: var(--color-primary); font-size: 20px; }
.capture-card > p { margin: 8px 2px 0; color: var(--text-muted); font-size: 12px; }
.capture-card code { color: var(--color-primary-text); }
.health-strip { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 12px; padding: 10px 14px; border: 1px solid var(--dash-glass-border); border-radius: 12px; background: var(--dash-glass-bg); color: var(--text-secondary); font-size: 13px; }
.health-strip--error .health-dot { background: var(--tag-danger-text); box-shadow: 0 0 0 3px var(--tag-danger-bg); }
.health-separator { width: 1px; height: 14px; background: var(--border-color); }
.digest-time { padding: 2px 7px; border-radius: 5px; background: var(--tag-gold-bg); color: var(--tag-gold-text); font-weight: 600; }
.list-card { margin-top: 12px; overflow: hidden; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--card-shadow); }
.view-tabs { display: flex; gap: 4px; overflow-x: auto; padding: 8px 14px 0; border-bottom: 1px solid var(--border-color); }
.view-tabs button { position: relative; padding: 9px 12px 12px; border: 0; background: transparent; color: var(--text-secondary); white-space: nowrap; cursor: pointer; }
.view-tabs button span { margin-left: 5px; color: var(--text-muted); font-size: 12px; }
.view-tabs button[aria-selected='true'] { color: var(--text-primary); font-weight: 600; }
.view-tabs button[aria-selected='true']::after { content: ''; position: absolute; right: 12px; bottom: -1px; left: 12px; height: 2px; background: var(--color-primary); }
.view-tabs .has-new span { padding: 1px 6px; border-radius: 9px; background: var(--tag-gold-solid); color: var(--tag-gold-ink); }
.filters { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 14px; }
.filters .el-select { width: 170px; }
.filters .keyword { flex: 1; min-width: 240px; max-width: 390px; }
.ingest-progress { margin: 0 14px 10px; border: 1px solid var(--tag-gold-border); border-radius: 10px; background: var(--tag-gold-bg); }
.progress-row { display: flex; gap: 12px; padding: 12px; }
.progress-row b { display: block; max-width: 720px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono); font-size: 12px; }
.progress-steps { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 5px; color: var(--text-muted); font-size: 12px; }
.progress-steps .done { color: var(--tag-success-text); }
.progress-steps .doing { color: var(--color-primary-text); }
.project-cell { display: flex; gap: 12px; min-width: 0; }
.project-icon { width: 36px; height: 36px; display: grid; place-items: center; flex-shrink: 0; border-radius: 10px; background: var(--sidebar-glass-to); color: var(--color-gold); font-size: 12px; font-weight: 700; }
.project-icon--website { background: var(--tag-info-bg); color: var(--tag-info-text); }
.project-icon--article { background: var(--tag-success-bg); color: var(--tag-success-text); }
.project-main { min-width: 0; }
.project-title { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.project-path { overflow: hidden; color: var(--text-muted); font-family: var(--font-mono); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.project-main p { display: -webkit-box; overflow: hidden; margin: 3px 0 0; color: var(--text-secondary); font-size: 13px; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.tag-list { display: flex; flex-wrap: wrap; gap: 5px; }
.muted { color: var(--text-muted); }
.unread-text { display: block; color: var(--color-primary-text); }
.radar-table { width: 100%; background: transparent; }
.pager { justify-content: flex-end; padding: 12px 16px; }
.footer-spacer { flex: 1; }
.dialog-note { color: var(--text-secondary); }
.candidate-list { display: grid; gap: 8px; }
.candidate-list p { margin: 4px 0 0; color: var(--text-muted); font-size: 12px; overflow-wrap: anywhere; }
.settings-form { display: grid; }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 13px 0; border-bottom: 1px solid var(--border-color); }
.setting-row p { margin: 3px 0 0; color: var(--text-muted); font-size: 12px; }
.setting-action { display: flex; justify-content: flex-end; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
@media (max-width: 900px) {
  .radar-page { padding: 16px 12px 36px; }
  .page-head { align-items: flex-start; flex-direction: column; }
  .page-actions { justify-content: flex-start; }
  .radar-table :deep(.radar-optional) { display: none; }
  .health-separator { display: none; }
}
@media (max-width: 600px) {
  .capture-form { align-items: stretch; flex-wrap: wrap; }
  .capture-form input { flex-basis: calc(100% - 40px); }
  .capture-form :deep(.glass-button) { width: 100%; }
  .filters .keyword, .filters .el-select { width: 100%; max-width: none; }
  .setting-row { align-items: flex-start; flex-direction: column; }
}
@media (prefers-reduced-motion: reduce) {
  .capture-form { transition: none; }
}
</style>

<style src="./ProjectRadarTable.css"></style>
