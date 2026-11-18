<template>
  <section class="summary-section" :class="`summary-section--${viewMode}`" aria-label="订单概览">
    <div class="summary-toolbar">
      <div class="summary-heading">
        <strong>订单概览</strong>
        <span>当前账号可见 · 已同步 · 排除取消中及已取消 · 按下单日期 · GMV 不含手续费</span>
      </div>
      <div class="summary-controls">
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        :clearable="false"
        aria-label="订单概览与列表日期范围"
        @change="$emit('range-change')"
      />
      <div class="summary-view-options" role="group" aria-label="订单概览显示方式">
        <button v-for="option in viewOptions" :key="option.value" type="button" :aria-pressed="viewMode === option.value" @click="viewMode = option.value">{{ option.label }}</button>
      </div>
      </div>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="summary-error" />
    <div v-show="viewMode !== 'collapsed'" v-loading="loading" class="summary-grid">
      <div class="summary-card summary-card--gmv lg-card is-static">
        <el-icon class="summary-card__icon" aria-hidden="true"><TrendCharts /></el-icon>
        <span>GMV（USD）</span>
        <strong>{{ summary ? money(summary.gmv) : '—' }}</strong>
        <el-icon class="summary-card__watermark" aria-hidden="true"><TrendCharts /></el-icon>
      </div>
      <div class="summary-card summary-card--received lg-card is-static">
        <el-icon class="summary-card__icon" aria-hidden="true"><Money /></el-icon>
        <span>回款金额（USD）</span>
        <strong>{{ summary?.received_amount == null ? '—' : money(summary.received_amount) }}</strong>
        <el-icon class="summary-card__watermark" aria-hidden="true"><Money /></el-icon>
      </div>
      <button type="button" class="summary-card summary-card--new lg-card is-static"
        title="按已标记新成交的客户去重，点击查看对应订单"
        :aria-pressed="activeMetric === 'new_sign'" @click="$emit('toggle-metric', 'new_sign')">
        <el-icon class="summary-card__icon" aria-hidden="true"><UserFilled /></el-icon>
        <el-icon v-if="activeMetric === 'new_sign'" class="summary-card__selected" aria-hidden="true"><Check /></el-icon>
        <span>新签个数</span>
        <strong>{{ summary?.new_sign_count ?? '—' }}</strong>
        <el-icon class="summary-card__watermark" aria-hidden="true"><UserFilled /></el-icon>
      </button>
      <button type="button" class="summary-card summary-card--return lg-card is-static"
        title="按已标记首返的客户去重，点击查看对应订单"
        :aria-pressed="activeMetric === 'first_return'" @click="$emit('toggle-metric', 'first_return')">
        <el-icon class="summary-card__icon" aria-hidden="true"><Refresh /></el-icon>
        <el-icon v-if="activeMetric === 'first_return'" class="summary-card__selected" aria-hidden="true"><Check /></el-icon>
        <span>首返个数</span>
        <strong>{{ summary?.first_return_count ?? '—' }}</strong>
        <el-icon class="summary-card__watermark" aria-hidden="true"><Refresh /></el-icon>
      </button>
      <div class="summary-card summary-card--orders lg-card is-static">
        <el-icon class="summary-card__icon" aria-hidden="true"><Tickets /></el-icon>
        <span>总下单数</span>
        <strong>{{ summary?.order_count ?? '—' }}</strong>
        <el-icon class="summary-card__watermark" aria-hidden="true"><Tickets /></el-icon>
      </div>
    </div>
    <p v-if="summary?.received_amount_partial" class="summary-note">回款金额仅汇总当前可查看且已核验的部分订单。</p>
    <p v-else-if="summary && summary.received_amount == null" class="summary-note">当前暂无可显示的已核验回款金额。</p>
    <p v-if="summary?.non_usd_count" class="summary-note">
      {{ summary.non_usd_count }} 张非 USD 发票参与数量统计，金额统计仅包含 USD 发票。
    </p>
    <p v-if="summary?.unknown_new_sign_count" class="summary-note">
      {{ summary.unknown_new_sign_count }} 张历史发票缺少新成交标记，未计入新签个数。
    </p>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Check, Money, Refresh, Tickets, TrendCharts, UserFilled } from '@element-plus/icons-vue'

defineProps({
  summary: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  money: { type: Function, required: true },
  activeMetric: { type: String, default: '' },
})
defineEmits(['range-change', 'toggle-metric'])
const viewOptions = [{ value: 'compact', label: '紧凑' }, { value: 'expanded', label: '展开' }, { value: 'collapsed', label: '收起' }]
const viewMode = ref('compact')
try {
  const saved = localStorage.getItem('invoice-overview-view')
  if (viewOptions.some(option => option.value === saved)) viewMode.value = saved
} catch { /* Browser preferences may be unavailable. */ }
watch(viewMode, value => { try { localStorage.setItem('invoice-overview-view', value) } catch { /* Keep the current view. */ } })
const dateRange = defineModel('dateRange', { type: Array, required: true })
</script>

<style scoped src="./invoice-overview.css"></style>
