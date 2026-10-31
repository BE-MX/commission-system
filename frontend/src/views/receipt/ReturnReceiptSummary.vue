<template>
  <div>
    <div class="detail-status"><StatusBadge type="info">退货退款</StatusBadge><StatusBadge type="info">仅方舟记账</StatusBadge></div>
    <h1 class="detail-amount">{{ receipt.currency }} {{ money(receipt.amount) }}</h1>
    <el-alert title="此凭证记录退货退款的财务事实，实际付款以退货单资金证据为准。退货详情需退货查看权限。" type="info" :closable="false" show-icon />
    <ResponsiveDescriptions :column="1" border class="receipt-descriptions">
      <el-descriptions-item label="退款凭证">{{ receipt.receipt_no }}</el-descriptions-item>
      <el-descriptions-item label="原订单">{{ receipt.order_no || receipt.order_id || '—' }}</el-descriptions-item>
      <el-descriptions-item label="订单发票">{{ receipt.invoice_no || '历史订单未关联方舟发票' }}</el-descriptions-item>
      <el-descriptions-item label="客户">{{ receipt.customer_name }}</el-descriptions-item>
      <el-descriptions-item label="记账日期">{{ receipt.collection_date }}</el-descriptions-item>
      <el-descriptions-item label="备注">{{ receipt.remark || '—' }}</el-descriptions-item>
    </ResponsiveDescriptions>
  </div>
</template>
<script setup>
import { money } from './useReceipts'
defineProps({ receipt: { type: Object, required: true } })
</script>
