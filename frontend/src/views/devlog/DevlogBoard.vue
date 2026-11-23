<template>
  <div class="devlog-page" :class="{ 'is-stale': stale }">
    <div class="devlog-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="devlog-head">
      <h1 class="devlog-head__title">方舟开发动态</h1>
      <div class="devlog-sync" role="status">
        <span class="devlog-sync__dot" :class="{ 'is-warn': syncState !== 'fresh', 'is-error': syncState === 'unknown' }" aria-hidden="true" />
        <template v-if="health.data.value?.last_sync_at">最后同步 {{ health.data.value.last_sync_at.slice(11) }}</template>
        <template v-else-if="syncState === 'loading'">正在读取同步状态</template>
        <template v-else-if="syncState === 'unknown'">同步状态未知</template>
        <template v-else>尚未同步</template>
        <template v-if="ledger"> · 账本最新 <code>{{ shortSha(ledger.revision) }}</code>（{{ ledger.released_at.slice(5, 16).replace('T', ' ') }}）</template>
      </div>
      <el-button :loading="refreshing" @click="refresh">刷新</el-button>
    </header>

    <el-alert v-if="syncState === 'stale'" class="devlog-stale" type="warning" :closable="false" show-icon
      :title="`数据截至 ${health.data.value.last_sync_at.replace('T', ' ')}，${health.data.value.sources?.some(source => !source.ok) || health.data.value.failed_keys?.length ? '本次采集不完整' : '开发机可能未开机'}。数字仅供参考，别用它判断能否发布。`" />
    <el-alert v-else-if="syncState === 'never'" class="devlog-stale" type="warning" :closable="false" show-icon title="开发机还没有上报过数据。" />
    <el-alert v-else-if="syncState === 'unknown'" class="devlog-stale" type="error" :closable="false" show-icon title="同步状态读取失败，请刷新重试。" />

    <el-alert v-if="health.data.value?.ledger_pending_check" class="devlog-stale" type="warning" :closable="false" show-icon title="新发布待核对：发布账本已更新，开发机尚未完成核对。请勿用当前清单判断能否发布。" />
    <el-alert v-if="summary.isStale.value || pending.isStale.value" class="devlog-stale" type="error" :closable="false" show-icon title="刷新失败，当前显示上次成功读取的数据，请刷新重试。" />
    <el-alert v-else-if="summary.error.value || pending.error.value" class="devlog-stale" type="error" :closable="false" show-icon title="开发动态读取失败，请刷新重试。" />

    <div v-if="health.data.value?.sources?.length" class="devlog-sources" aria-label="采集来源">
      <span v-for="source in health.data.value.sources" :key="source.name" :title="source.detail || ''">
        {{ sourceNames[source.name] || source.name }}：{{ source.ok ? '正常' : '读取失败' }}<span v-if="!source.ok && source.detail">（{{ source.detail }}）</span>
      </span>
    </div>
    <div class="devlog-bar">
      <el-radio-group v-model="filters.range" aria-label="时间范围">
        <el-radio-button value="day">今日</el-radio-button><el-radio-button value="week">本周</el-radio-button>
        <el-radio-button value="month">本月</el-radio-button><el-radio-button value="custom">自定义</el-radio-button>
      </el-radio-group>
      <el-date-picker v-if="filters.range === 'custom'" v-model="filters.custom" type="daterange" value-format="YYYY-MM-DD" unlink-panels aria-label="自定义日期范围" start-placeholder="开始日期" end-placeholder="结束日期" class="filter-w-lg" />
      <span v-else class="devlog-bar__range">{{ period.start }} ~ {{ period.end }}</span>
      <el-select v-model="filters.type" clearable aria-label="事项类型" placeholder="全部类型" class="filter-w-sm">
        <el-option v-for="(meta, key) in TYPE_META" :key="key" :label="meta.label" :value="key" />
      </el-select>
      <el-input v-model="filters.module" clearable aria-label="模块" placeholder="模块名称" maxlength="40" class="filter-w-sm" />
      <el-select v-model="filters.agent" clearable aria-label="代理" placeholder="全部代理" class="filter-w-sm">
        <el-option v-for="(label, key) in AGENT_LABELS" :key="key" :label="label" :value="key" />
      </el-select>
    </div>

    <div class="devlog-data" :aria-busy="summary.loading.value">
      <div class="devlog-kpis">
        <OverviewMetricCard label="上线功能" :value="kpis.features ?? '—'" :icon="Promotion" tone="gold" hint="所选期间已发布" interactive :selected="focus === 'features'" @click="pickKpi('features')" />
        <OverviewMetricCard label="修复问题" :value="kpis.bugs ?? '—'" :icon="CircleCheck" tone="success" hint="所选期间已发布"
          interactive :selected="focus === 'bugs'" @click="pickKpi('bugs')" />
        <OverviewMetricCard label="数据修复" :value="kpis.data ?? '—'" :icon="Coin" tone="violet" hint="P1 起接入" interactive :selected="focus === 'data'" @click="pickKpi('data')" />
        <OverviewMetricCard label="开发中" :value="kpis.dev ?? '—'" :icon="EditPen" tone="info" :hint="kpis.stale ? `另有 ${kpis.stale} 项停滞` : ''" interactive :selected="focus === 'dev'" @click="pickKpi('dev')" />
        <OverviewMetricCard label="待发布" :value="kpis.pending_release ?? '—'" :icon="Clock" tone="warning" hint="已合入 main，未部署"
          interactive :selected="tab === 'pending'" @click="pickKpi('pending_release')" />
      </div>

      <el-tabs v-model="tab" class="devlog-tabs">
        <el-tab-pane label="看板" name="board">
          <el-alert v-if="summary.error.value" type="error" :closable="false" title="加载失败" />
          <el-skeleton v-else-if="summary.loading.value && !summary.hasLoaded.value" :rows="6" />
          <div v-else class="devlog-board">
            <section v-for="(label, key) in COLUMN_LABELS" :key="key" class="devlog-col lg-card is-static" :aria-label="label">
              <h2 class="devlog-col__h"><span class="devlog-col__bar" :class="`is-${key}`" />{{ label }}<span class="devlog-col__n">{{ columns[key].length }}</span></h2>
              <button v-for="item in columns[key]" :key="item.id" type="button" class="devlog-card" @click="openItem(item.id)">
                <span class="devlog-card__tags">
                  <StatusBadge :type="tagType(TYPE_META[item.type].tone)" effect="light" :label="TYPE_META[item.type].label" />
                  <StatusBadge v-if="key === 'committed'" :type="tagType(SUB_TONE[item.status])" :label="STATUS_LABELS[item.status]" />
                  <StatusBadge v-if="item.unmerged_hotfix" type="danger" label="未回合 main" />
                </span>
                <span class="devlog-card__title">{{ item.title }}</span>
                <span class="devlog-card__meta">{{ item.module || '未归模块' }} · {{ AGENT_LABELS[item.agent] }} · {{ item.status_at.slice(5, 10) }}</span>
              </button>
              <el-button v-if="staleColumns[key].length" text @click="showStale = !showStale" :aria-expanded="showStale">{{ showStale ? '收起' : '展开' }} {{ staleColumns[key].length }} 项停滞事项</el-button>
              <template v-if="showStale">
                <button v-for="item in staleColumns[key]" :key="`stale-${item.id}`" type="button" class="devlog-card" @click="openItem(item.id)">
                  <span class="devlog-card__tags"><StatusBadge :type="tagType(TYPE_META[item.type].tone)" :label="TYPE_META[item.type].label" /></span>
                  <span class="devlog-card__title">{{ item.title }}</span><span class="devlog-card__meta">{{ STATUS_LABELS[item.status] }} · 停滞 · {{ item.module || '未归模块' }}</span>
                </button>
              </template>
              <p v-if="!columns[key].length" class="devlog-empty">这段时间没有</p>
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane label="时间线" name="timeline">
          <el-alert v-if="summary.error.value" type="error" :closable="false" title="时间线加载失败，请刷新重试" />
          <p v-else-if="!summary.data.value.timeline.length" class="devlog-empty">这段时间没有状态变化</p>
          <section v-for="day in summary.data.value.timeline" :key="day.date" class="devlog-day lg-card is-static">
            <h2 class="devlog-day__h">{{ day.date.slice(5) }}<span>{{ day.entries.length }} 条变化</span></h2>
            <ul class="devlog-day__list">
              <li v-for="entry in day.entries" :key="`${entry.id}-${entry.to_status}-${entry.occurred_at}`">
                <StatusBadge :type="tagType(TYPE_META[entry.type].tone)" effect="light" :label="TYPE_META[entry.type].label" />
                <time class="devlog-muted">{{ entry.occurred_at?.slice(11) }}</time>
                <span class="devlog-day__to">{{ STATUS_LABELS[entry.to_status] }}</span>
                <button type="button" class="devlog-link" @click="openItem(entry.id)">{{ entry.title }}</button>
              </li>
            </ul>
          </section>
        </el-tab-pane>

        <el-tab-pane :label="`待发布清单 ${pendingReleaseCount}`" name="pending">
          <div class="devlog-table lg-card is-static">
            <el-table :data="filteredPending" v-loading="pending.loading.value" border class="list-table" v-sticky-scrollbar>
              <template #empty><el-empty :image-size="96" :description="pending.error.value ? '加载失败，请刷新重试' : '没有待上线的事项'" /></template>
              <el-table-column label="事项" min-width="220" max-width="360" show-overflow-tooltip>
                <template #default="{ row }"><button type="button" class="devlog-link" @click="openItem(row.id)">{{ row.title }}</button></template>
              </el-table-column>
              <el-table-column label="状态" min-width="100" max-width="120">
                <template #default="{ row }"><StatusBadge :type="tagType(SUB_TONE[row.status])" :label="STATUS_LABELS[row.status]" /></template>
              </el-table-column>
              <el-table-column label="上线前提" min-width="260" max-width="420">
                <template #default="{ row }">
                  <span class="devlog-card__tags">
                    <StatusBadge v-for="tag in preconditionTags(row.preconditions)" :key="tag.text" :type="tagType(tag.tone)" :label="tag.text" />
                    <span v-if="!preconditionTags(row.preconditions).length" class="devlog-muted">无</span>
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="模块" prop="module" min-width="120" max-width="180" show-overflow-tooltip />
              <el-table-column label="能否随下次发布" min-width="140" max-width="180">
                <template #default="{ row }"><span :class="row.ready ? 'devlog-ok' : 'devlog-warn'">{{ readinessLabel(row) }}</span></template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <DevlogItemDrawer v-model="drawer.open" :item="detail.data.value" :loading="detail.loading.value" :error="detail.error.value" @retry="openItem(drawer.id)" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { CircleCheck, Clock, Coin, EditPen, Promotion } from '@element-plus/icons-vue'
import OverviewMetricCard from '@/components/OverviewMetricCard.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import DevlogItemDrawer from './DevlogItemDrawer.vue'
import { useDevlogBoard } from './composables/useDevlogBoard.js'
import { AGENT_LABELS, COLUMN_LABELS, STATUS_LABELS, SUB_TONE, TYPE_META, preconditionTags, readinessLabel, shortSha } from './devlogPresentation.js'

const { filters, tab, focus, showStale, visibleColumns, staleColumns, filteredPending, drawer, period, summary, health, pending, detail, stale, syncState, pendingReleaseCount, openItem, pickKpi, refresh, refreshing } = useDevlogBoard()
const kpis = computed(() => summary.data.value.kpis || {})
const sourceNames = { git: '本地 Git', fetch: '远端 Git', releases: '发布账本' }
const columns = visibleColumns
const ledger = computed(() => health.data.value?.ledger_latest)
const tagType = tone => ({ gold: 'warning', info: 'primary', danger: 'danger', violet: 'info', neutral: 'info', warning: 'warning', success: 'success' }[tone] || 'info')
</script>

<style scoped>
.devlog-page { position: relative; min-width: 0; }
.devlog-aurora { inset: -24px -28px; }
.devlog-head, .devlog-stale, .devlog-sources, .devlog-bar, .devlog-data { position: relative; z-index: 1; }
.devlog-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.devlog-head__title { margin: 0; font: 700 17px/1.3 Outfit, sans-serif; }
.devlog-sync { margin-left: auto; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary); }
.devlog-sync__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--tag-success-solid); }
.devlog-sync__dot.is-warn { background: var(--tag-warning-solid); }
.devlog-sync__dot.is-error { background: var(--tag-danger-solid); }
.devlog-sources { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; font-size: 12px; color: var(--text-secondary); overflow-wrap: anywhere; }
.devlog-stale { margin-bottom: 14px; }
.devlog-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 16px; }
.devlog-bar .filter-w-sm { width: 148px; }
.devlog-bar .filter-w-lg { width: 280px; }
.devlog-bar__range { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.is-stale .devlog-data { filter: grayscale(0.85); opacity: 0.55; }
.devlog-kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 8px; }
.devlog-board { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; align-items: start; }
.devlog-col { min-width: 0; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.devlog-col__h { display: flex; align-items: center; gap: 8px; margin: 0 0 2px; font: 700 15px/1.3 Outfit, sans-serif; }
.devlog-col__bar { width: 4px; height: 16px; border-radius: 2px; }
.devlog-col__bar.is-dev { background: var(--tag-info-solid); }
.devlog-col__bar.is-committed { background: var(--tag-warning-solid); }
.devlog-col__bar.is-released { background: var(--tag-success-solid); }
.devlog-col__n { font-size: 12px; font-weight: 500; color: var(--text-muted); }
.devlog-card { display: flex; flex-direction: column; gap: 6px; width: 100%; text-align: left; padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--border-color); background: var(--button-surface); cursor: pointer;
  transition: transform 200ms cubic-bezier(0.23, 1, 0.32, 1); }
.devlog-card:active:not(:focus-visible) { transform: scale(0.98); transition-duration: 140ms; }
@media (hover: hover) and (pointer: fine) { .devlog-card:hover { transform: translateY(-2px); box-shadow: var(--dash-glass-shadow); } }
.devlog-card:focus-visible, .devlog-link:focus-visible { outline: 2px solid var(--button-primary); outline-offset: 2px; }
.devlog-card__tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.devlog-card__title { overflow-wrap: anywhere; font-size: 14px; font-weight: 600; line-height: 1.4; color: var(--text-primary); }
.devlog-card__meta, .devlog-muted { font-size: 12px; color: var(--text-muted); }
.devlog-empty { margin: 0; padding: 24px 8px; text-align: center; font-size: 13px; color: var(--text-muted); }
.devlog-day { padding: 14px 18px; margin-bottom: 12px; }
.devlog-day__h { display: flex; gap: 10px; align-items: baseline; margin: 0 0 8px; font: 700 15px/1.3 Outfit, sans-serif; }
.devlog-day__h span { font: 500 12px/1 'DM Sans', sans-serif; color: var(--text-muted); }
.devlog-day__list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.devlog-day__list li { display: flex; gap: 8px; align-items: center; font-size: 13px; }
.devlog-day__to { width: 52px; flex: none; font-size: 12px; color: var(--text-secondary); }
.devlog-link { border: 0; background: none; padding: 0; text-align: left; font-weight: 600; color: var(--button-primary-text); cursor: pointer; }
@media (hover: hover) and (pointer: fine) { .devlog-link:hover { text-decoration: underline; } }
.devlog-table { padding: 4px; min-width: 0; }
.devlog-day__list li { flex-wrap: wrap; }
.devlog-link { overflow-wrap: anywhere; }
.devlog-ok { color: var(--tag-success-text); font-weight: 600; }
.devlog-warn { color: var(--tag-warning-text); font-weight: 600; }
@media (max-width: 1180px) { .devlog-kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 900px) { .devlog-board { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 768px) {
  .devlog-bar > * { max-width: 100%; }
  .devlog-bar .filter-w-lg { width: 100%; min-width: 0; }
  .devlog-bar .filter-w-sm { flex: 1 1 135px; min-width: 0; }
  .devlog-sync { line-height: 1.6; }
  .devlog-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .devlog-kpis > :last-child { grid-column: span 2; }
}
@media (prefers-reduced-motion: reduce) { .devlog-card, .devlog-card:active { transition: none; transform: none; } }
</style>
