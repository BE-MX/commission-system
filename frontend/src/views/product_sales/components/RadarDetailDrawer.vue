<!--
  产品风向标行详情抽屉：
  - 单层骨架占位（消除 v-loading 与文字重叠）
  - 12 个月柱状图改用 GPU scaleY transition（可打断 morph）、标注峰值参考线与 partial 未满月、
    高对比个人份额柱，支持 hover/点击查看单月精确数值
  - 主要规格/颜色/尺寸支持点击直接下钻，破除超 20 型号死胡同；支持抽屉内上一项/下一项切换
-->
<template>
  <DetailDrawer :model-value="detail.visible" :title="title" :width="640" :loading="false" @update:model-value="$emit('update:visible', $event)">
    <div class="drawer-nav" v-if="detail.history.length || canStep">
      <button v-if="detail.history.length" type="button" class="nav-chip" @click="$emit('drill-back')">
        <el-icon><ArrowLeft /></el-icon> 返回上一级
      </button>
      <div v-if="canStep" class="step-group">
        <button type="button" class="nav-chip" :disabled="detail.navIndex <= 0 || detail.loading" aria-label="上一项" @click="$emit('step', -1)">
          <el-icon><ArrowUp /></el-icon> 上一项
        </button>
        <span class="step-count">{{ detail.navIndex + 1 }} / {{ detail.navList.length }}</span>
        <button type="button" class="nav-chip" :disabled="detail.navIndex >= detail.navList.length - 1 || detail.loading" aria-label="下一项" @click="$emit('step', 1)">
          下一项 <el-icon><ArrowDown /></el-icon>
        </button>
      </div>
    </div>

    <ListPageStatus v-if="detail.error" :error="detail.error" :loading="detail.loading" :has-data="!!detail.data" :paged="false" @retry="$emit('retry')" />

    <div v-if="detail.loading && !detail.data" class="drawer-skeleton" aria-busy="true" aria-label="正在加载详情">
      <div class="sk-line sk-w-70" />
      <div class="sk-bars">
        <span v-for="n in 12" :key="n" :style="{ height: `${28 + ((n * 19) % 64)}%` }" />
      </div>
      <div class="sk-split">
        <div class="sk-block"><div class="sk-line sk-w-40" /><div class="sk-line" /><div class="sk-line sk-w-80" /><div class="sk-line sk-w-60" /></div>
        <div class="sk-block"><div class="sk-line sk-w-40" /><div class="sk-line" /><div class="sk-line sk-w-80" /><div class="sk-line sk-w-60" /></div>
      </div>
    </div>

    <div v-else-if="detail.data" class="drawer-content" :class="{ 'is-updating': detail.loading }">
      <p class="drawer-sub">
        <span>{{ detail.data.grade_label }} · 近 {{ detail.data.window.days }} 天 <strong>{{ kg(detail.data.summary?.kg) }}</strong></span>
        <span class="sub-sep">上期 {{ kg(detail.data.summary?.prev_kg) }}</span>
        <span v-if="hasMine && detail.data.summary?.my_share !== null && detail.data.summary?.my_share !== undefined" class="sub-sep">
          {{ detail.data.share_scope.label }}占 <strong>{{ percent(detail.data.summary.my_share) }}</strong>
        </span>
      </p>

      <div class="chart-head">
        <h4>近 12 个月走势</h4>
        <span class="chart-readout">
          <template v-if="activeMonth">
            <strong>{{ activeMonth.month }}</strong>：{{ kg(activeMonth.kg) }}
            <template v-if="hasMine"> · {{ detail.data.share_scope.label }} {{ kg(activeMonth.my_kg) }}</template>
            <em v-if="activeMonth.partial" class="month-tag">截至 {{ activeMonth.days_covered }} 日（未满月）</em>
            <em v-else-if="!activeMonth.credible" class="month-tag">估算月</em>
          </template>
          <template v-else>峰值 {{ kg(peakKg) }}</template>
        </span>
      </div>

      <div class="month-chart" :class="{ 'has-focus': activeMonthIndex !== null }" @mouseleave="hoveredIndex = null">
        <div class="chart-guide" aria-hidden="true"><span>{{ kg(peakKg) }}</span></div>
        <ol class="month-bars" :class="{ 'is-entering': barsEntering }">
          <li
            v-for="(m, i) in detail.data.monthly"
            :key="m.month"
            :class="{
              'is-estimate': !m.credible,
              'is-partial': m.partial,
              'is-active': activeMonthIndex === i,
            }"
            @mouseenter="hoveredIndex = i"
          >
            <button
              type="button"
              class="bar-trigger"
              :aria-pressed="pinnedIndex === i"
              :aria-label="monthAria(m)"
              @click="togglePin(i)"
            >
              <span class="bar-track">
                <span class="bar-fill" :style="barStyle(m.kg, i)" />
                <span v-if="hasMine && m.my_kg > 0" class="bar-mine" :style="barStyle(m.my_kg, i)" />
              </span>
              <small>{{ monthLabel(m, i) }}</small>
            </button>
          </li>
        </ol>
      </div>

      <p class="legend">
        <span><i class="lg-all" />全公司</span>
        <span v-if="hasMine"><i class="lg-mine" />{{ detail.data.share_scope.label }}</span>
        <span v-if="hasPartial"><i class="lg-partial" />本月未满月</span>
        <span v-if="hasEstimate"><i class="lg-est" />估算月</span>
      </p>

      <div class="drawer-split">
        <div v-for="block in detail.data.breakdowns" :key="block.dim" class="split-block">
          <h4>
            主要{{ block.label }}
            <small v-if="block.dim !== 'spec'" class="block-hint">点击下钻</small>
            <small v-else class="block-hint">点击下钻看客户</small>
          </h4>
          <ol v-if="block.rows.length" class="share-list">
            <li v-for="row in block.rows" :key="row.name">
              <button type="button" class="share-row is-clickable" @click="$emit('drill-down', block.dim, row.name)">
                <span class="share-name">{{ row.name }}</span>
                <span class="share-val">{{ kg(row.kg) }} · {{ percent(row.share) }}</span>
                <el-icon class="share-arrow"><ArrowRight /></el-icon>
                <i class="share-meter" aria-hidden="true" :style="{ transform: `scaleX(${Math.max(0.02, Math.min(1, row.share || 0))})` }" />
              </button>
            </li>
          </ol>
          <p v-else class="empty-hint">暂无可展示的分布</p>
        </div>

        <div class="split-block">
          <h4>主要国家</h4>
          <ol v-if="detail.data.top_countries.length" class="share-list">
            <li v-for="row in detail.data.top_countries" :key="row.name">
              <div class="share-row">
                <span class="share-name">{{ row.name }}</span>
                <span class="share-val">{{ kg(row.kg) }} · {{ percent(row.share) }}</span>
                <i class="share-meter" aria-hidden="true" :style="{ transform: `scaleX(${Math.max(0.02, Math.min(1, row.share || 0))})` }" />
              </div>
            </li>
          </ol>
          <p v-else class="empty-hint">客户数不足 3 家，暂不展示国家分布</p>
        </div>
      </div>
    </div>

    <template #footer>
      <GlassButton v-if="customerLink" variant="primary" left-icon="User" @click="$emit('go-customers')">
        查看买过的我的客户
      </GlassButton>
      <template v-else-if="detail.data && !canSeeCustomers">
        <span class="footer-hint">需要「订单经营决策台」权限才能查看客户</span>
      </template>
      <template v-else-if="detail.data && tooManyModels">
        <span class="footer-hint">涉及 {{ modelCount }} 个型号（上限 {{ maxLinkModels }} 个），可点击上方「主要规格」下钻</span>
        <GlassButton left-icon="Filter" @click="$emit('pivot-spec')">按规格筛选此项</GlassButton>
      </template>
    </template>
  </DetailDrawer>
</template>

<script setup>
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from '@element-plus/icons-vue'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { formatMoney } from '@/utils/money'

const props = defineProps({
  detail: { type: Object, required: true },
  title: { type: String, default: '详情' },
  customerLink: { type: Object, default: null },
  canSeeCustomers: { type: Boolean, default: false },
  tooManyModels: { type: Boolean, default: false },
  modelCount: { type: Number, default: 0 },
  maxLinkModels: { type: Number, default: 20 },
})
defineEmits(['update:visible', 'retry', 'drill-down', 'drill-back', 'step', 'go-customers', 'pivot-spec'])

const hoveredIndex = ref(null)
const pinnedIndex = ref(null)
const barsMounted = ref(false)
const barsEntering = ref(false)
let enterTimer = null

const kg = value => (value === null || value === undefined ? '—' : `${formatMoney(value, 1)} kg`)
const percent = value => (value === null || value === undefined ? '—' : `${formatMoney((Number(value) || 0) * 100, 0)}%`)

const hasMine = computed(() => props.detail.data?.share_scope?.mode !== 'none')
const hasEstimate = computed(() => (props.detail.data?.monthly || []).some(m => !m.credible))
const hasPartial = computed(() => (props.detail.data?.monthly || []).some(m => m.partial))
const canStep = computed(() => !props.detail.history.length && props.detail.navIndex >= 0 && props.detail.navList.length > 1)

const peakKg = computed(() => Math.max(0, ...(props.detail.data?.monthly || []).map(m => Number(m.kg || 0))))
const maxMonth = computed(() => Math.max(0.01, peakKg.value))

const activeMonthIndex = computed(() => (hoveredIndex.value !== null ? hoveredIndex.value : pinnedIndex.value))
const activeMonth = computed(() => (activeMonthIndex.value !== null ? props.detail.data?.monthly?.[activeMonthIndex.value] ?? null : null))

function barStyle(value, index) {
  const num = Number(value || 0)
  const ratio = num > 0 ? Math.max(0.03, Math.min(1, num / maxMonth.value)) : 0
  return {
    '--ratio': barsMounted.value ? ratio : 0,
    '--i': index,
  }
}

function monthLabel(m, index) {
  const mm = m.month.slice(5)
  if (mm === '01' || index === 0) return `${m.month.slice(2, 4)}/${mm}`
  return mm
}

function monthAria(m) {
  const parts = [`${m.month} 全公司 ${kg(m.kg)}`]
  if (hasMine.value) parts.push(`${props.detail.data.share_scope.label} ${kg(m.my_kg)}`)
  if (m.partial) parts.push(`截至 ${m.days_covered} 日未满月`)
  else if (!m.credible) parts.push('估算月')
  return parts.join('，')
}

function togglePin(index) {
  pinnedIndex.value = pinnedIndex.value === index ? null : index
}

watch(() => props.detail.visible, visible => {
  if (!visible) {
    if (enterTimer) { clearTimeout(enterTimer); enterTimer = null }
    barsMounted.value = false
    barsEntering.value = false
    hoveredIndex.value = null
    pinnedIndex.value = null
  }
})

watch(() => props.detail.data, async data => {
  hoveredIndex.value = null
  pinnedIndex.value = null
  if (!data) {
    barsMounted.value = false
    barsEntering.value = false
    return
  }
  if (!barsMounted.value) {
    barsEntering.value = true
    await nextTick()
    requestAnimationFrame(() => {
      barsMounted.value = true
      enterTimer = setTimeout(() => { barsEntering.value = false }, 320)
    })
  }
})

onBeforeUnmount(() => { if (enterTimer) clearTimeout(enterTimer) })
</script>

<style scoped>
.drawer-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}
.step-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
.step-count {
  color: var(--text-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.nav-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--card-bg);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color var(--motion-fast) ease, border-color var(--motion-fast) ease, transform var(--motion-press) var(--ease-out-strong);
}
@media (hover: hover) and (pointer: fine) {
  .nav-chip:hover:not(:disabled) {
    border-color: var(--color-primary);
    background: var(--color-primary-light);
    color: var(--color-primary-text);
  }
}
.nav-chip:active:not(:disabled) { transform: scale(0.97); }
.nav-chip:disabled { opacity: 0.45; cursor: not-allowed; }
.nav-chip:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }

.drawer-content {
  transition: opacity var(--motion-fast) var(--ease-out-strong);
}
.drawer-content.is-updating {
  opacity: 0.55;
  transition-delay: 120ms;
  pointer-events: none;
}

.drawer-sub {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin: 0 0 14px;
  color: var(--text-secondary);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.drawer-sub strong { color: var(--text-primary); font-weight: 600; }
.sub-sep::before { content: '·'; margin-right: 12px; color: var(--border-hover); }

.chart-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px 12px;
  margin-bottom: 8px;
}
.chart-head h4, .split-block h4 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}
.chart-readout {
  color: var(--text-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.chart-readout strong { color: var(--text-primary); }
.month-tag {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--tag-warning-bg);
  color: var(--tag-warning-text);
  font-style: normal;
  font-size: 11px;
}

.month-chart {
  position: relative;
  padding-top: 14px;
}
.chart-guide {
  position: absolute;
  top: 14px;
  right: 0;
  left: 0;
  border-top: 1px dashed var(--border-color);
  pointer-events: none;
}
.chart-guide span {
  position: absolute;
  top: -15px;
  right: 0;
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.month-bars {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 4px;
  align-items: end;
  height: 142px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.month-bars li {
  height: 100%;
  transition: opacity var(--motion-fast) ease;
}
.month-chart.has-focus .month-bars li:not(.is-active) {
  opacity: 0.55;
}
.bar-trigger {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  width: 100%;
  height: 100%;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
}
.bar-trigger:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.bar-track {
  position: relative;
  display: block;
  width: 72%;
  height: 114px;
  border-radius: 4px 4px 0 0;
  overflow: hidden;
  background: rgba(91, 102, 120, 0.05);
}
.bar-fill, .bar-mine {
  position: absolute;
  inset: 0;
  border-radius: 4px 4px 0 0;
  transform-origin: 50% 100%;
  transform: scaleY(var(--ratio, 0));
  transition: transform var(--motion-base) var(--ease-out-strong);
  transition-delay: 0ms;
}
.month-bars.is-entering .bar-fill,
.month-bars.is-entering .bar-mine {
  /* 入场交错仅首次打开抽屉生效，后续切项/下钻时 12 根柱同步 morph，可随时打断 */
  transition-delay: calc(var(--i, 0) * 8ms);
}
.bar-fill { background: var(--color-primary); }
.bar-mine { background: var(--tag-success-solid); }
.month-bars .is-estimate .bar-fill {
  background: repeating-linear-gradient(135deg, var(--color-info-bg) 0 4px, var(--border-hover) 4px 6px);
}
.month-bars .is-partial .bar-fill {
  background: repeating-linear-gradient(180deg, var(--color-primary) 0 5px, rgba(212, 148, 28, 0.35) 5px 8px);
}
.bar-trigger small {
  color: var(--text-secondary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.month-bars li.is-active small {
  color: var(--text-primary);
  font-weight: 600;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  align-items: center;
  margin: 8px 0 14px;
  color: var(--text-secondary);
  font-size: 12px;
}
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
.lg-all { background: var(--color-primary); }
.lg-mine { background: var(--tag-success-solid); }
.lg-partial { background: repeating-linear-gradient(180deg, var(--color-primary) 0 3px, rgba(212, 148, 28, 0.35) 3px 5px); }
.lg-est { background: repeating-linear-gradient(135deg, var(--color-info-bg) 0 3px, var(--border-hover) 3px 4px); }

.drawer-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 18px;
}
.split-block h4 {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 6px;
}
.block-hint {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 400;
}
.share-list { margin: 0; padding: 0; list-style: none; }
.share-row {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 13px;
  text-align: left;
  font-variant-numeric: tabular-nums;
}
.share-row.is-clickable {
  grid-template-columns: minmax(0, 1fr) auto 14px;
  cursor: pointer;
  transition: background-color var(--motion-fast) ease;
}
@media (hover: hover) and (pointer: fine) {
  .share-row.is-clickable:hover { background: var(--color-gold-soft); }
  .share-row.is-clickable:hover .share-arrow { transform: translateX(2px); color: var(--color-primary-text); }
}
.share-row.is-clickable:active { background: var(--color-warning-bg); }
.share-row.is-clickable:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
.share-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.share-val { color: var(--text-secondary); font-size: 12px; white-space: nowrap; }
.share-arrow { color: var(--text-muted); font-size: 12px; transition: transform var(--motion-press) var(--ease-out-strong), color var(--motion-fast) ease; }
.share-meter {
  position: absolute;
  right: 6px;
  bottom: 2px;
  left: 6px;
  height: 2px;
  border-radius: 2px;
  background: var(--color-primary-glow);
  transform-origin: 0 50%;
  transition: transform var(--motion-base) var(--ease-out-strong);
}
.empty-hint { margin: 6px 0; color: var(--text-secondary); font-size: 12px; }
.footer-hint { color: var(--text-secondary); font-size: 12px; margin-right: auto; align-self: center; }

/* 骨架屏占位（单层加载，避免遮罩叠加与结果硬跳） */
.drawer-skeleton { display: flex; flex-direction: column; gap: 18px; padding: 4px 0; }
.sk-line {
  height: 14px;
  border-radius: 6px;
  background: var(--border-color);
  opacity: 0.55;
  animation: sk-pulse 1.4s ease-in-out infinite;
}
.sk-w-40 { width: 40%; }
.sk-w-60 { width: 60%; }
.sk-w-70 { width: 70%; }
.sk-w-80 { width: 80%; }
.sk-bars {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  align-items: end;
  gap: 8px;
  height: 132px;
  padding-top: 12px;
}
.sk-bars span {
  display: block;
  border-radius: 4px 4px 0 0;
  background: var(--border-color);
  opacity: 0.45;
  animation: sk-pulse 1.4s ease-in-out infinite;
}
.sk-split { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.sk-block { display: flex; flex-direction: column; gap: 10px; }

@keyframes sk-pulse {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 0.7; }
}

@media (max-width: 640px) {
  .drawer-split, .sk-split { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .bar-fill, .bar-mine, .share-meter { transition: none; }
  .sk-line, .sk-bars span { animation: none; opacity: 0.45; }
}
</style>
