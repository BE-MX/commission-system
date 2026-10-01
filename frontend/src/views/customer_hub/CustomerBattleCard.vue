<template>
  <div class="battle-card customer-hub">
    <header><h2>{{ customer.display_name || customer.canonical_company_name || `客户 #${customerId}` }}</h2><p>{{ customer.customer_code || '客户编号未提供' }} · {{ identityLabel(customer.identity_status) }} · {{ customer.is_public_pool ? '公海 · 暂无主负责人' : '已分配客户' }} · 档案完整度 {{ customer.profile_completeness ?? '—' }}%</p></header>
    <el-tabs v-model="activeTab" @tab-change="changedTab">
      <el-tab-pane v-for="tab in WORKSPACE_TABS" :key="tab.key" :label="tab.label" :name="tab.key" lazy>
        <div v-if="activeTab===tab.key" class="tab-content">
          <template v-if="tab.key==='overview'"><WorkspaceOverview :key="customerId" :customer-id="customerId" :customer="customer" /><el-collapse v-model="expanded"><el-collapse-item title="历史订单、价格与复购分析" name="orders"><WorkspaceOrders v-if="expanded.includes('orders')" :customer-id="customerId" :customer="customer" /></el-collapse-item></el-collapse></template>
          <template v-else-if="tab.key==='conversations'"><WorkspaceConversations :customer-id="customerId" :customer="customer" /><WorkspaceTimeline :customer-id="customerId" /><MailOutreachPanel v-if="canReadMail" v-any-permission="['mail_outreach:read','mail_outreach:write','mail_outreach:admin']" :customer-id="customerId" /></template>
          <template v-else-if="tab.key==='profile'"><StructuredProfile :customer="customer" /><WorkspaceEnrichment v-if="!customer.is_public_pool" :customer-id="customerId" /><WorkspaceProfile :customer-id="customerId" :customer="customer" @updated="$emit('refresh-customer')" /><EvidencePicker :customer-id="customerId" readonly /><WorkspaceMonitor :customer-id="customerId" :customer="customer" /></template>
          <template v-else><WorkspaceMaintenance :customer-id="customerId" :customer="customer" /><WorkspaceMonitor :customer-id="customerId" :customer="customer" /></template>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { WORKSPACE_TABS } from './customerWorkspaceController'
import { normalizeWorkspaceTab } from './workbenchV2Controller'
import { identityLabel } from './operationsPresentation'
import StructuredProfile from './StructuredProfile.vue'
import EvidencePicker from './EvidencePicker.vue'
import WorkspaceOverview from './workspace/WorkspaceOverview.vue'
import WorkspaceOrders from './workspace/WorkspaceOrders.vue'
import WorkspaceConversations from './workspace/WorkspaceConversations.vue'
import WorkspaceTimeline from './workspace/WorkspaceTimeline.vue'
import WorkspaceProfile from './workspace/WorkspaceProfile.vue'
import WorkspaceMaintenance from './workspace/WorkspaceMaintenance.vue'
import WorkspaceMonitor from './workspace/WorkspaceMonitor.vue'
import WorkspaceEnrichment from './workspace/WorkspaceEnrichment.vue'
import MailOutreachPanel from './mail_outreach/MailOutreachPanel.vue'
const props=defineProps({customerId:{type:Number,required:true},customer:{type:Object,required:true},initialTab:{type:String,default:'overview'}})
const emit=defineEmits(['tab-change','refresh-customer'])
const activeTab=ref(normalizeWorkspaceTab(props.initialTab)),expanded=ref(props.initialTab==='orders'?['orders']:[])
const auth=useAuthStore(),canReadMail=computed(()=>auth.hasAnyPermission(['mail_outreach:read','mail_outreach:write','mail_outreach:admin']))
watch(()=>props.initialTab,value=>{activeTab.value=normalizeWorkspaceTab(value);if(value==='orders')expanded.value=['orders']})
watch(()=>props.customerId,()=>{activeTab.value=normalizeWorkspaceTab(props.initialTab);expanded.value=props.initialTab==='orders'?['orders']:[]})
function changedTab(value){emit('tab-change',value)}
</script>
<style scoped>.battle-card{color:var(--text-primary);min-width:0;--el-border-color:var(--border-color)}h2{font-size:17px;margin:0 0 8px}header p{color:var(--text-secondary);line-height:1.6}.tab-content{display:grid;gap:14px}</style>
