<!--
  产品风向标：按 B1 / B3 / 50%幅度 分标签页，每个大类下看 30/60/90/180 天的销量排行与涨跌，
  维度可选全部 SKU、颜色、尺寸、规格或自定义组合；大类级 AI 分析手动触发。
  点开某一行看 12 个月走势、其余维度（支持下钻）和国家分布，再跳到决策台找「买过的我的客户」。
  需求：docs/requirements/2026-11-18-product-sales-radar/README.md（第 8 节）
-->
<template>
  <div class="radar-page">
    <div class="radar-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="radar-head">
      <div class="radar-period">
        <span v-if="radar" class="period-text">{{ shortDate(radar.window.current[0]) }} ~ {{ shortDate(radar.window.current[1]) }} · 对比前 {{ radar.window.days }} 天</span>
        <span v-else class="period-text">按近 {{ filters.window }} 天对比前 {{ filters.window }} 天</span>
        <el-popover placement="bottom-start" :width="340" trigger="click">
          <template #reference>
            <button type="button" class="rule-trigger" aria-label="查看统计口径说明"><el-icon><QuestionFilled /></el-icon> 口径说明</button>
          </template>
          <div class="rule-popover">
            <p><strong>大类与规格：</strong>按型号前缀分 B1 / B3 / 50%幅度，规格为去掉前缀后的型号。</p>
            <p><strong>颜色与尺寸：</strong>仅统计能确切识别属性的订单行；旧产品库时期（2026 年 3 月前）仅含型号，只在「规格」视角计入。</p>
            <p v-if="radar?.unclassified?.kg"><strong>未归类：</strong>本期另有 {{ kg(radar.unclassified.kg) }}（配件、费用等）不属三大类，未计入。</p>
            <p v-if="radar"><strong>可信度：</strong>两期确切重量占比均 ≥ {{ percent(radar.credibility.threshold) }} 才判为可比（本期 {{ percent(radar.credibility.current.credible_share) }} / 上期 {{ percent(radar.credibility.previous.credible_share) }}）。</p>
          </div>
        </el-popover>
      </div>

      <div class="radar-controls">
        <SegmentedControl v-model="filters.window" :options="WINDOW_OPTIONS" aria-label="统计时间窗口" @change="onScopeSwitch" />
        <el-select v-if="canReadAll" v-model="filters.scopeKey" clearable filterable placeholder="份额：我" class="radar-scope-select" @change="() => load('scope')">
          <el-option-group v-if="scopes.teams.length" label="按团队">
            <el-option v-for="t in scopes.teams" :key="`team:${t}`" :label="`${t} 团队`" :value="`team:${t}`" />
          </el-option-group>
          <el-option-group v-if="scopes.users.length" label="按业务员">
            <el-option v-for="u in scopes.users" :key="`user:${u.user_id}`" :label="u.team ? `${u.name}（${u.team}）` : u.name" :value="`user:${u.user_id}`" />
          </el-option-group>
        </el-select>
      </div>
    </header>

    <el-tabs v-model="filters.grade" class="grade-tabs" @tab-change="onScopeSwitch">
      <el-tab-pane v-for="g in GRADE_OPTIONS" :key="g.value" :name="g.value">
        <template #label>
          <span class="grade-label">{{ g.label }}<small v-if="tabKg(g.value) !== null" :class="{ 'is-stale': tabs.days !== filters.window }">{{ kg(tabKg(g.value)) }}</small></span>
        </template>
      </el-tab-pane>
    </el-tabs>

    <ListPageStatus v-if="error" :error="error" :loading="loading" :has-data="!!radar" :paged="false" @retry="() => load('scope')" />

    <div v-if="loading && !radar" class="radar-skeleton" aria-busy="true" aria-label="正在加载产品风向标">
      <div class="sk-kpis"><div v-for="n in 4" :key="n" class="radar-card sk-kpi"><span class="sk-bar sk-w-40" /><span class="sk-bar sk-h-lg sk-w-70" /></div></div>
      <div class="radar-card sk-strip"><span class="sk-bar sk-w-50" /></div>
      <div class="radar-grid"><div v-for="n in 2" :key="n" class="radar-card sk-list"><span class="sk-bar sk-w-40" /><span v-for="r in 5" :key="r" class="sk-bar" /></div></div>
    </div>

    <div v-if="radar" class="radar-body" :class="{ 'is-scope-busy': scopeLoading }" :aria-busy="scopeLoading">
      <div class="collapse-shell" :class="{ 'is-open': !comparable }">
        <div class="collapse-inner">
          <div class="ref-banner" role="status">
            <el-icon class="ref-icon"><WarningFilled /></el-icon>
            <span>上期含旧库估算数据，涨跌仅供参考</span>
            <el-popover placement="bottom-start" :width="280" trigger="click">
              <template #reference><button type="button" class="ref-detail-btn">查看占比</button></template>
              <p class="ref-pop-text">本期确切重量占比 <strong>{{ percent(radar.credibility.current.credible_share) }}</strong>，上期 <strong>{{ percent(radar.credibility.previous.credible_share) }}</strong>（可信线 {{ percent(radar.credibility.threshold) }}）。</p>
            </el-popover>
          </div>
        </div>
      </div>

      <section class="radar-summary" :class="{ 'is-three': !showShareCard }" :aria-label="`${radar.grade_label} 总览`">
        <div class="summary-card"><span class="summary-label">本期销量</span><strong class="summary-value">{{ kg(radar.summary.kg) }}<small>{{ count(radar.summary.quantity) }} 件</small></strong></div>
        <div class="summary-card"><span class="summary-label">上期销量</span><strong class="summary-value">{{ kg(radar.summary.prev_kg) }}</strong></div>
        <div class="summary-card">
          <span class="summary-label">变化<em v-if="!comparable" class="ref-pill">参考</em></span>
          <strong class="summary-value" :class="deltaClass(radar.summary.kg - radar.summary.prev_kg)">{{ deltaText(radar.summary.kg - radar.summary.prev_kg) }}<small>{{ growthText(summaryRow) }}</small></strong>
        </div>
        <div v-if="showShareCard" class="summary-card">
          <span class="summary-label">{{ shareLabel }}的销量</span>
          <strong v-if="radar.summary.my_kg !== null" class="summary-value">{{ kg(radar.summary.my_kg) }}<small>占 {{ percent(radar.summary.my_share) }}</small></strong>
          <strong v-else class="summary-value is-muted">—<small>右上可切换团队或业务员</small></strong>
        </div>
      </section>

      <section class="radar-card dim-card" aria-label="查看维度">
        <div class="dim-bar">
          <span class="dim-title">按什么看</span>
          <SegmentedControl v-model="filters.view" :options="VIEW_OPTIONS" size="sm" aria-label="查看维度" @change="() => load('view')" />
          <Transition name="chip-fade">
            <el-checkbox-group v-if="filters.view === 'custom'" v-model="filters.customDims" :min="1" size="small" class="custom-dims" @change="onCustomDimsChange">
              <el-checkbox v-for="d in DIMENSIONS" :key="d.value" :value="d.value">{{ d.label }}</el-checkbox>
            </el-checkbox-group>
          </Transition>
          <el-popover v-if="radar.summary.excluded_quantity" placement="bottom-end" :width="280" trigger="click">
            <template #reference>
              <button type="button" class="exclude-chip">{{ count(radar.summary.excluded_quantity) }} 件未计入 <el-icon><QuestionFilled /></el-icon></button>
            </template>
            <p class="ref-pop-text">
              <template v-if="radar.dims.includes('color') || radar.dims.includes('size')">含颜色或尺寸的视角仅统计可确切识别这两项的订单行，本期有 {{ count(radar.summary.excluded_quantity) }} 件缺属性或克重未计入。</template>
              <template v-else>本期有 {{ count(radar.summary.excluded_quantity) }} 件缺克重或型号不含规格，未计入。</template>
            </p>
          </el-popover>
        </div>
      </section>

      <RadarInsightCard
        :insight="insight"
        :grade-label="radar.grade_label"
        :window-days="radar.window.days"
        :html="insightHtml"
        :content-key="insightContentKey"
        :stale="insightStale"
        :in-cooldown="inCooldown"
        :cooldown-seconds="cooldownRemainingSeconds"
        :disabled="loading"
        @explain="explain"
      />

      <div class="radar-data-zone" :class="{ 'is-view-busy': viewLoading }" :aria-busy="viewLoading">
        <div class="radar-grid">
          <section v-for="panel in moverPanels" :key="panel.key" class="radar-card">
            <h3>{{ dimTitle }} · {{ panel.title }}</h3>
            <ol v-if="panel.rows.length" class="mover-list">
              <li v-for="row in panel.rows" :key="row.key">
                <button type="button" class="mover-row" @click="openItem(row, panel.rows)">
                  <span class="mover-key">{{ row.key }}</span>
                  <span class="mover-meta">
                    <span class="mover-kg">{{ kg(row.kg) }}</span>
                    <span class="mover-delta" :class="deltaClass(row.delta_kg)">{{ deltaText(row.delta_kg) }} · {{ growthText(row) }}</span>
                  </span>
                  <el-icon class="row-chevron"><ArrowRight /></el-icon>
                </button>
              </li>
            </ol>
            <p v-else class="mover-empty">{{ panel.empty }}</p>
          </section>
        </div>

        <section class="radar-card lg-table-panel">
          <div class="table-head">
            <div class="table-title-group">
              <h3>{{ dimTitle }} · 销量排行 <small>共 {{ radar.summary.group_count }} 项有销量</small></h3>
              <div class="quick-pills" role="group" aria-label="快捷筛选">
                <button
                  v-for="qf in visibleQuickFilters"
                  :key="qf.value"
                  type="button"
                  class="quick-pill"
                  :class="{ 'is-active': table.quickFilter === qf.value }"
                  :aria-pressed="table.quickFilter === qf.value"
                  @click="setQuickFilter(qf.value)"
                >
                  {{ qf.label }}<small v-if="qf.value !== 'all'">{{ quickFilterCounts[qf.value] }}</small>
                </button>
              </div>
            </div>
            <el-input v-model="table.keyword" clearable placeholder="搜索规格 / 颜色 / 尺寸" class="radar-search" @input="table.page = 1" />
          </div>

          <el-table
            v-sticky-scrollbar
            :data="pagedRows"
            row-key="key"
            border
            class="list-table rank-table"
            row-class-name="rank-row"
            :default-sort="{ prop: 'kg', order: 'descending' }"
            @sort-change="onSort"
            @row-click="row => openItem(row, filteredRows)"
          >
            <template #empty>
              <div class="table-empty">
                <p>{{ hasTableFilter ? '当前筛选条件下没有匹配项' : '本期暂无可展示的销量数据' }}</p>
                <GlassButton v-if="hasTableFilter" @click="resetTableFilters">清除筛选</GlassButton>
              </div>
            </template>

            <el-table-column prop="rank" label="排名" min-width="96" sortable="custom">
              <template #default="{ row }"><span class="rank">{{ row.rank ?? '—' }}</span><small :class="['rank-move', rankClass(row)]">{{ rankMove(row) }}</small></template>
            </el-table-column>
            <el-table-column
              v-for="(d, idx) in radar.dims"
              :key="d"
              :prop="`dim:${d}`"
              :label="radar.dim_labels[d]"
              :min-width="d === 'spec' ? 200 : d === 'color' ? 140 : 88"
              :fixed="idx === 0 && isNarrow ? 'left' : false"
              sortable="custom"
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.values[d] }}</template>
            </el-table-column>
            <el-table-column prop="kg" label="本期 kg" min-width="116" align="right" sortable="custom"><template #default="{ row }">{{ num(row.kg, 1) }}</template></el-table-column>
            <el-table-column prop="quantity" label="件数" min-width="92" align="right" sortable="custom"><template #default="{ row }">{{ count(row.quantity) }}</template></el-table-column>
            <el-table-column prop="prev_kg" label="上期 kg" min-width="108" align="right" sortable="custom"><template #default="{ row }">{{ num(row.prev_kg, 1) }}</template></el-table-column>
            <el-table-column prop="delta_kg" label="变化" min-width="136" align="right" sortable="custom"><template #default="{ row }"><span :class="deltaClass(row.delta_kg)">{{ deltaText(row.delta_kg) }}</span></template></el-table-column>
            <el-table-column prop="growth" label="增长" min-width="96" align="right" sortable="custom"><template #default="{ row }"><span :class="deltaClass(row.delta_kg)">{{ growthText(row) }}</span></template></el-table-column>
            <el-table-column v-if="radar.summary.my_kg !== null" prop="my_share" :label="`${radar.share_scope.label}占`" min-width="92" align="right" sortable="custom"><template #default="{ row }">{{ row.my_share === null ? '—' : percent(row.my_share) }}</template></el-table-column>
            <el-table-column :sortable="false" min-width="40" align="right"><template #default><el-icon class="table-row-arrow"><ArrowRight /></el-icon></template></el-table-column>
          </el-table>

          <el-pagination v-if="filteredRows.length > 20" v-model:current-page="table.page" v-model:page-size="table.pageSize"
            :page-sizes="[20, 50, 100]" :total="filteredRows.length" layout="total, sizes, prev, pager, next" class="rank-pager" @size-change="table.page = 1" />
        </section>
      </div>
    </div>

    <RadarDetailDrawer
      :detail="detail"
      :title="detailTitle"
      :customer-link="customerLink"
      :can-see-customers="canSeeCustomers"
      :too-many-models="tooManyModels"
      :model-count="linkModels.length"
      :max-link-models="MAX_LINK_MODELS"
      @update:visible="detail.visible = $event"
      @retry="openItem({ values: detail.values })"
      @drill-down="drillDown"
      @drill-back="drillBack"
      @step="stepDetail"
      @go-customers="goCustomers"
      @pivot-spec="pivotToSpecFilter"
    />
  </div>
</template>

<script setup>
import { ArrowRight, QuestionFilled, WarningFilled } from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { formatMoney } from '@/utils/money'
import RadarDetailDrawer from './components/RadarDetailDrawer.vue'
import RadarInsightCard from './components/RadarInsightCard.vue'
import SegmentedControl from './components/SegmentedControl.vue'
import {
  DIMENSIONS, GRADE_OPTIONS, QUICK_FILTERS, VIEW_OPTIONS, WINDOW_OPTIONS, isNewAppearance, useProductRadar,
} from './composables/useProductRadar'

const {
  filters, radar, tabs, canReadAll, loading, scopeLoading, viewLoading, error, scopes, comparable,
  table, quickFilterCounts, filteredRows, pagedRows, onSort, resetTableFilters, onCustomDimsChange,
  detail, insight, inCooldown, cooldownRemainingSeconds,
  load, loadScopes, openItem, drillDown, drillBack, stepDetail, pivotToSpecFilter, explain, switchScope,
} = useProductRadar()
const router = useRouter()
const auth = useAuthStore()

const narrowQuery = globalThis.matchMedia?.('(max-width: 768px)')
const isNarrow = ref(narrowQuery?.matches ?? false)
const onNarrowChange = event => { isNarrow.value = event.matches }

const num = (value, digits) => formatMoney(value, digits)
const kg = value => (value === null || value === undefined ? '—' : `${formatMoney(value, 1)} kg`)
const count = value => formatMoney(value, 0)
const percent = value => (value === null || value === undefined ? '—' : `${formatMoney((Number(value) || 0) * 100, 0)}%`)
const shortDate = value => (value ? String(value).slice(5) : '')
const deltaText = value => `${value > 0 ? '+' : ''}${formatMoney(value, 1)} kg`
const trendClass = value => (value > 0 ? 'is-up' : value < 0 ? 'is-down' : '')
const deltaClass = value => (comparable.value ? trendClass(value) : 'is-ref')
const growthText = row => {
  if (row.growth === null || row.growth === undefined) return isNewAppearance(row) ? '新出现' : '—'
  return `${row.growth > 0 ? '+' : ''}${formatMoney(row.growth * 100, 0)}%`
}
const growthOf = summary => (summary.prev_kg > 0 ? (summary.kg - summary.prev_kg) / summary.prev_kg : null)
const summaryRow = computed(() => {
  const s = radar.value?.summary
  return s ? { kg: s.kg, prev_kg: s.prev_kg, growth: growthOf(s) } : { kg: 0, prev_kg: 0, growth: null }
})
const rankMove = row => {
  if (!row.rank) return '本期无'
  if (!row.prev_rank) return '新上榜'
  const diff = row.prev_rank - row.rank
  return diff > 0 ? `↑${diff}` : diff < 0 ? `↓${-diff}` : '持平'
}
const rankClass = row => (row.rank && row.prev_rank && comparable.value ? trendClass(row.prev_rank - row.rank) : '')

const showShareCard = computed(() => radar.value?.summary?.my_kg !== null || canReadAll.value)
const shareLabel = computed(() => (radar.value?.share_scope?.mode === 'none' ? '我' : radar.value?.share_scope?.label || '我'))
const tabKg = grade => tabs.value.items.find(tab => tab.grade === grade)?.kg ?? null
const dimTitle = computed(() => (radar.value ? radar.value.dims.map(d => radar.value.dim_labels[d]).join(' × ') : ''))
const detailTitle = computed(() => (detail.values ? Object.values(detail.values).join(' · ') : '详情'))

const insightHtml = computed(() => DOMPurify.sanitize(marked.parse(insight.data?.content || '', { gfm: true, breaks: true })))
const insightContentKey = computed(() => `${radar.value?.grade}-${radar.value?.window?.days}-${insight.data?.created_at || ''}`)
const insightStale = computed(() => {
  const saved = insight.data?.summary_kg
  const current = radar.value?.summary?.kg
  return Boolean(insight.data?.reused && saved !== null && saved !== undefined && current !== undefined && Math.abs(saved - current) >= 0.05)
})

const moverPanels = computed(() => [
  { key: 'risers', title: '涨得最多', rows: radar.value?.movers?.risers || [], empty: '本期没有上涨的项' },
  { key: 'fallers', title: '跌得最多', rows: radar.value?.movers?.fallers || [], empty: '本期没有下跌的项' },
])
const visibleQuickFilters = computed(() => QUICK_FILTERS.filter(f => f.value !== 'opportunity' || radar.value?.summary?.my_kg !== null))
const hasTableFilter = computed(() => Boolean(table.keyword.trim() || table.quickFilter !== 'all'))
function setQuickFilter(value) {
  table.quickFilter = table.quickFilter === value && value !== 'all' ? 'all' : value
  table.page = 1
}

const canSeeCustomers = computed(() => auth.hasPermission('order_intelligence:read'))
// 深链只带决策台能精确匹配的值：型号（本行实际出现的型号）和颜色。决策台不按尺寸筛，客户里会包含其他尺寸
// 型号必须带上，才能把客户限定在当前大类；决策台最多接收 20 个型号，超出时不给不完整的链接
const MAX_LINK_MODELS = 20
const linkModels = computed(() => detail.data?.models || [])
const tooManyModels = computed(() => linkModels.value.length > MAX_LINK_MODELS)
const customerLink = computed(() => {
  if (!detail.data || !canSeeCustomers.value || !linkModels.value.length || tooManyModels.value) return null
  const color = detail.data.values.color
  return { path: '/invoice/order-intelligence', query: { tab: 'customers', ...(color ? { colors: color } : {}), models: linkModels.value } }
})
const goCustomers = () => customerLink.value && router.push(customerLink.value)

function onScopeSwitch() {
  switchScope()
  load('scope')
  if (canReadAll.value) loadScopes()
}

onMounted(async () => {
  narrowQuery?.addEventListener('change', onNarrowChange)
  await load('scope')
  if (radar.value?.share_scope?.can_read_all) loadScopes()
})

onBeforeUnmount(() => narrowQuery?.removeEventListener('change', onNarrowChange))
</script>

<style scoped>
.radar-page { position: relative; display: flex; flex-direction: column; gap: 14px; }
.radar-aurora { inset: -24px -28px; }
.radar-head, .grade-tabs, .radar-skeleton, .radar-body { position: relative; z-index: 1; }

/* 换大类/窗口淡化整区；只换视角时仅淡化下方数据区，延迟 120ms 防快请求闪烁 */
.radar-body, .radar-data-zone { display: flex; flex-direction: column; gap: 14px; transition: opacity var(--motion-fast) var(--ease-out-strong); }
.radar-body.is-scope-busy, .radar-data-zone.is-view-busy { opacity: 0.55; transition-delay: 120ms; pointer-events: none; }

.radar-head { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; justify-content: space-between; }
.radar-period { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.period-text { color: var(--text-secondary); font-size: 13px; font-variant-numeric: tabular-nums; }
.rule-trigger, .ref-detail-btn, .exclude-chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--text-secondary); font-size: 12px; cursor: pointer; transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease; }
@media (hover: hover) and (pointer: fine) {
  .rule-trigger:hover, .ref-detail-btn:hover, .exclude-chip:hover { color: var(--color-primary-text); background: var(--color-primary-light); }
}
.rule-trigger:focus-visible, .ref-detail-btn:focus-visible, .exclude-chip:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.rule-popover p { margin: 0 0 8px; font-size: 12px; line-height: 1.6; color: var(--text-secondary); }
.rule-popover p:last-child { margin-bottom: 0; }
.rule-popover strong { color: var(--text-primary); }
.ref-pop-text { margin: 0; font-size: 12px; line-height: 1.6; color: var(--text-secondary); }

.radar-controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.radar-scope-select { width: 176px; }

.grade-tabs { margin-bottom: -14px; }
.grade-label { display: inline-flex; align-items: baseline; font-family: var(--font-display); }
.grade-label small { margin-left: 8px; color: var(--text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; transition: opacity var(--motion-fast) ease; }
.grade-label small.is-stale { opacity: 0.45; }

.collapse-shell { display: grid; grid-template-rows: 0fr; opacity: 0; transition: grid-template-rows var(--motion-fast) var(--ease-out-strong), opacity var(--motion-fast) var(--ease-out-strong); }
.collapse-shell.is-open { grid-template-rows: 1fr; opacity: 1; transition: grid-template-rows var(--motion-base) var(--ease-out-strong), opacity var(--motion-base) var(--ease-out-strong); }
.collapse-inner { overflow: hidden; min-height: 0; }

.ref-banner { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 12px; border: 1px solid var(--tag-warning-border); border-radius: 10px; background: var(--tag-warning-bg); color: var(--tag-warning-text); font-size: 13px; }
.ref-icon { font-size: 15px; flex-shrink: 0; }
.ref-detail-btn { margin-left: auto; color: var(--tag-warning-text); font-weight: 600; }

.radar-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.radar-summary.is-three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.summary-card, .radar-card { padding: 14px 16px; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); }
.summary-label { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 13px; }
.ref-pill { padding: 1px 6px; border-radius: 4px; background: var(--tag-warning-bg); color: var(--tag-warning-text); font-style: normal; font-size: 11px; font-weight: 600; }
.summary-value { display: block; margin-top: 6px; font-family: var(--font-display); font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.2; }
.summary-value small { margin-left: 8px; color: var(--text-secondary); font-family: var(--font-body); font-size: 12px; font-weight: 400; }
.is-up { color: var(--color-success-text); }
.is-down { color: var(--color-danger); }
.is-ref, .is-muted { color: var(--text-secondary); }

.dim-card { padding: 10px 16px; }
.dim-bar { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
.dim-title { font-family: var(--font-display); font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.custom-dims { display: inline-flex; align-items: center; }
.exclude-chip { margin-left: auto; border-color: var(--border-color); background: var(--card-bg); }
.chip-fade-enter-active { transition: opacity var(--motion-base) var(--ease-out-strong), transform var(--motion-base) var(--ease-out-strong); }
.chip-fade-leave-active { transition: opacity var(--motion-fast) var(--ease-out-strong), transform var(--motion-fast) var(--ease-out-strong); }
.chip-fade-enter-from, .chip-fade-leave-to { opacity: 0; transform: translateX(-6px); }

.radar-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.radar-card h3 { margin: 0 0 8px; font-family: var(--font-display); font-size: 15px; font-weight: 700; }
.radar-card h3 small { margin-left: 6px; color: var(--text-secondary); font-family: var(--font-body); font-size: 12px; font-weight: 400; font-variant-numeric: tabular-nums; }

.mover-list { margin: 0; padding: 0; list-style: none; }
.mover-row { display: grid; grid-template-columns: minmax(0, 1fr) auto 14px; align-items: center; gap: 8px; width: 100%; padding: 8px; border: 0; border-bottom: 1px solid var(--border-color); border-radius: 6px; background: transparent; color: inherit; font: inherit; font-size: 13px; text-align: left; cursor: pointer; font-variant-numeric: tabular-nums; transition: background-color var(--motion-fast) ease; }
.mover-list li:last-child .mover-row { border-bottom-color: transparent; }
@media (hover: hover) and (pointer: fine) {
  .mover-row:hover { background: var(--color-gold-soft); }
  .mover-row:hover .row-chevron { color: var(--color-primary-text); transform: translateX(2px); }
}
.mover-row:active { background: var(--color-warning-bg); }
.mover-row:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
.mover-key { overflow: hidden; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.mover-meta { display: inline-flex; align-items: baseline; gap: 10px; white-space: nowrap; }
.mover-kg { color: var(--text-secondary); }
.mover-delta { font-weight: 500; }
.row-chevron, .table-row-arrow { color: var(--text-muted); font-size: 12px; transition: transform var(--motion-press) var(--ease-out-strong), color var(--motion-fast) ease; }
.mover-empty { margin: 8px 0; color: var(--text-secondary); font-size: 13px; }

.table-head { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.table-title-group { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; }
.table-title-group h3 { margin: 0; }
.quick-pills { display: inline-flex; flex-wrap: wrap; gap: 6px; }
.quick-pill { display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 10px; border: 1px solid var(--border-color); border-radius: 999px; background: var(--card-bg); color: var(--text-secondary); font-size: 12px; cursor: pointer; font-variant-numeric: tabular-nums; transition: background-color var(--motion-fast) ease, border-color var(--motion-fast) ease, color var(--motion-fast) ease, transform var(--motion-press) var(--ease-out-strong); }
.quick-pill small { color: var(--text-muted); font-size: 11px; }
@media (hover: hover) and (pointer: fine) {
  .quick-pill:hover { border-color: var(--color-primary); color: var(--color-primary-text); }
}
.quick-pill:active { transform: scale(0.97); }
.quick-pill.is-active { border-color: var(--tag-gold-border); background: var(--tag-gold-bg); color: var(--tag-gold-text); font-weight: 600; }
.quick-pill.is-active small { color: var(--tag-gold-text); }
.quick-pill:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }

.radar-search { width: 220px; }
.rank-table { width: 100%; font-variant-numeric: tabular-nums; }
.rank-table :deep(.rank-row) { cursor: pointer; }
.rank-table :deep(.rank-row:active > td) { background: var(--color-warning-bg) !important; }
@media (hover: hover) and (pointer: fine) {
  .rank-table :deep(.rank-row:hover .table-row-arrow) { color: var(--color-primary-text); transform: translateX(2px); }
}
.rank { font-weight: 600; }
.rank-move { margin-left: 6px; color: var(--text-secondary); font-size: 12px; }
.rank-move.is-up { color: var(--color-success-text); }
.rank-move.is-down { color: var(--color-danger); }
.rank-pager { justify-content: flex-end; margin-top: 12px; }
.table-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 24px 0; color: var(--text-secondary); font-size: 13px; }
.table-empty p { margin: 0; }

.radar-skeleton { display: flex; flex-direction: column; gap: 14px; }
.sk-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.sk-kpi, .sk-list { display: flex; flex-direction: column; gap: 10px; }
.sk-strip { height: 48px; display: flex; align-items: center; }
.sk-bar { display: block; height: 14px; width: 100%; border-radius: 6px; background: var(--border-color); opacity: 0.5; animation: radar-pulse 1.4s ease-in-out infinite; }
.sk-h-lg { height: 24px; }
.sk-w-40 { width: 40%; }
.sk-w-50 { width: 50%; }
.sk-w-70 { width: 70%; }
@keyframes radar-pulse { 0%, 100% { opacity: 0.35; } 50% { opacity: 0.7; } }

@media (max-width: 1080px) {
  .radar-summary, .radar-summary.is-three, .sk-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .radar-grid { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .radar-aurora { inset: 0; }
  .summary-value { font-size: 18px; }
  .summary-value small { display: block; margin-left: 0; margin-top: 2px; }
  .radar-scope-select, .radar-search { width: 100%; }
  .mover-row { grid-template-columns: minmax(0, 1fr) 14px; row-gap: 2px; }
  .mover-meta { grid-column: 1; font-size: 12px; }
  .row-chevron { grid-column: 2; grid-row: 1 / span 2; }
  .exclude-chip { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .radar-body.is-scope-busy, .radar-data-zone.is-view-busy { transition-delay: 0ms; }
  .sk-bar { animation: none; opacity: 0.45; }
  .quick-pill:active { transform: none; }
}
</style>
