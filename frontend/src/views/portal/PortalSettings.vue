<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import { msgError, msgSuccess } from '@/utils/feedback'
import { createAccessMutation } from './customerAccess.mjs'
import { sitePolicyPayload } from './sitePolicy.mjs'

const auth = useAuthStore(), current = ref(null), loading = ref(false), state = ref('idle'), error = ref(''), notice = ref(''), confirmed = ref(false)
const form = reactive({ name: '', status: 'disabled', quote_valid_minutes: 15, proposal_hours: '24, 48', payment_terms: [], sales_contacts: [], default_payment_term_code: null, reason: '' })
const errorSummary = ref(null), noticeSummary = ref(null)
let generation = 0, sequence = 0, controller, disposed = false, errorSequence = 0
const mutation = createAccessMutation(async operation => {
  const result = await portalAdminApi.updateSiteSettings(operation.body, operation.version)
  if (result?.configured !== true || !result?.id || result.site_code !== operation.id) throw new Error('站点回执不完整，请读取当前配置核对。')
  return { ...result, public_id: result.id, id: result.site_code }
})
const locked = computed(() => loading.value || ['sending', 'uncertain'].includes(state.value))
const message = e => e?.response?.data?.message || (e?.code === 'ERR_NETWORK' ? '网络连接中断，请按页面提示核对。' : e?.message) || '站点配置暂不可用。'
async function showError(value) {
  const current = ++errorSequence
  error.value = value
  await nextTick()
  if (!disposed && current === errorSequence && error.value === value) errorSummary.value?.$el?.focus()
}
async function focusNotice(identity, request) {
  await nextTick()
  if (!disposed && identity === generation && (request === undefined || request === sequence) && notice.value) noticeSummary.value?.$el?.focus()
}
watch(form, () => { confirmed.value = false }, { deep: true, flush: 'sync' })
function clear() {
  generation++; sequence++; errorSequence++; controller?.abort(); mutation.clear(); current.value = null; state.value = 'idle'; loading.value = false
  Object.assign(form, { name: '', status: 'disabled', quote_valid_minutes: 15, proposal_hours: '', payment_terms: [], sales_contacts: [], default_payment_term_code: null, reason: '' }); confirmed.value = false
}
async function load(recovery = false) {
  if (state.value === 'sending' || loading.value) return
  const identity = generation, request = ++sequence
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''
  try {
    const result = await portalAdminApi.siteSettings(controller.signal)
    if (identity !== generation || request !== sequence) return
    current.value = result
    Object.assign(form, { name: result.name || '', status: result.status || 'disabled', quote_valid_minutes: result.policy.quote_valid_minutes, proposal_hours: result.policy.proposal_valid_hours.join(', '), payment_terms: structuredClone(result.policy.payment_terms), sales_contacts: structuredClone(result.policy.sales_contacts || []), default_payment_term_code: result.policy.default_payment_term_code, reason: '' })
    mutation.clear(); state.value = 'idle'; confirmed.value = false
    notice.value = recovery ? '已读取当前配置并放弃本地草稿；不能据此确认先前保存成功。本次未重发写入。' : ''
    if (recovery) void focusNotice(identity, request)
  } catch (e) {
    if (identity === generation && request === sequence) {
      if ([401, 403, 404].includes(e?.response?.status)) clear()
      else if (state.value !== 'uncertain') current.value = null
      void showError(message(e))
    }
  } finally { if (identity === generation && request === sequence) loading.value = false }
}
async function save() {
  if (locked.value || !confirmed.value || !current.value) return
  let body
  try { body = sitePolicyPayload(form) } catch (e) { void showError(message(e)); return }
  const identity = generation
  try {
    error.value = ''; notice.value = ''
    const promise = mutation.execute({ action: 'site', id: current.value.site_code, version: current.value.row_version, body }); state.value = mutation.state
    const result = await promise
    if (identity !== generation || !result) return
    state.value = mutation.state; current.value = { ...result, id: result.public_id }; confirmed.value = false; form.reason = ''
    msgSuccess('保存站点配置'); notice.value = '站点配置已保存。客户访问仍受部署功能开关、账号、目录与价格等条件共同控制。'
    void focusNotice(identity)
  } catch (e) { if (identity === generation) { state.value = mutation.state; if ([401, 403, 404].includes(e?.response?.status)) clear(); void showError(message(e)) } }
}
function removeTerm(index) { if (!locked.value) form.payment_terms.splice(index, 1) }
function beforeUnload(event) { if (locked.value) { event.preventDefault(); event.returnValue = '' } }
watch(() => [auth.accessToken, auth.user], () => { clear(); error.value = ''; notice.value = '' })
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError('请先核对站点保存结果。'); return false } })
onBeforeUnmount(() => { disposed = true; clear(); window.removeEventListener('beforeunload', beforeUnload) })
onMounted(() => load())
</script>

<template>
  <section class="portal-settings" v-loading="loading" :aria-busy="loading || state === 'sending' || undefined">
    <header><div><h1>客户门户站点设置</h1><p>统一维护客户站入口状态、报价期限与可选付款条件。</p></div><GlassButton :disabled="loading || state === 'sending'" @click="load(true)">读取当前配置并放弃草稿</GlassButton></header>
    <p v-if="loading || state === 'sending'" role="status">{{ loading ? '正在读取站点配置…' : '正在保存站点配置，请等待回执…' }}</p>
    <el-alert v-if="error" ref="errorSummary" id="portal-settings-error" tabindex="-1" :title="error" type="error" :closable="false" />
    <el-alert v-if="notice" ref="noticeSummary" tabindex="-1" :title="notice" type="info" :closable="false" />
    <el-alert v-if="state === 'uncertain'" title="保存结果未知，表单已冻结。请读取当前配置核对，不会自动重试保存。" type="warning" :closable="false" />
    <template v-if="current">
      <div class="site-facts"><span>{{ current.configured ? '已配置' : '尚未初始化' }} · 版本 {{ current.row_version }}</span><span>站点 {{ current.site_code }}</span><span>域名 {{ current.origin }}</span><span>USD · English</span></div>
      <el-form label-position="top" :disabled="locked" :aria-describedby="error ? 'portal-settings-error' : undefined">
        <div class="settings-card"><h2>访问与期限</h2><el-form-item label="站点名称"><el-input v-model="form.name" aria-label="站点名称" maxlength="100" /></el-form-item>
          <el-form-item label="站点访问状态"><el-radio-group v-model="form.status"><el-radio-button value="disabled">停用</el-radio-button><el-radio-button value="enabled">启用</el-radio-button></el-radio-group></el-form-item>
          <p>切换启停会撤销当前登录及待验证会话，并使旧报价失效；重新启用不会恢复旧会话。修改政策会使旧报价失效。域名和部署密钥由部署配置管理。</p>
          <div class="field-grid"><el-form-item label="报价有效期（分钟）"><el-input-number v-model="form.quote_valid_minutes" aria-label="报价有效期" :min="1" :max="30" :precision="0" /></el-form-item><el-form-item label="提案可选有效期（小时）"><el-input v-model="form.proposal_hours" aria-label="提案有效期" placeholder="如 24, 48" maxlength="40" /></el-form-item></div>
        </div>
        <div class="settings-card"><h2>付款条件</h2><p>填写已确认的英文客户说明和定金比例；这些内容将进入客户确认的交易条件。此处不预设任何商业承诺。</p>
          <article v-for="(term, index) in form.payment_terms" :key="index" class="payment-term">
            <div class="field-grid"><el-form-item :label="`条件 ${index + 1} · 稳定代码`"><el-input v-model="term.code" :aria-label="`付款代码 ${index + 1}`" maxlength="64" /></el-form-item><el-form-item label="定金比例（%）"><el-input v-model="term.deposit_percent" :aria-label="`定金比例 ${index + 1}`" placeholder="0.00–100.00" maxlength="6" /></el-form-item></div>
            <el-form-item label="客户付款说明（英文）"><el-input v-model="term.display_text" :aria-label="`付款说明 ${index + 1}`" maxlength="256" /></el-form-item><GlassButton :disabled="locked" @click="removeTerm(index)">移除此付款条件</GlassButton>
          </article>
          <GlassButton :disabled="locked || form.payment_terms.length >= 20" @click="form.payment_terms.push({ code: '', display_text: '', deposit_percent: '' })">添加付款条件</GlassButton>
          <el-form-item label="默认付款条件" class="default-term"><el-select v-model="form.default_payment_term_code" aria-label="默认付款条件" clearable><el-option v-for="(term, index) in form.payment_terms.filter(t => t.code)" :key="index" :label="`${term.code} · ${term.display_text}`" :value="term.code" /></el-select></el-form-item>
        </div>
        <div class="settings-card"><h2>获准对外展示的业务员名片</h2><p>客户只可查看当前负责人的获准名片。这里单独填写对外信息，不读取员工账号的邮箱和手机号；取消批准后，下次客户读取将隐藏名片。</p>
          <article v-for="(contact, index) in form.sales_contacts" :key="index" class="payment-term">
            <div class="field-grid"><el-form-item label="方舟员工"><el-select v-model="contact.user_id" filterable :aria-label="`名片员工 ${index + 1}`"><el-option v-for="employee in current.contact_employee_options || []" :key="employee.id" :value="employee.id" :label="employee.name" /></el-select></el-form-item><el-form-item label="对外称呼（英文）"><el-input v-model="contact.display_name" :aria-label="`对外称呼 ${index + 1}`" maxlength="100" /></el-form-item></div>
            <div class="field-grid"><el-form-item label="对外邮箱"><el-input v-model="contact.email" :aria-label="`对外邮箱 ${index + 1}`" maxlength="254" /></el-form-item><el-form-item label="WhatsApp（含国家码）"><el-input v-model="contact.whatsapp" :aria-label="`WhatsApp ${index + 1}`" placeholder="+8613800000000" maxlength="16" /></el-form-item></div>
            <el-checkbox v-model="contact.approved">批准此名片对所属客户展示</el-checkbox><GlassButton :disabled="locked" @click="form.sales_contacts.splice(index, 1)">移除此名片</GlassButton>
          </article>
          <GlassButton :disabled="locked || form.sales_contacts.length >= 200" @click="form.sales_contacts.push({ user_id: '', display_name: '', email: '', whatsapp: '', approved: false })">添加业务员名片</GlassButton>
        </div>
        <div class="settings-card"><el-form-item label="操作原因"><el-input v-model="form.reason" aria-label="站点操作原因" type="textarea" :rows="2" maxlength="500" /></el-form-item><el-checkbox v-model="confirmed">我已核对启停、报价失效和付款条件对客户的影响</el-checkbox><div class="save"><GlassButton v-permission="'portal_site:admin'" :disabled="locked || !confirmed" variant="primary" @click="save">保存站点配置</GlassButton></div></div>
      </el-form>
    </template>
  </section>
</template>

<style scoped>
.portal-settings { max-width: 1040px; margin: 0 auto; }
header { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 24px; }
h1 { font-size: 24px; margin: 0; } h2 { font-size: 18px; margin-top: 0; }
p, .site-facts { color: var(--text-secondary); line-height: 1.7; overflow-wrap: anywhere; }
.site-facts { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 20px 0; }
.settings-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 24px; margin-bottom: 20px; }
.field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.payment-term { border-bottom: 1px solid var(--border-color); padding: 16px 0; margin-bottom: 16px; }
.el-select { width: 100%; } .default-term { margin-top: 20px; }
.el-alert { margin-bottom: 16px; } .el-alert:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; } .save { display: flex; justify-content: flex-end; margin-top: 20px; }
.el-checkbox { height: auto; white-space: normal; }
@media (max-width: 600px) { header { align-items: flex-start; flex-direction: column; } .field-grid { grid-template-columns: 1fr; gap: 0; } .settings-card { padding: 16px; } }
</style>
<style>.portal-settings .el-checkbox__label { white-space: normal; line-height: 1.6; }</style>
