<template>
  <section class="decision-panel">
    <div class="section-heading"><div><h2>发型师工作量</h2><p>统计 {{ applied.start_date }} 至 {{ applied.end_date }}（北京时间）的“做发型”有效报工</p></div>
      <el-select v-model="stylistId" aria-label="选择发型师" clearable placeholder="全部发型师"><el-option v-for="person in data.people" :key="person.user_id" :value="person.user_id" :label="person.name" /></el-select>
    </div>
    <p class="decision-note">沿用上方已应用的客户范围和产品筛选；件数为报工数量之和，涉及明细按明细ID去重。分批报工、多人协作分别计入各自工作量，不代表整单已完工。已撤销报工、已删除及无效状态订单不计入。</p>
    <DecisionMetrics :data="summary" :cards="cards" />
    <DecisionTable :rows="people" :columns="peopleColumns" id-key="user_id" action="查看报工明细" @open="row => $emit('rows', 'stylist_reports', { stylist_id: row.user_id }, row.name + ' · 做发型报工')" />
    <p class="decision-note">对照件数按上方对照周期的报工日期统计；跨发型师的明细数、订单数可能重叠。当前未记录耗时和难度系数，件数不等于效率或计件工资。</p>
  </section>
  <div class="decision-grid">
    <section class="decision-panel"><div class="section-heading"><h2>完成件数趋势</h2><el-select v-model="grain" aria-label="报工时间粒度"><el-option label="按日" value="day" /><el-option label="按月" value="month" /></el-select></div>
      <DecisionChart title="做发型完成件数趋势" :rows="trend" value="quantity" :columns="trendColumns" @select="row => $emit('evidence', row.evidence_refs)" />
    </section>
    <section class="decision-panel"><div class="section-heading"><h2>产品属性分布</h2><el-select v-model="dimension" aria-label="发型师分析维度"><el-option v-for="field in fields" :key="field" :label="FIELD_LABELS[field]" :value="field" /></el-select></div>
      <DecisionChart :title="FIELD_LABELS[dimension] + ' · 完成件数'" type="bar" x="label" value="quantity" :rows="dimensionRows" :columns="dimensionColumns" @select="row => $emit('evidence', row.evidence_refs)" />
    </section>
  </div>
  <section class="decision-panel"><h2>发型师 × {{ FIELD_LABELS[dimension] }}</h2>
    <DecisionChart :title="'发型师 × ' + FIELD_LABELS[dimension]" type="heatmap" x="x" :rows="matrix" :columns="matrixColumns" @select="row => $emit('evidence', row.evidence_refs)" />
  </section>
  <section class="decision-panel"><h2>完成产品与型号明细</h2>
    <DecisionTable :rows="products" :columns="productColumns" action="原始报工证据" @open="row => $emit('evidence', row.evidence_refs)" />
  </section>
  <section class="decision-panel"><h2>做发型报工记录</h2>
    <DecisionTable :rows="details" :columns="detailColumns" action="原始证据" @open="row => $emit('evidence', [{ type: 'reports', id: row.id }])" />
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import DecisionTable from './DecisionTable.vue'
import DecisionChart from './DecisionChart.vue'
import DecisionMetrics from './DecisionMetrics.vue'
import { FIELD_LABELS } from '../state'
import { groupStylistFacts, stylistTotals } from '../stylistState'
const props = defineProps({ data: { type: Object, required: true }, applied: { type: Object, required: true } })
defineEmits(['evidence', 'rows'])
const stylistId = ref(null), dimension = ref('hair_style_series'), grain = ref('day')
const fields = ['product_type', 'craft', 'net_color', 'size', 'length', 'density', 'hair_style_series', 'color']
const col = (key, label, format) => ({ key, label, format })
const details = computed(() => props.data.details.filter(row => !stylistId.value || row.user_id === stylistId.value))
const people = computed(() => props.data.people.filter(row => !stylistId.value || row.user_id === stylistId.value))
const summary = computed(() => stylistTotals(details.value))
const cards = [
  { key: 'quantity', label: '完成件数', note: '有效做发型报工数量之和' },
  { key: 'item_count', label: '涉及明细数', note: '按明细ID去重，不等于已整行完工' },
  { key: 'report_count', label: '报工次数', note: '有效报工记录数' },
  { key: 'active_days', label: '报工天数', note: '北京时间报工日期去重' },
]
const peopleColumns = [col('name', '发型师'), col('quantity', '完成件数', 'number'), col('item_count', '涉及明细数', 'number'), col('order_count', '涉及订单数', 'number'), col('report_count', '报工次数', 'number'), col('active_days', '报工天数', 'number'), col('previous_quantity', '对照件数', 'number'), col('quantity_change', '件数变化', 'number')]
const trendColumns = [col('date', '报工日期'), col('quantity', '完成件数', 'number'), col('report_count', '报工次数', 'number')]
const trend = computed(() => groupStylistFacts(details.value, row => row.reported_at.slice(0, grain.value === 'day' ? 10 : 7)).map(row => ({ ...row, date: row.key })).sort((a, b) => a.date.localeCompare(b.date)))
const dimensionRows = computed(() => groupStylistFacts(details.value, row => row.attrs[dimension.value]))
const dimensionColumns = computed(() => [col('label', FIELD_LABELS[dimension.value]), col('quantity', '完成件数', 'number'), col('item_count', '涉及明细数', 'number')])
const matrix = computed(() => (props.data.dimensions[dimension.value] || []).filter(row => !stylistId.value || row.user_id === stylistId.value).map(row => ({ ...row, x: row.name + ' (#' + row.user_id + ')', y: row[dimension.value], value: row.quantity })))
const matrixColumns = computed(() => [col('name', '发型师'), col(dimension.value, FIELD_LABELS[dimension.value]), col('quantity', '完成件数', 'number')])
const products = computed(() => props.data.products.filter(row => !stylistId.value || row.user_id === stylistId.value))
const productColumns = [col('name', '发型师'), col('product_name', '型号 / 产品'), ...fields.map(field => col(field, FIELD_LABELS[field])), col('quantity', '完成件数', 'number'), col('item_count', '涉及明细数', 'number'), col('report_count', '报工次数', 'number')]
const detailColumns = [col('reported_at', '报工时间（北京）'), col('name', '发型师'), col('domestic_no', '订单号'), col('item_id', '明细ID'), col('product_name', '型号 / 产品'), col('report_qty', '完成件数', 'number'), ...fields.map(field => col('attrs.' + field, FIELD_LABELS[field]))]
watch(() => props.data, data => { if (!data.people.some(row => row.user_id === stylistId.value)) stylistId.value = null })
</script>
