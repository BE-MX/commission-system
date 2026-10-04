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
    :max-height="560"
    @sort-change="changeSort" v-sticky-scrollbar>
    <el-table-column sortable="custom" prop="collection_date" label="回款日期" min-width="104" max-width="140" show-overflow-tooltip>
      <template #default="{ row }">{{ row.isMonthGroup ? `${row.month}（${row.children.length} 笔）` : row.collection_date }}</template>
    </el-table-column>
    <el-table-column sortable="custom" prop="salesperson_name" label="业务员" min-width="92" max-width="130" show-overflow-tooltip>
      <template #default="{ row }">{{ row.isMonthGroup ? '月度汇总' : (row.salesperson_name || row.salesperson_id || '') }}</template>
    </el-table-column>
    <el-table-column sortable="custom" prop="order_name" label="订单名称" min-width="122" max-width="240" show-overflow-tooltip>
      <template #default="{ row }">{{ row.isMonthGroup ? '' : (row.order_name || row.order_no || row.order_id) }}</template>
    </el-table-column>
    <el-table-column sortable="custom" prop="customer_name" label="客户" min-width="140" max-width="240" show-overflow-tooltip />
    <el-table-column sortable="custom" prop="customer_country" label="国家" min-width="76" max-width="120" show-overflow-tooltip />
    <el-table-column sortable="custom" prop="payment_amount" label="回款金额（美元）" min-width="112" max-width="160" align="right">
      <template #default="{ row }">{{ usd(row.isMonthGroup ? row.total_payment_amount : row.payment_amount) }}</template>
    </el-table-column>
    <el-table-column sortable="custom" prop="service_fee" label="服务费（美元）" min-width="104" max-width="150" align="right">
      <template #default="{ row }">{{ usd(row.isMonthGroup ? row.total_service_fee : row.service_fee) }}</template>
    </el-table-column>
    <el-table-column sortable="custom" :prop="roleField(role, 'rate')" label="提成比例" min-width="82" max-width="120" align="right">
      <template #default="{ row }">{{ row.isMonthGroup ? '' : commissionRate(row[roleField(role, 'rate')]) }}</template>
    </el-table-column>
    <el-table-column sortable="custom" :prop="roleField(role, 'commission')" label="提成金额（美元）" min-width="112" max-width="160" align="right">
      <template #default="{ row }">{{ usd(row.isMonthGroup ? row.total_commission : row[roleField(role, 'commission')]) }}</template>
    </el-table-column>
    <el-table-column sortable="custom" prop="type" label="付款方式" min-width="92" max-width="140" show-overflow-tooltip />
    <el-table-column sortable="custom" prop="order_source" label="订单来源" min-width="96" max-width="150" show-overflow-tooltip />
    <el-table-column sortable="custom" prop="calc_rule_note" label="计算说明" min-width="150" max-width="260" show-overflow-tooltip />
  </el-table>
</template>

<script setup>
// 提成明细树表：明细行按回款月份聚成分组行（分组/汇总口径见 commissionGrouping.js），
// 行底色与选中样式在 commission.css（.cm-month-group-*）统一定义。
import { computed, ref } from 'vue'
import { getSortValue, sortTableTree } from '../../../utils/tableSort.js'
import { commissionRate, usd } from '../commissionFormat'
import { groupedRows, roleField } from '../commissionGrouping'

const props = defineProps({
  rows: { type: Array, required: true },
  role: { type: String, required: true },
})

const sort = ref({ prop: '', order: null })
const tableRows = computed(() => sortTableTree(groupedRows(props.rows, props.role), sort.value.prop, sort.value.order, sortValue))

function changeSort({ prop, order }) { sort.value = { prop, order } }

function sortValue(row) {
  const field = sort.value.prop
  if (row.isMonthGroup) {
    return {
      collection_date: row.month === '未设置日期' ? null : row.month,
      payment_amount: row.total_payment_amount,
      service_fee: row.total_service_fee,
      [roleField(props.role, 'commission')]: row.total_commission,
    }[field] ?? null
  }
  if (field === 'salesperson_name') return row.salesperson_name || row.salesperson_id || null
  if (field === 'order_name') return row.order_name || row.order_no || row.order_id || null
  return getSortValue(row, field)
}

function cellClassName({ row }) {
  return row.isMonthGroup ? 'cm-month-group-cell' : ''
}

function rowClassName({ row, rowIndex }) {
  if (!row.isMonthGroup) return ''
  return rowIndex % 2 === 0 ? 'cm-month-group-row cm-month-group-row-a' : 'cm-month-group-row cm-month-group-row-b'
}
</script>
