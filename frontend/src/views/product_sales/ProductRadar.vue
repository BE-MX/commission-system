<!--
  产品风向标（P1）：业务员看「最近什么在涨、什么在跌、我卖了多少」，点开某款看走势、AI 解读，
  再跳到决策台找「买过这款的我的客户」。只讲产品，客户层不在本页重做。
  需求：docs/requirements/2026-11-18-product-sales-radar/README.md
-->
<template>
  <div class="radar-page">
    <header class="radar-head">
      <div>
        <h2>产品风向标</h2>
        <p v-if="radar">{{ radar.window.current[0] }} 至 {{ radar.window.current[1] }}，对比前 {{ radar.window.days }} 天 · 重量 kg</p>
      </div>
      <div class="radar-controls">
        <el-radio-group v-model="filters.window" @change="reload">
          <el-radio-button v-for="opt in WINDOW_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</el-radio-button>
        </el-radio-group>
        <el-select v-model="filters.models" multiple collapse-tags collapse-tags-tooltip clearable filterable placeholder="全部型号" class="radar-select" @change="load">
          <el-option v-for="m in radar?.model_options || []" :key="m" :label="m" :value="m" />
        </el-select>
        <template v-if="radar?.share_scope?.can_read_all">
          <el-select v-model="filters.team" clearable filterable placeholder="份额：我" class="radar-select-sm" @change="() => { filters.userId = ''; load() }">
            <el-option v-for="t in scopes.teams" :key="t" :label="`${t} 团队`" :value="t" />
          </el-select>
          <el-select v-model="filters.userId" clearable filterable placeholder="或选业务员" class="radar-select-sm" @change="load">
            <el-option v-for="u in scopedUsers" :key="u.user_id" :label="u.name" :value="u.user_id" />
          </el-select>
        </template>
      </div>
    </header>

    <ListPageStatus :error="error" :loading="loading" :has-data="!!radar" @retry="load" />

    <template v-if="radar">
      <el-alert v-if="!comparable" type="warning" :closable="false" show-icon class="radar-alert"
        :title="`对比期里有估算数据（本期确切 ${percent(radar.credibility.current.credible_share)}，上期 ${percent(radar.credibility.previous.credible_share)}，可信线 ${percent(radar.credibility.threshold)}），涨跌只作参考`" />

      <section class="radar-summary" aria-label="总览">
        <div><span>本期销量</span><strong>{{ kg(radar.summary.kg) }}</strong></div>
        <div><span>上期销量</span><strong>{{ kg(radar.summary.prev_kg) }}</strong></div>
        <div><span>变化</span><strong :class="trendClass(radar.summary.kg - radar.summary.prev_kg)">{{ deltaText(radar.summary.kg - radar.summary.prev_kg) }}</strong></div>
        <div>
          <span>{{ radar.share_scope.label }}的销量</span>
          <strong v-if="radar.summary.my_kg !== null">{{ kg(radar.summary.my_kg) }}<small>占 {{ percent(radar.summary.my_share) }}</small></strong>
          <strong v-else class="is-muted">—<small>账号未绑定 OKKI 业务员</small></strong>
        </div>
      </section>

      <div class="radar-grid">
        <section class="radar-card">
          <h3>颜色 × 发长 · 在涨</h3>
          <MoverList :rows="radar.color_size.risers" empty="本期没有上涨的组合" @open="key => openItem('color_size', key)" />
        </section>
        <section class="radar-card">
          <h3>颜色 × 发长 · 在跌</h3>
          <MoverList :rows="radar.color_size.fallers" empty="本期没有下跌的组合" @open="key => openItem('color_size', key)" />
        </section>
        <section class="radar-card">
          <h3>小款冒头 <small>上期不在前 20、增长过半的款</small></h3>
          <MoverList :rows="radar.small_risers" empty="暂时没有冒头的小款" @open="key => openItem('item', key)" />
        </section>
        <section class="radar-card">
          <h3>品类</h3>
          <MoverList :rows="radar.categories" empty="暂无数据" @open="key => openItem('category', key)" />
        </section>
      </div>
      <p class="radar-foot">颜色 × 发长只统计能识别这两个维度的订单行，本期有 {{ count(radar.summary.color_size_excluded_quantity) }} 件识别不出，未计入。旧产品库时期（2026 年 3 月前）只有型号。</p>
    </template>

    <DetailDrawer v-model="detail.visible" :title="detail.key || '详情'" :width="640" :loading="detail.loading">
      <ListPageStatus :error="detail.error" :loading="detail.loading" :has-data="!!detail.data" @retry="openItem(detail.dimension, detail.key)" />
      <template v-if="detail.data">
        <p class="drawer-sub">{{ detail.data.dimension_label }} · 近 {{ detail.data.window.days }} 天 {{ kg(detail.data.summary?.kg) }}，上期 {{ kg(detail.data.summary?.prev_kg) }}<template v-if="detail.data.summary?.my_share !== null && detail.data.summary?.my_share !== undefined"> · {{ detail.data.share_scope.label }}占 {{ percent(detail.data.summary.my_share) }}</template></p>
        <h4>近 12 个月走势</h4>
        <ol class="month-bars" :style="{ '--max': maxMonth }">
          <li v-for="m in detail.data.monthly" :key="m.month" :class="{ 'is-estimate': !m.credible }" :title="`${m.month}：${kg(m.kg)}${m.credible ? '' : '（估算月）'}`">
            <span class="bar" :style="{ '--v': m.kg }"><span class="bar-mine" :style="{ '--v': m.my_kg }" /></span>
            <small>{{ m.month.slice(5) }}</small>
          </li>
        </ol>
        <p class="legend"><i class="lg-all" />全公司 <i class="lg-mine" />{{ detail.data.share_scope.label }} <i class="lg-est" />估算月</p>
        <div class="drawer-split">
          <div><h4>主要型号</h4><ShareList :rows="detail.data.top_models" /></div>
          <div><h4>主要国家</h4><ShareList :rows="detail.data.top_countries" /></div>
        </div>

        <section class="insight">
          <div class="insight-head">
            <h4>AI 解读</h4>
            <GlassButton variant="primary" left-icon="MagicStick" :loading="insight.loading" @click="explain">{{ insight.data ? '重新解读' : '解读这款' }}</GlassButton>
          </div>
          <el-alert v-if="insight.error" type="error" :title="insight.error" :closable="false" show-icon />
          <template v-if="insight.data">
            <p class="insight-meta">{{ insight.data.source === 'ai' ? 'AI 生成' : 'AI 暂不可用，规则摘要' }} · {{ insight.data.created_at }}<template v-if="insight.data.reused">（24 小时内复用）</template><template v-if="!insight.data.comparable"> · 对比期含估算，不下趋势结论</template></p>
            <pre class="insight-body">{{ insight.data.content }}</pre>
          </template>
          <p v-else-if="!insight.loading" class="insight-meta">根据走势、型号和国家分布说明这款为什么涨或跌，数字只来自上面的数据。</p>
        </section>
      </template>
      <template #footer>
        <GlassButton v-if="customerLink" left-icon="User" @click="goCustomers">查看买过这款的我的客户</GlassButton>
        <span v-else-if="detail.data && detail.dimension !== 'category'" class="insight-meta">需要「订单经营决策台」权限才能查看客户</span>
      </template>
    </DetailDrawer>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { formatMoney } from '@/utils/money'
import { WINDOW_OPTIONS, useProductRadar } from './composables/useProductRadar'

const { filters, radar, loading, error, scopes, comparable, detail, insight, load, loadScopes, openItem, explain } = useProductRadar()
const router = useRouter()
const auth = useAuthStore()

const kg = value => (value === null || value === undefined ? '—' : `${formatMoney(value, 1)} kg`)
const count = value => formatMoney(value, 0)
const percent = value => (value === null || value === undefined ? '—' : `${formatMoney((Number(value) || 0) * 100, 0)}%`)
const deltaText = value => `${value > 0 ? '+' : ''}${formatMoney(value, 1)} kg`
const trendClass = value => (value > 0 ? 'is-up' : value < 0 ? 'is-down' : '')
const growthText = row => (row.growth === null || row.growth === undefined ? '新出现' : `${row.growth > 0 ? '+' : ''}${formatMoney(row.growth * 100, 0)}%`)

const scopedUsers = computed(() => (filters.team ? scopes.value.users.filter(u => u.team === filters.team) : scopes.value.users))
const maxMonth = computed(() => Math.max(1, ...(detail.data?.monthly || []).map(m => m.kg)))

const MoverList = defineComponent({
  props: { rows: { type: Array, default: () => [] }, empty: { type: String, default: '' } },
  emits: ['open'],
  setup(props, { emit }) {
    return () => (props.rows.length
      ? h('ol', { class: 'mover-list' }, props.rows.map(row => h('li', { key: row.key }, [
        h('button', { type: 'button', class: 'mover-row', onClick: () => emit('open', row.key) }, [
          h('span', { class: 'mover-key' }, row.key),
          h('span', { class: 'mover-kg' }, kg(row.kg)),
          h('span', { class: ['mover-delta', trendClass(row.delta_kg)] }, `${deltaText(row.delta_kg)} · ${growthText(row)}`),
          h('span', { class: 'mover-mine' }, row.my_share === null || row.my_share === undefined ? '' : `我 ${percent(row.my_share)}`),
        ]),
      ])))
      : h('p', { class: 'mover-empty' }, props.empty))
  },
})

const ShareList = defineComponent({
  props: { rows: { type: Array, default: () => [] } },
  setup(props) {
    return () => h('ol', { class: 'share-list' }, props.rows.map(row => h('li', { key: row.name }, [
      h('span', row.name), h('span', `${kg(row.kg)} · ${percent(row.share)}`),
    ])))
  },
})

const canSeeCustomers = computed(() => auth.hasPermission('order_intelligence:read'))
// 深链只带决策台能精确匹配的值：颜色；款再带上型号。决策台不按发长筛，客户里会包含其他发长
const customerLink = computed(() => {
  if (!detail.data || detail.dimension === 'category' || !canSeeCustomers.value) return null
  const parts = detail.key.split(' · ')
  const color = detail.dimension === 'item' ? parts[1] : parts[0]
  const model = detail.dimension === 'item' ? parts[0] : null
  if (!color) return null
  return { path: '/invoice/order-intelligence', query: { tab: 'customers', colors: color, ...(model ? { models: model } : {}) } }
})
const goCustomers = () => customerLink.value && router.push(customerLink.value)

function reload() {
  load()
  if (radar.value?.share_scope?.can_read_all) loadScopes()
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
.radar-select { width: 240px; }
.radar-select-sm { width: 160px; }
.radar-alert { margin: 0; }

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

:deep(.mover-list), :deep(.share-list) { margin: 0; padding: 0; list-style: none; }
:deep(.mover-row) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto 52px;
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
:deep(.mover-kg), :deep(.mover-mine) { color: var(--text-secondary); white-space: nowrap; }
:deep(.mover-delta) { white-space: nowrap; }
:deep(.mover-mine) { text-align: right; }
:deep(.mover-delta.is-up) { color: var(--color-success-text); }
:deep(.mover-delta.is-down) { color: var(--color-danger); }
:deep(.mover-empty) { margin: 8px 0; color: var(--text-secondary); font-size: 13px; }
:deep(.share-list li) { display: flex; justify-content: space-between; gap: 8px; padding: 4px 0; font-size: 13px; }

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
.drawer-split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.insight { margin-top: 16px; padding-top: 4px; border-top: 1px solid var(--border-color); }
.insight-head { display: flex; align-items: center; justify-content: space-between; }
.insight-meta { margin: 6px 0; color: var(--text-secondary); font-size: 12px; }
.insight-body { margin: 8px 0 0; font: inherit; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }

@media (max-width: 768px) {
  .radar-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .radar-grid, .drawer-split { grid-template-columns: 1fr; }
  :deep(.mover-row) { grid-template-columns: minmax(0, 1fr) auto; }
  :deep(.mover-kg), :deep(.mover-mine) { display: none; }
  .radar-select, .radar-select-sm { width: 100%; }
}
</style>
