<template>
  <div class="workspace-overview">
    <section class="lg-card panel">
      <h3>客户概要</h3>
      <el-descriptions v-if="customer" :column="2" size="small" border>
        <el-descriptions-item label="公司名">{{ customer.canonical_company_name || '—' }}</el-descriptions-item>
        <el-descriptions-item label="关系阶段">{{ customer.relationship_stage || '—' }}</el-descriptions-item>
        <el-descriptions-item label="档案完整度">{{ customer.profile_completeness ?? '—' }}%</el-descriptions-item>
        <el-descriptions-item label="客户编号">{{ customer.customer_code || '—' }}</el-descriptions-item>
      </el-descriptions>
    </section>
    <section class="lg-card panel">
      <h3>复购窗口 <span class="hint">基于商业订单周期 · 非库存预测</span></h3>
      <el-empty v-if="!windows.length" description="暂无可靠复购窗口" :image-size="60" />
      <div v-for="item in mappedWindows" :key="item.id" class="window-row">
        <strong>{{ item.productFamily }}</strong>
        <span>中位数 {{ item.medianIntervalDays ?? '—' }} 天</span>
        <span>{{ item.windowFrom }} ~ {{ item.windowTo }}</span>
        <el-tag size="small" :type="item.degraded ? 'warning' : 'success'">{{ item.confidenceLabel }}</el-tag>
      </div>
    </section>
    <section class="lg-card panel">
      <h3>当前待办</h3>
      <WorkbenchList :customer-id="customerId" scope="visible" @open-customer="noop" />
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getReorderWindows } from '@/api/customerHub'
import { mapReorderWindow } from '../customerWorkspaceController'
import WorkbenchList from '../WorkbenchList.vue'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const windows = ref([])
const mappedWindows = computed(() => windows.value.map(mapReorderWindow))
function noop() {}

onMounted(async () => {
  try {
    const response = await getReorderWindows(props.customerId, { state: 'open' })
    windows.value = response.data?.items ?? response.data ?? []
    if (!Array.isArray(windows.value)) windows.value = []
  } catch { windows.value = [] }
})
</script>

<style scoped>
.workspace-overview { display: grid; gap: 14px; }
.panel { padding: 14px 16px; }
.panel h3 { margin: 0 0 10px; font-size: 14px; }
.hint { font-size: 12px; color: var(--text-muted); font-weight: normal; }
.window-row { display: flex; gap: 12px; align-items: center; padding: 6px 0; font-size: 13px; color: var(--text-secondary); flex-wrap: wrap; }
</style>
