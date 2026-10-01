<template>
  <DetailDrawer class="customer-hub-drawer" append-to-body :model-value="modelValue" :title="customerTitle" width="min(980px, 100vw)" :loading="loading" @update:model-value="$emit('update:modelValue',$event)">
    <el-alert v-if="detailError" type="error" title="客户详情加载失败，请检查权限或网络后重试。" :closable="false" show-icon><template #default><GlassButton variant="link" @click="retryDetail">重试</GlassButton></template></el-alert>
    <template v-else-if="customer"><div class="detail-shortcuts"><router-link :to="{path:`/customer-hub/workspace/${customer.customer_id}`,query:{...route.query,tab:activeTab}}">打开完整作战卡</router-link><GlassButton variant="secondary" @click="retryDetail">刷新客户</GlassButton></div><CustomerBattleCard :key="customer.customer_id" :customer-id="customer.customer_id" :customer="customer" :initial-tab="initialTab" @tab-change="activeTab=$event" @refresh-customer="retryDetail" /></template>
  </DetailDrawer>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import DetailDrawer from '@/components/DetailDrawer.vue'
import CustomerBattleCard from './CustomerBattleCard.vue'
import { normalizeWorkspaceTab } from './workbenchV2Controller'
const props=defineProps({modelValue:{type:Boolean,default:false},customer:{type:Object,default:null},loading:{type:Boolean,default:false},detailError:{type:Object,default:null},retryDetail:{type:Function,required:true},initialTab:{type:String,default:'overview'}})
defineEmits(['update:modelValue','action-saved'])
const activeTab=ref(normalizeWorkspaceTab(props.initialTab))
const route=useRoute()
watch(()=>props.customer?.customer_id,()=>{activeTab.value=normalizeWorkspaceTab(props.initialTab)})
const customerTitle=computed(()=>props.customer?`客户作战卡 · ${props.customer.display_name || props.customer.customer_code || props.customer.customer_id}`:'客户作战卡')
</script>
<style scoped>.detail-shortcuts{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.detail-shortcuts a{color:var(--color-primary)}</style>
