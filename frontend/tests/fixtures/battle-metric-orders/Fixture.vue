<template>
  <main class="fixture">
    <h2>临时战报 · 明细验收（模拟数据）</h2>
    <el-tabs v-model="tab">
      <el-tab-pane v-for="item in tabs" :key="item.name" :label="item.label" :name="item.name">
        <ReportMetricOrders v-if="tab === item.name" :key="item.name" :report="report" :metric="item.name" />
      </el-tab-pane>
    </el-tabs>
  </main>
</template>
<script setup>
import { ref } from 'vue'
import ReportMetricOrders from '@/views/battle-report/components/ReportMetricOrders.vue'
const tab = ref('new_sign')
const report = { id: 1, members: [{ id: 1, user_name: '模拟业务员', team: 'A' }], detail_member_ids: [1] }
const tabs = [{ name: 'new_sign', label: '新签客户' }, { name: 'repeat', label: '复购客户' }, { name: 'combined', label: '新签+复购金额' }]
</script>
<style scoped>
.fixture { padding: 16px; max-width: 1440px; margin: auto; }
</style>
