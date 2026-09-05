<template>
  <main class="daily-page">
    <header><h1>今日工作台</h1><p>从今天最需要处理的客户开始，登记结果并安排下次跟进。</p></header>
    <WorkbenchList ref="workbench" @open-customer="openCustomer" />
    <CustomerDetailDrawer v-model="drawerVisible" :customer="detail" :loading="detailLoading" :timeline="timeline" :timeline-total="timelineTotal" :timeline-loading="timelineLoading" :detail-error="detailError" :timeline-error="timelineError" :load-timeline="loadTimeline" :retry-detail="() => loadDetail(currentCustomerId)" @action-saved="workbench.refresh()" />
  </main>
</template>
<script setup>
import { ref } from 'vue'
import WorkbenchList from './WorkbenchList.vue'
import CustomerDetailDrawer from './CustomerDetailDrawer.vue'
import { useCustomerHub } from './composables/useCustomerHub'
const drawerVisible = ref(false), workbench = ref(null)
const { detail, detailLoading, detailError, timeline, timelineTotal, timelineLoading, timelineError, currentCustomerId, loadDetail, loadTimeline } = useCustomerHub('customers', { immediate: false })
async function openCustomer(id) { drawerVisible.value = true; await loadDetail(id) }
</script>
<style scoped>.daily-page { display: grid; gap: 20px; color: var(--text-primary); }.daily-page h1 { margin: 0 0 8px; font-size: 22px; }.daily-page header p { margin: 0; color: var(--text-secondary); line-height: 1.6; }</style>
