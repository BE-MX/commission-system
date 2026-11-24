<!--
  产品风向标：按 B1 / B3 / 50%幅度 分标签页，每个大类下看 30/60/90/180 天的销量排行与涨跌，
  维度可选全部 SKU、颜色、尺寸、规格或自定义组合；大类级 AI 分析手动触发。
  点开某一行看 12 个月走势、其余维度和国家分布，再跳到决策台找「买过的我的客户」。
  需求：docs/requirements/2026-11-18-product-sales-radar/README.md（第 8 节）
-->
<template>
  <div class="radar-page">
    <header class="radar-head">
      <div>
        <h2>产品风向标</h2>
        <p v-if="radar">{{ radar.window.current[0] }} 至 {{ radar.window.current[1] }}，对比前 {{ radar.window.days }} 天 · 重量 kg</p>
      </div>
      <div class="radar-controls">
        <el-radio-group v-model="filters.window" @change="onScopeSwitch">
          <el-radio-button v-for="opt in WINDOW_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</el-radio-button>
        </el-radio-group>
        <template v-if="canReadAll">
          <el-select v-model="filters.team" clearable filterable placeholder="份额：我" class="radar-select-sm" @change="() => { filters.userId = ''; load() }">
            <el-option v-for="t in scopes.teams" :key="t" :label="`${t} 团队`" :value="t" />
          </el-select>
          <el-select v-model="filters.userId" clearable filterable placeholder="或选业务员" class="radar-select-sm" @change="load">
            <el-option v-for="u in scopedUsers" :key="u.user_id" :label="u.name" :value="u.user_id" />
          </el-select>
        </template>
      </div>
    </header>

    <el-tabs v-model="filters.grade" class="grade-tabs" @tab-change="onScopeSwitch">
      <el-tab-pane v-for="g in GRADE_OPTIONS" :key="g.value" :name="g.value">
        <template #label>
          <span class="grade-label">{{ g.label }}<small v-if="tabKg(g.value) !== null">{{ kg(tabKg(g.value)) }}</small></span>
        </template>
      </el-tab-pane>
    </el-tabs>

    <ListPageStatus :error="error" :loading="loading && !radar" :has-data="!!radar" @retry="load" />

    <template v-if="radar">
      <el-alert v-if="!comparable" type="warning" :closable="false" show-icon class="radar-alert"
        :title="`对比期里有估算数据（本期确切 ${percent(radar.credibility.current.credible_share)}，上期 ${percent(radar.credibility.previous.credible_share)}，可信线 ${percent(radar.credibility.threshold)}），涨跌只作参考`" />

      <section class="radar-summary" :aria-label="`${radar.grade_label} 总览`">
        <div><span>本期销量</span><strong>{{ kg(radar.summary.kg) }}<small>{{ count(radar.summary.quantity) }} 件</small></strong></div>
        <div><span>上期销量</span><strong>{{ kg(radar.summary.prev_kg) }}</strong></div>
        <div><span>变化</span><strong :class="trendClass(radar.summary.kg - radar.summary.prev_kg)">{{ deltaText(radar.summary.kg - radar.summary.prev_kg) }}<small>{{ growthText({ growth: growthOf(radar.summary) }) }}</small></strong></div>
        <div>
          <span>{{ radar.share_scope.mode === 'none' ? '我' : radar.share_scope.label }}的销量</span>
          <strong v-if="radar.summary.my_kg !== null">{{ kg(radar.summary.my_kg) }}<small>占 {{ percent(radar.summary.my_share) }}</small></strong>
          <strong v-else class="is-muted">—<small>账号未绑定 OKKI 业务员</small></strong>
        </div>
      </section>

      <section class="radar-card insight" :aria-busy="insight.loading">
        <div class="insight-head">
          <div>
            <h3>{{ radar.grade_label }} · AI 分析</h3>
            <p class="insight-meta">
              <template v-if="insight.data">{{ insight.data.source === 'ai' ? 'AI 生成' : 'AI 暂不可用，规则摘要' }} · {{ insight.data.created_at }}<template v-if="insight.data.reused">（基于当时的数据<template v-if="insight.data.summary_kg !== null && insight.data.summary_kg !== undefined && Math.abs(insight.data.summary_kg - radar.summary.kg) >= 0.05">，之后销量已变为 {{ kg(radar.summary.kg) }}，可重新分析</template>）</template><template v-if="!insight.data.comparable"> · 对比期含估算</template><template v-if="insight.data.cooldown_until"> · 刚生成过，{{ insight.data.cooldown_until.slice(11, 16) }} 后可重新分析</template><template v-if="insight.data.refresh_failed"> · 本次重新分析失败，仍显示上次结果</template></template>
              <template v-else>汇总近 {{ radar.window.days }} 天颜色、尺寸、规格和 SKU 的排行与涨跌，给出规律和趋势预测。数字只来自本页数据，全公司口径。</template>
            </p>
          </div>
          <GlassButton variant="primary" left-icon="MagicStick" :loading="insight.loading" @click="explain">{{ insight.data ? '重新分析' : '生成 AI 分析' }}</GlassButton>
        </div>
        <el-alert v-if="insight.error" type="error" :title="insight.error" :closable="false" show-icon />
        <p v-if="insight.loading" class="insight-meta">正在分析，通常需要 10~30 秒…</p>
        <!-- v-html 内容已经 DOMPurify 清洗 -->
        <div v-else-if="insight.data" class="insight-body" v-html="insightHtml" />
      </section>

      <section class="radar-card" aria-label="查看维度">
        <div class="dim-bar">
          <span class="dim-title">按什么看</span>
          <el-radio-group v-model="filters.view" size="small" @change="load">
            <el-radio-button v-for="v in VIEW_OPTIONS" :key="v.value" :value="v.value">{{ v.label }}</el-radio-button>
          </el-radio-group>
          <el-checkbox-group v-if="filters.view === 'custom'" v-model="filters.customDims" :min="1" size="small" @change="load">
            <el-checkbox v-for="d in DIMENSIONS" :key="d.value" :value="d.value">{{ d.label }}</el-checkbox>
          </el-checkbox-group>
        </div>
        <p v-if="radar.summary.excluded_quantity" class="radar-foot">
          <template v-if="radar.dims.includes('color') || radar.dims.includes('size')">含颜色或尺寸的视角只统计能确切识别这两项的订单行，本期有 {{ count(radar.summary.excluded_quantity) }} 件识别不出或缺克重，未计入；只看规格时历史估算行会计入。</template>
          <template v-else>本期有 {{ count(radar.summary.excluded_quantity) }} 件缺克重或型号里没有规格，未计入。</template>
        </p>
      </section>

      <div class="radar-grid">
        <section class="radar-card">
          <h3>{{ dimTitle }} · 涨得最多</h3>
          <MoverList :rows="radar.movers.risers" empty="本期没有上涨的项" @open="openItem" />
        </section>
        <section class="radar-card">
          <h3>{{ dimTitle }} · 跌得最多</h3>
          <MoverList :rows="radar.movers.fallers" empty="本期没有下跌的项" @open="openItem" />
        </section>
      </div>

      <section class="radar-card">
        <div class="table-head">
          <h3>{{ dimTitle }} · 销量排行 <small>共 {{ radar.summary.group_count }} 项有销量</small></h3>
          <el-input v-model="table.keyword" clearable placeholder="搜索规格 / 颜色 / 尺寸" class="radar-search" @input="table.page = 1" />
        </div>
        <el-table v-sticky-scrollbar :data="pagedRows" row-key="key" border class="list-table rank-table" row-class-name="rank-row"
          :default-sort="{ prop: 'kg', order: 'descending' }" @sort-change="onSort" @row-click="openItem">
          <el-table-column label="排名" min-width="92">
            <template #default="{ row }">
              <span class="rank">{{ row.rank ?? '—' }}</span>
              <small :class="['rank-move', rankClass(row)]">{{ rankMove(row) }}</small>
            </template>
          </el-table-column>
          <el-table-column v-for="d in radar.dims" :key="d" :label="radar.dim_labels[d]" :min-width="d === 'spec' ? 200 : d === 'color' ? 140 : 80" show-overflow-tooltip>
            <template #default="{ row }">{{ row.values[d] }}</template>
          </el-table-column>
          <el-table-column prop="kg" label="本期 kg" min-width="120" align="right" sortable="custom">
            <template #default="{ row }">{{ num(row.kg, 1) }}</template>
          </el-table-column>
          <el-table-column prop="quantity" label="件数" min-width="96" align="right" sortable="custom">
            <template #default="{ row }">{{ count(row.quantity) }}</template>
          </el-table-column>
          <el-table-column prop="prev_kg" label="上期 kg" min-width="110" align="right" sortable="custom">
            <template #default="{ row }">{{ num(row.prev_kg, 1) }}</template>
          </el-table-column>
          <el-table-column prop="delta_kg" label="变化" min-width="140" align="right" sortable="custom">
            <template #default="{ row }"><span :class="trendClass(row.delta_kg)">{{ deltaText(row.delta_kg) }}</span></template>
          </el-table-column>
          <el-table-column prop="growth" label="增长" min-width="96" align="right" sortable="custom">
            <template #default="{ row }"><span :class="trendClass(row.delta_kg)">{{ growthText(row) }}</span></template>
          </el-table-column>
          <el-table-column v-if="radar.summary.my_kg !== null" prop="my_share" :label="`${radar.share_scope.label}占`" min-width="90" align="right" sortable="custom">
            <template #default="{ row }">{{ row.my_share === null ? '—' : percent(row.my_share) }}</template>
          </el-table-column>
        </el-table>
        <el-pagination v-if="filteredRows.length > 20" v-model:current-page="table.page" v-model:page-size="table.pageSize"
          :page-sizes="[20, 50, 100]" :total="filteredRows.length" layout="total, sizes, prev, pager, next" class="rank-pager"
          @size-change="table.page = 1" />
      </section>

      <p class="radar-foot">
        大类按型号前缀划分，规格是去掉前缀后的型号。
        <template v-if="radar.unclassified.kg">本期另有 {{ kg(radar.unclassified.kg) }} 不属于三个大类（配件、费用等），未计入。</template>
        旧产品库时期（2026 年 3 月前）只有型号，只在「规格」视角里计入。
      </p>
    </template>

    <DetailDrawer v-model="detail.visible" :title="detailTitle" :width="640" :loading="detail.loading">
      <ListPageStatus :error="detail.error" :loading="detail.loading" :has-data="!!detail.data" @retry="openItem({ values: detail.values })" />
      <template v-if="detail.data">
        <p class="drawer-sub">{{ detail.data.grade_label }} · 近 {{ detail.data.window.days }} 天 {{ kg(detail.data.summary?.kg) }}，上期 {{ kg(detail.data.summary?.prev_kg) }}<template v-if="detail.data.share_scope.mode !== 'none' && detail.data.summary?.my_share !== null && detail.data.summary?.my_share !== undefined"> · {{ detail.data.share_scope.label }}占 {{ percent(detail.data.summary.my_share) }}</template></p>
        <h4>近 12 个月走势</h4>
        <ol class="month-bars" :style="{ '--max': maxMonth }">
          <li v-for="m in detail.data.monthly" :key="m.month" :class="{ 'is-estimate': !m.credible }" :title="`${m.month}：${kg(m.kg)}${m.credible ? '' : '（估算月）'}`">
            <span class="bar" :style="{ '--v': m.kg }"><span class="bar-mine" :style="{ '--v': m.my_kg }" /></span>
            <small>{{ m.month.slice(5) }}</small>
          </li>
        </ol>
        <p class="legend"><i class="lg-all" />全公司 <template v-if="detail.data.share_scope.mode !== 'none'"><i class="lg-mine" />{{ detail.data.share_scope.label }}</template> <i class="lg-est" />估算月</p>
        <div class="drawer-split">
          <div v-for="block in detail.data.breakdowns" :key="block.dim"><h4>主要{{ block.label }}<small v-if="block.dim !== 'spec'" class="insight-meta"> 仅含确切识别的订单</small></h4><ShareList :rows="block.rows" /></div>
          <div><h4>主要国家</h4><ShareList :rows="detail.data.top_countries" /></div>
        </div>
      </template>
      <template #footer>
        <GlassButton v-if="customerLink" left-icon="User" @click="goCustomers">查看买过的我的客户</GlassButton>
        <span v-else-if="detail.data && !canSeeCustomers" class="insight-meta">需要「订单经营决策台」权限才能查看客户</span>
        <span v-else-if="detail.data && tooManyModels" class="insight-meta">涉及型号超过 {{ MAX_LINK_MODELS }} 个，请先按规格查看再找客户</span>
      </template>
    </DetailDrawer>
  </div>
</template>

<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, defineComponent, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { formatMoney } from '@/utils/money'
import { DIMENSIONS, GRADE_OPTIONS, VIEW_OPTIONS, WINDOW_OPTIONS, useProductRadar } from './composables/useProductRadar'

const {
  filters, radar, loading, error, scopes, comparable, table, filteredRows, pagedRows, onSort,
  detail, insight, load, loadScopes, openItem, explain, switchScope, tabs, canReadAll,
} = useProductRadar()
const router = useRouter()
const auth = useAuthStore()

const num = (value, digits) => formatMoney(value, digits)
const kg = value => (value === null || value === undefined ? '—' : `${formatMoney(value, 1)} kg`)
const count = value => formatMoney(value, 0)
const percent = value => (value === null || value === undefined ? '—' : `${formatMoney((Number(value) || 0) * 100, 0)}%`)
const deltaText = value => `${value > 0 ? '+' : ''}${formatMoney(value, 1)} kg`
const trendClass = value => (value > 0 ? 'is-up' : value < 0 ? 'is-down' : '')
const growthText = row => (row.growth === null || row.growth === undefined ? '新出现' : `${row.growth > 0 ? '+' : ''}${formatMoney(row.growth * 100, 0)}%`)
const growthOf = summary => (summary.prev_kg > 0 ? (summary.kg - summary.prev_kg) / summary.prev_kg : null)
const rankMove = row => {
  if (!row.rank) return '本期无'
  if (!row.prev_rank) return '新上榜'
  const diff = row.prev_rank - row.rank
  return diff > 0 ? `↑${diff}` : diff < 0 ? `↓${-diff}` : '持平'
}
const rankClass = row => (row.rank && row.prev_rank ? trendClass(row.prev_rank - row.rank) : '')

const tabKg = grade => (tabs.value.days === filters.window ? tabs.value.items.find(tab => tab.grade === grade)?.kg ?? null : null)
const dimTitle = computed(() => (radar.value ? radar.value.dims.map(d => radar.value.dim_labels[d]).join(' × ') : ''))
const detailTitle = computed(() => (detail.values ? Object.values(detail.values).join(' · ') : '详情'))
const scopedUsers = computed(() => (filters.team ? scopes.value.users.filter(u => u.team === filters.team) : scopes.value.users))
const maxMonth = computed(() => Math.max(1, ...(detail.data?.monthly || []).map(m => m.kg)))
const insightHtml = computed(() => DOMPurify.sanitize(marked.parse(insight.data?.content || '', { gfm: true, breaks: true })))

const MoverList = defineComponent({
  props: { rows: { type: Array, default: () => [] }, empty: { type: String, default: '' } },
  emits: ['open'],
  setup(props, { emit }) {
    return () => (props.rows.length
      ? h('ol', { class: 'mover-list' }, props.rows.map(row => h('li', { key: row.key }, [
        h('button', { type: 'button', class: 'mover-row', onClick: () => emit('open', row) }, [
          h('span', { class: 'mover-key' }, row.key),
          h('span', { class: 'mover-kg' }, kg(row.kg)),
          h('span', { class: ['mover-delta', trendClass(row.delta_kg)] }, `${deltaText(row.delta_kg)} · ${growthText(row)}`),
        ]),
      ])))
      : h('p', { class: 'mover-empty' }, props.empty))
  },
})

const ShareList = defineComponent({
  props: { rows: { type: Array, default: () => [] } },
  setup(props) {
    return () => (props.rows.length
      ? h('ol', { class: 'share-list' }, props.rows.map(row => h('li', { key: row.name }, [
        h('span', row.name), h('span', `${kg(row.kg)} · ${percent(row.share)}`),
      ])))
      : h('p', { class: 'mover-empty' }, '暂无可展示的分布'))
  },
})

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
  load()
  if (canReadAll.value) loadScopes()
}

onMounted(async () => {
  await load()
  if (radar.value?.share_scope?.can_read_all) loadScopes()
})
</script>

<style scoped>
.radar-page { display: flex; flex-direction: column; gap: 16px; }
.radar-head { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: flex-end; justify-content: space-between; }
.radar-head h2 { margin: 0; font-size: 20px; }
.radar-head p { margin: 4px 0 0; color: var(--text-secondary); font-size: 13px; }
.radar-controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.radar-select-sm { width: 160px; }
.radar-alert { margin: 0; }
.grade-tabs { margin-bottom: -16px; }
.grade-label small { margin-left: 8px; color: var(--text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }

.radar-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.radar-summary > div, .radar-card {
  padding: 14px 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}
.radar-summary span { color: var(--text-secondary); font-size: 13px; }
.radar-summary strong { display: block; margin-top: 4px; font-size: 22px; font-variant-numeric: tabular-nums; }
.radar-summary small { margin-left: 8px; color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.is-up { color: var(--color-success-text); }
.is-down { color: var(--color-danger); }
.is-muted { color: var(--text-secondary); }

.radar-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 12px; }
.radar-card h3 { margin: 0 0 8px; font-size: 15px; }
.radar-card h3 small { margin-left: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.radar-foot { margin: 0; color: var(--text-secondary); font-size: 12px; }
.radar-card .radar-foot { margin-top: 8px; }

.dim-bar { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; }
.dim-title { font-size: 14px; font-weight: 600; }

.table-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; justify-content: space-between; }
.radar-search { width: 240px; }
.rank-table { width: 100%; font-variant-numeric: tabular-nums; }
.rank-table :deep(.rank-row) { cursor: pointer; }
.rank { font-weight: 600; }
.rank-move { margin-left: 6px; color: var(--text-secondary); font-size: 12px; }
.rank-move.is-up { color: var(--color-success-text); }
.rank-move.is-down { color: var(--color-danger); }
.rank-pager { justify-content: flex-end; margin-top: 12px; }

:deep(.mover-list), :deep(.share-list) { margin: 0; padding: 0; list-style: none; }
:deep(.mover-row) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  padding: 8px 6px;
  border: 0;
  border-bottom: 1px solid var(--border-color);
  background: none;
  color: inherit;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  font-variant-numeric: tabular-nums;
  transition: background-color 150ms ease;
}
@media (hover: hover) and (pointer: fine) {
  :deep(.mover-row:hover) { background: var(--color-info-bg); }
}
:deep(.mover-row:focus-visible) { outline: 2px solid var(--color-primary); outline-offset: -2px; }
:deep(.mover-key) { overflow: hidden; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
:deep(.mover-kg) { color: var(--text-secondary); white-space: nowrap; }
:deep(.mover-delta) { white-space: nowrap; }
:deep(.mover-delta.is-up) { color: var(--color-success-text); }
:deep(.mover-delta.is-down) { color: var(--color-danger); }
:deep(.mover-empty) { margin: 8px 0; color: var(--text-secondary); font-size: 13px; }
:deep(.share-list li) { display: flex; justify-content: space-between; gap: 8px; padding: 4px 0; font-size: 13px; }

.insight-head { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: flex-start; justify-content: space-between; }
.insight-head h3 { margin: 0; }
.insight-meta { margin: 4px 0; color: var(--text-secondary); font-size: 12px; }
.insight-body { margin-top: 8px; font-size: 13px; line-height: 1.75; }
.insight-body :deep(p) { margin: 4px 0; }
.insight-body :deep(ul), .insight-body :deep(ol) { margin: 4px 0; padding-left: 20px; }

.drawer-sub { margin: 0 0 12px; color: var(--text-secondary); font-size: 13px; }
.radar-page h4 { margin: 12px 0 8px; font-size: 14px; }
.month-bars { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 4px; align-items: end; height: 140px; margin: 0; padding: 0; list-style: none; }
.month-bars li { display: flex; flex-direction: column; align-items: center; gap: 4px; height: 100%; justify-content: flex-end; }
.month-bars .bar { position: relative; display: block; width: 70%; height: calc(var(--v) / var(--max) * 110px); min-height: 2px; border-radius: 3px 3px 0 0; background: var(--color-primary); }
.month-bars .bar-mine { position: absolute; right: 0; bottom: 0; left: 0; height: calc(var(--v) / var(--max) * 110px); border-radius: 3px 3px 0 0; background: var(--color-gold-muted); }
.month-bars .is-estimate .bar { background: repeating-linear-gradient(135deg, var(--color-info-bg) 0 4px, var(--border-color) 4px 6px); }
.month-bars small { color: var(--text-secondary); font-size: 11px; }
.legend { display: flex; gap: 12px; align-items: center; margin: 6px 0 0; color: var(--text-secondary); font-size: 12px; }
.legend i { display: inline-block; width: 10px; height: 10px; margin-right: 4px; border-radius: 2px; }
.lg-all { background: var(--color-primary); }
.lg-mine { background: var(--color-gold-muted); }
.lg-est { background: repeating-linear-gradient(135deg, var(--color-info-bg) 0 3px, var(--border-color) 3px 4px); }
.drawer-split { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }

@media (max-width: 768px) {
  .radar-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .radar-summary strong { font-size: 18px; }
  .radar-summary small { display: block; margin-left: 0; }
  .radar-grid, .drawer-split { grid-template-columns: 1fr; }
  :deep(.mover-row) { grid-template-columns: minmax(0, 1fr) auto; }
  :deep(.mover-kg) { display: none; }
  .radar-select-sm, .radar-search { width: 100%; }
}
</style>
