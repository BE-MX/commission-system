<template>
  <el-table
    :data="tableRows"
    border
    class="list-table cm-detail-table"
    empty-text="暂无明细"
    row-key="id"
    default-expand-all
    :cell-class-name="cellClassName"
    :row-class-name="rowClassName"
    :tree-props="{ children: 'children' }"
    :max-height="560" v-sticky-scrollbar>
    <el-table-column prop="collection_date" label="回款日期" min-width="104" max-width="140" show-overflow-tooltip>
      <template #default="{ row }">{{ row.isMonthGroup ? `${row.month}（${row.children.length} 笔）` : row.collection_date }}</template>
    </el-table-column>
    <el-table-column prop="salesperson_name" label="业务员" min-width="92" max-width="130" show-overflow-tooltip>
      <template #default="{ row }">{{ row.isMonthGroup ? '月度汇总' : (row.salesperson_name || row.salesperson_id || '') }}</template>
    </el-table-column>
    <el-table-column label="订单名称" min-width="122" max-width="240" show-overflow-tooltip>
      <template #default="{ row }">{{ row.isMonthGroup ? '' : (row.order_name || row.order_no || row.order_id) }}</template>
    </el-table-column>
    <el-table-column prop="customer_name" label="客户" min-width="140" max-width="240" show-overflow-tooltip />
    <el-table-column prop="customer_country" label="国家" min-width="76" max-width="120" show-overflow-tooltip />
    <el-table-column label="回款金额（美元）" min-width="112" max-width="160" align="right">
      <template #default="{ row }">{{ usd(row.isMonthGroup ? row.total_payment_amount : row.payment_amount) }}</template>
    </el-table-column>
    <el-table-column label="服务费（美元）" min-width="104" max-width="150" align="right">
      <template #default="{ row }">{{ usd(row.isMonthGroup ? row.total_service_fee : row.service_fee) }}</template>
    </el-table-column>
    <el-table-column label="提成比例" min-width="82" max-width="120" align="right">
      <template #default="{ row }">{{ row.isMonthGroup ? '' : commissionRate(row[roleField(role, 'rate')]) }}</template>
    </el-table-column>
    <el-table-column label="提成金额（美元）" min-width="112" max-width="160" align="right">
      <template #default="{ row }">{{ usd(row.isMonthGroup ? row.total_commission : row[roleField(role, 'commission')]) }}</template>
    </el-table-column>
    <el-table-column prop="type" label="付款方式" min-width="92" max-width="140" show-overflow-tooltip />
    <el-table-column prop="order_source" label="订单来源" min-width="96" max-width="150" show-overflow-tooltip />
    <el-table-column prop="calc_rule_note" label="计算说明" min-width="150" max-width="260" show-overflow-tooltip />
  </el-table>
</template>

<script setup>
// 提成明细树表：明细行按回款月份聚成分组行（分组/汇总口径见 commissionGrouping.js），
// 行底色与选中样式在 commission.css（.cm-month-group-*）统一定义。
import { computed } from 'vue'
import { commissionRate, usd } from '../commissionFormat'
import { groupedRows, roleField } from '../commissionGrouping'

const props = defineProps({
  rows: { type: Array, required: true },
  role: { type: String, required: true },
})

const tableRows = computed(() => groupedRows(props.rows, props.role))

function cellClassName({ row }) {
  return row.isMonthGroup ? 'cm-month-group-cell' : ''
}

function rowClassName({ row, rowIndex }) {
  if (!row.isMonthGroup) return ''
  return rowIndex % 2 === 0 ? 'cm-month-group-row cm-month-group-row-a' : 'cm-month-group-row cm-month-group-row-b'
}
</script>
