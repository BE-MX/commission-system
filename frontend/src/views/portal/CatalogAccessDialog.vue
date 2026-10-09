<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import { msgError, msgSuccess } from '@/utils/feedback'
import CatalogPicker from './CatalogPicker.vue'
import { createAccessMutation } from './customerAccess.mjs'

const props = defineProps({ access: { type: Object, required: true } })
const emit = defineEmits(['close', 'changed', 'denied'])
const auth = useAuthStore(), data = ref(null), products = ref([]), reason = ref(''), confirmed = ref(false)
const state = ref('idle'), loading = ref(false), error = ref(''), notice = ref('')
const mutation = createAccessMutation(value => portalAdminApi.accessMutation(value))
const locked = computed(() => loading.value || ['sending', 'uncertain'].includes(state.value))
const removed = computed(() => data.value?.items.filter(item => !products.value.some(row => row.id === item.id)) || [])
const added = computed(() => products.value.filter(item => !data.value?.items.some(row => row.id === item.id)))
let generation = 0, sequence = 0, controller, disposed = false, feedbackSequence = 0
const denied = ref(false), errorSummary = ref(null), noticeSummary = ref(null)
const message = e => e?.response?.data?.message || (e?.code === 'ERR_NETWORK' ? '网络连接中断，请按页面提示核对。' : e?.message) || '商品授权读取失败。'

async function showFeedback(value, isNotice = false) {
  const current = ++feedbackSequence, identity = generation
  const text = isNotice ? notice : error, target = isNotice ? noticeSummary : errorSummary
  text.value = value
  await nextTick()
  if (!disposed && current === feedbackSequence && identity === generation && text.value === value) target.value?.$el?.focus()
}
function hideDenied(e) {
  if (![401, 403, 404].includes(typeof e === 'number' ? e : e?.response?.status)) return
  denied.value = true; ++sequence; controller?.abort(); loading.value = false; data.value = null; notice.value = ''
  products.value = []; reason.value = ''; confirmed.value = false
  // Keep the original in-flight/unknown mutation for GET inspection; never resend it.
  emit('denied')
}
watch([products, reason], () => { confirmed.value = false }, { deep: true, flush: 'sync' })
async function load(recovery = false) {
  if (state.value === 'sending' || loading.value) return
  const identity = generation, current = ++sequence
  loading.value = true; error.value = ''; notice.value = ''; ++feedbackSequence; controller?.abort(); controller = new AbortController()
  try {
    const result = await portalAdminApi.customerCatalog(props.access.id, controller.signal)
    if (identity !== generation || current !== sequence) return
    if (result.id !== props.access.id || !Array.isArray(result.items)) throw new Error('商品授权回执不完整。')
    denied.value = false; data.value = result; products.value = structuredClone(result.items); reason.value = ''; confirmed.value = false
    mutation.clear(); state.value = 'idle'
    if (recovery) { const text = '已读取当前授权并放弃本地草稿，不能据此确认刚才保存成功。请核对后重新编辑；本次没有重发写入。'; void showFeedback(text, true); emit('changed', text) }
  } catch (e) {
    if (identity === generation && current === sequence) {
      hideDenied(e); void showFeedback(message(e)); if (state.value !== 'uncertain') { data.value = null; products.value = [] }
    }
  } finally { if (identity === generation && current === sequence) loading.value = false }
}
async function save() {
  if (locked.value || denied.value || !data.value || !confirmed.value) return
  if (!reason.value.trim()) { void showFeedback('请填写操作原因。'); return }
  const current = generation
  try {
    const promise = mutation.execute({ action: 'catalog', id: props.access.id, version: data.value.row_version,
      body: { catalog_item_ids: products.value.map(item => item.id), reason: reason.value.trim() } })
    state.value = mutation.state; error.value = ''; notice.value = ''; ++feedbackSequence
    const result = await promise
    if (current !== generation || !result) return
    state.value = mutation.state; msgSuccess('保存商品授权'); emit('changed', '商品授权已更新，客户需重新登录；旧报价需要重新获取，历史订单保持原样。'); emit('close')
  } catch (e) { if (current === generation) { state.value = mutation.state; hideDenied(e); void showFeedback(message(e)) } }
}
function close() { if (!locked.value) emit('close') }
function clear() { generation++; sequence++; feedbackSequence++; controller?.abort(); mutation.clear(); data.value = null; products.value = []; reason.value = ''; confirmed.value = false; state.value = 'idle'; loading.value = false }
watch(() => [auth.accessToken, auth.user], () => { clear(); emit('close') })
function beforeUnload(event) { if (locked.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError('请先读取并核对商品授权结果。'); return false } })
onBeforeUnmount(() => { disposed = true; clear(); window.removeEventListener('beforeunload', beforeUnload) })
onMounted(() => load())
</script>

<template>
  <el-dialog :model-value="true" :title="denied ? '商品授权 · 权限需要核对' : `商品授权 · ${access.company_display_name}`" width="760px" class="portal-catalog-access" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <div v-loading="loading" class="review-content" :aria-busy="loading || state === 'sending' || undefined">
      <p v-if="loading || state === 'sending'" role="status">{{ loading ? '正在读取当前商品授权…' : '正在保存商品授权，请等待回执…' }}</p>
      <el-alert v-if="error" ref="errorSummary" id="portal-catalog-access-error" tabindex="-1" :title="error" type="error" :closable="false" />
      <el-alert v-if="notice" ref="noticeSummary" tabindex="-1" :title="notice" type="info" :closable="false" />
      <el-alert v-if="state === 'uncertain'" title="保存结果未知，当前选择已冻结。请读取当前授权核对，不会自动重发写入。" type="warning" :closable="false" />
      <template v-if="data">
        <el-alert title="本次只调整商品授权，不启用客户、不修改查价或下单能力。保存后现有会话与报价失效，历史订单保留。已下架商品即使保留授权也不会显示给客户；移除后不可重新添加，直至再次发布。" type="info" :closable="false" />
        <CatalogPicker v-model="products" title="客户商品授权" :disabled="locked || data.status === 'review_required'" @denied="status => { hideDenied(status); void showFeedback('当前商品或客户授权范围已变化，请重新核对。') }" />
        <p>本次新增 {{ added.length }} 项 · 移除 {{ removed.length }} 项 · 保留 {{ products.filter(item => item.status && item.status !== 'published').length }} 项已下架授权</p>
        <details v-if="removed.length"><summary>查看将移除的商品</summary><p v-for="item in removed" :key="item.id">{{ item.model_name }} / {{ item.color_name }} · {{ item.length }} · {{ item.weight }}</p></details>
        <el-alert v-if="!products.length" title="当前选择为空，保存将撤销该客户全部商品授权。" type="warning" :closable="false" />
        <el-form label-position="top" :disabled="locked || data.status === 'review_required'" :aria-describedby="error ? 'portal-catalog-access-error' : undefined">
          <el-form-item label="操作原因"><el-input v-model="reason" aria-label="商品授权操作原因" maxlength="500" type="textarea" :rows="2" /></el-form-item>
          <el-checkbox v-model="confirmed">我已核对新增、移除和保留商品，以及重新登录和报价失效的影响</el-checkbox>
        </el-form>
      </template>
    </div>
    <template #footer>
      <GlassButton :disabled="locked" @click="close">关闭</GlassButton>
      <GlassButton :disabled="loading || state === 'sending'" @click="load(true)">读取当前授权并放弃草稿</GlassButton>
      <GlassButton v-permission="'portal_access:admin'" variant="primary" :disabled="locked || !confirmed || !reason.trim() || !data || data.status === 'review_required'" @click="save">保存商品授权</GlassButton>
    </template>
  </el-dialog>
</template>

<style scoped>
.el-alert:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.el-alert { margin-bottom: 16px; }
.el-form { margin-top: 20px; }
.el-checkbox { height: auto; white-space: normal; }
p { color: var(--text-secondary); overflow-wrap: anywhere; }
</style>
<style>.portal-catalog-access { max-width: calc(100vw - 24px); } .portal-catalog-access .el-checkbox__label { white-space: normal; line-height: 1.6; } .portal-catalog-access .el-dialog__footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; } .portal-catalog-access .el-dialog__footer button { margin-left: 0; }</style>
