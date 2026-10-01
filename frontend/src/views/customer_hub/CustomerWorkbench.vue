<template><main class="customer-workbench customer-hub"><header><span class="kicker">CUSTOMER OPERATIONS</span><h1>客户工作台</h1><p>围绕客户目标推进事项、核验准备结果，再登记真实行动与业务结果。</p></header><el-tabs v-model="mode"><el-tab-pane label="客户事项" name="items"><WorkbenchList v-if="mode==='items'" ref="workbench" :initial-item-id="route.query.item_id ? Number(route.query.item_id) : null" @open-customer="openCustomer" /></el-tab-pane><el-tab-pane v-if="canReadCustomers" label="客户组合" name="customers" lazy><CustomerDirectory v-if="mode==='customers'" @open-customer="openCustomer" /></el-tab-pane></el-tabs><CustomerDetailDrawer v-model="drawerVisible" :customer="detail" :loading="detailLoading" :detail-error="detailError" :retry-detail="()=>loadDetail(currentCustomerId)" /></main></template>
<script setup>
import './customerHub.css'
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useRoute } from 'vue-router'
import WorkbenchList from './WorkbenchList.vue'
import CustomerDirectory from './CustomerDirectory.vue'
import CustomerDetailDrawer from './CustomerDetailDrawer.vue'
import { useCustomerHub } from './composables/useCustomerHub'
const route=useRoute(),mode=ref(route.query.mode==='customers' && !route.query.item_id?'customers':'items'),drawerVisible=ref(false),workbench=ref(null)
const auth=useAuthStore(),canReadCustomers=computed(()=>auth.hasPermission('customer:read'))
if(!canReadCustomers.value)mode.value='items'
const {detail,detailLoading,detailError,currentCustomerId,loadDetail}=useCustomerHub('customers',{immediate:false})
async function openCustomer(id){drawerVisible.value=true;await loadDetail(id)}
if(route.query.customer_id && !route.query.item_id)openCustomer(Number(route.query.customer_id))
</script>
<style scoped>.customer-workbench{display:grid;gap:16px;min-width:0;color:var(--text-primary)}h1{font-size:17px;margin:6px 0}header p{margin:0;color:var(--text-secondary);line-height:1.6}.kicker{font-size:11px;letter-spacing:.12em;color:var(--color-primary)}</style>
