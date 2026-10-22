<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import { msgError, msgSuccess } from '@/utils/feedback'
import { statusDictionary } from '@/utils/status'
import { createAccessMutation } from './customerAccess.mjs'
import { formatTiers, sitePolicyPayload } from './sitePolicy.mjs'

const SITE_STATE = statusDictionary([['enabled', '站点已启用', 'success'], ['disabled', '站点已停用', 'warning']])

const auth = useAuthStore(), current = ref(null), loading = ref(false), state = ref('idle'), error = ref(''), notice = ref(''), confirmed = ref(false)
const form = reactive({ name: '', status: 'disabled', quote_valid_minutes: 15, proposal_hours: '24, 48', payment_terms: [], sales_contacts: [], default_payment_term_code: null, auto_fees_enabled: false, shipping_tiers: '300=40.00, 600=48.00, 800=56.00, 1000=64.00, 1300=72.00, 1600=80.00, 1800=88.00, 2000=96.00', reason: '' })
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
  Object.assign(form, { name: '', status: 'disabled', quote_valid_minutes: 15, proposal_hours: '', payment_terms: [], sales_contacts: [], default_payment_term_code: null, auto_fees_enabled: false, shipping_tiers: '', reason: '' }); confirmed.value = false
}
async function load(recovery = false) {
  if (state.value === 'sending' || loading.value) return
  const identity = generation, request = ++sequence
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''
  try {
    const result = await portalAdminApi.siteSettings(controller.signal)
    if (identity !== generation || request !== sequence) return
    current.value = result
    Object.assign(form, { name: result.name || '', status: result.status || 'disabled', quote_valid_minutes: result.policy.quote_valid_minutes, proposal_hours: result.policy.proposal_valid_hours.join(', '), payment_terms: structuredClone(result.policy.payment_terms), sales_contacts: structuredClone(result.policy.sales_contacts || []), default_payment_term_code: result.policy.default_payment_term_code, auto_fees_enabled: result.policy.auto_fees?.enabled === true, shipping_tiers: formatTiers(result.policy.auto_fees?.shipping_tiers), reason: '' })
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
  <section class="portal-page portal-settings" :aria-busy="loading || state === 'sending' || undefined">
    <div class="portal-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" /></div>
    <header class="page-header"><div><h2>客户门户站点设置</h2><p>统一维护客户站入口状态、报价期限与可选付款条件。</p></div></header>
    <div class="settings-body" v-loading="loading">
      <div class="settings-card facts-card">
        <div v-if="current" class="site-facts"><StatusBadge :value="current.status" :dictionary="SITE_STATE" effect="plain" /><span>{{ current.configured ? '已配置' : '尚未初始化' }} · 版本 {{ current.row_version }}</span><span>站点 {{ current.site_code }}</span><span>域名 {{ current.origin }}</span><span>USD · English</span></div>
        <span v-else class="site-facts">{{ loading ? '正在读取站点配置…' : '尚未读取站点配置' }}</span>
        <GlassButton variant="secondary" left-icon="RefreshLeft" :disabled="loading || state === 'sending'" @click="load(true)">读取当前配置并放弃草稿</GlassButton>
      </div>
      <p v-if="state === 'sending'" role="status" class="status-line">正在保存站点配置，请等待回执…</p>
      <el-alert v-if="error" ref="errorSummary" id="portal-settings-error" tabindex="-1" :title="error" type="error" :closable="false" show-icon />
      <el-alert v-if="notice" ref="noticeSummary" tabindex="-1" :title="notice" type="info" :closable="false" show-icon />
      <el-alert v-if="state === 'uncertain'" title="保存结果未知，表单已冻结。请读取当前配置核对，不会自动重试保存。" type="warning" :closable="false" show-icon />
      <el-form v-if="current" label-position="top" :disabled="locked" :aria-describedby="error ? 'portal-settings-error' : undefined">
        <div class="settings-card"><h3>访问与期限</h3><el-form-item label="站点名称"><el-input v-model="form.name" aria-label="站点名称" maxlength="100" /></el-form-item>
          <el-form-item label="站点访问状态"><el-radio-group v-model="form.status"><el-radio-button value="disabled">停用</el-radio-button><el-radio-button value="enabled">启用</el-radio-button></el-radio-group></el-form-item>
          <p class="card-hint">切换启停会撤销当前登录及待验证会话，并使旧报价失效；重新启用不会恢复旧会话。修改政策会使旧报价失效。域名和部署密钥由部署配置管理。</p>
          <div class="field-grid"><el-form-item label="报价有效期（分钟）"><el-input-number v-model="form.quote_valid_minutes" aria-label="报价有效期" :min="1" :max="30" :precision="0" /></el-form-item><el-form-item label="提案可选有效期（小时）"><el-input v-model="form.proposal_hours" aria-label="提案有效期" placeholder="如 24, 48" maxlength="40" /></el-form-item></div>
        </div>
        <div class="settings-card"><h3>付款条件</h3><p class="card-hint">填写已确认的英文客户说明和定金比例；这些内容将进入客户确认的交易条件。此处不预设任何商业承诺。</p>
          <article v-for="(term, index) in form.payment_terms" :key="index" class="payment-term">
            <div class="field-grid"><el-form-item :label="`条件 ${index + 1} · 稳定代码`"><el-input v-model="term.code" :aria-label="`付款代码 ${index + 1}`" maxlength="64" /></el-form-item><el-form-item label="定金比例（%）"><el-input v-model="term.deposit_percent" :aria-label="`定金比例 ${index + 1}`" placeholder="0.00–100.00" maxlength="6" /></el-form-item></div>
            <el-form-item label="客户付款说明（英文）"><el-input v-model="term.display_text" :aria-label="`付款说明 ${index + 1}`" maxlength="256" /></el-form-item>
            <div class="field-grid"><el-form-item label="客户可见付款方式名称（如 PayPal）"><el-input v-model="term.method_label" :aria-label="`付款方式名称 ${index + 1}`" maxlength="40" /></el-form-item><el-form-item label="付款手续费（%，按货款+运费计）"><el-input v-model="term.surcharge_percent" :aria-label="`付款手续费 ${index + 1}`" placeholder="PayPal 5.00；银行转账 0.00" maxlength="5" /></el-form-item></div>
            <GlassButton variant="ghost" left-icon="Delete" :disabled="locked" @click="removeTerm(index)">移除此付款条件</GlassButton>
          </article>
          <GlassButton variant="outline" left-icon="Plus" :disabled="locked || form.payment_terms.length >= 20" @click="form.payment_terms.push({ code: '', display_text: '', deposit_percent: '', method_label: '', surcharge_percent: '0.00' })">添加付款条件</GlassButton>
          <el-form-item label="默认付款条件" class="default-term"><el-select v-model="form.default_payment_term_code" aria-label="默认付款条件" clearable><el-option v-for="(term, index) in form.payment_terms.filter(t => t.code)" :key="index" :label="`${term.code} · ${term.display_text}`" :value="term.code" /></el-select></el-form-item>
        </div>
        <div class="settings-card"><h3>自动运费与付款手续费</h3><p class="card-hint">启用后，客户在确认页按总克重看到运费、所选付款方式的手续费和总额；提交即视为客户确认，订单直接进入「待审核」，业务在订单页一键审核即生成正式 PI。超过最高档克重的订单不自动计价，由业务按原提案流程报运费。</p>
          <el-checkbox v-model="form.auto_fees_enabled">启用自动运费与付款手续费</el-checkbox>
          <el-form-item label="运费阶梯（克重上限=运费 USD，按总克重≤上限取第一档）" class="tiers"><el-input v-model="form.shipping_tiers" aria-label="运费阶梯" type="textarea" :rows="2" maxlength="600" placeholder="300=40.00, 600=48.00, 800=56.00" /></el-form-item>
        </div>
        <div class="settings-card"><h3>获准对外展示的业务员名片</h3><p class="card-hint">客户只可查看当前负责人的获准名片。这里单独填写对外信息，不读取员工账号的邮箱和手机号；取消批准后，下次客户读取将隐藏名片。</p>
          <article v-for="(contact, index) in form.sales_contacts" :key="index" class="payment-term">
            <div class="field-grid"><el-form-item label="方舟员工"><el-select v-model="contact.user_id" filterable :aria-label="`名片员工 ${index + 1}`"><el-option v-for="employee in current.contact_employee_options || []" :key="employee.id" :value="employee.id" :label="employee.name" /></el-select></el-form-item><el-form-item label="对外称呼（英文）"><el-input v-model="contact.display_name" :aria-label="`对外称呼 ${index + 1}`" maxlength="100" /></el-form-item></div>
            <div class="field-grid"><el-form-item label="对外邮箱"><el-input v-model="contact.email" :aria-label="`对外邮箱 ${index + 1}`" maxlength="254" /></el-form-item><el-form-item label="WhatsApp（含国家码）"><el-input v-model="contact.whatsapp" :aria-label="`WhatsApp ${index + 1}`" placeholder="+8613800000000" maxlength="16" /></el-form-item></div>
            <div class="term-actions"><el-checkbox v-model="contact.approved">批准此名片对所属客户展示</el-checkbox><GlassButton variant="ghost" left-icon="Delete" :disabled="locked" @click="form.sales_contacts.splice(index, 1)">移除此名片</GlassButton></div>
          </article>
          <GlassButton variant="outline" left-icon="Plus" :disabled="locked || form.sales_contacts.length >= 200" @click="form.sales_contacts.push({ user_id: '', display_name: '', email: '', whatsapp: '', approved: false })">添加业务员名片</GlassButton>
        </div>
        <div class="settings-card save-card"><el-form-item label="操作原因" required><el-input v-model="form.reason" aria-label="站点操作原因" type="textarea" :rows="2" maxlength="500" show-word-limit /></el-form-item><el-checkbox v-model="confirmed">我已核对启停、报价失效和付款条件对客户的影响</el-checkbox><div class="save"><GlassButton v-permission="'portal_site:admin'" :loading="state === 'sending'" :disabled="locked || !confirmed" variant="primary" left-icon="Check" @click="save">保存站点配置</GlassButton></div></div>
      </el-form>
    </div>
  </section>
</template>

<style scoped src="./portal-page.css"></style>
<style scoped>
.settings-body { max-width: 1040px; }
.settings-card { position: relative; margin-bottom: 16px; padding: 20px 24px; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); }
.settings-card h3 { margin: 0 0 12px; font-family: var(--font-display); font-size: 15px; font-weight: 700; color: var(--text-primary); }
.facts-card { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px 24px; padding: 14px 20px; }
.site-facts { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 20px; color: var(--text-secondary); font-size: 13px; overflow-wrap: anywhere; }
.card-hint { margin: 0 0 14px; color: var(--text-secondary); font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.status-line { margin: 0 0 12px; color: var(--text-secondary); font-size: 13px; }
.field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; }
.payment-term { border-bottom: 1px solid var(--border-color); padding: 14px 0; margin-bottom: 14px; }
.term-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.el-select { width: 100%; } .default-term, .tiers { margin-top: 18px; }
.el-alert { margin-bottom: 14px; } .el-alert:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.save { display: flex; justify-content: flex-end; margin-top: 16px; }
.el-checkbox { height: auto; white-space: normal; }
@media (max-width: 600px) { .field-grid { grid-template-columns: 1fr; } .settings-card { padding: 16px; } }
</style>
<style>.portal-settings .el-checkbox__label { white-space: normal; line-height: 1.6; }</style>
