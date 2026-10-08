<template>
  <DetailDrawer v-model="state.open" :title="title" :width="760">
    <el-skeleton v-if="state.loading" :rows="8" animated />
    <el-alert v-else-if="state.error" :title="state.error" type="error" :closable="false" />
    <template v-else-if="state.data">
      <div class="profile-heading"><span class="person-avatar">{{ title.slice(0, 1) }}</span><div><h2>{{ title }}</h2><p>{{ state.data.meta?.period.start_date }} — {{ state.data.meta?.period.end_date }} · 当前授权范围</p></div></div>
      <template v-if="customer">
        <div class="filter-chips"><span>{{ customer.province || '省份未知' }} {{ customer.city }}</span><span>{{ customer.store_type || '门店类型未知' }}</span><span>{{ customer.customer_source || '来源未知' }}</span><span>{{ label(customer.history.cycle_status) }}</span></div>
        <DecisionMetrics :data="customer" :cards="customerCards" />
        <section class="decision-panel"><h2>完整购买历史</h2><div class="fact-grid"><div><span>系统累计销售额</span><strong>{{ money(customer.history.system_amount) }}</strong></div><div><span>档案历史销售额</span><strong>{{ money(customer.history.archival_amount) }}</strong></div><div><span>系统商业购买日</span><strong>{{ number(customer.history.purchase_days) }}</strong></div><div><span>商业订单数</span><strong>{{ number(customer.history.commercial_order_count) }}</strong></div><div><span>末次购买</span><strong>{{ customer.history.last_purchase_date || '未知' }}</strong></div><div><span>距末次购买</span><strong>{{ number(customer.history.recency_days) }} 天</strong></div><div><span>复购周期</span><strong>{{ number(customer.history.cycle_days) }} 天</strong></div><div><span>周期来源 / 同群样本</span><strong>{{ label(customer.history.cycle_basis) }} / {{ number(customer.history.cycle_peer_count) }}</strong></div></div><p class="decision-note">{{ label(customer.history.first_purchase_status) }} · 档案额与系统额分开，不相加。</p><p v-for="note in customer.history.history_limitations" :key="note" class="decision-note">{{ note }}</p><GlassButton variant="link" @click="$emit('evidence', customer.history.evidence_refs)">查看商业购买日证据</GlassButton><DecisionTable :rows="historyWindows" :columns="windowColumns" :paginate="false" /></section>
        <section class="decision-panel"><h2>RFM 与复购样本</h2><div class="fact-grid"><div><span>R · 距末次购买天数</span><strong>{{ number(customer.history.rfm.r) }}</strong></div><div><span>F · 180天购买日</span><strong>{{ number(customer.history.rfm.f) }}</strong></div><div><span>M · 180天商业金额</span><strong>{{ money(customer.history.rfm.m) }}</strong></div><div><span>同群样本</span><strong>{{ number(customer.history.rfm.peer_count) }}</strong></div></div><p class="decision-note">{{ label(customer.history.rfm.status) }} · {{ customer.history.rfm.scores ? `R/F/M 分数：${customer.history.rfm.scores.r}/${customer.history.rfm.scores.f}/${customer.history.rfm.scores.m}` : '同群不足 30 人不评分，不伪造客户价值等级。' }}</p></section>
        <section class="decision-panel"><div class="section-heading"><div><h2>常购规格与历史偏好</h2><p>{{ preferences.status === 'preference' ? '购买日与主要结构覆盖达到门槛' : '仅表示已观察购买，样本不足以声称稳定偏好' }}</p></div><el-radio-group v-model="preferencePeriod"><el-radio-button value="recent_180_days">近180天</el-radio-button><el-radio-button value="history">全部系统历史</el-radio-button></el-radio-group></div><DecisionTable :rows="preferences[preferencePeriod] || []" :columns="preferenceColumns" action="规格证据" @open="row => $emit('evidence', row.evidence_refs)" /><p class="decision-note">属性有效覆盖 {{ percent(preferences.effective_coverage) }} · {{ number(preferences.purchase_days) }} 个购买日；库存与交期仍需核对。</p></section>
        <section class="decision-panel"><h2>服务建议与共购观察</h2><InsightCards :insights="customerRecommendations" :customers="[customer]" @evidence="$emit('evidence', $event)" @action="$emit('action', $event)" /><div v-for="(pair, index) in preferences.co_purchase || []" :key="index" class="recommendation-pair"><strong>{{ pair.products.map(product => product.label).join(' + ') }}</strong><p>{{ pair.support_customer_count }}/{{ pair.peer_customer_count }} 位客户出现同单组合 · 支持度 {{ percent(pair.support) }} · Lift {{ number(pair.lift, 2) }}</p><p class="decision-note">{{ pair.limitation }} · 库存与交期未知。</p></div><p v-if="!preferences.co_purchase?.length" class="decision-note">共购样本未达到至少 20 位客户且 5 位支持客户的门槛，暂不生成交叉销售推断。</p></section>
      </template>
      <template v-else><DecisionMetrics :data="state.data.summary" :cards="personCards" /><div class="decision-notice">按当前客户归属统计；历史个人业绩归属未知。</div><section class="decision-panel"><h2>当前客户组合</h2><DecisionTable :rows="state.data.customers" :columns="personCustomerColumns" action="客户画像" @open="row => $emit('customer', row.customer_id)" /></section><section class="decision-panel"><h2>产品贡献</h2><DecisionTable :rows="state.data.products" :columns="personProductColumns" action="证据" @open="row => $emit('evidence', row.evidence_refs)" /></section></template>
      <section class="decision-panel"><h2>同周期成交趋势</h2><DecisionChart :title="`${title} · 画像成交走势`" :snapshot="state.data.meta" :rows="state.data.trend" value="amount" :columns="[{ key: 'date', label: '日期' }, { key: 'amount', label: '整单额', format: 'money' }, { key: 'matched_amount', label: '明细额', format: 'money' }]" @select="row => $emit('evidence', dayEvidence(row))" /></section>
      <section v-if="state.data.finance && financeAllowed" class="decision-panel"><h2>资金与会员口径</h2><template v-if="customer"><div class="filter-chips"><span>当前结算：{{ label(customer.settle_mode) }}</span><span>当前会员：{{ customer.membership_level || '未记录' }}</span></div><DecisionTable :rows="state.data.finance.customers" :columns="financeColumns" :paginate="false" /><DecisionTable :rows="state.data.finance.customers[0]?.monthly_balances || []" :columns="monthColumns" :paginate="false" /><p class="decision-note">月末余额使用历史账本，不以当前余额倒填；订单明细会员快照与当前会员分开。</p></template><template v-else><DecisionTable :rows="[state.data.finance.summary]" :columns="personFinanceColumns" :paginate="false" /></template><GlassButton variant="link" @click="$emit('evidence', state.data.finance.ledger.map(row => ({ type: 'ledger', id: row.id })))">查看资金流水</GlassButton><GlassButton variant="link" @click="$emit('evidence', state.data.finance.requests.map(row => ({ type: 'requests', id: row.id })))">申请证据</GlassButton></section>
      <section class="decision-panel"><h2>可核验事实</h2><InsightCards :insights="state.data.insights || []" :customers="state.data.customers || (customer ? [customer] : [])" @evidence="$emit('evidence', $event)" @action="$emit('action', $event)" @customer="$emit('customer', $event)" /></section>
      <p v-for="note in state.data.meta?.warnings" :key="note" class="decision-note">{{ note }}</p>
    </template>
  </DetailDrawer>
</template>
<script setup>
import { computed, ref } from 'vue'
import { Money, Tickets, Goods, UserFilled } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import DecisionMetrics from './DecisionMetrics.vue'
import DecisionTable from './DecisionTable.vue'
import DecisionChart from './DecisionChart.vue'
import InsightCards from './InsightCards.vue'
import { label, money, number, percent, FIELD_LABELS } from '../state'
const props = defineProps({ state: Object, financeAllowed: Boolean })
defineEmits(['evidence', 'customer', 'action'])
const preferencePeriod = ref('recent_180_days')
const customer = computed(() => props.state.data?.customer)
const title = computed(() => customer.value?.shop_name || props.state.data?.name || '经营画像')
const preferences = computed(() => customer.value?.preferences || {})
const customerRecommendations = computed(() => (customer.value?.recommendations || []).map(row => ({ ...row, customer_id: customer.value.customer_id })))
const historyWindows = computed(() => Object.entries(customer.value?.history.windows || {}).map(([days, row]) => ({ days, ...row })))
const col = (key, label, format) => ({ key, label, format })
const customerCards = [{ key: 'amount', label: '当期相关整单额', format: 'money', icon: Money, note: '当前画像周期' }, { key: 'matched_amount', label: '当期明细额', format: 'money', icon: Goods, tone: 'success', note: '画像使用该客户完整产品' }, { key: 'order_count', label: '当期订单数', icon: Tickets, tone: 'info', note: '有效业务订单' }]
const personCards = [...customerCards.slice(0, 2), { key: 'customer_count', label: '当期购买客户', icon: UserFilled, note: '当前归属组合', tone: 'info' }]
const windowColumns = [col('days', '观察窗口（天）'), col('amount', '商业购买额', 'money'), col('purchase_days', '购买日数', 'number')]
const preferenceColumns = [...['product_type', 'craft', 'size', 'length', 'color'].map(field => col(`attrs.${field}`, FIELD_LABELS[field])), col('quantity', '数量', 'number'), col('quantity_share', '近180天数量占比', 'percent'), col('amount', '成交额', 'money'), col('purchase_days', '购买日', 'number'), col('last_purchase_date', '末次购买')]
const personCustomerColumns = [col('shop_name', '客户'), col('province', '省份'), col('amount', '周期整单额', 'money'), col('history.recency_days', '距末购天数', 'number'), col('history.cycle_status', '节奏')]
const personProductColumns = [col('label', '产品组合'), col('amount', '成交額', 'money'), col('quantity', '数量', 'number'), col('customer_count', '客户数', 'number')]
const financeColumns = [col('opening_balance', '期初余额', 'money'), col('closing_balance', '期末余额', 'money'), col('recharge_amount', '当期充值', 'money'), col('debt_improvement', '充值改善欠款', 'money'), col('pending_recharge_amount', '待审核充值', 'money'), col('coverage_days', '覆盖天数', 'number'), col('coverage_status', '状态'), col('recharge_cycle_days', '充值周期天数', 'number'), col('bridge_difference', '资金桥差异', 'money'), col('current_reconciliation_difference', '当前余额对账差', 'money')]
const monthColumns = [col('month', '已完成月份'), col('closing_balance', '账本月末余额', 'money'), col('debt', '月末欠款', 'money'), col('ledger_id', '依据流水ID')]
const personFinanceColumns = [col('recharge_amount', '充值额', 'money'), col('net_order_deduction', '净订单扣款', 'money'), col('positive_balance', '正余额', 'money'), col('debt', '欠款', 'money'), col('anomaly_count', '账链异常', 'number')]
function dayEvidence(row) { return (props.state.data.evidence?.orders || []).filter(order => order.order_date === row.date).map(order => ({ type: 'orders', id: order.id })) }
</script>
