<script setup>
import { computed, nextTick, onBeforeUnmount, ref, toRaw, watch } from 'vue'
import { View } from '@element-plus/icons-vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import TableTools from '@/components/TableTools.vue'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import { msgError } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import AccessActionDialog from './AccessActionDialog.vue'
import MappingDialog from './MappingDialog.vue'
import OnboardingDialog from './OnboardingDialog.vue'
import CatalogAccessDialog from './CatalogAccessDialog.vue'
import BindingReviewDialog from './BindingReviewDialog.vue'
import { accountStatuses } from './customerAccess.mjs'
import { ACCESS_STATUS } from './portalStatus'

const columnDefs = [{ key: 'company', label: '客户公司' }, { key: 'status', label: '访问状态' }, { key: 'capabilities', label: '客户能力' }, { key: 'sales-user', label: '负责业务员' }]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('portal-customers', columnDefs)
const capabilityText = row => row.capabilities.can_order ? '查价与下单' : row.capabilities.can_view_price ? '仅查价' : '仅查看目录'
// A deactivated or deleted salesperson has no name; keep the ID visible so ownership is still traceable.
const salesName = row => row.sales_user_name || `未知业务员（ID ${row.sales_user_id}）`
// 原「刷新」按钮已由 TableTools 承担；焦点回退到操作行第一个可用按钮
const pageRefresh = { get value() { return { $el: panelRef.value?.querySelector('.action-bar button:not([disabled])') } } }

const auth = useAuthStore(), listError = ref(''), detailError = ref(''), notice = ref('')
const detail = ref(null), detailVisible = ref(false), detailLoading = ref(false), accountPage = ref(1), accountPageSize = ref(20)
const copySource = ref(null), copyLoading = ref(false)
let copyGeneration = 0, copyController
function cancelCopy() { copyGeneration++; copyController?.abort(); copyLoading.value = false }
const action = ref(null), mappingAccess = ref(null), onboardingVisible = ref(false), catalogAccess = ref(null), bindingAccess = ref(null)
let listController, detailController, listSequence = 0, detailSequence = 0, disposed = false, detailId = ''
const mappingTrigger = ref(null), pageRoot = ref(null), detailContent = ref(null), detailRefresh = ref(null), onboardingTrigger = ref(null)
let onboardingRefresh = Promise.resolve(), onboardingFocusSequence = 0, onboardingCreatedId = null
let actionRefresh = Promise.resolve(), actionFocusSequence = 0, actionRefreshed = false, actionDenied = false
let mappingRefresh = Promise.resolve(), mappingFocusSequence = 0
const catalogTrigger = ref(null), bindingTrigger = ref(null)
let reviewRefresh = Promise.resolve(), reviewFocusSequence = 0, reviewRefreshed = false, reviewDenied = false
function openReview(type) {
  ++reviewFocusSequence; reviewRefresh = Promise.resolve(); reviewRefreshed = false; reviewDenied = false
  const target = type === 'catalog' ? catalogAccess : bindingAccess
  target.value = { id: detail.value.id, company_display_name: detail.value.company_display_name }
}
function reviewChanged(text) { reviewRefreshed = true; reviewRefresh = Promise.resolve(changed(text)) }
function hideReviewPrivate() { reviewDenied = true; hideCustomerPrivate() }
async function closeReview(type) {
  const target = type === 'catalog' ? catalogAccess : bindingAccess, id = target.value?.id, denied = reviewDenied, refreshed = reviewRefreshed
  target.value = null
  const current = ++reviewFocusSequence
  await reviewRefresh
  await nextTick()
  if (!id || disposed || current !== reviewFocusSequence || catalogAccess.value || bindingAccess.value || action.value || mappingAccess.value || onboardingVisible.value) return
  let button
  if (detailVisible.value && detail.value?.id === id) {
    button = (type === 'catalog' ? catalogTrigger : bindingTrigger).value?.$el
    if (!button?.isConnected || button.disabled || !button.getClientRects().length) button = detailRefresh.value?.$el
  }
  else if (!detailVisible.value) button = denied && !refreshed ? pageRefresh.value?.$el : [...(pageRoot.value?.querySelectorAll('button[data-portal-access]') || [])].find(el => el.dataset.portalAccess === id) || pageRefresh.value?.$el
  if (button?.isConnected && !button.disabled) button.focus()
}
function openMapping() { ++mappingFocusSequence; mappingRefresh = Promise.resolve(); mappingAccess.value = { id: detail.value.id, company_display_name: detail.value.company_display_name } }
function mappingChanged() { mappingRefresh = Promise.resolve(changed('')) }
async function closeMapping() {
  const id = mappingAccess.value?.id
  mappingAccess.value = null
  const current = ++mappingFocusSequence
  await mappingRefresh
  await nextTick()
  if (disposed || current !== mappingFocusSequence || !detailVisible.value || detail.value?.id !== id || mappingAccess.value || action.value || onboardingVisible.value || catalogAccess.value || bindingAccess.value) return
  const button = mappingTrigger.value?.$el
  if (button?.isConnected) button.focus()
}
const message = e => e?.response?.data?.message || '读取失败，请重试。'
const { list, total, page, pageSize, loading, searchForm, appliedSearchForm, hasPendingSearch, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = useListPage(async params => {
  const current = ++listSequence
  listController?.abort(); listController = new AbortController()
  list.value = []; total.value = 0; listError.value = ''
  try {
    const result = await portalAdminApi.customers(params, listController.signal)
    return !disposed && current === listSequence ? result : { items: [], total: 0 }
  } catch (e) {
    if (!disposed && current === listSequence) listError.value = message(e)
    return { items: [], total: 0 }
  }
}, { searchForm: { keyword: '', status: '' } })
const hasAppliedFilters = computed(() => Boolean(appliedSearchForm.value.keyword || appliedSearchForm.value.status))
async function loadDetail(id = detailId, pageNumber = accountPage.value) {
  if (!id) return
  const current = ++detailSequence
  detailController?.abort(); detailController = new AbortController()
  detailId = id; accountPage.value = pageNumber; detail.value = null; detailError.value = ''; detailLoading.value = true; detailVisible.value = true
  try {
    const data = await portalAdminApi.customer(id, { page: pageNumber, page_size: accountPageSize.value }, detailController.signal)
    if (!disposed && current === detailSequence) detail.value = data
  } catch (e) { if (!disposed && current === detailSequence) detailError.value = message(e) }
  finally { if (current === detailSequence) detailLoading.value = false }
}
function openDetail(id) { notice.value = ''; loadDetail(id, 1) }
function clearDetail() { ++reviewFocusSequence; ++onboardingFocusSequence; ++actionFocusSequence; ++mappingFocusSequence; ++detailSequence; detailController?.abort(); detail.value = null; detailError.value = ''; detailLoading.value = false; detailId = '' }
watch(detailVisible, value => { if (!value) clearDetail() })
function openAction(type, account = null) {
  ++actionFocusSequence; actionRefresh = Promise.resolve(); actionRefreshed = false; actionDenied = false
  notice.value = ''
  action.value = { type, access: structuredClone(toRaw(detail.value)), account: account && structuredClone(toRaw(account)) }
}
function changed(text) { notice.value = text; return Promise.all([fetchList(), detailId ? loadDetail() : undefined]) }
function actionChanged(text) { actionRefreshed = true; actionRefresh = Promise.resolve(changed(text)) }
function hideActionPrivate() { actionDenied = true; hideCustomerPrivate() }
function hideCustomerPrivate() {
  ++listSequence; listController?.abort(); list.value = []; total.value = 0; listError.value = ''; notice.value = ''
  detailVisible.value = false; clearDetail()
}
async function closeAction() {
  const closing = action.value, denied = actionDenied, refreshed = actionRefreshed
  action.value = null
  const current = ++actionFocusSequence
  await actionRefresh
  await nextTick()
  if (!closing || disposed || current !== actionFocusSequence || action.value || mappingAccess.value || onboardingVisible.value || catalogAccess.value || bindingAccess.value) return
  let button
  if (detailVisible.value && detail.value?.id === closing.access.id) {
    const buttons = [...(detailContent.value?.querySelectorAll('button[data-portal-action]') || [])]
    button = buttons.find(el => el.dataset.portalAction === closing.type && (el.dataset.portalAccount || '') === (closing.account?.id || '') && !el.disabled)
      || buttons.find(el => el.dataset.portalAction === 'createAccount' && !el.dataset.portalAccount && !el.disabled)
      || detailRefresh.value?.$el
  } else if (!detailVisible.value) {
    button = denied && !refreshed ? pageRefresh.value?.$el
      : [...(pageRoot.value?.querySelectorAll('button[data-portal-access]') || [])].find(el => el.dataset.portalAccess === closing.access.id) || pageRefresh.value?.$el
  }
  if (button?.isConnected && !button.disabled) button.focus()
}
async function openCopy(id) {
  if (copyLoading.value || onboardingVisible.value) return
  const current = ++copyGeneration
  copyController?.abort(); copyController = new AbortController(); copyLoading.value = true
  notice.value = ''
  const identity = auth.accessToken
  try {
    const source = await portalAdminApi.customer(id, { page: 1, page_size: 1 }, copyController.signal)
    if (disposed || current !== copyGeneration || identity !== auth.accessToken) return
    openOnboarding(); copySource.value = source
  } catch (e) { if (!disposed && current === copyGeneration && identity === auth.accessToken) { notice.value = message(e); msgError(notice.value) } }
  finally { if (current === copyGeneration) copyLoading.value = false }
}
function openOnboarding() { cancelCopy(); copySource.value = null; ++onboardingFocusSequence; onboardingRefresh = Promise.resolve(); onboardingCreatedId = null; onboardingVisible.value = true }
function created({ id, recovered, copied }) {
  notice.value = copied ? '客户访问已复制，新采购账号可使用邮箱和密码登录。' : recovered ? '已找到现有客户授权，请核对当前设置；此查询不证明先前命令执行结果。' : '客户授权草稿已创建。请核对后设置为启用，再创建采购账号。'
  onboardingCreatedId = id; onboardingRefresh = Promise.all([fetchList(), loadDetail(id, 1)])
}
async function closeOnboarding() {
  cancelCopy()
  onboardingVisible.value = false
  const current = ++onboardingFocusSequence, id = onboardingCreatedId
  await onboardingRefresh
  await nextTick()
  if (disposed || current !== onboardingFocusSequence || onboardingVisible.value || action.value || mappingAccess.value || catalogAccess.value || bindingAccess.value) return
  const button = id && detailVisible.value && detail.value?.id === id ? detailRefresh.value?.$el : !detailVisible.value ? onboardingTrigger.value?.$el : null
  if (button?.isConnected && !button.disabled) button.focus()
}
function clearPrivate() {
  cancelCopy()
  ++reviewFocusSequence; reviewRefresh = Promise.resolve()
  ++onboardingFocusSequence; onboardingRefresh = Promise.resolve(); onboardingCreatedId = null
  ++actionFocusSequence; actionRefresh = Promise.resolve()
  ++mappingFocusSequence; mappingRefresh = Promise.resolve()
  ++listSequence; listController?.abort(); list.value = []; total.value = 0; listError.value = ''; notice.value = ''; copySource.value = null; action.value = null; mappingAccess.value = null; onboardingVisible.value = false; catalogAccess.value = null; bindingAccess.value = null
  detailVisible.value = false; clearDetail()
}
watch(() => [auth.accessToken, auth.user], clearPrivate)
onBeforeUnmount(() => { disposed = true; clearPrivate() })
</script>

<template>
  <section ref="pageRoot" class="portal-page portal-customers">
    <div class="portal-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" /></div>
    <header class="page-header"><div><h2>客户访问与采购账号</h2><p>管理客户查价、下单和登录资格，变更按方舟当前客户归属生效。</p></div></header>
    <div ref="panelRef" class="table-card portal-panel">
      <FilterBar label="客户访问筛选" :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset">
        <el-input v-model="searchForm.keyword" maxlength="100" clearable aria-label="搜索客户" placeholder="公司名称或完整 OKKI 公司 ID" class="filter-w-lg" />
        <el-select v-model="searchForm.status" aria-label="访问状态" placeholder="全部状态" clearable class="filter-w-sm"><el-option v-for="(entry, value) in ACCESS_STATUS" :key="value" :label="entry.label" :value="value" /></el-select>
      </FilterBar>
      <div class="action-bar">
        <GlassButton v-permission="'portal_access:admin'" ref="onboardingTrigger" variant="primary" left-icon="Plus" @click="openOnboarding">开通客户门户</GlassButton>
        <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columnDefs" :fullscreen="isFullscreen" :loading="loading" @refresh="fetchList" @fullscreen="toggleFullscreen" />
      </div>
      <el-alert v-if="listError" :title="listError" type="error" :closable="false" show-icon class="panel-alert" />
      <el-table v-loading="loading" :data="list" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty><el-empty v-if="!loading && !listError" :image-size="96" :description="hasAppliedFilters ? '没有符合条件的客户授权' : '暂无数据'"><GlassButton v-if="hasAppliedFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton></el-empty></template>
        <el-table-column v-if="visibleKeys.includes('company')" prop="company_display_name" label="客户公司" min-width="220" max-width="360" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('status')" prop="status" label="访问状态" min-width="120" max-width="180"><template #default="{ row }"><StatusBadge :value="row.status" :dictionary="ACCESS_STATUS" effect="plain" /></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('capabilities')" label="客户能力" min-width="140" max-width="220" :sort-by="capabilityText" show-overflow-tooltip><template #default="{ row }">{{ capabilityText(row) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('sales-user')" label="负责业务员" min-width="110" max-width="180" :sort-by="salesName" show-overflow-tooltip><template #default="{ row }">{{ salesName(row) }}</template></el-table-column>
        <el-table-column label="操作" fixed="right" min-width="160" max-width="220" class-name="table-action-column" :sortable="false"><template #default="{ row }"><GlassButton v-permission="'portal_access:read'" variant="link" :left-icon="View" :data-portal-access="row.id" @click="openDetail(row.id)">管理</GlassButton><GlassButton v-permission="'portal_access:admin'" variant="link" :disabled="row.status !== 'enabled' || copyLoading" @click="openCopy(row.id)" left-icon="Edit">复制</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination class="pager" :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>
    <DetailDrawer v-model="detailVisible" title="客户访问与账号" :width="760" :loading="detailLoading">
      <div ref="detailContent">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <el-alert v-if="notice" :title="notice" type="info" :closable="false" />
      <template v-if="detail">
        <div class="drawer-title"><h3>{{ detail.company_display_name }}</h3><StatusBadge :value="detail.status" :dictionary="ACCESS_STATUS" effect="plain" /></div>
        <p>方舟客户 {{ detail.canonical_customer_id }} · 负责业务员 {{ salesName(detail) }}</p>
        <p>查价 {{ detail.capabilities.can_view_price ? '已允许' : '未允许' }} · 下单 {{ detail.capabilities.can_order ? '已允许' : '未允许' }} · 已授权商品 {{ detail.catalog_item_ids.length }} 项</p>
        <el-alert v-if="detail.status === 'review_required'" title="客户身份或归属需要复核，普通启停不能解除此状态。" type="warning" :closable="false" />
        <div class="actions">
          <span v-permission="'portal_access:admin'" class="actions">
            <GlassButton variant="primary" :disabled="detail.status !== 'enabled'" data-portal-action="createAccount" @click="openAction('createAccount')">创建采购账号</GlassButton>
            <GlassButton :disabled="detail.status === 'review_required'" data-portal-action="access" @click="openAction('access')">设置客户访问</GlassButton>
            <GlassButton ref="catalogTrigger" :disabled="detail.status === 'review_required'" @click="openReview('catalog')">管理商品授权</GlassButton>
            <GlassButton ref="bindingTrigger" @click="openReview('binding')">归属与身份复核</GlassButton>
          </span>
          <GlassButton v-permission="'portal_mapping:read'" @click="$router.push({ name: 'PortalCustomerPreview', params: { accessId: detail.id } })">预览客户目录</GlassButton>
          <GlassButton ref="mappingTrigger" v-permission="'portal_mapping:read'" @click="openMapping">型号颜色映射</GlassButton>
          <GlassButton v-if="!detailLoading" ref="detailRefresh" variant="ghost" left-icon="Refresh" @click="loadDetail()">刷新详情</GlassButton>
        </div>
        <h3>采购账号 <small>共 {{ detail.accounts.total }} 个</small></h3>
        <p>公司成员共享该公司的订单。账号密码、账号状态和成员关系均须有效。</p>
        <el-empty v-if="!detail.accounts.items.length" :image-size="72" description="暂无采购账号，可在启用客户后创建账号" />
        <article v-for="account in detail.accounts.items" :key="account.id" class="account-card">
          <strong>{{ account.contact_name || '采购联系人' }}</strong><p>{{ account.email }}</p>
          <p>{{ accountStatuses[account.status] || '状态待核实' }} · {{ account.password_configured ? '已设置密码' : '待设置密码' }} · 成员{{ accountStatuses[account.membership_status] || account.membership_status }}</p>
          <div v-permission="'portal_access:admin'" class="actions">
            <GlassButton data-portal-action="account" :data-portal-account="account.id" @click="openAction('account', account)">{{ account.status === 'active' ? '停用账号' : '恢复账号' }}</GlassButton>
            <GlassButton data-portal-action="password" :data-portal-account="account.id" @click="openAction('password', account)">设置密码</GlassButton>
          </div>
        </article>
        <el-pagination class="pager" :current-page="accountPage" v-model:page-size="accountPageSize" :page-sizes="[20, 50, 100]" :total="detail.accounts.total" layout="total, sizes, prev, pager, next" @current-change="value => loadDetail(detailId, value)" @size-change="loadDetail(detailId, 1)" />
      </template>
      <GlassButton v-else-if="!detailLoading" left-icon="Refresh" @click="loadDetail()">刷新详情</GlassButton>
      </div>
    </DetailDrawer>
    <BindingReviewDialog v-if="bindingAccess" :access="bindingAccess" @close="closeReview('binding')" @changed="reviewChanged" @denied="hideReviewPrivate" />
    <CatalogAccessDialog v-if="catalogAccess" :access="catalogAccess" @close="closeReview('catalog')" @changed="reviewChanged" @denied="hideReviewPrivate" />
    <OnboardingDialog v-if="onboardingVisible" :key="copySource?.id || 'new'" :source="copySource" @close="closeOnboarding" @created="created" @denied="hideCustomerPrivate" />
    <MappingDialog v-if="mappingAccess" :access="mappingAccess" @close="closeMapping" @changed="mappingChanged" />
    <AccessActionDialog v-if="action" :access="action.access" :action="action.type" :account="action.account" @close="closeAction" @changed="actionChanged" @denied="hideActionPrivate" />
  </section>
</template>

<style scoped src="./portal-page.css"></style>
<style scoped>
.panel-alert { margin: 12px 14px 0; width: auto; }
p, small { color: var(--text-secondary); overflow-wrap: anywhere; }
.drawer-title { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
h3 { margin: 20px 0 8px; font-family: var(--font-display); font-size: 15px; font-weight: 700; color: var(--text-primary); }
.drawer-title h3 { margin: 0; }
.el-alert { margin-bottom: 12px; }
.account-card { border: 1px solid var(--border-color); padding: 14px 16px; border-radius: var(--card-radius); margin: 12px 0; font-size: 13px; background: var(--card-bg); }
.account-card p { margin: 6px 0; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.actions .actions { margin: 0; }
</style>
