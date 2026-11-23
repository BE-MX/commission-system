<template>
  <DetailDrawer :model-value="modelValue" :title="`核对详情 · ${detail?.order_no || ''}`" :loading="loading" width="760px" @update:model-value="$emit('update:modelValue', $event)">
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <template v-if="detail">
      <section v-if="detail.exported_id"><h3>历史报关文件 #{{ detail.exported_id }}</h3><GlassButton variant="link" @click="$emit('download', 'order', detail.exported_id)">下载报关订单</GlassButton><GlassButton variant="link" @click="$emit('download', 'receipt', detail.exported_id)">下载报关收款单</GlassButton></section>
      <section><h3>核对结果</h3><el-alert v-for="issue in detail.issues" class="detail-alert" :key="issue.code" :type="issue.blocking ? 'error' : 'warning'" :title="issue.label" :description="issue.message || issueHints[issue.code] || '请核对原始申报、发票和物流信息后处理。'" :closable="false" /><StatusBadge v-if="!detail.issues?.length" type="success">核对通过</StatusBadge><div class="actions"><GlassButton v-for="action in actionsFor(detail)" :key="action.action" v-permission="'cross_border:write'" @click="$emit('review', detail, action.action)">{{ action.label }}</GlassButton></div></section>
      <section v-if="detail.row_type === 'declaration'"><h3>金额核对</h3><div class="comparison"><div>申报金额<strong>{{ money(detail.head_json?.goodsValue) }}</strong></div><div>{{ !detail.ticket && detail.reference_ticket ? '参考票金额（未配对）' : detail.ticket?.kind === 'split' ? '本票产品金额下限' : '票应付合计' }}<strong>{{ money(detail.ticket?.amount ?? detail.ticket?.product_floor ?? detail.reference_ticket?.amount ?? detail.reference_ticket?.product_floor) }}</strong></div><div>差额<strong>{{ money(detail.difference) }}</strong></div></div>
        <p v-if="detail.ticket?.kind === 'split' && ticketQuantities(detail.ticket)">分票发货：本票出库 {{ ticketQuantities(detail.ticket).shipped }} / 发票 {{ ticketQuantities(detail.ticket).total }} 件。费用各票各算，全部发完后核对组合计。</p>
        <p v-if="detail.ticket?.kind === 'split' && !ticketQuantities(detail.ticket)">本票出库件数无法计算，请核对出库明细。</p>
        <dl v-if="detail.split_group"><dt>分票组出库</dt><dd>{{ detail.split_group.shipped_quantity ?? '无法计算' }} / {{ detail.split_group.total_quantity }} 件 · {{ detail.split_group.complete ? '已发完，申报已全部配对' : '合计尚无法完整核验' }}</dd><dt>已配对申报小计</dt><dd>{{ money(detail.split_group.declared_total) }} USD</dd><dt>分票组应付合计</dt><dd>{{ money(detail.split_group.invoice_total) }} USD</dd></dl>
      </section>
      <section><h3>DHL 原始申报与收款</h3><p v-if="detail.row_type === 'ticket'">此票暂无匹配申报，请在 DHL 申报并导入最新订单文件。</p><p v-if="detail.row_type === 'receipt'">此收款单暂无同号同额申报，请导入最新订单文件。</p><dl><dt>商品金额</dt><dd>{{ detail.head_json?.goodsValue || '—' }}</dd><dt>运杂费</dt><dd>{{ detail.head_json?.freight || '—' }}</dd><dt>商品明细</dt><dd>{{ detail.line_json?.itemName || '—' }} · {{ detail.line_json?.qty || '—' }} × {{ detail.line_json?.price || '—' }}</dd><dt>收款金额</dt><dd>{{ detail.receipt_json?.charge || '—' }}</dd><dt>到账时间</dt><dd>{{ accountingTime(detail.receipt_json?.accountingDate) }}</dd></dl></section>
      <section><h3>方舟发票</h3><el-table border class="list-table" v-sticky-scrollbar :data="detail.invoices || detail.ticket?.invoices || []"><el-table-column label="发票号" min-width="130"><template #default="{ row }"><router-link :to="{ path: '/invoice/manage', query: { edit: row.id } }">{{ row.number || row.id }}</router-link><StatusBadge v-if="row.cancelled" type="danger">已取消</StatusBadge></template></el-table-column><el-table-column prop="salesperson" label="业务员" min-width="120" show-overflow-tooltip /><el-table-column prop="shop" label="店铺" min-width="100" show-overflow-tooltip /><el-table-column label="产品金额" :min-width="amountWidth('product_amount')" align="right"><template #default="{ row }">{{ money(row.product_amount) }}</template></el-table-column><el-table-column label="费用" :min-width="amountWidth('fees')" align="right"><template #default="{ row }">{{ money(row.fees) }}</template></el-table-column><el-table-column label="应付合计" :min-width="amountWidth('total_amount', true)" align="right" class-name="invoice-total-column"><template #default="{ row }"><span class="invoice-total">{{ money(row.total_amount) }} {{ row.currency }}</span></template></el-table-column></el-table></section>
      <section v-if="detail.ticket"><h3>运单与验货单</h3><GlassButton v-permission="'tracking:write'" :loading="refreshing" @click="$emit('refresh-tracking', detail)">立即刷新物流</GlassButton><dl><dt>运单号</dt><dd><router-link :to="`/tracking/${encodeURIComponent(detail.ticket.waybill_no)}`">{{ detail.ticket.waybill_no }}</router-link>（{{ detail.ticket.carrier }}）</dd><dt>物流状态</dt><dd>{{ TRACKING_STATUS_LABELS[detail.ticket.logistics_status] || detail.ticket.logistics_status || '—' }}</dd><dt>揽收事件</dt><dd>{{ detail.ticket.picked_up ? '已有有效揽收事件' : '尚无有效揽收事件' }}</dd><dt>上传物流单时间</dt><dd>{{ formatBeijingDateTime(detail.ticket.bound_at) }}</dd><dt>验货单</dt><dd><router-link v-for="id in detail.ticket.inspection_ids || []" :key="id" :to="{ path: '/shipping/inspections', query: { inspection_id: String(id) } }" class="inspection-link">验货单 #{{ id }}</router-link></dd></dl></section>
      <section><h3>操作记录</h3><el-timeline><el-timeline-item v-for="(item, index) in detail.audit || detail.reviews || []" :key="index" :timestamp="formatBeijingDateTime(item.created_at)">{{ actionLabels[item.action] || '核对处理' }} · {{ item.actor_name || '操作人信息待补充' }}<p>{{ item.reason }}</p></el-timeline-item></el-timeline><p v-if="!(detail.audit || detail.reviews)?.length">暂无人工处理记录</p></section>
    </template>
  </DetailDrawer>
</template>
<script setup>
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { formatBeijingDateTime } from '@/utils/datetime'
import { TRACKING_STATUS_LABELS } from '@/views/tracking/trackingStatus.js'
import { accountingTime, actionLabels, actionsFor, issueHints, money, ticketQuantities } from './reviewPresentation.js'
const props = defineProps({ modelValue: Boolean, detail: Object, loading: Boolean, error: String, refreshing: Boolean })
defineEmits(['update:modelValue', 'review', 'download', 'refresh-tracking'])
function amountWidth(field, includeCurrency = false) {
  const invoices = props.detail?.invoices || props.detail?.ticket?.invoices || []
  return Math.max(includeCurrency ? 210 : 140, ...invoices.map(invoice => {
    const text = money(invoice[field]) + (includeCurrency ? ` ${invoice.currency || ''}` : '')
    return text.length * 9 + 32
  }))
}
</script>
<style scoped>
section { margin-bottom: 24px; }
h3 { font-size: 14px; margin: 0 0 14px; }
.detail-alert { margin-bottom: 10px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.comparison { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.comparison div { padding: 14px; background: var(--tag-neutral-bg); border-radius: 8px; font-size: 12px; }
.comparison strong { display: block; margin-top: 10px; font-size: 20px; font-variant-numeric: tabular-nums; }
dl { display: grid; grid-template-columns: 120px 1fr; gap: 12px; font-size: 13px; }
dt { color: var(--text-secondary); }
dd { margin: 0; overflow-wrap: anywhere; }
.invoice-total { display: inline-block; white-space: nowrap; font-variant-numeric: tabular-nums; }
.inspection-link { margin-right: 12px; }
@media (max-width: 540px) { .comparison { grid-template-columns: 1fr; } dl { grid-template-columns: 100px 1fr; } }
</style>
