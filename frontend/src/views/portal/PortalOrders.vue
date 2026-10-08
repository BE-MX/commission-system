<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { View, Refresh } from '@element-plus/icons-vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import ReviewDialog from './ReviewDialog.vue'
import AuditDialog from './AuditDialog.vue'
import NotificationDialog from './NotificationDialog.vue'
import PiReviewDialog from './PiReviewDialog.vue'
import { useListPage } from '@/composables/useListPage'
import { portalAdminApi } from '@/api/portal'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useAuthStore } from '@/stores/auth'
import { proposalNotice, piNotice, snapshotTitle } from './presentation.mjs'

const statuses = { submitted: '待业务员审核', awaiting_customer: '待客户确认', ready_for_review: '待最终审核', invoice_created: '已生成 PI', rejected: '已拒绝', cancelled: '已取消' }
const events = { 'order.submitted': '客户提交请求', 'order.proposed': '已发送确认提案', 'order.accepted': '客户已确认', 'order.proposal_rejected': '客户拒绝提案', 'order.invoice_created': '生成正式 PI', 'order.cancelled': '客户取消请求', 'order.rejected': '业务员拒绝请求', 'order.pi_proposed': '发送 PI 修改提案', 'order.pi_accepted': '客户接受 PI 修改', 'order.pi_rejected': '客户拒绝 PI 修改', 'order.pi_published': '发布已确认 PI', 'order.pi_voided': 'PI 已作废' }
const deliveryLabels = { contact_name: '联系人', phone: '电话', formatted_address: '完整地址', country_code: '国家', region: '省 / 州', city: '城市', address_line1: '地址', address_line2: '补充地址', postal_code: '邮编' }
const auth = useAuthStore(), route = useRoute()
const listError = ref('')
const detailError = ref('')
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const reviewId = ref('')
const piReviewId = ref('')
const auditId = ref('')
const notificationId = ref(''), notificationTrigger = ref(null)
let notificationFocusSequence = 0
function openNotifications(id) { ++notificationFocusSequence; notificationId.value = id }
async function closeNotifications() {
  const id = notificationId.value
  notificationId.value = ''
  const current = ++notificationFocusSequence
  await nextTick()
  if (disposed || current !== notificationFocusSequence || !detailVisible.value || notificationId.value || detail.value?.request_id !== id) return
  const button = notificationTrigger.value?.$el
  if (button?.isConnected && !button.disabled && button.getClientRects().length) button.focus()
}
const piTrigger = ref(null)
let piRefresh = Promise.resolve(), piFocusSequence = 0
function reviewed(id) { fetchList(); if (detailVisible.value && detail.value?.request_id === id) return openDetail(id) }
function openPiReview(id) { ++piFocusSequence; piRefresh = Promise.resolve(); piReviewId.value = id }
function piReviewed(id) { piRefresh = Promise.resolve(reviewed(id)) }
async function closePiReview() {
  const requestId = piReviewId.value
  piReviewId.value = ''
  const current = ++piFocusSequence
  await piRefresh
  await nextTick()
  if (disposed || current !== piFocusSequence || !detailVisible.value || piReviewId.value || reviewId.value || detail.value?.request_id !== requestId || detail.value?.status !== 'invoice_created') return
  const button = piTrigger.value?.$el
  if (button?.isConnected) button.focus()
}
let listController, detailController
let listSequence = 0, detailSequence = 0, disposed = false
const errorText = error => {
  const code = error?.response?.data?.data?.error_code
  return ({ RESOURCE_NOT_FOUND: '请求不存在或已不在当前授权范围内。', AUTH_FORBIDDEN: '当前账号没有查看权限。', ACTION_FORBIDDEN: '当前账号没有查看权限。', PORTAL_DISABLED: '客户下单门户尚未启用。' })[code] || '暂时无法读取数据，请重试。'
}
const { list, total, page, pageSize, loading, searchForm, fetchList, handleSearch, handlePageChange, handleSizeChange } = useListPage(async params => {
  const sequence = ++listSequence
  listController?.abort()
  listController = new AbortController()
  list.value = []
  total.value = 0
  listError.value = ''
  try {
    const result = await portalAdminApi.orders(params, listController.signal)
    return disposed || sequence !== listSequence ? { items: [], total: 0 } : result
  } catch (error) {
    if (!disposed && sequence === listSequence) listError.value = errorText(error)
    return { items: [], total: 0 }
  }
}, { searchForm: { status: '' } })

async function openDetail(id) {
  const sequence = ++detailSequence
  detailController?.abort()
  detailController = new AbortController()
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  detailVisible.value = true
  try {
    const result = await portalAdminApi.order(id, detailController.signal)
    if (!disposed && sequence === detailSequence) detail.value = result
  } catch (error) {
    if (!disposed && sequence === detailSequence) detailError.value = errorText(error)
  } finally {
    if (sequence === detailSequence) detailLoading.value = false
  }
}
function clearDetail() {
  ++notificationFocusSequence
  ++piFocusSequence
  ++detailSequence
  detailController?.abort()
  detail.value = null
  detailError.value = ''
  detailLoading.value = false
}
watch(detailVisible, visible => { if (!visible) clearDetail() })
watch(() => route.query.request, value => {
  if (typeof value === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value)) openDetail(value)
}, { immediate: true })
function clearPrivateState() {
  ++piFocusSequence; piRefresh = Promise.resolve()
  ++listSequence
  listController?.abort()
  list.value = []
  total.value = 0
  detailVisible.value = false
  auditId.value = ''
  notificationId.value = ''
  clearDetail()
}
watch(() => [auth.accessToken, auth.user], clearPrivateState)
onBeforeUnmount(() => { disposed = true; clearPrivateState() })
const amount = (value, currency = 'USD') => value == null ? '待确认' : `${currency} ${value}`
</script>

<template>
  <section class="portal-orders">
    <header class="portal-heading"><div><h1>客户下单请求</h1><p>核对客户需求，跟进确认与正式 PI。当前列表仅包含服务端授权的请求。</p></div>
      <GlassButton :left-icon="Refresh" :disabled="loading" @click="fetchList">刷新</GlassButton>
    </header>
    <el-row :gutter="16" class="toolbar"><el-col :xs="24" :sm="10" :md="7">
      <el-select v-model="searchForm.status" aria-label="请求状态" placeholder="全部状态" clearable @change="handleSearch">
        <el-option v-for="(label, value) in statuses" :key="value" :label="label" :value="value" />
      </el-select>
    </el-col></el-row>
    <el-alert v-if="listError" :title="listError" type="error" :closable="false" show-icon />
    <div class="table-card">
      <el-table v-loading="loading" :data="list" border class="list-table" empty-text="当前条件下没有可查看的请求">
        <el-table-column prop="request_no" label="请求编号" min-width="180" />
        <el-table-column prop="customer_po" label="客户 PO" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" min-width="150"><template #default="{ row }"><el-tag effect="plain">{{ statuses[row.status] || '状态待核实' }}</el-tag></template></el-table-column>
        <el-table-column label="金额" min-width="185"><template #default="{ row }"><div>{{ amount(row.total_amount ?? row.product_amount, row.currency) }}</div><small>{{ row.total_amount == null ? '商品小计 · 费用待确认' : row.status === 'invoice_created' ? '最近发布金额' : '请求金额' }}</small></template></el-table-column>
        <el-table-column label="提交时间（北京）" min-width="180"><template #default="{ row }">{{ formatBeijingDateTime(row.submitted_at) }}</template></el-table-column>
        <el-table-column label="操作" fixed="right" min-width="100" class-name="table-action-column"><template #default="{ row }"><GlassButton v-permission="'portal_order:read'" variant="link" :left-icon="View" @click="openDetail(row.request_id)">详情</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>
    <DetailDrawer class="portal-order-drawer" v-model="detailVisible" :title="detail?.request_no || '请求详情'" :width="820" :loading="detailLoading">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <template v-if="detail">
        <span v-permission="'portal_order:write'"><GlassButton v-if="detail.status !== 'invoice_created'" variant="primary" @click="reviewId = detail.request_id">处理请求</GlassButton><GlassButton v-else ref="piTrigger" v-permission="'invoice:write'" variant="primary" @click="openPiReview(detail.request_id)">处理原 PI</GlassButton></span>
        <el-tag effect="plain">{{ statuses[detail.status] || '状态待核实' }}</el-tag>
        <p>客户 PO：{{ detail.customer_po || '未填写' }} · {{ formatBeijingDateTime(detail.submitted_at) }}</p>
        <el-alert v-if="detail.fees?.status !== 'confirmed'" title="费用尚未确认，商品小计不是最终应付金额。" type="info" :closable="false" />
        <el-alert v-if="proposalNotice(detail)" :title="proposalNotice(detail)" type="info" :closable="false" />
        <el-alert v-if="piNotice(detail)" :title="piNotice(detail)" type="info" :closable="false" />
        <h2>{{ snapshotTitle(detail) }}</h2>
        <article v-for="item in detail.items" :key="item.line_key" class="request-line">
          <strong>{{ item.display_snapshot.model_name }} · {{ item.display_snapshot.color_name }}</strong>
          <p>{{ item.display_snapshot.customer_sku || '未设置客户货号' }} · {{ item.display_snapshot.length || '—' }} · {{ item.display_snapshot.weight || '—' }}</p>
          <div>{{ item.quantity }} {{ item.display_snapshot.unit }} × {{ amount(item.unit_price, detail.currency) }}</div>
          <div>优惠：{{ amount(item.discount_amount, detail.currency) }} · 行金额：{{ amount(item.line_amount, detail.currency) }}</div>
        </article>
        <dl class="totals"><div><dt>商品小计</dt><dd>{{ amount(detail.product_amount, detail.currency) }}</dd></div><div><dt>运费</dt><dd>{{ amount(detail.fees?.shipping_amount, detail.currency) }}</dd></div><div><dt>包装费</dt><dd>{{ amount(detail.fees?.packaging_amount, detail.currency) }}</dd></div><div><dt>{{ detail.fees?.surcharge_name || '附加费' }}</dt><dd>{{ amount(detail.fees?.surcharge_amount, detail.currency) }}</dd></div><div><dt>{{ detail.status === 'invoice_created' ? '最近发布总额' : '总额' }}</dt><dd><strong>{{ amount(detail.total_amount, detail.currency) }}</strong></dd></div></dl>
        <h2>收货信息</h2><dl class="delivery"><template v-for="(label, key) in deliveryLabels" :key="key"><div v-if="detail.delivery?.[key]"><dt>{{ label }}</dt><dd>{{ detail.delivery[key] }}</dd></div></template></dl>
        <h2>付款与备注</h2><p class="multiline">{{ detail.payment_terms_snapshot?.display_text || '付款条件待确认' }}</p><p class="multiline">{{ detail.remark || '无备注' }}</p>
        <GlassButton ref="notificationTrigger" v-permission="'portal_order:read'" @click="openNotifications(detail.request_id)">查看通知投递</GlassButton>
        <GlassButton v-permission="'portal_order:read'" @click="auditId = detail.request_id">查看操作审计</GlassButton>
        <h2>请求记录</h2><ol class="timeline"><li v-for="(event, index) in detail.customer_safe_timeline" :key="index"><span>{{ events[event.event] || '请求更新' }}</span><time>{{ formatBeijingDateTime(event.at) }}</time></li></ol>
      </template>
    </DetailDrawer>
    <AuditDialog v-if="auditId" :key="auditId" :request-id="auditId" @close="auditId = ''" />
    <NotificationDialog v-if="notificationId" :key="notificationId" :request-id="notificationId" @close="closeNotifications" />
    <ReviewDialog v-if="reviewId" :request-id="reviewId" @close="reviewId = ''" @changed="reviewed" />
    <PiReviewDialog v-if="piReviewId" :request-id="piReviewId" @close="closePiReview" @changed="piReviewed" />
  </section>
</template>

<style scoped>
.portal-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px; }
h1 { font-size: 24px; margin: 0 0 8px; }
h2 { font-size: 15px; margin: 24px 0 12px; }
p, small { color: var(--text-secondary); }
.toolbar { margin-bottom: 16px; }
.el-select { width: 100%; }
.table-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; overflow: hidden; }
.el-pagination { padding: 16px; overflow-x: auto; }
.el-alert { margin-bottom: 16px; }
.request-line { padding: 16px 0; border-bottom: 1px solid var(--border-color); overflow-wrap: anywhere; }
.request-line p { margin: 8px 0; }
.totals div, .delivery div { display: flex; justify-content: space-between; gap: 20px; margin: 10px 0; }
dd { margin: 0; text-align: right; overflow-wrap: anywhere; min-width: 0; }
dt { flex-shrink: 0; color: var(--text-secondary); max-width: 45%; overflow-wrap: anywhere; }
.multiline { white-space: pre-wrap; overflow-wrap: anywhere; }
.timeline { padding-left: 20px; }
.timeline li { margin: 12px 0; }
time { display: block; color: var(--text-secondary); font-size: 12px; }
@media (max-width: 600px) { .portal-heading { align-items: flex-start; } h1 { font-size: 20px; } }
</style>

<style>
/* Keep the full request number readable without pushing the close control outside mobile view. */
.portal-order-drawer .el-drawer__title { min-width: 0; overflow-wrap: anywhere; }
.portal-order-drawer .el-drawer__close-btn { flex-shrink: 0; }
.portal-order-drawer .el-drawer__close-btn:focus-visible { outline: 2px solid var(--color-primary-hover); outline-offset: 3px; border-radius: 4px; }
</style>
