<template>
  <main class="customer-image-admin">
    <header class="admin-hero">
      <div>
        <p class="eyebrow">CUSTOMER RENDER PORTAL</p>
        <h1>客户产品效果图</h1>
        <p>维护客户可选产品、发放专属邀请，并追踪生成额度与结果状态。</p>
      </div>
      <el-tag v-if="canAdmin" effect="plain" type="warning">模板管理员</el-tag>
    </header>

    <section class="admin-surface">
      <el-tabs v-model="activeTab" class="admin-tabs">
        <el-tab-pane label="产品模板" name="products">
          <ProductTemplateList :state="state" :can-admin="canAdmin" />
        </el-tab-pane>
        <el-tab-pane label="客户邀请" name="invites" lazy>
          <InviteList :state="state" :can-write="canWrite" />
        </el-tab-pane>
        <el-tab-pane v-if="canRead" label="生成用量" name="usage" lazy>
          <GenerationUsageList :state="state" />
        </el-tab-pane>
      </el-tabs>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import * as customerImageApi from '@/api/customerImage'
import ProductTemplateList from './ProductTemplateList.vue'
import InviteList from './InviteList.vue'
import GenerationUsageList from './GenerationUsageList.vue'
import {
  createCustomerImageAdminState,
  customerImageAdminCapabilities,
} from './composables/useCustomerImageAdmin'

const auth = useAuthStore()
const activeTab = ref('products')
const access = computed(() => customerImageAdminCapabilities(permission => auth.hasPermission(permission)))
const canAdmin = computed(() => access.value.canAdmin)
const canRead = computed(() => access.value.canRead)
const canWrite = computed(() => access.value.canWrite)
const state = createCustomerImageAdminState({ api: customerImageApi })
onBeforeUnmount(state.dispose)
</script>

<style scoped>
.customer-image-admin {
  --admin-gold: var(--color-primary, #b78b3e);
  display: grid;
  gap: 18px;
  min-width: 0;
}

.admin-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 24px 26px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 18px;
  background: linear-gradient(120deg, var(--el-bg-color) 20%, color-mix(in srgb, var(--admin-gold) 9%, var(--el-bg-color)));
  box-shadow: var(--el-box-shadow-light);
}

.eyebrow { margin: 0 0 6px; color: var(--admin-gold); font-size: 12px; font-weight: 700; letter-spacing: .14em; }
h1 { margin: 0; color: var(--el-text-color-primary); font-size: clamp(24px, 2.4vw, 34px); line-height: 1.2; }
.admin-hero p:last-child { margin: 8px 0 0; color: var(--el-text-color-secondary); }
.admin-surface { min-width: 0; padding: 0 20px 20px; border: 1px solid var(--el-border-color-lighter); border-radius: 18px; background: var(--el-bg-color); }
.admin-tabs :deep(.el-tabs__item) { min-height: 48px; }

@media (max-width: 720px) {
  .admin-hero { padding: 20px; }
  .admin-surface { padding-inline: 12px; }
}
</style>
