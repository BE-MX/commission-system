<template>
  <section v-if="data.customer_segments" class="decision-panel">
    <div class="section-heading"><div><h2>充值与非充值客户经营</h2><p>截至统计期末有实际充值入账记录即为充值客户；下单客户按组去重</p></div></div>
    <section v-for="group in data.customer_segments.groups" :key="group.key">
      <div class="section-heading"><h3>{{ group.label }}</h3><GlassButton variant="link" @click="$emit('evidence', group.evidence_refs)">核对订单与折让</GlassButton></div>
      <DecisionMetrics :data="group" :cards="segmentCards" />
    </section>
    <p class="decision-note">订单金额为筛选关联整单额；折让金额为命中明细每件折让 × 下单数量。{{ data.customer_segments.limitation }}</p>
  </section>
  <div v-else class="decision-notice">充值分组和意向观察需要资金阅读权限。</div>
  <section class="decision-panel">
    <div class="section-heading"><div><h2>门店复购与流失线索</h2><p>先看持续复购的门店，再核查购买节奏延后和长期未购的门店</p></div><el-select v-model="retentionFilter" aria-label="门店复购状态"><el-option label="全部门店" value="all" /><el-option v-for="status in retentionStatuses" :key="status" :label="label(status)" :value="status" /></el-select></div>
    <DecisionMetrics :data="data.retention?.summary" :cards="retentionCards" />
    <DecisionTable :rows="stores" :columns="retentionColumns" id-key="customer_id" action="查看门店画像" @open="row => $emit('profile', 'customer', row.customer_id)" />
    <p class="decision-note">{{ data.retention?.limitation }} 当前长期未购阈值 {{ data.retention?.dormant_days }} 天；产品筛选不改变门店完整商业购买周期。</p>
  </section>
  <section v-if="data.customer_segments" class="decision-panel">
    <div class="section-heading"><div><h2>客户充值意向观察</h2><p>从已发生行为找到询问切入点，客户真实意向待跟进确认</p></div></div>
    <DecisionTable :rows="data.customers" :columns="intentColumns" id-key="customer_id" action="行为证据" @open="row => $emit('evidence', row.recharge_behavior_refs)" />
    <p class="decision-note">原价下单要求成交价等于已知原价加手工费、每件折让为零。充值可能用于偿还欠款，折扣也可能来自手工调价，均需询问客户实际选择。</p>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { Money, UserFilled, Tickets, TrendCharts } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import DecisionMetrics from './DecisionMetrics.vue'
import DecisionTable from './DecisionTable.vue'
import { label } from '../state'
const props = defineProps({ data: Object })
defineEmits(['evidence', 'profile'])
const retentionFilter = ref('all')
const retentionStatuses = ['sustained_repeat', 'losing_rhythm', 'dormant', 'repeat_observed', 'sample_accumulating', 'no_system_purchase', 'inactive_store']
const stores = computed(() => props.data.customers.filter(row => retentionFilter.value === 'all' || row.retention_status === retentionFilter.value).sort((a, b) => retentionStatuses.indexOf(a.retention_status) - retentionStatuses.indexOf(b.retention_status) || (b.history.recency_days ?? -1) - (a.history.recency_days ?? -1)))
const segmentCards = [{ key: 'customer_count', label: '下单客户数量', icon: UserFilled, note: '同一客户不重复累计' }, { key: 'amount', label: '订单金额', format: 'money', icon: Money, note: '正常业务单关联整单额' }, { key: 'order_count', label: '订单数量', icon: Tickets, tone: 'info', note: '按订单去重' }, { key: 'discount_amount', label: '折让金额', format: 'money', icon: TrendCharts, tone: 'warning', note: '每件折让 × 命中明细数量' }]
const retentionCards = [{ key: 'sustained_repeat', label: '持续复购门店', icon: UserFilled, tone: 'success', note: '近三个月均购买且本期商业下单' }, { key: 'losing_rhythm', label: '购买周期延后', icon: TrendCharts, tone: 'warning', note: '距末次购买超过周期 1.5 倍' }, { key: 'dormant', label: '长期未购门店', icon: UserFilled, tone: 'warning', note: '达到配置的长期未购天数' }, { key: 'repeat_observed', label: '已观察复购', icon: Tickets, tone: 'info', note: '至少两个不同商业购买日' }]
const col = (key, text, format) => ({ key, label: text, format })
const retentionColumns = [col('shop_name', '门店'), col('retention_status', '经营信号'), col('order_count', '当期业务单', 'number'), col('history.purchase_days', '商业购买日', 'number'), col('history.last_purchase_date', '末次购买'), col('history.recency_days', '未购天数', 'number'), col('history.cycle_days', '周期天数', 'number'), col('history.cycle_basis', '周期依据')]
const intentColumns = [col('shop_name', '门店'), col('recharge_group', '充值分组'), col('recharge_behavior', '已观察行为'), col('recharge_intent', '真实意向'), col('amount', '订单金额', 'money'), col('discount_amount', '折让金额', 'money')]
</script>
