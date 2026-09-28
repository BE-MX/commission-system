<template>
  <div class="fx-page" :class="{ 'fx-app': standalone }">
    <div class="fx-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /></div>
    <header class="fx-header"><div><span class="eyebrow">SETTLEMENT ADVISOR</span><h2>结汇决策助手</h2><p>用最新参考报价、你的资金期限与风险预算，找到当前条件下更合适的结汇方案。</p></div><div class="header-tools"><span class="mode-label">美元 → 人民币</span><RouterLink v-if="!standalone" to="/fx-settlement" class="app-link">手机应用入口 ↗</RouterLink><button v-else class="account-button" type="button" :disabled="!!busy" @click="signOut">退出登录</button></div></header>
    <div class="mobile-section" :class="{ 'mobile-hidden': activeSection !== 'market' }">
      <FxInstallHint v-if="standalone" />
    <FxMarket :market="market" :loading="marketLoading" :error="marketError" :clock="clock" @refresh="loadMarket" />
      <GlassButton class="mobile-start" variant="primary" @click="showSection('calculate')">填写资金，开始测算</GlassButton>
    </div>
    <div class="workspace">
      <form ref="formElement" novalidate class="input-panel lg-card is-static" :class="{ 'mobile-hidden': activeSection !== 'calculate' }" @submit.prevent="run(false)">
        <div class="mobile-context"><span>美元 → 人民币</span><strong>{{ market?.quote ? Number(market.quote.rate).toFixed(4) : '暂无参考价' }}</strong><button type="button" @click="showSection('market')">查看行情</button></div>
        <fieldset :disabled="!!busy">
          <legend>这笔资金的条件</legend><p class="form-intro">只填已到账资金。未来尚未收到的货款，需要单独匹配远期结汇期限。</p>
          <div class="field-pair"><label>已到账美元金额 <span>USD</span><input v-model="form.usd_balance" name="usd_balance" type="number" inputmode="decimal" min="0.01" max="1000000000" step="0.01" placeholder="例如 100000" required></label><label>必须保留的美元 <span>USD</span><input v-model="form.reserved_usd" name="reserved_usd" type="number" inputmode="decimal" min="0" :max="form.usd_balance || 1000000000" step="0.01" required></label></div>
          <label>现在必须补足的人民币净缺口 <span>CNY</span><input v-model="form.immediate_cny_need" name="immediate_cny_need" type="number" inputmode="decimal" min="0" max="1000000000" step="0.01" required><small>已扣除现有可用人民币；这部分优先结汇。</small></label>
          <label>剩余美元最晚结汇日期<input v-model="form.settle_by" name="settle_by" type="date" :min="today" :max="maxDate" required></label>
          <label>相对全部现在结汇，可接受少得多少 <span>CNY</span><input v-model="form.max_loss_cny" name="max_loss_cny" type="number" inputmode="decimal" min="0" max="1000000000" step="0.01" placeholder="例如 2000" required><small>填 0 表示不留等待敞口；不是实际损失保证上限。</small></label>
          <label>压力情景：美元下跌幅度 <span>%</span><input v-model="form.stress_drop_pct" name="stress_drop_pct" type="number" inputmode="decimal" min="0.1" max="30" step="0.1" required><small>默认 2% 是假设，可以按你的判断调整，并非预测。</small></label>
          <label class="check-label"><input v-model="manualQuote" type="checkbox" @change="setQuoteTime">填写银行实际报价</label>
          <div v-if="manualQuote" class="quote-fields"><label>实际结汇报价 <span>CNY / USD</span><input v-model="form.bank_rate" name="bank_rate" type="number" inputmode="decimal" min="1" max="20" step="0.0001" placeholder="例如 6.7000" required></label><label>报价时间（北京时间）<input v-model="form.bank_quote_at" name="bank_quote_at" type="datetime-local" step="1" required><small>报价超过 15 分钟需重新核对。</small></label></div>
          <details class="advanced"><summary>利息和费用（可选）</summary><div class="field-pair"><label>美元年化利率 <span>%</span><input v-model="form.usd_interest_pct" name="usd_interest_pct" type="number" inputmode="decimal" min="0" max="20" step="0.01" required></label><label>人民币年化利率 <span>%</span><input v-model="form.cny_interest_pct" name="cny_interest_pct" type="number" inputmode="decimal" min="0" max="20" step="0.01" required></label></div><label>报价外额外费用 <span>基点</span><input v-model="form.fee_bps" name="fee_bps" type="number" inputmode="decimal" min="0" max="1000" step="0.1" required><small>1 基点 = 0.01%；报价已含全部费用时填 0。</small></label></details>
        </fieldset>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <div class="form-actions"><GlassButton native-type="submit" variant="secondary" :disabled="!!busy" :loading="busy === 'calculate'">先算金额</GlassButton><GlassButton v-permission="'fx_settlement:write'" variant="primary" :disabled="!!busy" :loading="busy === 'ai'" @click="run(true)">{{ busy === 'ai' ? 'AI 正在分析…' : '生成 AI 策略' }}</GlassButton></div>
        <p class="privacy">输入只用于本次测算；AI 分析会将金额和条件交给系统配置的模型。此工具不会执行结汇。</p>
      </form>
      <div class="result-section" :class="{ 'mobile-hidden': activeSection !== 'result' }">
        <div class="mobile-result-actions"><GlassButton variant="secondary" @click="showSection('calculate')">{{ result ? '修改条件 / 重新测算' : '填写资金条件' }}</GlassButton></div>
        <SettlementResult :result="result" :stale="resultStale" />
      </div>
    </div>
    <nav class="mobile-nav" aria-label="结汇助手导航">
      <button v-for="item in sections" :key="item.id" type="button" :aria-current="activeSection === item.id ? 'page' : undefined" @click="showSection(item.id)"><component :is="item.icon" aria-hidden="true" /><span>{{ item.label }}</span><span v-if="item.id === 'result' && resultStale" class="stale-dot" aria-label="需要重新测算" /></button>
    </nav>
  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { TrendCharts, EditPen, Document } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { fxSettlementLogin } from '@/router/fxSettlementRoute'
import FxInstallHint from './FxInstallHint.vue'
import GlassButton from '@/components/GlassButton.vue'
import { calculateSettlement, generateSettlementAdvice, getFxMarket } from '@/api/fxSettlement'
import { currentBeijingDate, currentBeijingDateTime, formatBeijingDate, parseApiDateTime } from '@/utils/datetime'
import FxMarket from './FxMarket.vue'
import SettlementResult from './SettlementResult.vue'

const route = useRoute()
const auth = useAuthStore()
const standalone = computed(() => route.meta.fullscreen === true)
const activeSection = ref('market')
const sections = [{ id: 'market', label: '行情', icon: TrendCharts }, { id: 'calculate', label: '测算', icon: EditPen }, { id: 'result', label: '方案', icon: Document }]
async function showSection(section) {
  activeSection.value = section
  await nextTick()
  if (window.matchMedia('(max-width: 800px)').matches) window.scrollTo({ top: 0, behavior: 'instant' })
}
async function signOut() { if (!busy.value) await auth.logout(fxSettlementLogin()) }
const clock = ref(Date.now())
const today = computed(() => currentBeijingDate(new Date(clock.value)))
const maxDate = computed(() => formatBeijingDate(new Date(clock.value + 365 * 86400000)))
const form = reactive({ usd_balance: '', reserved_usd: '0', immediate_cny_need: '0', settle_by: formatBeijingDate(new Date(Date.now() + 30 * 86400000)), max_loss_cny: '', stress_drop_pct: '2', bank_rate: '', bank_quote_at: '', fee_bps: '0', usd_interest_pct: '0', cny_interest_pct: '0' })
const manualQuote = ref(false)
const formElement = ref(null)
const market = ref(null), marketLoading = ref(false), marketError = ref('')
const result = ref(null), busy = ref(''), error = ref(''), inputSnapshot = ref('')
let timer, alive = true

function payload() {
  return { ...form, bank_rate: manualQuote.value ? form.bank_rate : null, bank_quote_at: manualQuote.value ? form.bank_quote_at : null }
}
const resultStale = computed(() => {
  if (!result.value) return false
  const age = clock.value - parseApiDateTime(result.value.rate_at).getTime()
  return inputSnapshot.value !== JSON.stringify(payload())
    || age > (result.value.input.bank_rate == null ? 1800000 : 900000)
    || (result.value.input.bank_rate == null && market.value?.quote?.rate !== result.value.rate)
})
function errorText(exc) {
  const detail = exc.response?.data?.detail
  if (Array.isArray(detail)) return '请检查金额、日期和利率是否在允许范围内。'
  return typeof detail === 'string' ? detail : exc.message || '请求失败，请稍后重试'
}
function setQuoteTime() {
  if (manualQuote.value) form.bank_quote_at = currentBeijingDateTime()
}
function applyMarket(data) {
  if (!market.value || parseApiDateTime(data.checked_at) >= parseApiDateTime(market.value.checked_at)) market.value = data
}
async function loadMarket() {
  if (marketLoading.value) return
  marketLoading.value = true
  try {
    const data = await getFxMarket()
    if (alive) { applyMarket(data); marketError.value = '' }
  } catch (exc) { if (alive) marketError.value = errorText(exc) }
  finally { if (alive) marketLoading.value = false }
}
async function run(withAi) {
  if (busy.value) return
  // Reveal invalid optional fields before native validation tries to focus them.
  const invalid = formElement.value.querySelector('input:invalid')
  if (invalid?.closest('details')) invalid.closest('details').open = true
  if (!formElement.value.reportValidity()) return
  const data = payload()
  busy.value = withAi ? 'ai' : 'calculate'
  error.value = ''
  try {
    const response = await (withAi ? generateSettlementAdvice(data) : calculateSettlement(data))
    if (!alive) return
    result.value = response
    applyMarket(response.market)
    clock.value = Date.now()
    inputSnapshot.value = JSON.stringify(data)
    await showSection('result')
  } catch (exc) { if (alive) error.value = errorText(exc) }
  finally { if (alive) busy.value = '' }
}
function startPolling() {
  if (timer) return
  clock.value = Date.now()
  loadMarket()
  timer = setInterval(() => { clock.value = Date.now(); if (document.visibilityState === 'visible') loadMarket() }, 60000)
}
function stopPolling() { clearInterval(timer); timer = null }
onMounted(startPolling)
onActivated(startPolling)
onDeactivated(stopPolling)
onBeforeUnmount(() => { alive = false; stopPolling() })
</script>

<style scoped src="./fx-mobile.css"></style>

<style scoped>
.fx-page { position: relative; max-width: 1440px; margin: 0 auto; color: var(--text-primary); }.fx-aurora { inset: -24px -28px; }
.fx-header,.workspace,.mobile-section { position: relative; z-index: 1; }.fx-header { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 24px; }.eyebrow { font: 700 11px var(--font-display); letter-spacing: .13em; color: var(--color-primary-hover); }h2 { font-size: 28px; margin: 8px 0; letter-spacing: -.04em; }.fx-header p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }.mode-label { flex-shrink: 0; border: 1px solid var(--border-color); border-radius: 20px; padding: 8px 15px; font-size: 12px; background: var(--dash-glass-bg); }
.workspace { display: grid; grid-template-columns: minmax(320px, .9fr) minmax(0, 1.6fr); gap: 22px; margin-top: 22px; }.result-section { min-width: 0; }.input-panel { padding: 24px; min-width: 0; align-self: start; }fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }legend { font-size: 17px; font-weight: 700; margin-bottom: 8px; }.form-intro,.privacy { color: var(--text-secondary); font-size: 12px; line-height: 1.65; margin: 0 0 20px; }.privacy { margin: 14px 0 0; }
label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 17px; }label>span { float: right; color: var(--text-secondary); font-size: 11px; font-weight: 400; }input:not([type=checkbox]) { box-sizing: border-box; display: block; width: 100%; min-width: 0; margin-top: 7px; height: 40px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--card-bg); color: var(--text-primary); padding: 8px 10px; font: 400 14px var(--font-body); }input:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }small { display: block; margin-top: 5px; font-size: 11px; line-height: 1.6; font-weight: 400; color: var(--text-secondary); }.field-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }.check-label { display: flex; align-items: center; gap: 7px; min-height: 32px; }.check-label input { accent-color: var(--color-primary); }.quote-fields { padding: 14px 12px 1px; border-radius: 10px; background: var(--color-primary-light); }.advanced { margin-top: 10px; }summary { color: var(--text-secondary); font-size: 12px; cursor: pointer; padding-bottom: 16px; }.form-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }.form-actions>* { flex: 1; }.form-error { color: var(--color-danger-text); font-size: 13px; line-height: 1.6; }
@media(max-width:1100px) { .workspace { grid-template-columns: minmax(280px,.9fr) minmax(0,1.2fr); }.field-pair { grid-template-columns: 1fr; gap: 0; } }
@media(max-width:800px) { .workspace { grid-template-columns: 1fr; }.fx-header { align-items: flex-start; flex-direction: column; }.fx-header h2 { font-size: 25px; }.field-pair { grid-template-columns: 1fr 1fr; gap: 12px; }.input-panel { padding: 18px; } }
@media(max-width:450px) { .field-pair { grid-template-columns: 1fr; gap: 0; }input:not([type=checkbox]) { font-size: 16px; } }
</style>
