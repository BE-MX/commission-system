<template>
  <section>
    <div v-if="panel.summary" class="detail-metrics">
      <div><span>订单数量</span><strong>{{ panel.summary.ordered_quantity }} 件</strong></div>
      <div><span>检验已提交 · 已出库</span><strong>{{ panel.summary.shipped_quantity }} 件</strong></div>
      <div><span>尚未确认出库</span><strong>{{ Number(panel.summary.ordered_quantity) - Number(panel.summary.shipped_quantity) }} 件</strong></div>
    </div>
    <p class="detail-source">对应出库单提交检验完成即计入出库；草稿、撤回、同步中或待补验不计入。</p>
    <div class="detail-filter"><h3>关联出库单 <small>{{ panel.items?.length || 0 }} 张 · 仅本订单关联明细</small></h3><el-input v-model="keyword" clearable placeholder="搜索出库单号 / 批次" aria-label="搜索关联出库单" /></div>
    <el-empty v-if="!documents.length" :description="keyword ? '没有符合条件的出库单' : panel.state === 'ready' ? '暂无关联出库单' : '实际出库单尚未核验'" :image-size="64" />
    <details v-for="doc in documents" :key="doc.id" class="detail-document" open>
      <summary><strong>{{ doc.number }}</strong><span>{{ formatInvoiceDateTime(doc.date) }}</span><span>{{ doc.quantity ?? '待核验' }} {{ doc.quantity != null ? '件' : '' }}</span><StatusBadge :type="detailStatus(doc.anomaly || doc.state).type">{{ detailStatus(doc.anomaly || doc.state).label }}</StatusBadge></summary>
      <p class="detail-source">制单人 {{ doc.maker_name || '镜像待刷新' }} · 检验 {{ inspectionLabel(doc.inspection) }}</p>
      <el-table v-sticky-scrollbar :data="doc.items || []" class="list-table" border>
        <el-table-column prop="product_name" label="本订单关联商品 / 规格" min-width="260" max-width="600" />
        <el-table-column prop="quantity" label="本次数量（件）" min-width="130" max-width="160" align="right" />
        <el-table-column prop="ordered_quantity" label="订单数量（件）" min-width="130" max-width="160" align="right" />
      </el-table>
    </details>
    <h3 v-if="panel.tasks?.length">生成任务</h3>
    <div v-for="(task, index) in panel.tasks || []" :key="index" class="detail-document detail-task"><span>{{ task.number }}</span><StatusBadge :type="detailStatus(task.state).type">{{ detailStatus(task.state).label }}</StatusBadge><small>生成后须提交完成检验才计入出库进度</small></div>
    <h3 v-if="panel.batches?.length">预售发货批次 <small>计划数量不计入实际出库</small></h3>
    <details v-for="batch in batches" :key="batch.number" class="detail-document">
      <summary><strong>{{ batch.number }}</strong><StatusBadge :type="detailStatus(batch.state).type">{{ detailStatus(batch.state).label }}</StatusBadge><span>{{ batch.outbound_id ? '已关联出库单' : `第 ${batch.sequence} 批 · 待生成出库单` }}</span></summary>
      <p>本批冻结商品明细{{ batch.is_final ? ' · 末批' : '' }}</p>
      <p v-for="item in batch.items" :key="item.invoice_item_id">{{ item.product_name }} <strong>{{ item.quantity }} 件（计划）</strong><span v-if="item.line_amount != null"> · 单价 {{ formatMoney(item.sale_price,{precision:4}) }} · 本批净额 {{ formatMoney(item.line_amount) }} {{ batch.currency }}</span></p>
      <div v-if="batch.amounts" class="detail-totals"><span v-for="field in batchAmounts" :key="field[0]">{{ field[1] }} <strong>{{ formatMoney(batch.amounts[field[0]],{missing:'—'}) }}</strong> {{ batch.currency }}</span></div>
      <p v-else class="detail-source">本批资金信息不在当前查看权限或归属范围内</p>
    </details>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { detailStatus } from './invoiceDetailLabels'
import { formatInvoiceDateTime } from '../composables/invoiceDateTime'
import { formatMoney } from '@/utils/money'
const batchAmounts = [['goods_amount','本批商品净额'],['packaging_amount','包装费'],['handling_amount','手续费'],['freight_amount','独立运费'],['deposit_applied','预付款抵扣'],['goods_payment_due','本批应付商品款']]
const inspectionLabel = inspection => inspection?.state === 'restricted' ? '无查看权限' : inspection?.state !== 'ready' ? '镜像待刷新' : ({not_inspected:'未检验',draft:'检验草稿',submitted:'已提交'}[inspection.status] || inspection.status)
const props = defineProps({ panel: {type:Object,required:true} })
const keyword = ref('')
const matches = row => !keyword.value.trim() || row.number?.toLowerCase().includes(keyword.value.trim().toLowerCase())
const documents = computed(() => (props.panel.items || []).filter(matches))
const batches = computed(() => (props.panel.batches || []).filter(matches))
</script>
