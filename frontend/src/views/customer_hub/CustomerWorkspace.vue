<template>
  <main class="customer-workspace customer-hub">
    <header class="workspace-header">
      <div>
        <el-button text @click="goBack">← 返回列表</el-button>
        <h1>{{ detail?.display_name || `客户 #${customerId}` }}</h1>
        <div class="header-meta">
          <el-tag v-if="detail?.identity_status" size="small">{{ detail.identity_status }}</el-tag>
          <el-tag v-if="detail?.is_public_pool" size="small" type="warning">公海 · 暂无主负责人</el-tag>
          <el-tag v-else size="small" type="success">私海 · 已有主负责人</el-tag>
          <span v-if="detail?.customer_code" class="meta-code">{{ detail.customer_code }}</span>
        </div>
      </div>
    </header>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <el-tabs v-model="activeTab" class="workspace-tabs">
      <el-tab-pane v-for="tab in WORKSPACE_TABS" :key="tab.key" :name="tab.key" :label="tab.label" lazy>
        <component :is="panelFor(tab.key)" v-if="activeTab === tab.key" :customer-id="customerId" :customer="detail" />
      </el-tab-pane>
    </el-tabs>
  </main>
</template>

<script setup>
import './customerHub.css'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCustomer } from '@/api/customerHub'
import { WORKSPACE_TABS } from './customerWorkspaceController'
import WorkspaceOverview from './workspace/WorkspaceOverview.vue'
import WorkspaceProfile from './workspace/WorkspaceProfile.vue'
import WorkspaceConversations from './workspace/WorkspaceConversations.vue'
import WorkspaceOrders from './workspace/WorkspaceOrders.vue'
import WorkspaceMonitor from './workspace/WorkspaceMonitor.vue'
import WorkspaceMaintenance from './workspace/WorkspaceMaintenance.vue'

const route = useRoute()
const router = useRouter()
const customerId = computed(() => Number(route.params.id))
const activeTab = ref(String(route.query.tab || 'overview'))
const detail = ref(null)
const loadError = ref('')

const PANELS = {
  overview: WorkspaceOverview,
  profile: WorkspaceProfile,
  conversations: WorkspaceConversations,
  orders: WorkspaceOrders,
  monitor: WorkspaceMonitor,
  maintenance: WorkspaceMaintenance,
}
const panelFor = key => PANELS[key] || WorkspaceOverview

async function loadDetail() {
  loadError.value = ''
  try {
    const response = await getCustomer(customerId.value)
    detail.value = response.data
  } catch (error) {
    const code = error?.response?.data?.data?.error_code
    loadError.value = code === 'CUSTOMER_NOT_FOUND_OR_FORBIDDEN'
      ? '客户不存在或当前账号无权访问'
      : '客户信息加载失败，请重试'
    detail.value = null
  }
}

function goBack() {
  // 返回保留来源筛选
  router.push({ path: '/customer-hub/customers', query: route.query.from ? { ...route.query } : {} })
}

onMounted(loadDetail)
</script>

<style scoped>
.customer-workspace { display: grid; gap: 16px; color: var(--text-primary); }
.workspace-header h1 { margin: 8px 0 6px; font-size: 18px; }
.header-meta { display: flex; gap: 8px; align-items: center; color: var(--text-secondary); font-size: 13px; }
.meta-code { color: var(--text-muted); }
.workspace-tabs :deep(.el-tabs__header) { margin-bottom: 12px; }
</style>
