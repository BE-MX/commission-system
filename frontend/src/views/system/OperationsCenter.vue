<template>
  <div class="operations-page" v-loading="loading">
    <div class="operations-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="page-header">
      <div>
        <p class="eyebrow">SYSTEM OPERATIONS</p>
        <h1>运行与自动化中心</h1>
        <p class="subtitle">集中查看平台服务、外部集成和本实例定时任务。远程服务仅健康探测，不开放任意命令执行。</p>
      </div>
    </header>

    <ListPageStatus v-if="overviewResource.error.value || !overview" v-bind="resourceStatus(overviewResource)" @retry="loadOverview" />
    <section v-if="overview" class="metric-grid" aria-label="运行摘要">
      <article class="metric-card lg-card is-static">
        <span>健康服务</span><strong>{{ summary.healthy_services ?? '—' }}</strong><small>当前检查通过</small>
      </article>
      <article class="metric-card lg-card is-static" :class="{ attention: summary.attention_services }">
        <span>待处理服务</span><strong>{{ summary.attention_services ?? '—' }}</strong><small>未配置、未纳管或异常</small>
      </article>
      <article class="metric-card lg-card is-static">
        <span>已注册任务</span><strong>{{ summary.registered_jobs ?? '—' }}</strong><small>预期 {{ scheduler.expected_job_count ?? '—' }} 项</small>
      </article>
      <article class="metric-card lg-card is-static" :class="{ attention: summary.failed_jobs }">
        <span>最近异常</span><strong>{{ summary.failed_jobs ?? '—' }}</strong><small>失败、错过或并发跳过</small>
      </article>
      <article class="metric-card lg-card is-static">
        <span>云端实例</span><strong>{{ runtimeInstances.length }}</strong><small>{{ summary.healthy_instances ?? 0 }} 个心跳正常</small>
      </article>
      <article class="metric-card lg-card is-static" :class="{ attention: summary.degraded_instances }">
        <span>失联实例</span><strong>{{ summary.degraded_instances ?? 0 }}</strong><small>超过部署策略未上报</small>
      </article>
    </section>

    <section ref="runtimePanelRef" class="section-card lg-card is-static table-card">
      <div class="section-heading">
        <div><h2>跨服务器运行实例</h2><p>Shopify、OpenClaw、MCP 及云端任务使用实例级机器凭证主动上报</p></div>
        <StatusBadge v-if="overview" effect="plain" round>{{ runtimeInstances.length ? `${runtimeInstances.length} 个实例` : '待接入' }}</StatusBadge>
      </div>
      <div class="action-bar">
        <TableTools v-model:visible-keys="runtimeVisibleKeys" v-model:density="runtimeDensity" :columns="runtimeColumnDefs" :fullscreen="runtimeIsFullscreen" @refresh="loadDashboard" @fullscreen="toggleRuntimeFullscreen" />
      </div>
      <el-table :data="runtimeInstances" class="list-table" :class="runtimeDensityClass" :max-height="runtimeIsFullscreen ? undefined : 640" border v-sticky-scrollbar>
        <template #empty><ListPageStatus v-bind="resourceStatus(overviewResource)" @retry="loadOverview"><el-empty description="暂无记录" /></ListPageStatus></template>
        <el-table-column v-if="runtimeVisibleKeys.includes('service')" label="服务 / 实例" min-width="220" show-overflow-tooltip>
          <template #default="{ row }"><strong class="job-name">{{ row.service_name }}</strong><small class="job-id">{{ row.service_id }} · {{ row.instance_id }}</small></template>
        </el-table-column>
        <el-table-column v-if="runtimeVisibleKeys.includes('environment')" prop="environment" label="环境" min-width="120" show-overflow-tooltip />
        <el-table-column v-if="runtimeVisibleKeys.includes('version')" prop="version" label="版本" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.version || '—' }}</template>
        </el-table-column>
        <el-table-column v-if="runtimeVisibleKeys.includes('status')" label="状态" min-width="120">
          <template #default="{ row }"><StatusBadge :type="statusType(row.status)" effect="plain" round>{{ statusLabel(row.status) }}</StatusBadge></template>
        </el-table-column>
        <el-table-column v-if="runtimeVisibleKeys.includes('heartbeat')" label="最近心跳" min-width="180">
          <template #default="{ row }">{{ formatTime(row.last_heartbeat_at) }}<small class="job-id">{{ ageLabel(row.heartbeat_age_seconds) }}</small></template>
        </el-table-column>
        <el-table-column v-if="runtimeVisibleKeys.includes('capabilities')" label="能力" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.capabilities?.join('、') || '未声明' }}</template>
        </el-table-column>
        <el-table-column v-if="runtimeVisibleKeys.includes('dependencies')" label="依赖" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.dependencies?.join('、') || '无' }}</template>
        </el-table-column>
      </el-table>
    </section>

    <section class="section-card lg-card is-static">
      <div class="section-heading">
        <div><h2>运行服务</h2><p>当前实例与跨服务器运行单元的集中清单</p></div>
        <StatusBadge v-if="overview?.instance" effect="plain" round>{{ overview.instance.hostname }} · {{ roleLabel(overview.instance.role) }}</StatusBadge>
      </div>
      <div class="service-grid">
        <article v-for="service in services" :key="service.id" class="service-card">
          <div class="service-top">
            <span class="status-dot" :class="service.status" />
            <div><h3>{{ service.name }}</h3><p>{{ service.category }} · {{ service.environment }}</p></div>
            <StatusBadge :type="statusType(service.status)" effect="plain" round>{{ statusLabel(service.status) }}</StatusBadge>
          </div>
          <p class="service-detail">{{ service.detail }}</p>
          <dl>
            <div><dt>责任归属</dt><dd>{{ service.owner }}</dd></div>
            <div><dt>纳管级别</dt><dd>{{ managementLabel(service.management) }}</dd></div>
            <div v-if="service.latency_ms != null"><dt>探测延迟</dt><dd>{{ service.latency_ms }} ms</dd></div>
          </dl>
          <code v-if="service.endpoint">{{ service.endpoint }}</code>
        </article>
      </div>
    </section>

    <section ref="runsPanelRef" class="section-card lg-card is-static table-card">
      <div class="section-heading run-history-heading">
        <div><h2>最近运行记录</h2><p>按部署保留策略落库；此处展示最新 30 次，可按状态筛选</p></div>

      </div>
      <FilterBar :loading="runsResource.loading.value" :pending="runsPending" @search="searchRuns" @reset="resetRuns">
        <el-select v-model="runStatus" class="filter-w-md" aria-label="运行状态筛选">
          <el-option label="全部状态" value="" />
          <el-option label="执行失败" value="failed" />
          <el-option label="错过执行" value="missed" />
          <el-option label="并发跳过" value="skipped" />
          <el-option label="执行中" value="running" />
          <el-option label="执行成功" value="success" />
        </el-select>
      </FilterBar>
      <ListPageStatus v-if="runsResource.error.value && jobRuns.length" v-bind="resourceStatus(runsResource)" @retry="loadJobRuns" />
      <div class="action-bar">
        <TableTools v-model:visible-keys="runsVisibleKeys" v-model:density="runsDensity" :columns="runsColumnDefs" :fullscreen="runsIsFullscreen" :loading="runsResource.loading.value" @refresh="loadJobRuns" @fullscreen="toggleRunsFullscreen" />
      </div>
      <el-table :data="jobRuns" class="list-table" :class="runsDensityClass" :max-height="runsIsFullscreen ? undefined : 640" border v-sticky-scrollbar>
        <template #empty><ListPageStatus v-bind="resourceStatus(runsResource)" @retry="loadJobRuns"><el-empty description="暂无记录" /></ListPageStatus></template>
        <el-table-column v-if="runsVisibleKeys.includes('job')" label="任务" min-width="200" show-overflow-tooltip>
          <template #default="{ row }"><strong class="job-name">{{ row.job_name }}</strong><small class="job-id">{{ row.domain }} · {{ row.job_id }}</small></template>
        </el-table-column>
        <el-table-column v-if="runsVisibleKeys.includes('status')" label="状态" min-width="120">
          <template #default="{ row }"><StatusBadge :type="jobStatusType(row.status)" effect="plain" round>{{ jobStatusLabel(row.status) }}</StatusBadge></template>
        </el-table-column>
        <el-table-column v-if="runsVisibleKeys.includes('planned')" label="计划时间" min-width="175"><template #default="{ row }">{{ formatTime(row.planned_at) }}</template></el-table-column>
        <el-table-column v-if="runsVisibleKeys.includes('duration')" label="耗时" min-width="100"><template #default="{ row }">{{ durationLabel(row.duration_ms) }}</template></el-table-column>
        <el-table-column v-if="runsVisibleKeys.includes('trigger')" prop="triggered_by" label="触发来源" min-width="110" show-overflow-tooltip />
        <el-table-column v-if="runsVisibleKeys.includes('instance')" prop="instance_id" label="执行实例" min-width="150" show-overflow-tooltip />
        <el-table-column v-if="runsVisibleKeys.includes('result')" prop="error_digest" label="结果摘要" min-width="210" show-overflow-tooltip>
          <template #default="{ row }">{{ row.error_digest || '—' }}</template>
        </el-table-column>
      </el-table>
    </section>

    <section ref="schedulerPanelRef" class="section-card lg-card is-static table-card">
      <div class="section-heading">
        <div><h2>定时任务</h2><p>{{ scheduler.timezone || '—' }} · {{ scheduler.running ? '调度器运行中' : '当前实例未启用调度器' }}</p></div>
        <StatusBadge :type="scheduler.running ? 'success' : 'info'" effect="plain" round>{{ scheduler.running ? '运行中' : '未启用' }}</StatusBadge>
      </div>
      <div class="action-bar">
        <TableTools v-model:visible-keys="schedulerVisibleKeys" v-model:density="schedulerDensity" :columns="schedulerColumnDefs" :fullscreen="schedulerIsFullscreen" @refresh="loadDashboard" @fullscreen="toggleSchedulerFullscreen" />
      </div>
      <el-table :data="scheduler.jobs || []" class="list-table" :class="schedulerDensityClass" :max-height="schedulerIsFullscreen ? undefined : 640" border v-sticky-scrollbar>
        <template #empty><ListPageStatus v-bind="resourceStatus(overviewResource)" @retry="loadOverview"><el-empty description="暂无记录" /></ListPageStatus></template>
        <el-table-column v-if="schedulerVisibleKeys.includes('job')" label="任务" min-width="190" show-overflow-tooltip>
          <template #default="{ row }"><strong class="job-name">{{ row.name }}</strong><small class="job-id">{{ row.id }}</small></template>
        </el-table-column>
        <el-table-column v-if="schedulerVisibleKeys.includes('domain')" prop="domain" label="领域" min-width="110" show-overflow-tooltip />
        <el-table-column v-if="schedulerVisibleKeys.includes('owner')" prop="owner" label="责任归属" min-width="110" show-overflow-tooltip />
        <el-table-column v-if="schedulerVisibleKeys.includes('trigger')" prop="trigger" label="计划" min-width="180" show-overflow-tooltip />
        <el-table-column v-if="schedulerVisibleKeys.includes('next')" label="下次执行" min-width="175">
          <template #default="{ row }">{{ formatTime(row.next_run_at) }}</template>
        </el-table-column>
        <el-table-column v-if="schedulerVisibleKeys.includes('status')" label="最近状态" min-width="120">
          <template #default="{ row }"><StatusBadge :type="jobStatusType(row.last_status)" effect="plain" round>{{ jobStatusLabel(row.last_status) }}</StatusBadge></template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="230" fixed="right">
          <template #default="{ row }">
            <template v-if="row.registered">
              <el-button v-permission="'operations:admin'" link type="primary" :disabled="row.paused || Boolean(actionJobId)" :loading="actionJobId === row.id" @click="operateJob(row, 'run')"><el-icon><VideoPlay /></el-icon>立即执行</el-button>
              <el-button v-if="!row.paused" v-permission="'operations:admin'" link type="warning" :disabled="Boolean(actionJobId)" @click="operateJob(row, 'pause')"><el-icon><VideoPause /></el-icon>暂停</el-button>
              <el-button v-else v-permission="'operations:admin'" link type="success" :disabled="Boolean(actionJobId)" @click="operateJob(row, 'resume')"><el-icon><RefreshRight /></el-icon>恢复</el-button>
            </template>
            <span v-else class="disabled-hint">当前实例未启用</span>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { statusDictionary, statusLabels, statusTypes, resolveStatus } from '@/utils/status'

import { RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { useOperationsCenter } from './composables/useOperationsCenter'
import { formatBeijingDateTime } from '@/utils/datetime'

const {
  loading, actionJobId, overview, scheduler, services, runtimeInstances, summary,
  jobRuns, runStatus, runsPending, searchRuns, resetRuns, overviewResource, runsResource, loadOverview, loadDashboard, loadJobRuns, operateJob,
} = useOperationsCenter()
const resourceStatus = resource => ({ error: resource.errorMessage.value, loading: resource.loading.value, hasData: resource.hasLoaded.value, paged: false })

const runtimeColumnDefs = [
  { key: 'service', label: '服务 / 实例' }, { key: 'environment', label: '环境' },
  { key: 'version', label: '版本' }, { key: 'status', label: '状态' },
  { key: 'heartbeat', label: '最近心跳' }, { key: 'capabilities', label: '能力' },
  { key: 'dependencies', label: '依赖' },
]
const runsColumnDefs = [
  { key: 'job', label: '任务' }, { key: 'status', label: '状态' },
  { key: 'planned', label: '计划时间' }, { key: 'duration', label: '耗时' },
  { key: 'trigger', label: '触发来源' }, { key: 'instance', label: '执行实例' },
  { key: 'result', label: '结果摘要' },
]
const schedulerColumnDefs = [
  { key: 'job', label: '任务' }, { key: 'domain', label: '领域' },
  { key: 'owner', label: '责任归属' }, { key: 'trigger', label: '计划' },
  { key: 'next', label: '下次执行' }, { key: 'status', label: '最近状态' },
]
const {
  density: runtimeDensity, densityClass: runtimeDensityClass, visibleKeys: runtimeVisibleKeys,
  panelRef: runtimePanelRef, isFullscreen: runtimeIsFullscreen, toggleFullscreen: toggleRuntimeFullscreen,
} = useTableView('operations-runtime', runtimeColumnDefs)
const {
  density: runsDensity, densityClass: runsDensityClass, visibleKeys: runsVisibleKeys,
  panelRef: runsPanelRef, isFullscreen: runsIsFullscreen, toggleFullscreen: toggleRunsFullscreen,
} = useTableView('operations-runs', runsColumnDefs)
const {
  density: schedulerDensity, densityClass: schedulerDensityClass, visibleKeys: schedulerVisibleKeys,
  panelRef: schedulerPanelRef, isFullscreen: schedulerIsFullscreen, toggleFullscreen: toggleSchedulerFullscreen,
} = useTableView('operations-scheduler', schedulerColumnDefs)

const COMPONENT_STATUS = statusDictionary([
  ['healthy', '健康', 'success'],
  ['degraded', '异常', 'danger'],
  ['unconfigured', '未配置', 'warning'],
  ['unmanaged', '未纳管', 'info'],
  ['unknown', '未知', 'info'],
])
const STATUS_LABELS = statusLabels(COMPONENT_STATUS)
const STATUS_TYPES = statusTypes(COMPONENT_STATUS)
const SCHEDULER_STATUS = statusDictionary([
  ['disabled', '未注册', 'info'],
  ['never', '未执行', 'info'],
  ['running', '执行中', 'primary'],
  ['success', '成功', 'success'],
  ['failed', '失败', 'danger'],
  ['missed', '已错过', 'warning'],
  ['skipped', '并发跳过', 'warning'],
])
const JOB_STATUS_LABELS = statusLabels(SCHEDULER_STATUS)
const JOB_STATUS_TYPES = statusTypes(SCHEDULER_STATUS)

function statusLabel(value) { return resolveStatus(value, COMPONENT_STATUS).label }
function statusType(value) { return resolveStatus(value, COMPONENT_STATUS).type }
function jobStatusLabel(value) { return resolveStatus(value, SCHEDULER_STATUS).label }
function jobStatusType(value) { return resolveStatus(value, SCHEDULER_STATUS).type }
function managementLabel(value) { return ({ managed: '平台管理', observed: '状态监测', unmanaged: '待接入' })[value] || '待接入' }
function roleLabel(value) { return value === 'scheduler-primary' ? '调度主实例' : '应用副本' }
function formatTime(value) { return formatBeijingDateTime(value, { naiveTimeZone: 'UTC', fallback: '已暂停 / 无计划' }) }
function ageLabel(seconds) {
  if (seconds < 60) return `${seconds} 秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  return `${Math.floor(seconds / 3600)} 小时前`
}
function durationLabel(value) {
  if (value === null || value === undefined) return '—'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(1)} s`
}
</script>

<style scoped>
.operations-page { position: relative; min-height: 100%; }
.operations-aurora { inset: -24px -28px; }
.page-header, .metric-grid, .section-card { position: relative; z-index: 1; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 20px; }
.eyebrow { margin: 0 0 4px; color: var(--color-primary-text); font: 700 11px/1.4 var(--font-display); letter-spacing: .16em; }
h1 { margin: 0; color: var(--text-primary); font: 800 28px/1.25 var(--font-display); }
.subtitle { max-width: 760px; margin: 7px 0 0; color: var(--text-secondary); font-size: 13px; }
.metric-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
.metric-card { display: grid; gap: 5px; padding: 18px 20px; }
.metric-card span, .metric-card small { color: var(--text-secondary); font-size: 12px; }
.metric-card strong { color: var(--text-primary); font: 800 28px/1 var(--font-display); font-variant-numeric: tabular-nums; }
.metric-card.attention strong { color: var(--color-danger); }
.section-card { overflow: hidden; margin-bottom: 18px; padding: 20px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.section-heading h2 { margin: 0; color: var(--text-primary); font: 700 16px/1.4 var(--font-display); }
.section-heading p { margin: 3px 0 0; color: var(--text-secondary); font-size: 12px; }
.service-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.service-card { min-width: 0; padding: 15px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: rgba(255, 255, 255, .55); }
.service-top { display: flex; align-items: flex-start; gap: 9px; }
.service-top > div { min-width: 0; flex: 1; }
.service-top h3 { overflow: hidden; margin: 0; color: var(--text-primary); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.service-top p, .service-detail { margin: 3px 0 0; color: var(--text-secondary); font-size: 12px; }
.status-dot { width: 8px; height: 8px; flex: none; margin-top: 5px; border-radius: 50%; background: var(--text-muted); }
.status-dot.healthy { background: var(--color-success); box-shadow: 0 0 0 4px var(--color-success-bg); }
.status-dot.degraded { background: var(--color-danger); box-shadow: 0 0 0 4px var(--color-danger-bg); }
.status-dot.unconfigured { background: var(--color-primary); box-shadow: 0 0 0 4px var(--color-warning-bg); }
.service-detail { min-height: 34px; padding-top: 8px; }
dl { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 10px 0 0; }
dl div { display: flex; gap: 5px; font-size: 11px; }
dt { color: var(--text-muted); } dd { margin: 0; color: var(--text-secondary); }
code { display: block; overflow: hidden; margin-top: 10px; padding: 6px 8px; border-radius: 6px; color: var(--text-secondary); background: var(--toolbar-bg); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.job-name, .job-id { display: block; }
.job-id { margin-top: 2px; color: var(--text-muted); font-size: 10px; font-weight: 400; }
.disabled-hint { color: var(--text-muted); font-size: 12px; }
.status-filter { width: 150px; }
:deep(.el-table) { --el-table-bg-color: transparent; --el-table-tr-bg-color: transparent; --el-table-header-bg-color: rgba(255, 255, 255, .5); --el-table-row-hover-bg-color: rgba(255, 255, 255, .7); background: transparent; }
:deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, .97); }
:deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, .98); }
:deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, .98); }
@media (max-width: 1200px) { .metric-grid { grid-template-columns: repeat(3, 1fr); } .service-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 720px) { .page-header, .run-history-heading { align-items: stretch; flex-direction: column; } .metric-grid, .service-grid { grid-template-columns: 1fr; } .section-card { padding: 14px; } .status-filter { width: 100%; } }
</style>
