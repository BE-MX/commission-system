<template>
  <DetailDrawer v-model="state.open" :title="state.title || '事实证据'" :width="760">
    <p class="decision-note">分析与证据列表绑定快照；打开原始记录时重新鉴权，记录为当前源状态。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <DecisionTable :rows="state.refs || []" :columns="[{ key: 'type', label: '证据类型', get: row => typeLabels[row.type] || row.type }, { key: 'id', label: '记录ID' }]" action="打开原始记录" @open="load" />
    <section v-if="loading || record" class="decision-panel"><el-skeleton v-if="loading" :rows="5" animated /><template v-else><h2>{{ typeLabels[selected?.type] }} #{{ selected?.id }}</h2><dl class="evidence-record"><template v-for="(value, key) in record" :key="key"><dt>{{ fieldLabels[key] || FIELD_LABELS[key] || key }}</dt><dd>{{ formatValue(value, key) }}</dd></template></dl></template></section>
  </DetailDrawer>
</template>
<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import DecisionTable from './DecisionTable.vue'
import { domesticDecisionApi as api } from '@/api/domesticDecision'
import { ORDER_STATUS_LABELS } from '@/api/domestic'
import { FIELD_LABELS, label, latestRequestGate, money } from '../state'
const props = defineProps({ state: Object, failure: Function })
const record = ref(null), selected = ref(null), error = ref(''), loading = ref(false), gate = latestRequestGate()
const typeLabels = { orders: '订单', order: '订单', items: '产品明细', item: '产品明细', ledger: '资金流水', requests: '申请', request: '申请' }
const fieldLabels = { id: '记录ID', domestic_no: '订单编号', order_date: '订单日期', customer_id: '客户ID', order_id: '订单ID', status: '当前状态', total_amount: '相关整单额', order_kind: '订单属性', deleted_flag: '删除标记', line_no: '明细序号', product_name: '产品名称', attrs_snapshot: '原始属性快照', order_qty: '数量', unit_price: '成交单价', labor_fee: '工费', membership_level_snapshot: '下单时会员快照', pricing_version: '历史价格版本', transaction_type: '流水类型', amount: '金额', balance_before: '发生前余额', balance_after: '发生后余额', created_at: '发生时间（北京时间）', request_type: '申请类型', reviewed_at: '审核时间（北京时间）' }
function formatValue(value, key) { if (key === 'status' && ['orders', 'order'].includes(selected.value?.type)) return ORDER_STATUS_LABELS[value] || label(value); if (key === 'deleted_flag') return value ? '是' : '否'; if (['total_amount', 'unit_price', 'labor_fee', 'amount', 'balance_before', 'balance_after'].includes(key)) return money(value); if (value && typeof value === 'object') return Object.entries(value).map(([field, item]) => `${FIELD_LABELS[field] || field}：${label(item)}`).join('；'); return label(value) }
async function load(ref) { const token = gate.next(); selected.value = ref; record.value = null; error.value = ''; loading.value = true; try { const data = await api.evidence(ref.type, ref.id); if (gate.isCurrent(token) && props.state.open) record.value = data } catch (cause) { if (gate.isCurrent(token)) error.value = props.failure(cause) } finally { if (gate.isCurrent(token)) loading.value = false } }
watch(() => props.state.refs, () => { gate.invalidate(); record.value = null; selected.value = null; error.value = ''; loading.value = false })
watch(() => props.state.open, value => { if (!value) gate.invalidate() })
onBeforeUnmount(() => gate.invalidate())
</script>
