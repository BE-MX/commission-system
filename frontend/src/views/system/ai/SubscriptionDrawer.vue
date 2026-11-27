<template>
  <DetailDrawer
    :model-value="modelValue"
    :title="editId ? `编辑订阅源 · ${providerForm.name || ''}` : '新增订阅源'"
    width="660px"
    :loading="drawerLoading"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="sub-drawer">
      <!-- 1. 连接配置（复用既有 Provider 表单与校验） -->
      <section class="drawer-sec">
        <h4 class="drawer-sec__title">1. 连接配置</h4>
        <el-form ref="providerFormRef" label-position="top" :model="providerForm" :rules="providerRules">
          <el-row :gutter="12">
            <el-col :xs="24" :sm="12">
              <el-form-item label="名称" prop="name">
                <el-input v-model="providerForm.name" placeholder="如 TeamRouter / DeepSeek" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="接入类型" prop="provider_type">
                <el-radio-group v-model="providerForm.provider_type">
                  <el-radio-button value="direct">直连大模型</el-radio-button>
                  <el-radio-button value="accio_work">ACCIO WORK</el-radio-button>
                </el-radio-group>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="API Base" prop="api_base">
            <el-input
              v-model="providerForm.api_base"
              :placeholder="providerForm.provider_type === 'accio_work' ? '填写 ACCIO 服务地址' : 'https://api.example.com/v1'"
            />
          </el-form-item>
          <el-row v-if="providerForm.provider_type === 'direct'" :gutter="12">
            <el-col :xs="24" :sm="12">
              <el-form-item label="协议类型">
                <el-radio-group v-model="providerForm.api_type">
                  <el-radio-button value="openai">OpenAI</el-radio-button>
                  <el-radio-button value="anthropic">Anthropic</el-radio-button>
                </el-radio-group>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="渠道归类">
                <el-radio-group v-model="billingForm.service_kind">
                  <el-radio-button value="official">直连官方</el-radio-button>
                  <el-radio-button value="relay">第三方中转站</el-radio-button>
                </el-radio-group>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col v-if="providerForm.provider_type !== 'accio_work'" :xs="24" :sm="16">
              <el-form-item label="API Key">
                <el-input
                  v-model="providerForm.api_key"
                  type="password"
                  show-password
                  :placeholder="editId ? '留空表示不修改' : 'sk-xxxxxxxxxxxxxxxx'"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="超时（秒）">
                <el-input-number v-model="providerForm.timeout_sec" :min="1" :max="3600" class="w-full" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-collapse>
            <el-collapse-item title="接口、认证、运行与测试配置" name="runtime">
              <AiConfigFields v-model="providerForm.runtime_config" :fields="providerFields" @validity="fieldsValid = $event" />
              <el-form-item label="附加请求头（JSON）">
                <el-input v-model="providerForm.extra_headers" type="textarea" :rows="3" placeholder='{"X-Project": "ark"}' />
                <div class="form-hint">认证值使用 {api_key} 占位符，密钥填入上方 API Key。</div>
              </el-form-item>
              <el-form-item label="运行配置（JSON）">
                <el-input v-model="providerForm.runtime_config" type="textarea" :rows="4" />
              </el-form-item>
            </el-collapse-item>
          </el-collapse>
          <el-form-item label="备注" style="margin-top: 10px">
            <el-input v-model="providerForm.remark" type="textarea" :rows="2" placeholder="用途说明" />
          </el-form-item>
        </el-form>
      </section>

      <!-- 2. 订阅、周期与外链 -->
      <section class="drawer-sec">
        <h4 class="drawer-sec__title">2. 订阅、周期与余额扣减（正交可选）</h4>
        <el-form label-position="top" :model="billingForm">
          <el-row :gutter="12">
            <el-col :xs="24" :sm="12">
              <el-form-item label="套餐名称">
                <el-input v-model="billingForm.plan_name" maxlength="64" placeholder="如 Pro 包月 / 按量充值" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="主计费方式">
                <el-select v-model="billingForm.billing_mode" class="w-full">
                  <el-option label="按量充值" value="pay_as_you_go" />
                  <el-option label="包月" value="monthly" />
                  <el-option label="包季" value="quarterly" />
                  <el-option label="包年" value="yearly" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :xs="24" :sm="8">
              <el-form-item label="周期订阅金额">
                <el-input-number v-model="billingForm.price_amount" :min="0" :precision="2" class="w-full" placeholder="可空" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="币种">
                <el-select v-model="billingForm.price_currency" class="w-full">
                  <el-option label="CNY" value="CNY" />
                  <el-option label="USD" value="USD" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="低余额预警线">
                <el-input-number v-model="billingForm.low_balance_threshold" :min="0" :precision="2" class="w-full" placeholder="可空" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :xs="24" :sm="12">
              <el-form-item label="订阅日期">
                <el-date-picker v-model="billingForm.subscribed_at" type="date" value-format="YYYY-MM-DD" class="w-full" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="下次续费 / 到期日">
                <el-date-picker v-model="billingForm.renew_at" type="date" value-format="YYYY-MM-DD" class="w-full" clearable />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item>
            <el-switch v-model="billingForm.is_balance_deducted_by_usage" active-text="按调用估算自动扣减余额（按量/额度池开启，纯固定包月可关闭）" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :xs="24" :sm="12">
              <el-form-item label="控制台链接（仅 https）">
                <el-input v-model="billingForm.console_url" placeholder="https://..." />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="API 文档链接（仅 https）">
                <el-input v-model="billingForm.docs_url" placeholder="https://..." />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item v-if="editId" label="提供商 LOGO（PNG / JPEG / WEBP，≤ 512KB，禁 SVG）">
            <div class="logo-upload-row">
              <el-upload
                :auto-upload="false"
                :show-file-list="false"
                accept=".png,.jpg,.jpeg,.webp"
                :on-change="handleLogoSelect"
              >
                <el-button :loading="logoUploading">上传 / 更换 LOGO</el-button>
              </el-upload>
              <span class="form-hint">未上传时自动展示名称首字字标。</span>
            </div>
          </el-form-item>
        </el-form>
      </section>

      <!-- 3. 余额核对与充值流水（编辑模式） -->
      <section v-if="editId" class="drawer-sec">
        <div class="drawer-sec__head">
          <h4 class="drawer-sec__title">3. 余额核对与充值流水</h4>
          <el-button @click="$emit('open-balance', subscriptionItem)">+ 登记余额</el-button>
        </div>
        <div v-if="checkpoints.length" class="cp-list">
          <div v-for="cp in checkpoints" :key="cp.id" class="cp-row">
            <div>
              <strong>{{ cp.checkpoint_kind === 'topup' ? '充值' : '核对' }} {{ formatMoney(cp.balance_amount, cp.balance_currency) }}</strong>
              <span v-if="cp.drift_amount != null" class="cp-drift">
                （较原估算 {{ Number(cp.drift_amount) >= 0 ? '+' : '' }}{{ formatMoney(cp.drift_amount, cp.balance_currency) }}）
              </span>
              <div class="form-hint">{{ cp.remark || '—' }}</div>
            </div>
            <span class="cp-time num">{{ (cp.recorded_at || '').replace('T', ' ').slice(0, 16) }}</span>
          </div>
        </div>
        <p v-else class="form-hint">尚无余额核对流水。</p>
      </section>

      <!-- 4. 统一模型单价表（编辑模式） -->
      <section v-if="editId && providerForm.provider_type !== 'accio_work'" class="drawer-sec">
        <div class="drawer-sec__head">
          <h4 class="drawer-sec__title">4. 统一模型单价表（仅影响后续新调用）</h4>
          <el-button @click="addPriceRow">+ 添加模型单价</el-button>
        </div>
        <p class="form-hint" style="margin-bottom: 8px">全平台唯一单价源，优先于预设内的 chat.pricing；支持百万 token（最多 6 位小数）、按次及生图 rate_card。</p>
        <div v-for="(row, idx) in priceRows" :key="idx" class="price-edit-row">
          <el-input v-model="row.model" placeholder="模型名" />
          <el-select v-model="row.pricing_mode">
            <el-option label="百万Token" value="token" />
            <el-option label="按次" value="per_call" />
            <el-option label="RateCard" value="image_rate_card" />
          </el-select>
          <el-input-number
            v-if="row.pricing_mode === 'token'"
            v-model="row.input_per_million"
            :min="0"
            :precision="6"
            :controls="false"
            placeholder="输入/M"
          />
          <el-input-number
            v-if="row.pricing_mode === 'token'"
            v-model="row.output_per_million"
            :min="0"
            :precision="6"
            :controls="false"
            placeholder="输出/M"
          />
          <el-input-number
            v-else-if="row.pricing_mode === 'per_call'"
            v-model="row.per_call_amount"
            :min="0"
            :precision="6"
            :controls="false"
            placeholder="单次费用"
            class="span-two"
          />
          <span v-else class="form-hint span-two">复用预设 rate_card (USD)</span>
          <el-select v-model="row.currency" :disabled="row.pricing_mode === 'image_rate_card'">
            <el-option label="CNY" value="CNY" />
            <el-option label="USD" value="USD" />
          </el-select>
          <el-button link type="danger" @click="priceRows.splice(idx, 1)">删</el-button>
        </div>
        <p v-if="!priceRows.length" class="form-hint">暂未配置单价；点击「添加模型单价」录入。</p>
      </section>
    </div>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="!fieldsValid" @click="handleSave">
        保存配置
      </el-button>
    </template>
  </DetailDrawer>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import AiConfigFields from '../components/AiConfigFields.vue'
import { providerFields } from '../aiConfigFields'
import {
  createProvider,
  getBalanceCheckpoints,
  getModelPrices,
  replaceModelPrices,
  updateProvider,
  uploadProviderLogo,
  upsertProviderBilling,
} from '@/api/ai'
import { msgError, msgSuccessText } from '@/utils/feedback'
import { formatMoney as fmtMoney } from '@/utils/money'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  subscriptionItem: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved', 'logo-updated', 'open-balance'])

const SYM = { CNY: '¥', USD: '$' }
const editId = ref(null)
const drawerLoading = ref(false)
const saving = ref(false)
const logoUploading = ref(false)
const fieldsValid = ref(true)
const providerFormRef = ref(null)

const providerForm = reactive({
  name: '',
  provider_type: 'direct',
  api_base: '',
  api_key: '',
  api_type: 'openai',
  timeout_sec: 60,
  runtime_config: '{}',
  extra_headers: '{}',
  remark: '',
})

const providerRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  provider_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  api_base: [
    { required: true, message: '请输入 API Base', trigger: 'blur' },
    { pattern: /^https?:\/\/.+/, message: '必须以 http:// 或 https:// 开头', trigger: 'blur' },
  ],
}

const billingForm = reactive({
  service_kind: 'official',
  plan_name: '',
  billing_mode: 'pay_as_you_go',
  is_balance_deducted_by_usage: true,
  price_amount: null,
  price_currency: 'CNY',
  subscribed_at: null,
  renew_at: null,
  console_url: '',
  docs_url: '',
  low_balance_threshold: null,
})

const checkpoints = ref([])
const priceRows = ref([])
const pricesLoaded = ref(false)
let loadSeq = 0

function formatMoney(val, cur = 'CNY') {
  if (val == null) return '—'
  return `${SYM[cur] || `${cur} `}${fmtMoney(val, 2)}`
}

async function refreshCheckpoints(providerId) {
  if (!editId.value || editId.value !== providerId) return
  try {
    const cpRes = await getBalanceCheckpoints(providerId)
    if (editId.value === providerId) {
      checkpoints.value = cpRes.data?.items || []
    }
  } catch { /* ignore */ }
}

defineExpose({ refreshCheckpoints })

async function loadDetail(item) {
  const seq = ++loadSeq
  editId.value = item?.id || null
  pricesLoaded.value = false
  fieldsValid.value = true
  Object.assign(providerForm, item
    ? {
        name: item.name || '',
        provider_type: item.provider_type || 'direct',
        api_base: item.api_base || '',
        api_key: '',
        api_type: item.api_type || 'openai',
        timeout_sec: item.timeout_sec || 60,
        runtime_config: JSON.stringify(item.runtime_config || {}, null, 2),
        extra_headers: JSON.stringify(item.extra_headers || {}, null, 2),
        remark: item.remark || '',
      }
    : {
        name: '',
        provider_type: 'direct',
        api_base: '',
        api_key: '',
        api_type: 'openai',
        timeout_sec: 60,
        runtime_config: '{}',
        extra_headers: '{}',
        remark: '',
      })

  const b = item?.billing || {}
  Object.assign(billingForm, {
    service_kind: item?.service_kind === 'relay' ? 'relay' : 'official',
    plan_name: b.plan_name || '',
    billing_mode: b.billing_mode || 'pay_as_you_go',
    is_balance_deducted_by_usage: b.is_balance_deducted_by_usage ?? true,
    price_amount: b.price_amount != null ? Number(b.price_amount) : null,
    price_currency: b.price_currency || 'CNY',
    subscribed_at: b.subscribed_at || null,
    renew_at: b.renew_at || null,
    console_url: b.console_url || '',
    docs_url: b.docs_url || '',
    low_balance_threshold: b.low_balance_threshold != null ? Number(b.low_balance_threshold) : null,
  })

  checkpoints.value = []
  priceRows.value = []
  if (!item?.id) return
  drawerLoading.value = true
  try {
    const [cpRes, prRes] = await Promise.all([
      getBalanceCheckpoints(item.id),
      getModelPrices(item.id),
    ])
    if (seq !== loadSeq) return
    checkpoints.value = cpRes.data?.items || []
    priceRows.value = (prRes.data?.items || []).map(r => ({
      model: r.model,
      pricing_mode: r.pricing_mode,
      input_per_million: r.input_per_million != null ? Number(r.input_per_million) : null,
      output_per_million: r.output_per_million != null ? Number(r.output_per_million) : null,
      per_call_amount: r.per_call_amount != null ? Number(r.per_call_amount) : null,
      currency: r.currency || 'CNY',
      _suggested: false,
    }))
    // 自动补列已启用预设中尚未填单价的模型，方便直接填价
    for (const modelName of item.models || []) {
      if (!priceRows.value.some(r => r.model === modelName)) {
        priceRows.value.push({
          model: modelName,
          pricing_mode: 'token',
          input_per_million: null,
          output_per_million: null,
          per_call_amount: null,
          currency: billingForm.price_currency || 'CNY',
          _suggested: true,
        })
      }
    }
    pricesLoaded.value = true
  } finally {
    if (seq === loadSeq) drawerLoading.value = false
  }
}

watch(
  () => [props.modelValue, props.subscriptionItem],
  ([open, item]) => { if (open) loadDetail(item) },
  { immediate: true },
)

function addPriceRow() {
  priceRows.value.push({
    model: '',
    pricing_mode: 'token',
    input_per_million: null,
    output_per_million: null,
    per_call_amount: null,
    currency: billingForm.price_currency || 'CNY',
  })
}

async function handleLogoSelect(uploadFile) {
  const file = uploadFile.raw
  if (!file || !editId.value) return
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    msgError('LOGO 仅支持 PNG / JPEG / WEBP 图片（不支持 SVG）')
    return
  }
  if (file.size > 512 * 1024) {
    msgError('LOGO 文件大小不能超过 512KB')
    return
  }
  logoUploading.value = true
  try {
    await uploadProviderLogo(editId.value, file)
    msgSuccessText('LOGO 已更新')
    emit('logo-updated', editId.value)
  } finally {
    logoUploading.value = false
  }
}

function validateHttps(url, label) {
  if (!url || !url.trim()) return true
  if (!url.trim().startsWith('https://')) {
    msgError(`${label}仅支持 https:// 开头的有效地址`)
    return false
  }
  return true
}

async function handleSave() {
  const valid = await providerFormRef.value?.validate().catch(() => false)
  if (!valid) return
  if (!validateHttps(billingForm.console_url, '控制台链接') || !validateHttps(billingForm.docs_url, 'API 文档链接')) return
  if (billingForm.subscribed_at && billingForm.renew_at && billingForm.renew_at < billingForm.subscribed_at) {
    msgError('下次续费日期不能早于订阅日期')
    return
  }

  const providerPayload = { ...providerForm }
  for (const key of ['runtime_config', 'extra_headers']) {
    try {
      const parsed = JSON.parse(providerPayload[key] || '{}')
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('object required')
      providerPayload[key] = parsed
    } catch {
      msgError(`${key === 'runtime_config' ? '运行配置' : '附加请求头'}必须是有效的 JSON 对象`)
      return
    }
  }
  if (!providerPayload.api_key) delete providerPayload.api_key

  // 先校验单价表，杜绝部分填写或重复模型静默丢弃
  let validPrices = null
  if (pricesLoaded.value && providerForm.provider_type !== 'accio_work') {
    const seenModels = new Set()
    validPrices = []
    for (const r of priceRows.value) {
      const model = (r.model || '').trim()
      const isBlankSuggested = r._suggested && r.pricing_mode === 'token' && r.input_per_million == null && r.output_per_million == null
      const isCompletelyEmpty = !model && r.input_per_million == null && r.output_per_million == null && r.per_call_amount == null
      if (isBlankSuggested || isCompletelyEmpty) continue
      if (!model) {
        msgError('单价表中存在未填写模型名的行，请补全或删除')
        return
      }
      if (seenModels.has(model)) {
        msgError(`模型「${model}」在单价表中重复，请合并后再保存`)
        return
      }
      seenModels.add(model)
      if (r.pricing_mode === 'token' && (r.input_per_million == null || r.output_per_million == null)) {
        msgError(`模型「${model}」需同时填写输入与输出单价，若需移除请点击删除`)
        return
      }
      if (r.pricing_mode === 'per_call' && r.per_call_amount == null) {
        msgError(`模型「${model}」按次模式需填写单次费用，若需移除请点击删除`)
        return
      }
      validPrices.push({
        model,
        pricing_mode: r.pricing_mode,
        input_per_million: r.pricing_mode === 'token' ? r.input_per_million : null,
        output_per_million: r.pricing_mode === 'token' ? r.output_per_million : null,
        per_call_amount: r.pricing_mode === 'per_call' ? r.per_call_amount : null,
        currency: r.pricing_mode === 'image_rate_card' ? 'USD' : r.currency,
      })
    }
  }

  saving.value = true
  const wasEditing = Boolean(editId.value)
  try {
    let targetId = editId.value
    if (targetId) {
      await updateProvider(targetId, providerPayload)
    } else {
      const created = await createProvider(providerPayload)
      targetId = created.data.id
      // 创建成功后立即切换为编辑态，避免后续账务步骤报错重试时重复创建报错
      editId.value = targetId
    }

    await upsertProviderBilling(targetId, {
      service_kind: billingForm.service_kind,
      plan_name: billingForm.plan_name.trim() || null,
      billing_mode: billingForm.billing_mode,
      is_balance_deducted_by_usage: billingForm.is_balance_deducted_by_usage,
      price_amount: billingForm.price_amount,
      price_currency: billingForm.price_currency,
      subscribed_at: billingForm.subscribed_at || null,
      renew_at: billingForm.renew_at || null,
      console_url: billingForm.console_url.trim() || null,
      docs_url: billingForm.docs_url.trim() || null,
      low_balance_threshold: billingForm.low_balance_threshold,
    })

    if (validPrices !== null) {
      await replaceModelPrices(targetId, validPrices)
    }

    msgSuccessText(wasEditing ? '订阅与提供商配置已保存' : '订阅源已创建')
    emit('update:modelValue', false)
    emit('saved')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.w-full { width: 100%; }
.span-two { grid-column: span 2; align-self: center; }
.sub-drawer { display: flex; flex-direction: column; gap: 18px; }
.drawer-sec { padding-bottom: 14px; border-bottom: 1px solid var(--border-color); }
.drawer-sec:last-child { border-bottom: 0; }
.drawer-sec__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.drawer-sec__title { margin: 0 0 10px; font-family: var(--font-display); font-size: 14px; font-weight: 700; color: var(--text-primary); }
.drawer-sec__head .drawer-sec__title { margin-bottom: 0; }
.form-hint { font-size: 12px; color: var(--text-muted); line-height: 1.5; margin-top: 4px; }
.logo-upload-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.cp-list { border: 1px solid var(--border-color); border-radius: 10px; overflow: hidden; }
.cp-row {
  padding: 9px 12px; border-bottom: 1px solid var(--border-color);
  display: flex; justify-content: space-between; gap: 10px; font-size: 12px;
}
.cp-row:last-child { border-bottom: 0; }
.cp-drift { color: var(--text-secondary); }
.cp-time { color: var(--text-muted); white-space: nowrap; }
.num { font-variant-numeric: tabular-nums; }
.price-edit-row {
  display: grid; grid-template-columns: 1.3fr 104px 86px 86px 76px 32px;
  gap: 6px; align-items: center; margin-bottom: 8px;
}
@media (max-width: 640px) {
  .price-edit-row { grid-template-columns: 1fr 1fr; }
}
</style>
