<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useListPage } from '@/composables/useListPage'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import { msgError, msgSuccess } from '@/utils/feedback'
import CatalogPicker from './CatalogPicker.vue'

const emit = defineEmits(['close', 'created', 'denied'])
const auth = useAuthStore(), selected = ref(null), products = ref([]), error = ref(''), state = ref('idle'), checking = ref(false), denied = ref(false), errorSummary = ref(null)
const form = reactive({ can_view_price: true, can_order: true, confirmed: false })
const reasons = { CUSTOMER_DISPUTED: '客户身份存在冲突', VERIFIED_IDENTITY_MISSING: '缺少当前来源的已验证公司身份', MULTIPLE_VERIFIED_IDENTITIES: '存在多个已验证外部身份，需先复核', IDENTITY_VALUE_INVALID: '外部公司 ID 不符合要求', ACCESS_ALREADY_EXISTS: '已经配置门户授权' }
const locked = computed(() => ['sending', 'uncertain'].includes(state.value) || checking.value)
let generation = 0, sequence = 0, controller, statusController, frozen = null, disposed = false, errorSequence = 0
const message = e => e?.response?.data?.message || (e?.code === 'ERR_NETWORK' ? '网络连接中断，请按页面提示核对。' : e?.message) || '操作失败，请重试。'
async function showError(value) {
  const current = ++errorSequence, identity = generation
  error.value = value
  await nextTick()
  if (!disposed && current === errorSequence && identity === generation && error.value === value) errorSummary.value?.$el?.focus()
}
function hideDenied(e) {
  if (![401, 403, 404].includes(typeof e === 'number' ? e : e?.response?.status)) return
  denied.value = true; ++sequence; controller?.abort()
  selected.value = null; products.value = []; list.value = []; total.value = 0; searchForm.keyword = ''; form.confirmed = false
  // An unknown result must retain its original binding/body for inspection or exact retry.
  if (!['sending', 'uncertain'].includes(state.value)) frozen = null
  emit('denied')
}
function catalogDenied(status) { hideDenied(status); void showError('当前商品或客户授权范围已变化，请重新核对。') }
const { list, total, page, pageSize, loading, searchForm, handleSearch, handlePageChange, handleSizeChange } = useListPage(async params => {
  const current = ++sequence, identity = generation
  controller?.abort(); controller = new AbortController(); list.value = []; total.value = 0; error.value = ''
  try {
    const result = await portalAdminApi.onboardingCustomers(params, controller.signal)
    return current === sequence && identity === generation ? result : { items: [], total: 0 }
  } catch (e) { if (current === sequence && identity === generation) { hideDenied(e); void showError(message(e)) }; return { items: [], total: 0 } }
}, { searchForm: { keyword: '' } })
function choose(row) { if (!locked.value && row.ready) { selected.value = row; products.value = []; form.confirmed = false; error.value = ''; state.value = 'idle'; frozen = null } }
watch(() => form.can_view_price, value => { if (!value) form.can_order = false })
watch(() => [form.can_view_price, form.can_order, products.value], () => { form.confirmed = false }, { deep: true, flush: 'sync' })
function body() {
  if (!selected.value?.ready || !form.confirmed) throw new Error('请核对客户、商品和能力后确认。')
  return { binding_fingerprint: selected.value.binding_fingerprint, canonical_customer_id: selected.value.canonical_customer_id, assignment_id: selected.value.assignment_id,
    okki_identity_id: selected.value.okki_identity_id, catalog_item_ids: products.value.map(item => item.id),
    capabilities: { can_view_price: form.can_view_price, can_order: form.can_order } }
}
async function create(retry = false) {
  if (state.value === 'sending' || checking.value || (state.value === 'uncertain' && !retry) || (denied.value && !retry)) return
  try { if (!retry) frozen = structuredClone(body()); else if (!frozen) return } catch (e) { void showError(message(e)); return }
  const identity = generation, wasUnknown = state.value === 'uncertain'
  state.value = 'sending'; error.value = ''
  try {
    const result = await portalAdminApi.createCustomer(structuredClone(frozen))
    if (identity !== generation) return
    if (!result.id || result.canonical_customer_id !== frozen.canonical_customer_id || result.status !== 'draft') throw new Error('创建回执不完整，请查询当前客户授权。')
    state.value = 'success'; msgSuccess('创建客户授权草稿'); emit('created', { id: result.id, recovered: false }); emit('close')
  } catch (e) {
    if (identity !== generation) return
    state.value = wasUnknown || !e?.response?.status || e.response.status >= 500 ? 'uncertain' : 'failed'
    hideDenied(e); void showError(message(e))
  }
}
async function inspectExisting() {
  const customerId = frozen?.canonical_customer_id || selected.value?.canonical_customer_id
  if (state.value === 'sending' || checking.value || !customerId) return
  const identity = generation
  checking.value = true; error.value = ''; statusController?.abort(); statusController = new AbortController()
  try {
    const result = await portalAdminApi.onboardingStatus(customerId, statusController.signal)
    if (identity !== generation) return
    if (result.existing_access?.id) {
      state.value = 'idle'; emit('created', { id: result.existing_access.id, recovered: true }); emit('close')
    } else void showError(result.existing_access ? '该客户已有授权，但当前归属需要管理员复核。' : '尚未查到已有授权，不能据此判断先前请求未执行。结果未知时请仅重试原内容。')
  } catch (e) { if (identity === generation) { hideDenied(e); void showError(message(e)) } }
  finally { if (identity === generation) checking.value = false }
}
function openExisting(row) { if (row.existing_access?.id && !locked.value) { emit('created', { id: row.existing_access.id, recovered: true }); emit('close') } }
function close() { if (!locked.value) emit('close') }
function clear() { generation++; sequence++; errorSequence++; controller?.abort(); statusController?.abort(); frozen = null; selected.value = null; products.value = []; list.value = []; state.value = 'idle' }
watch(() => [auth.accessToken, auth.user], () => { clear(); emit('close') })
function beforeUnload(event) { if (locked.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError('开通结果待核对，请先查询当前授权。'); return false } })
onBeforeUnmount(() => { disposed = true; clear(); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <el-dialog :model-value="true" :title="!denied && selected ? `创建授权草稿 · ${selected.company_display_name}` : '开通客户门户 · 选择方舟客户'" width="760px" class="portal-onboarding-dialog" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <div class="onboarding-content" :aria-busy="loading || state === 'sending' || checking || undefined">
    <p v-if="loading || state === 'sending' || checking" role="status">{{ checking ? '正在查询已有客户授权…' : state === 'sending' ? '正在创建客户授权草稿，请等待回执…' : '正在读取可开通客户…' }}</p>
    <el-alert v-if="error" ref="errorSummary" id="portal-onboarding-error" tabindex="-1" :title="error" type="error" :closable="false" />
    <el-alert v-if="state === 'uncertain'" title="创建结果未知，原客户、身份和商品内容已冻结。请先查询已有授权；未查到时只重试原内容，不更换客户或商品。" type="warning" :closable="false" />
    <template v-if="!selected && !denied">
      <p>只显示当前有效主负责人范围内的客户。开通需要唯一、已验证的方舟外部公司身份；身份缺失或冲突须先在客户档案中复核。</p>
      <div class="candidate-search"><el-input v-model="searchForm.keyword" aria-label="搜索开通客户" placeholder="公司名称或完整方舟客户编码" maxlength="100" @keyup.enter="handleSearch" /><GlassButton :disabled="loading" @click="handleSearch">搜索客户</GlassButton></div>
      <el-table v-loading="loading" :data="list" border class="list-table" v-sticky-scrollbar><template #empty><el-empty :image-size="72" description="没有匹配客户，请先核对客户建档和主负责人归属" /></template>
        <el-table-column label="方舟客户" min-width="200"><template #default="{ row }"><strong>{{ row.company_display_name }}</strong><p>{{ row.customer_code || row.canonical_customer_id }}</p></template></el-table-column>
        <el-table-column label="主负责人" min-width="140"><template #default="{ row }">{{ row.sales_display_name || row.sales_user_id }}</template></el-table-column>
        <el-table-column label="开通条件" min-width="240"><template #default="{ row }"><span v-if="row.ready">可开通 · OKKI 公司 {{ row.okki_company_id }}</span><p v-for="reason in row.blocked_reasons" v-else :key="reason">{{ reasons[reason] || '需要复核' }}</p></template></el-table-column>
        <el-table-column label="操作" min-width="130" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton v-if="row.existing_access?.id" v-permission="'portal_access:read'" variant="link" @click="openExisting(row)">查看已有授权</GlassButton><GlassButton v-else v-permission="'portal_access:admin'" :disabled="!row.ready" variant="link" @click="choose(row)">选择此客户</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </template>
    <template v-else-if="!denied">
      <dl class="identity"><div><dt>方舟客户</dt><dd>{{ selected.company_display_name }} · {{ selected.customer_code || selected.canonical_customer_id }}</dd></div><div><dt>主负责人</dt><dd>{{ selected.sales_display_name || selected.sales_user_id }}</dd></div><div><dt>已验证 OKKI 公司</dt><dd>{{ selected.okki_company_id }}</dd></div></dl>
      <CatalogPicker v-model="products" :disabled="locked" @denied="catalogDenied" />
      <el-form label-position="top" :disabled="locked" :aria-describedby="error ? 'portal-onboarding-error' : undefined">
        <h3>客户能力</h3><el-checkbox v-model="form.can_view_price">允许查看价格、订单金额与 PI</el-checkbox><el-checkbox v-model="form.can_order" :disabled="locked || !form.can_view_price">允许下单及确认交易条件</el-checkbox>
        <el-alert title="此步骤只创建授权草稿，不启用访问、不创建采购账号、不发送邀请。核对草稿后，再启用客户并邀请采购联系人。" type="info" :closable="false" />
        <el-checkbox v-model="form.confirmed">我已核对公司身份、负责人、已选商品和客户能力</el-checkbox>
      </el-form>
    </template>
    </div>
    <template #footer>
      <GlassButton :disabled="locked" @click="close">关闭</GlassButton>
      <GlassButton v-if="selected && !locked" @click="selected = null; form.confirmed = false">返回选择客户</GlassButton>
      <GlassButton v-if="selected || state === 'uncertain'" :disabled="state === 'sending'" :loading="checking" @click="inspectExisting">查询已有授权</GlassButton>
      <GlassButton v-if="state === 'uncertain'" v-permission="'portal_access:admin'" :disabled="checking" variant="primary" @click="create(true)">重试原内容</GlassButton>
      <GlassButton v-else-if="selected" v-permission="'portal_access:admin'" :loading="state === 'sending'" :disabled="!form.confirmed || checking" variant="primary" @click="create()">创建授权草稿</GlassButton>
    </template>
  </el-dialog>
</template>

<style scoped>
.candidate-search { display: flex; gap: 12px; margin: 16px 0; }
.el-alert { margin: 12px 0; }
.el-alert:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.el-pagination { overflow-x: auto; padding: 16px 0; }
p { color: var(--text-secondary); overflow-wrap: anywhere; }
.identity div { display: flex; justify-content: space-between; gap: 16px; margin: 12px 0; }
dt { flex-shrink: 0; color: var(--text-secondary); } dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
.el-checkbox { display: flex; height: auto; white-space: normal; margin: 12px 0; }
</style>
<style>.portal-onboarding-dialog { max-width: calc(100vw - 24px); } .portal-onboarding-dialog .el-checkbox__label { white-space: normal; line-height: 1.6; } .portal-onboarding-dialog .el-dialog__footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; } .portal-onboarding-dialog .el-dialog__footer button { margin-left: 0; }</style>
