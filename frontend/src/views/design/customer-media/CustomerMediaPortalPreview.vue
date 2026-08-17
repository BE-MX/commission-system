<template>
  <main class="portal-preview-page">
    <header class="workspace-header">
      <div>
        <span class="eyebrow">LESHINE CLIENT CONTENT HUB</span>
        <h2>客户素材门户</h2>
        <p>切换客户即可查看其当前实际可见的已发布素材。</p>
      </div>
      <div class="workspace-actions">
        <span class="customer-total">{{ customers.length }} 个客户门户</span>
        <GlassButton variant="secondary" left-icon="Refresh" :loading="loadingCustomers" @click="loadCustomers()">刷新</GlassButton>
        <GlassButton class="mobile-clients" variant="primary" left-icon="Menu" @click="showMobileNav = true">切换客户</GlassButton>
      </div>
    </header>

    <section class="portal-shell">
      <aside :class="['client-sidebar', { 'mobile-open': showMobileNav }]">
        <div class="sidebar-mobile-head"><strong>选择客户</strong><button type="button" aria-label="关闭客户列表" @click="showMobileNav = false">×</button></div>
        <div class="owner-card">
          <span class="owner-avatar">{{ initials(viewerName) }}</span>
          <div><span class="eyebrow">BUSINESS PORTAL</span><strong>{{ viewerName }}</strong><small>仅显示当前账号有权查看的客户</small></div>
        </div>

        <div class="sidebar-heading">
          <div><span class="eyebrow">SELECT CLIENT</span><h3>Clients</h3></div>
          <span>{{ filteredCustomers.length }}</span>
        </div>
        <label class="client-search"><span>⌕</span><input v-model="customerSearch" aria-label="搜索客户" placeholder="Search clients" /></label>

        <div v-loading="loadingCustomers" class="client-list">
          <button
            v-for="customer in filteredCustomers"
            :key="customer.customer_id"
            type="button"
            :class="['client-row', { selected: customer.customer_id === selectedCustomerId }]"
            :aria-current="customer.customer_id === selectedCustomerId ? 'page' : undefined"
            @click="chooseCustomer(customer.customer_id)"
          >
            <span class="client-avatar">{{ initials(customer.customer_name) }}</span>
            <span class="client-copy"><strong>{{ customer.customer_name }}</strong><small>{{ customer.login_email }}</small></span>
            <span class="client-meta"><small>{{ customer.asset_count }}</small><i :class="['status-dot', portalStatusMeta(customer.status).tone]" /></span>
          </button>
          <div v-if="!loadingCustomers && !filteredCustomers.length" class="sidebar-empty">
            <strong>{{ customers.length ? '没有匹配的客户' : '暂无可预览门户' }}</strong>
            <span>{{ customers.length ? '请更换搜索关键词' : '客户需先配置门户账号，且归属到当前业务员。' }}</span>
          </div>
        </div>

        <div class="sidebar-key">
          <span><i class="status-dot ready" /> 已发布</span>
          <span><i class="status-dot in-review" /> 审核中</span>
          <span><i class="status-dot changes-requested" /> 待修改</span>
          <span><i class="status-dot disabled" /> 已停用</span>
        </div>
        <div class="preview-note"><span>PREVIEW MODE</span><p>右侧只展示客户门户会返回的已发布内容，不包含草稿和审核中的文件。</p></div>
      </aside>

      <button v-if="showMobileNav" class="mobile-backdrop" type="button" aria-label="关闭客户列表" @click="showMobileNav = false" />

      <div class="preview-stage">
        <CustomerMediaClientLibrary
          :customer="detail?.customer || activeCustomer"
          :batches="detail?.batches || []"
          :loading="loadingDetail"
          :error="detailError"
        />
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import CustomerMediaClientLibrary from './CustomerMediaClientLibrary.vue'
import { initials, portalStatusMeta } from './portalPreviewState'
import { useCustomerMediaPortalPreview } from './useCustomerMediaPortalPreview'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const showMobileNav = ref(false)
const viewerName = computed(() => auth.user?.real_name || auth.user?.username || '业务账号')
const {
  customers,
  filteredCustomers,
  activeCustomer,
  selectedCustomerId,
  detail,
  customerSearch,
  loadingCustomers,
  loadingDetail,
  detailError,
  loadCustomers,
  selectCustomer,
} = useCustomerMediaPortalPreview({ route, router })

async function chooseCustomer(customerId) {
  showMobileNav.value = false
  await selectCustomer(customerId)
}
</script>

<style scoped>
.portal-preview-page { position: relative; min-width: 0; }
.workspace-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.workspace-header .eyebrow,.owner-card .eyebrow,.sidebar-heading .eyebrow { color: var(--color-gold-muted); font: 700 10px var(--font-display); letter-spacing: 0.14em; }
.workspace-header h2 { margin: 6px 0 4px; font: 700 23px var(--font-display); }
.workspace-header p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.workspace-actions { display: flex; align-items: center; gap: 10px; }
.customer-total { padding-right: 4px; color: var(--text-secondary); font-size: 12px; }
.mobile-clients { display: none; }
.portal-shell { display: grid; min-height: 690px; grid-template-columns: 300px minmax(0, 1fr); overflow: hidden; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--card-bg); box-shadow: var(--dash-glass-shadow); }
.client-sidebar { display: flex; min-width: 0; flex-direction: column; border-right: 1px solid rgba(61, 51, 35, 0.13); background: linear-gradient(165deg, rgba(255, 255, 255, 0.95), rgba(253, 244, 220, 0.58)); }
.sidebar-mobile-head { display: none; }
.owner-card { display: flex; align-items: center; gap: 11px; padding: 18px; border-bottom: 1px solid rgba(61, 51, 35, 0.1); }
.owner-avatar,.client-avatar { display: grid; flex: 0 0 auto; place-items: center; border-radius: 50%; color: var(--text-on-dark); background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover)); font-family: var(--font-display); font-weight: 700; }
.owner-avatar { width: 44px; height: 44px; font-size: 13px; }
.owner-card>div { display: grid; min-width: 0; gap: 3px; }
.owner-card strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.owner-card small { color: var(--text-secondary); font-size: 10px; }
.sidebar-heading { display: flex; align-items: end; justify-content: space-between; padding: 19px 18px 11px; }
.sidebar-heading h3 { margin: 4px 0 0; font: 500 24px Georgia, serif; }
.sidebar-heading>span { display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid rgba(61, 51, 35, 0.13); border-radius: 50%; color: var(--text-secondary); font-size: 11px; }
.client-search { display: flex; align-items: center; gap: 7px; margin: 0 18px 10px; border-bottom: 1px solid var(--border-hover); }
.client-search>span { color: var(--text-secondary); font-size: 19px; }
.client-search input { width: 100%; height: 37px; border: 0; outline: 0; color: var(--text-primary); background: transparent; font-size: 12px; }
.client-list { min-height: 180px; flex: 1; overflow-y: auto; padding: 2px 9px 10px; }
.client-row { display: grid; width: 100%; grid-template-columns: 38px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 10px 9px; border: 0; border-radius: 2px; color: var(--text-primary); background: transparent; cursor: pointer; text-align: left; transition: background 180ms ease, box-shadow 180ms ease; }
.client-row:hover { background: rgba(255, 255, 255, 0.72); }
.client-row.selected { background: var(--card-bg); box-shadow: 0 5px 17px rgba(117, 79, 24, 0.12); }
.client-avatar { width: 38px; height: 38px; font-size: 11px; }
.client-row:not(.selected) .client-avatar { color: var(--color-gold-muted); background: var(--color-gold-soft); }
.client-copy { display: grid; min-width: 0; gap: 3px; }
.client-copy strong,.client-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.client-copy strong { font-size: 12px; }
.client-copy small { color: var(--text-secondary); font-size: 9px; }
.client-meta { display: grid; justify-items: end; gap: 6px; }
.client-meta small { color: var(--text-secondary); font: 600 10px var(--font-body); }
.status-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--text-muted); }
.status-dot.ready { background: var(--color-success); }.status-dot.in-review { background: var(--color-primary); }.status-dot.changes-requested { background: var(--color-danger); }.status-dot.draft,.status-dot.empty { background: var(--text-muted); }.status-dot.disabled { background: var(--text-secondary); }
.sidebar-key { display: flex; flex-wrap: wrap; gap: 8px 13px; padding: 12px 18px; border-top: 1px solid rgba(61, 51, 35, 0.09); color: var(--text-secondary); font-size: 9px; }
.sidebar-key span { display: flex; align-items: center; gap: 5px; }
.preview-note { margin: 0 13px 14px; padding: 13px; border: 1px solid rgba(212, 148, 28, 0.16); background: var(--color-primary-light); }
.preview-note>span { color: var(--color-gold-muted); font: 700 9px var(--font-display); letter-spacing: 0.13em; }
.preview-note p { margin: 6px 0 0; color: var(--text-secondary); font-size: 10px; line-height: 1.55; }
.sidebar-empty { display: grid; gap: 6px; padding: 28px 15px; color: var(--text-secondary); text-align: center; }
.sidebar-empty strong { color: var(--text-primary); font-size: 12px; }.sidebar-empty span { font-size: 10px; line-height: 1.5; }
.preview-stage { min-width: 0; overflow: auto; }
.mobile-backdrop { display: none; }
@media (max-width: 900px) {
  .customer-total { display: none; }.mobile-clients { display: inline-flex; }.portal-shell { grid-template-columns: minmax(0, 1fr); }.client-sidebar { position: fixed; z-index: 2100; top: 0; bottom: 0; left: 0; width: min(330px, 88vw); transform: translateX(-102%); transition: transform 240ms var(--ease-out-strong); box-shadow: 18px 0 50px rgba(26, 24, 22, 0.22); }.client-sidebar.mobile-open { transform: translateX(0); }.sidebar-mobile-head { display: flex; align-items: center; justify-content: space-between; padding: 15px 18px; border-bottom: 1px solid var(--border-color); }.sidebar-mobile-head button { border: 0; color: var(--text-primary); background: transparent; font-size: 26px; }.mobile-backdrop { position: fixed; z-index: 2050; inset: 0; display: block; border: 0; background: rgba(16, 14, 12, 0.38); }.preview-stage { overflow: visible; }
}
@media (max-width: 640px) { .workspace-header { align-items: flex-start; flex-direction: column; }.workspace-actions { width: 100%; }.workspace-actions :deep(.glass-button) { flex: 1; }.portal-shell { min-height: 620px; border-radius: 12px; } }
@media (prefers-reduced-motion: reduce) { .client-sidebar,.client-row { transition: none; } }
</style>
