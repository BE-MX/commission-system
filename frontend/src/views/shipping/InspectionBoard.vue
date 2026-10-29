<template>
  <div class="qc-board">
    <div class="qc-stage" :style="{ transform: `scale(${scale})`, left: `${offset.x}px`, top: `${offset.y}px` }">
      <header class="qc-header">
        <div class="qc-brand">
          <div class="qc-mark"><Icon :is="Box" :size="24" /></div>
          <h1>发货检验看板</h1>
        </div>
        <div class="qc-hdr-right">
          <div class="qc-sync" :class="{ stale }"><i></i>{{ stale ? '数据未更新' : `${lastSyncText} 已同步` }}</div>
          <div class="qc-date"><div>{{ today.text }}</div><div>{{ today.week }}</div></div>
          <div class="qc-clock qc-num">{{ clock }}</div>
        </div>
      </header>
      <div v-if="error" class="qc-error" role="alert">{{ error }}，30 秒后自动重试</div>

      <main class="qc-main">
        <section class="qc-col">
          <div class="qc-tiles">
            <div class="qc-tile">
              <div><div class="qc-lbl">待检出库单</div><div><span class="qc-big qc-num" :class="metricSize(summary.total)">{{ summary.total }}</span><span class="qc-unit">单</span></div></div>
            </div>
            <div class="qc-tile col">
              <div class="qc-lbl">待检产品</div>
              <div><span class="qc-big qc-num" :class="metricSize(summary.totalQty)">{{ fmt(summary.totalQty) }}</span><span class="qc-unit">件</span></div>
            </div>
            <div class="qc-tile hot">
              <div>
                <div class="qc-lbl">优先检验</div>
                <div><span class="qc-big qc-num" :class="metricSize(summary.counts[0] + summary.counts[1] + summary.counts[2])">{{ summary.counts[0] + summary.counts[1] + summary.counts[2] }}</span><span class="qc-unit">单</span></div>
                <div class="qc-chips">
                  <span class="qc-chip" style="color: var(--qc-new-hi)">新签 <b>{{ summary.counts[0] }}</b></span>
                  <span class="qc-chip" style="color: var(--qc-s)">S <b>{{ summary.counts[1] }}</b></span>
                  <span class="qc-chip" style="color: var(--qc-a)">A <b>{{ summary.counts[2] }}</b></span>
                </div>
              </div>
            </div>
            <div class="qc-tile late">
              <div><div class="qc-lbl">等待超 24h</div><div><span class="qc-big qc-num" :class="metricSize(summary.late)">{{ summary.late }}</span><span class="qc-unit">单</span></div></div>
            </div>
          </div>

          <div class="qc-panel qc-queue">
            <div class="qc-qhead">
              <div class="qc-ttl">待检验出库单</div>
              <div class="qc-legend">
                <span><i style="background: var(--qc-new)"></i>新签</span>
                <span><i style="background: var(--qc-s)"></i>S 级客户</span>
                <span><i style="background: var(--qc-a)"></i>A 级客户</span>
                <span><i style="border: 1.5px solid var(--qc-detail)"></i>详检</span>
                <span><i style="background: var(--qc-heavy)"></i>大单 ≥{{ HEAVY_LINES }} 行</span>
              </div>
            </div>
            <div class="qc-cols"><span style="text-align: center">#</span><span>标记</span><span>出库单 / 客户</span><span>业务员</span><span>已等待</span><span>检验工作量</span></div>
            <div v-if="data && !pending.length" class="qc-empty">
              <div><Icon :is="CircleCheck" :size="96" /><b>待检出库单已全部完成</b></div>
            </div>
            <div v-else class="qc-rows">
              <div v-for="(row, i) in visibleRows" :key="row.outbound_record_id"
                class="qc-row" :class="[`p${row.priority}`, { gap: i === paged.pinned.length - 1 && paged.rest.length }]">
                <span class="rank">{{ row.rank }}</span>
                <span class="qc-tags">
                  <span v-if="row.is_new_deal" class="qc-tag new">新签</span>
                  <span v-if="row.customer_grade" class="qc-tag" :class="['S', 'A'].includes(row.customer_grade) ? row.customer_grade : 'g'">{{ row.customer_grade }}</span>
                  <span v-if="row.inspection_requirement === 'detail'" class="qc-tag detail">详检</span>
                </span>
                <div class="qc-ob">
                  <div class="no" :title="row.outbound_no">{{ row.outbound_no }}</div>
                  <div class="cu">{{ maskCustomer(row.customer_name) }}<span v-if="row.inspecting" class="doing">● 检验中</span></div>
                </div>
                <div class="qc-sales">
                  <span :title="row.salesperson_name || '—'">{{ row.salesperson_name || '—' }}</span>
                </div>
                <div class="qc-age">
                  <span class="v qc-num" :class="row.level">{{ row.age.value }}<small>{{ row.age.unit }}</small></span>
                </div>
                <div class="qc-load" :class="{ heavy: row.item_count >= HEAVY_LINES }">
                  <div class="meta"><b>{{ row.item_count }}</b><small> 行</small><small class="block">{{ fmt(row.total_qty) }} 件</small></div>
                </div>
              </div>
            </div>
            <div class="qc-pager">
              <template v-if="paged.pages > 1"><i v-for="k in paged.pages" :key="k" :class="{ on: k - 1 === paged.page }"></i></template>
              <span v-if="paged.hiddenPinned" class="more">另有 {{ paged.hiddenPinned }} 张优先单</span>
              <span v-if="data?.pending_truncated" class="more">仅显示最近 {{ data.pending.length }} 张</span>
            </div>
          </div>
        </section>

        <section class="qc-col">
          <div class="qc-panel qc-today">
            <div class="qc-ttl">今日已完成</div>
            <div class="qc-today-body">
              <div class="qc-kpis">
                <div class="qc-kpi">
                  <div><div class="v qc-num">{{ todayStats.orders }}<small>单</small></div><div class="l">出库单</div></div></div>
                <div class="qc-kpi">
                  <div><div class="v qc-num">{{ fmt(todayStats.qty) }}<small>件</small></div><div class="l">产品数量</div></div></div>
                <div class="qc-kpi">
                  <div><div class="v qc-num">{{ todayStats.customers }}<small>家</small></div><div class="l">客户</div></div></div>
                <div class="qc-kpi">
                  <div><div class="v qc-num">{{ amountText }}</div>
                    <div class="l">订单金额 USD<em v-if="todayStats.amount_missing_orders"> · {{ todayStats.amount_missing_orders }} 单待同步</em></div></div></div>
              </div>
              <div class="qc-completion" title="今日完成 ÷（今日完成＋当前待检）">
                <span>今日完成率</span><b class="qc-num">{{ Math.round(completion * 100) }}%</b>
              </div>
            </div>
          </div>

          <div class="qc-panel qc-trend">
            <div class="qc-ttl">近 7 天检验量
              <div class="qc-tleg">
                <span><i style="width: 12px; height: 12px; border-radius: 3px; background: var(--qc-bar)"></i>出库单</span>
                <span><i style="width: 18px; height: 3px; background: var(--qc-ok)"></i>产品件数</span>
              </div>
            </div>
            <BoardTrendChart :trend="data?.trend || []" />
          </div>

          <div class="qc-panel qc-done">
            <div class="qc-ttl">已完成检验</div>
            <div class="qc-insp">
              <div v-for="p in (data?.inspectors || []).slice(0, 4)" :key="p.name" class="p">
                <span>{{ p.name }}</span><b>{{ p.count }}</b>
              </div>
            </div>
            <div class="qc-dcols"><span>出库单号</span><span>客户</span><span>业务员</span><span>提交</span><span>检验员</span></div>
            <div class="qc-dwrap">
              <div v-for="row in data?.done || []" :key="row.outbound_record_id" class="qc-drow" :class="{ fresh: freshIds.has(row.outbound_record_id) }">
                <span class="no"><i><Icon :is="Check" :size="11" /></i>{{ row.outbound_no }}</span>
                <span class="cu">{{ maskCustomer(row.customer_name) }}</span>
                <span class="sl">{{ row.salesperson_name || '—' }}</span>
                <span class="tm">{{ formatBeijingTime(row.submitted_at, { seconds: false }) }}</span>
                <span class="ins">{{ row.inspector_name || '—' }}</span>
              </div>
            </div>
          </div>
        </section>
      </main>

      <Transition name="qc-alert">
        <div v-if="currentAlert" :key="currentAlert.outbound_record_id" class="qc-alert" role="alertdialog" aria-live="assertive" @click="dismissAlert">
          <div class="qc-acard">
            <div class="qc-aband"><Icon :is="BellFilled" :size="54" /><b>新签订单</b><span v-if="alertQueue.length > 1" class="queue">还有 {{ alertQueue.length - 1 }} 单</span></div>
            <div class="qc-abody">
              <div class="qc-awho"><em>{{ currentAlert.salesperson_name || '—' }}</em> 业务员有新签订单</div>
              <div class="qc-ano">{{ currentAlert.outbound_no }}</div>
              <div class="qc-ameta">
                <span v-if="currentAlert.customer_grade"><b :style="{ color: gradeColor(currentAlert.customer_grade) }">{{ currentAlert.customer_grade }}</b>级客户</span>
                <span>明细 <b>{{ currentAlert.item_count }}</b> 行</span>
                <span>产品 <b>{{ fmt(currentAlert.total_qty) }}</b> 件</span>
              </div>
              <div class="qc-acta">请优先检验</div>
            </div>
            <div class="qc-acount"><i :style="{ animationDuration: `${alertMs}ms` }"></i></div>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { BellFilled, Box, Check, CircleCheck } from '@element-plus/icons-vue'
import Icon from './components/BoardIcon.vue'
import { formatBeijingTime } from '@/utils/datetime'
import { formatMoney } from '@/utils/money'
import BoardTrendChart from './components/BoardTrendChart.vue'
import { useInspectionBoard } from './composables/useInspectionBoard'
import { HEAVY_LINES, ageHours, ageLabel, ageLevel, maskCustomer, pageRows, priorityOf } from './composables/inspectionBoard'
import './board.css'

const SLOTS = 10
const {
  data, now, pending, summary, page, scale, offset, error, stale, lastOk, clock, today,
  currentAlert, alertQueue, dismissAlert, freshIds, alertMs,
} = useInspectionBoard()

const fmt = n => formatMoney(n, 0)
// Large totals keep their full value; only the display size changes.
const metricSize = n => {
  const length = fmt(n).length
  return length > 9 ? 'qc-big-small' : length > 6 ? 'qc-big-compact' : ''
}
const gradeColor = g => (g === 'S' ? 'var(--qc-s)' : g === 'A' ? 'var(--qc-a)' : 'var(--qc-text)')
const lastSyncText = computed(() => (lastOk.value ? formatBeijingTime(new Date(lastOk.value), { seconds: false }) : ''))

const paged = computed(() => pageRows(pending.value, SLOTS, page.value))
const visibleRows = computed(() => {
  const decorate = (row, rank) => {
    const hours = ageHours(row, now.value)
    return {
      ...row, rank, priority: priorityOf(row), age: ageLabel(hours), level: ageLevel(hours),
    }
  }
  return [
    ...paged.value.pinned.map((row, i) => decorate(row, i + 1)),
    ...paged.value.rest.map((row, i) => decorate(row, paged.value.pinned.length + paged.value.hiddenPinned + paged.value.restOffset + i + 1)),
  ]
})

const todayStats = computed(() => data.value?.today || { orders: 0, qty: 0, customers: 0, amount_usd: 0, amount_missing_orders: 0 })
const completion = computed(() => {
  const done = todayStats.value.orders
  const total = done + summary.value.total
  return total ? done / total : 0
})
const amountText = computed(() => {
  const value = Number(todayStats.value.amount_usd || 0)
  return value >= 10000 ? formatMoney(value, { precision: 1, notation: 'compact' }) : fmt(value)
})
</script>
