<template>
  <main class="customer-workspace customer-hub"><GlassButton variant="link" @click="goBack">← 返回客户工作台</GlassButton><el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon /><GlassButton v-if="loadError" variant="secondary" @click="loadDetail">重新加载</GlassButton><CustomerBattleCard v-if="detail" :key="customerId" :customer-id="customerId" :customer="detail" :initial-tab="String(route.query.tab || 'overview')" @tab-change="changeTab" @refresh-customer="loadDetail" /></main>
</template>
<script setup>
import './customerHub.css'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCustomer } from '@/api/customerHub'
import CustomerBattleCard from './CustomerBattleCard.vue'
import { errorMessage } from './workbenchV2Controller'
const route=useRoute(),router=useRouter(),customerId=computed(()=>Number(route.params.id)),detail=ref(null),loadError=ref('')
let latest=0
async function loadDetail(){const request=++latest;loadError.value='';try{const response=await getCustomer(customerId.value);if(request===latest)detail.value=response.data}catch(e){if(request===latest){detail.value=null;loadError.value=errorMessage(e)}}}
function changeTab(tab){router.replace({query:{...route.query,tab}})}
function goBack(){router.push({path:'/customer-hub/customers',query:Object.fromEntries(Object.entries(route.query).filter(([key])=>key!=='tab'))})}
watch(customerId,()=>{detail.value=null;loadDetail()},{immediate:true})
</script>
<style scoped>.customer-workspace{display:grid;gap:16px;min-width:0;color:var(--text-primary)}</style>
