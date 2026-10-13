<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { portalAdminApi } from '@/api/portal'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import { isEmail } from '@/utils/validators'
import { createAccessMutation, accessStatuses } from './customerAccess.mjs'

const props = defineProps({ access: { type: Object, required: true }, action: { type: String, required: true }, account: { type: Object, default: null } })
const emit = defineEmits(['close', 'changed', 'denied'])
const auth = useAuthStore(), error = ref(''), state = ref('idle'), resolving = ref(false), denied = ref(false), errorSummary = ref(null)
const titles = { access: '设置客户访问', createAccount: '创建采购账号', account: '设置采购账号', password: '设置账号密码' }
const form = reactive({ email: props.account?.email || '', contact_name: props.account?.contact_name || '', password: '', reason: '', confirmed: false,
  status: ['enabled', 'suspended'].includes(props.access.status) ? props.access.status : '',
  can_view_price: props.access.capabilities.can_view_price, can_order: props.access.capabilities.can_order,
  account_status: props.account?.status === 'active' ? 'disabled' : 'active' })
const mutation = createAccessMutation(value => portalAdminApi.accessMutation(value))
const locked = computed(() => ['sending', 'uncertain'].includes(state.value) || resolving.value)
let generation = 0, controller, disposed = false, errorSequence = 0
const message = e => e?.response?.data?.message || (e?.code === 'ERR_NETWORK' ? '网络连接中断，请按页面提示核对。' : e?.message) || '操作失败，请重试。'
async function showError(value) {
  const current = ++errorSequence, identity = generation
  error.value = value
  await nextTick()
  if (!disposed && current === errorSequence && identity === generation && error.value === value) errorSummary.value?.$el?.focus()
}
function hideDenied(e) {
  if (![401, 403, 404].includes(e?.response?.status)) return
  denied.value = true
  // Retain the uncertain creation command in memory; clear the visible private draft.
  Object.assign(form, { email: '', contact_name: '', password: '', reason: '', confirmed: false })
  emit('denied')
}
watch(() => [form.email, form.contact_name, form.password, form.reason, form.status, form.can_view_price, form.can_order, form.account_status], () => { form.confirmed = false }, { flush: 'sync' })
watch(() => form.can_view_price, value => { if (!value) form.can_order = false })
function close() { if (!locked.value) { form.password = ''; emit('close') } }
function resetIdentity() { form.password = ''; generation++; errorSequence++; controller?.abort(); mutation.clear(); state.value = 'idle'; emit('close') }
watch(() => [auth.accessToken, auth.user], resetIdentity)
function beforeUnload(event) { if (locked.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError('请先核对当前操作结果。'); return false } })
onBeforeUnmount(() => { form.password = ''; disposed = true; generation++; errorSequence++; controller?.abort(); mutation.clear(); window.removeEventListener('beforeunload', beforeUnload) })
function validatePassword() {
  if (form.password.length < 8 || form.password.length > 64 || new TextEncoder().encode(form.password).length > 72) throw new Error('密码须为 8–64 个字符，且不超过 72 个 UTF-8 字节。')
}
function operation() {
  if (!form.confirmed) throw new Error('请先核对并确认操作。')
  if (props.action === 'createAccount') {
    const email = form.email.trim(), contact_name = form.contact_name.trim()
    if (!isEmail(email) || email.length > 254 || !contact_name || contact_name.length > 100) throw new Error('请填写有效邮箱和采购联系人。')
    validatePassword()
    return { action: 'createAccount', id: props.access.id, key: crypto.randomUUID(), body: { email, contact_name, password: form.password } }
  }
  const reason = form.reason.trim()
  if (!reason || reason.length > 500) throw new Error('请填写 1–500 字的操作原因。')
  if (props.action === 'access') {
    if (!['enabled', 'suspended'].includes(form.status)) throw new Error('请选择启用或暂停。')
    return { action: 'access', id: props.access.id, version: props.access.row_version,
      body: { status: form.status, capabilities: { can_view_price: form.can_view_price, can_order: form.can_order }, reason } }
  }
  if (props.action === 'account') return { action: 'account', id: props.account.id, version: props.account.row_version, body: { status: form.account_status, reason } }
  validatePassword()
  return { action: 'password', id: props.account.id, version: props.account.row_version, body: { password: form.password, reason } }
}
async function submit(retry = false) {
  if (state.value === 'sending' || resolving.value || (denied.value && !retry)) return
  let value
  try { value = retry ? undefined : operation() } catch (e) { void showError(message(e)); return }
  const current = generation
  error.value = ''
  try {
    const promise = mutation.execute(value); state.value = mutation.state
    const result = await promise
    if (current !== generation || !result) return
    state.value = mutation.state
    if (props.action !== 'createAccount') msgSuccess('保存设置')
    emit('changed', props.action === 'createAccount' ? '采购账号已创建。请通过约定渠道将登录邮箱和密码交给客户。' : '')
    emit('close')
  } catch (e) { if (current === generation) { state.value = mutation.state; hideDenied(e); void showError(message(e)) } }
}
async function inspectCurrent() {
  if (props.action === 'createAccount' || state.value !== 'uncertain' || resolving.value) return
  const current = generation
  controller?.abort(); controller = new AbortController(); resolving.value = true; error.value = ''
  try {
    await portalAdminApi.customer(props.access.id, { page: 1, page_size: 20 }, controller.signal)
    if (current !== generation) return
    mutation.clear(); state.value = 'idle'
    emit('changed', '已重新读取当前状态，但无法确认刚才操作是否成功。请核对账号和访问状态后再处理；本次没有重发写入。')
    emit('close')
  } catch (e) { if (current === generation) { hideDenied(e); void showError(message(e)) } }
  finally { if (current === generation) resolving.value = false }
}
</script>

<template>
  <el-dialog :model-value="true" :title="titles[action]" width="640px" class="portal-access-action" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <div class="access-action-content" :aria-busy="state === 'sending' || resolving || undefined">
    <p v-if="!denied"><strong>{{ access.company_display_name }}</strong><br />{{ account?.email || '仅对当前客户生效' }}</p>
    <p v-if="state === 'sending' || resolving" role="status">{{ resolving ? '正在读取当前客户与账号状态…' : '正在提交账号操作，请等待回执…' }}</p>
    <el-alert v-if="error" ref="errorSummary" id="portal-access-action-error" tabindex="-1" :title="error" type="error" :closable="false" />
    <el-alert v-if="state === 'uncertain'" title="结果尚未确认。账号创建可按原操作标识重试；其他设置请读取当前状态核对，不会自动重复写入。请勿刷新或关闭浏览器。" type="warning" :closable="false" />
    <el-form v-if="!denied" label-position="top" :disabled="locked" :aria-describedby="error ? 'portal-access-action-error' : undefined">
      <template v-if="action === 'createAccount'">
        <el-alert title="账号可读取该公司的订单与授权金额。密码只用于登录，不会通过邮件发送。" type="info" :closable="false" />
        <el-form-item label="采购邮箱"><el-input v-model="form.email" aria-label="采购邮箱" maxlength="254" autocomplete="off" /></el-form-item>
        <el-form-item label="采购联系人"><el-input v-model="form.contact_name" aria-label="采购联系人" maxlength="100" /></el-form-item>
        <el-form-item label="登录密码"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" aria-label="登录密码" maxlength="64" /></el-form-item>
      </template>
      <template v-else-if="action === 'access'">
        <el-alert title="保存后该公司现有登录会话失效，需要重新登录。暂停后客户不能继续访问或提交；已有订单保留。商品授权保持原样。" type="warning" :closable="false" />
        <el-form-item label="客户访问状态"><el-radio-group v-model="form.status"><el-radio-button value="enabled">启用</el-radio-button><el-radio-button value="suspended">暂停</el-radio-button></el-radio-group></el-form-item>
        <p>当前状态：{{ accessStatuses[access.status] }}</p>
        <el-checkbox v-model="form.can_view_price">允许查看价格、订单金额与 PI</el-checkbox>
        <el-checkbox v-model="form.can_order" :disabled="locked || !form.can_view_price">允许下单及确认交易条件</el-checkbox>
      </template>
      <el-alert v-else-if="action === 'account'" :title="form.account_status === 'disabled' ? '停用账号并撤销全部登录会话，历史订单保留。' : '恢复账号；已设置密码、客户授权、成员关系及公司归属仍须有效。'" type="warning" :closable="false" />
      <template v-else-if="action === 'password'">
        <el-alert title="设置密码会立即撤销该账号的旧会话。账号启停状态保持原值，客户需使用新密码重新登录。" type="warning" :closable="false" />
        <el-form-item label="新密码"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" aria-label="新密码" maxlength="64" /></el-form-item>
      </template>
      <el-form-item v-if="action !== 'createAccount'" label="操作原因"><el-input v-model="form.reason" aria-label="操作原因" type="textarea" maxlength="500" show-word-limit /></el-form-item>
      <el-checkbox v-model="form.confirmed">我已核对客户与影响，确认本次操作</el-checkbox>
    </el-form>
    </div>
    <template #footer>
      <GlassButton :disabled="locked" @click="close">取消</GlassButton>
      <template v-if="state === 'uncertain'">
        <GlassButton v-if="action !== 'createAccount'" :loading="resolving" @click="inspectCurrent">读取当前状态</GlassButton>
        <GlassButton v-if="action === 'createAccount'" v-permission="'portal_access:admin'" :disabled="resolving" variant="primary" @click="submit(true)">重试原创建</GlassButton>
      </template>
      <GlassButton v-else-if="!denied" v-permission="'portal_access:admin'" variant="primary" :disabled="!form.confirmed" :loading="state === 'sending'" @click="submit()">确认操作</GlassButton>
    </template>
  </el-dialog>
</template>

<style scoped>
.el-alert { margin: 12px 0 16px; }
.el-alert:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
p { overflow-wrap: anywhere; }
.el-checkbox { display: flex; height: auto; margin: 12px 0; white-space: normal; }
</style>
<style>.portal-access-action { max-width: calc(100vw - 24px); } .portal-access-action .el-checkbox__label { white-space: normal; line-height: 1.6; }</style>
