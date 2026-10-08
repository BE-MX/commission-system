<script setup>
import { nextTick, onBeforeUnmount, ref, toRaw, watch } from 'vue'
import { Refresh, View } from '@element-plus/icons-vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { useListPage } from '@/composables/useListPage'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import AccessActionDialog from './AccessActionDialog.vue'
import MappingDialog from './MappingDialog.vue'
import OnboardingDialog from './OnboardingDialog.vue'
import CatalogAccessDialog from './CatalogAccessDialog.vue'
import BindingReviewDialog from './BindingReviewDialog.vue'
import { accessStatuses, accountStatuses, invitationStatuses } from './customerAccess.mjs'

const auth = useAuthStore(), listError = ref(''), detailError = ref(''), notice = ref('')
const detail = ref(null), detailVisible = ref(false), detailLoading = ref(false), accountPage = ref(1)
const action = ref(null), mappingAccess = ref(null), onboardingVisible = ref(false), catalogAccess = ref(null), bindingAccess = ref(null)
let listController, detailController, listSequence = 0, detailSequence = 0, disposed = false, detailId = ''
const mappingTrigger = ref(null), pageRoot = ref(null), pageRefresh = ref(null), detailContent = ref(null), detailRefresh = ref(null), onboardingTrigger = ref(null)
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
const { list, total, page, pageSize, loading, searchForm, fetchList, handleSearch, handlePageChange, handleSizeChange } = useListPage(async params => {
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
async function loadDetail(id = detailId, pageNumber = accountPage.value) {
  if (!id) return
  const current = ++detailSequence
  detailController?.abort(); detailController = new AbortController()
  detailId = id; accountPage.value = pageNumber; detail.value = null; detailError.value = ''; detailLoading.value = true; detailVisible.value = true
  try {
    const data = await portalAdminApi.customer(id, { page: pageNumber, page_size: 20 }, detailController.signal)
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
      || buttons.find(el => el.dataset.portalAction === 'invite' && !el.dataset.portalAccount && !el.disabled)
      || detailRefresh.value?.$el
  } else if (!detailVisible.value) {
    button = denied && !refreshed ? pageRefresh.value?.$el
      : [...(pageRoot.value?.querySelectorAll('button[data-portal-access]') || [])].find(el => el.dataset.portalAccess === closing.access.id) || pageRefresh.value?.$el
  }
  if (button?.isConnected && !button.disabled) button.focus()
}
function openOnboarding() { ++onboardingFocusSequence; onboardingRefresh = Promise.resolve(); onboardingCreatedId = null; onboardingVisible.value = true }
function created({ id, recovered }) {
  notice.value = recovered ? '已找到现有客户授权，请核对当前设置；此查询不证明先前命令执行结果。' : '客户授权草稿已创建。请核对后设置为启用，再邀请采购联系人。'
  onboardingCreatedId = id; onboardingRefresh = Promise.all([fetchList(), loadDetail(id, 1)])
}
async function closeOnboarding() {
  onboardingVisible.value = false
  const current = ++onboardingFocusSequence, id = onboardingCreatedId
  await onboardingRefresh
  await nextTick()
  if (disposed || current !== onboardingFocusSequence || onboardingVisible.value || action.value || mappingAccess.value || catalogAccess.value || bindingAccess.value) return
  const button = id && detailVisible.value && detail.value?.id === id ? detailRefresh.value?.$el : !detailVisible.value ? onboardingTrigger.value?.$el : null
  if (button?.isConnected && !button.disabled) button.focus()
}
function clearPrivate() {
  ++reviewFocusSequence; reviewRefresh = Promise.resolve()
  ++onboardingFocusSequence; onboardingRefresh = Promise.resolve(); onboardingCreatedId = null
  ++actionFocusSequence; actionRefresh = Promise.resolve()
  ++mappingFocusSequence; mappingRefresh = Promise.resolve()
  ++listSequence; listController?.abort(); list.value = []; total.value = 0; listError.value = ''; notice.value = ''; action.value = null; mappingAccess.value = null; onboardingVisible.value = false; catalogAccess.value = null; bindingAccess.value = null
  detailVisible.value = false; clearDetail()
}
watch(() => [auth.accessToken, auth.user], clearPrivate)
onBeforeUnmount(() => { disposed = true; clearPrivate() })
</script>

<template>
  <section ref="pageRoot" class="portal-customers">
    <header class="portal-heading"><div><h1>客户访问与采购账号</h1><p>管理客户查价、下单和登录资格，变更按方舟当前客户归属生效。</p></div><div class="actions"><GlassButton v-permission="'portal_access:admin'" ref="onboardingTrigger" variant="primary" @click="openOnboarding">开通客户门户</GlassButton><GlassButton ref="pageRefresh" :left-icon="Refresh" :disabled="loading" @click="fetchList">刷新</GlassButton></div></header>
    <el-row :gutter="16" class="toolbar">
      <el-col :xs="24" :sm="12" :md="9"><el-input v-model="searchForm.keyword" maxlength="100" clearable aria-label="搜索客户" placeholder="公司名称或完整 OKKI 公司 ID" @keyup.enter="handleSearch" @clear="handleSearch" /></el-col>
      <el-col :xs="16" :sm="8" :md="6"><el-select v-model="searchForm.status" aria-label="访问状态" placeholder="全部状态" clearable @change="handleSearch"><el-option v-for="(label, value) in accessStatuses" :key="value" :label="label" :value="value" /></el-select></el-col>
      <el-col :xs="8" :sm="4" :md="3"><GlassButton @click="handleSearch">搜索</GlassButton></el-col>
    </el-row>
    <el-alert v-if="listError" :title="listError" type="error" :closable="false" />
    <div class="table-card">
      <el-table v-loading="loading" :data="list" border class="list-table" empty-text="当前范围内没有匹配的客户授权">
        <el-table-column prop="company_display_name" label="客户公司" min-width="220" show-overflow-tooltip />
        <el-table-column label="访问状态" min-width="130"><template #default="{ row }"><el-tag effect="plain">{{ accessStatuses[row.status] || '状态待核实' }}</el-tag></template></el-table-column>
        <el-table-column label="客户能力" min-width="180"><template #default="{ row }">{{ row.capabilities.can_order ? '查价与下单' : row.capabilities.can_view_price ? '仅查价' : '仅查看目录' }}</template></el-table-column>
        <el-table-column prop="sales_user_id" label="负责人 ID" min-width="130" />
        <el-table-column label="操作" fixed="right" min-width="100" class-name="table-action-column"><template #default="{ row }"><GlassButton v-permission="'portal_access:read'" variant="link" :left-icon="View" :data-portal-access="row.id" @click="openDetail(row.id)">管理</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>
    <DetailDrawer v-model="detailVisible" title="客户访问与账号" :width="820" :loading="detailLoading">
      <div ref="detailContent">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <el-alert v-if="notice" :title="notice" type="info" :closable="false" />
      <GlassButton v-if="!detailLoading" ref="detailRefresh" @click="loadDetail()">刷新详情</GlassButton>
      <template v-if="detail">
        <h2>{{ detail.company_display_name }}</h2>
        <p>方舟客户 {{ detail.canonical_customer_id }} · 负责人 {{ detail.sales_user_id }} · {{ accessStatuses[detail.status] }}</p>
        <p>查价 {{ detail.capabilities.can_view_price ? '已允许' : '未允许' }} · 下单 {{ detail.capabilities.can_order ? '已允许' : '未允许' }} · 已授权商品 {{ detail.catalog_item_ids.length }} 项</p>
        <el-alert v-if="detail.status === 'review_required'" title="客户身份或归属需要复核，普通启停不能解除此状态。" type="warning" :closable="false" />
        <div v-permission="'portal_access:admin'" class="actions">
          <GlassButton ref="bindingTrigger" @click="openReview('binding')">归属与身份复核</GlassButton>
          <GlassButton ref="catalogTrigger" :disabled="detail.status === 'review_required'" @click="openReview('catalog')">管理商品授权</GlassButton>
          <GlassButton :disabled="detail.status === 'review_required'" data-portal-action="access" @click="openAction('access')">设置客户访问</GlassButton>
          <GlassButton variant="primary" :disabled="detail.status !== 'enabled'" data-portal-action="invite" @click="openAction('invite')">邀请采购账号</GlassButton>
        </div>
        <GlassButton v-permission="'portal_mapping:read'" @click="$router.push({ name: 'PortalCustomerPreview', params: { accessId: detail.id } })">预览客户目录</GlassButton>
        <GlassButton ref="mappingTrigger" v-permission="'portal_mapping:read'" @click="openMapping">型号颜色映射</GlassButton>
        <h3>采购账号 <small>共 {{ detail.accounts.total }} 个</small></h3>
        <p>公司成员共享该公司的订单。邮箱验证、账号状态和成员关系均须有效。</p>
        <el-empty v-if="!detail.accounts.items.length" description="暂无采购账号，可在启用客户后发送邀请" />
        <article v-for="account in detail.accounts.items" :key="account.id" class="account-card">
          <strong>{{ account.contact_name || '采购联系人' }}</strong><p>{{ account.email }}</p>
          <p>{{ accountStatuses[account.status] || '状态待核实' }} · {{ account.email_verified ? '邮箱已验证' : '邮箱未验证' }} · 成员{{ accountStatuses[account.membership_status] || account.membership_status }}</p>
          <p v-if="account.invitation">最近邀请：{{ invitationStatuses[account.invitation.status] || '状态待核实' }}</p>
          <div v-permission="'portal_access:admin'" class="actions">
            <GlassButton data-portal-action="account" :data-portal-account="account.id" @click="openAction('account', account)">{{ account.status === 'disabled' ? '恢复账号' : '停用账号' }}</GlassButton>
            <GlassButton :disabled="detail.status !== 'enabled' || account.status === 'disabled' || account.membership_status === 'disabled'" data-portal-action="invite" :data-portal-account="account.id" @click="openAction('invite', account)">重新邀请</GlassButton>
            <GlassButton v-if="account.invitation?.status === 'pending'" data-portal-action="revoke" :data-portal-account="account.id" @click="openAction('revoke', account)">撤销邀请</GlassButton>
          </div>
        </article>
        <el-pagination :current-page="accountPage" :page-size="20" :total="detail.accounts.total" layout="total, prev, pager, next" @current-change="value => loadDetail(detailId, value)" />
      </template>
      </div>
    </DetailDrawer>
    <BindingReviewDialog v-if="bindingAccess" :access="bindingAccess" @close="closeReview('binding')" @changed="reviewChanged" @denied="hideReviewPrivate" />
    <CatalogAccessDialog v-if="catalogAccess" :access="catalogAccess" @close="closeReview('catalog')" @changed="reviewChanged" @denied="hideReviewPrivate" />
    <OnboardingDialog v-if="onboardingVisible" @close="closeOnboarding" @created="created" @denied="hideCustomerPrivate" />
    <MappingDialog v-if="mappingAccess" :access="mappingAccess" @close="closeMapping" @changed="mappingChanged" />
    <AccessActionDialog v-if="action" :access="action.access" :action="action.type" :account="action.account" @close="closeAction" @changed="actionChanged" @denied="hideActionPrivate" />
  </section>
</template>

<style scoped>
.portal-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 24px; }
h1 { margin: 0 0 8px; font-size: 24px; }
p, small { color: var(--text-secondary); overflow-wrap: anywhere; }
.toolbar { row-gap: 12px; margin-bottom: 16px; }
.el-select { width: 100%; }
.table-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; overflow: hidden; }
.el-pagination { padding: 16px; overflow-x: auto; }
.el-alert { margin-bottom: 16px; }
.account-card { border: 1px solid var(--border-color); padding: 16px; border-radius: 12px; margin: 16px 0; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 600px) { .portal-heading { align-items: flex-start; flex-direction: column; } h1 { font-size: 20px; } }
</style>
