<template>
  <section class="decision-panel">
    <div class="section-heading"><div><h2>哪些款式持续出货，哪些偶发出货？</h2><p>按发货完成报工日期看实际出货，包含以前下单、本期出货的产品</p></div><el-select v-model="demandFilter" aria-label="款式出货类型"><el-option label="全部款式" value="all" /><el-option label="持续畅销观察" value="steady_seller" /><el-option label="偶发出货 / 样本待积累" value="occasional_shipping" /><el-option label="本期下单尚未出货" value="ordered_not_shipped" /><el-option label="仅售后 / 零价出货" value="noncommercial_shipping" /></el-select></div>
    <DecisionTable :rows="products" :columns="demandColumns" id-key="key" action="出货与订单证据" @open="row => $emit('evidence', row.evidence_refs)" />
    <p class="decision-note">持续畅销观察仅使用正价、非售后的商业报工样本，需至少 3 个出货日、跨 2 周、2 位下单客户及 2 个下单日期；只反映本次样本。发货复现客户数按多个发货日观察，不等于多次下单。客户集中度高的款式需核对是否依赖单个大客户。</p>
  </section>
  <section v-if="data.production_operations" class="decision-panel">
    <div class="section-heading"><div><h2>毛坯补货速度与积压线索</h2><p>{{ data.production_operations.includes_unassigned_production ? '含授权的无客户生产单' : '当前仅含授权客户关联生产单；全量无客户生产单需全量经营及内贸全量订单权限' }}</p></div></div>
    <DecisionTable :rows="data.production_operations.rows" :columns="supplyColumns" id-key="key" action="入出库与生产证据" @open="row => $emit('evidence', row.evidence_refs)" />
    <p class="decision-note">{{ data.production_operations.limitation }}</p>
  </section>
  <section class="decision-panel">
    <h2>产品利润核算条件</h2>
    <div class="decision-notice"><strong>缺成本，待核算</strong><span>生产单售价为零，订单手工费属于收入。材料、加工及其他成本尚未关联到内贸款式，当前不能判断哪些产品利润好。</span></div>
    <p class="decision-note">当前优先核对持续出货、客户分布、下单至入库周期和长期在制量。补齐款式成本、期初库存与批次消耗记录后，才能核算毛利与真实库存风险。</p>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import DecisionTable from './DecisionTable.vue'
const props = defineProps({ data: Object })
defineEmits(['evidence'])
const demandFilter = ref('all')
const products = computed(() => props.data.products.filter(row => demandFilter.value === 'all' || row.demand_status === demandFilter.value))
const col = (key, text, format) => ({ key, label: text, format })
const demandColumns = [col('label', '款式组合'), col('demand_status', '需求信号'), col('shipped_quantity', '发货件数', 'number'), col('shipped_amount', '发货出库金额', 'money'), col('shipping_days', '全部出货天数', 'number'), col('commercial_shipping_days', '商业出货天数', 'number'), col('commercial_shipping_customer_count', '商业出货客户', 'number'), col('shipping_order_days', '下单日期数', 'number'), col('shipping_customer_count', '出货客户数', 'number'), col('repeat_shipping_customer_count', '发货复现客户', 'number'), col('top_customer_quantity_share', '最大客户件数占比', 'percent'), col('previous_shipping_quantity', '对照期出货件数', 'number')]
const supplyColumns = [col('label', '毛坯规格'), col('production_received_quantity', '生产入库件数', 'number'), col('blank_issued_quantity', '业务毛坯出库', 'number'), col('production_wip_quantity', '未入库在制量', 'number'), col('aged_wip_quantity', '90天以上在制量', 'number'), col('production_cycle_days', '下单至整行入库天数', 'number'), col('production_completed_item_count', '完工明细样本', 'number'), col('replenishment_status', '相对补货速度'), col('inventory_signal', '供需观察信号'), col('inventory_quantity', '真实库存', 'number')]
</script>
