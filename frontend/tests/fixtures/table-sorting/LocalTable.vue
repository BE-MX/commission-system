<template>
  <div class="table-card">
    <FilterBar><el-input placeholder="筛选" class="filter-w-md" /></FilterBar>
    <div class="action-bar"><GlassButton>导入</GlassButton></div>
    <el-table :data="rows" row-key="id" border>
      <el-table-column type="selection" />
      <el-table-column label="基本信息">
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="amount" label="金额" min-width="100"><template #default="{ row }">{{ row.amount == null ? '—' : `$${row.amount}` }}</template></el-table-column>
      </el-table-column>
      <el-table-column prop="date" label="日期" min-width="130" />
      <el-table-column class-name="table-action-column" label="操作"><template #default="{ row }"><GlassButton variant="link" @click="row.amount = 5">编辑</GlassButton></template></el-table-column>
    </el-table>
    <DetailTable :rows="rows" :columns="[{ key: 'name', label: '明细名称' }, { key: 'computed_amount', label: '明细金额', sortValue: row => row.amount }]">
      <template #computed_amount="{ row }">{{ row.amount ?? '—' }}</template>
    </DetailTable>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import DetailTable from '@/components/production/DetailTable.vue'
const rows = ref([{ id: 1, name: '订单10', amount: 100, date: '2026-10-02' },
  { id: 2, name: '订单2', amount: 2, date: '2026-01-03' },
  { id: 3, name: '订单1', amount: null, date: null },
  { id: 4, name: '订单3', amount: 20, date: '2026-09-03' }])
</script>
