<template>
  <div class="commission-metrics">
    <div
      v-for="card in cards"
      :key="card.key"
      class="commission-metric lg-card"
      :class="`commission-metric--${card.tone}`"
    >
      <div class="commission-metric__icon"><el-icon><component :is="card.icon" /></el-icon></div>
      <span>{{ card.label }}</span>
      <strong>{{ card.value }}</strong>
    </div>
  </div>
</template>

<script setup>
// 提成指标卡：回款总额 + 三种角色提成 + 总提成，样式与语义色在
// commission.css（.commission-metric--*）统一定义，本组件只组合数据。
import { computed } from 'vue'
import { Connection, Money, TrendCharts, User, UserFilled } from '@element-plus/icons-vue'
import { usd } from '../commissionFormat'

const props = defineProps({
  summary: { type: Object, default: () => ({}) },
  /** 口径说明（如选中月份），追加到每张卡的标签后 */
  suffix: { type: String, default: '' },
})

const cards = computed(() => {
  const s = props.summary || {}
  const label = (text) => (props.suffix ? `${text} · ${props.suffix}` : text)
  return [
    { key: 'payment', tone: 'payment', icon: Money, label: label('回款总额'), value: usd(s.total_payment_amount) },
    { key: 'sales', tone: 'sales', icon: User, label: label('业务员提成'), value: usd(s.total_salesperson_commission) },
    { key: 'supervisor', tone: 'supervisor', icon: UserFilled, label: label('一级主管提成'), value: usd(s.total_supervisor_commission) },
    { key: 'second', tone: 'second', icon: Connection, label: label('二级主管提成'), value: usd(s.total_second_supervisor_commission) },
    { key: 'total', tone: 'total', icon: TrendCharts, label: label('总提成'), value: usd(s.total_commission) },
  ]
})
</script>
