<template>
  <div class="okki-settings-page">
    <div class="page-header">
      <div>
        <h2>OKKI 推单设置</h2>
        <p>推单凭证、生产单自定义产品使用的通用产品、以及推单默认参数。推单接口尚未接通，配置先行生效于同步前校验。</p>
      </div>
    </div>

    <section class="table-card" v-loading="loading">
      <el-form :model="form" label-width="130px" class="settings-form">
        <h3 class="section-title">通用产品（生产单自定义产品推单时占位）</h3>
        <el-form-item label="产品编号">
          <div class="inline-row">
            <el-input
              v-model="form.generic_product_no"
              maxlength="64"
              clearable
              placeholder="OKKI 产品库 product_no，如 P001"
              style="width: 280px"
              @change="onProductNoChange"
            />
            <el-button :loading="resolving" :disabled="!form.generic_product_no" @click="resolveProduct">
              <el-icon><Search /></el-icon>
              解析
            </el-button>
          </div>
          <div class="field-hint">保存时后端会按产品编号重新解析并校验，留空表示未配置通用产品。</div>
        </el-form-item>
        <el-form-item v-if="resolved" label="解析结果">
          <el-tag v-if="resolved.found" type="success" effect="plain">
            {{ resolved.product.product_name }}（ID {{ resolved.product.product_id }}）
          </el-tag>
          <el-tag v-else type="danger" effect="plain">产品库中未找到该编号</el-tag>
          <el-tag v-if="resolved.found && !skuOptions.length" type="warning" effect="plain" class="sku-warn">
            该产品无启用 SKU，推单时无法带 SKU
          </el-tag>
        </el-form-item>
        <el-form-item v-if="skuOptions.length > 1" label="SKU">
          <el-select v-model="form.generic_sku_id" placeholder="该产品有多个 SKU，请选择" style="width: 280px">
            <el-option v-for="s in skuOptions" :key="s" :label="`SKU ${s}`" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item v-else-if="current.generic_sku_id" label="SKU">
          <el-tag effect="plain">SKU {{ current.generic_sku_id }}（已关联）</el-tag>
        </el-form-item>

        <h3 class="section-title">推单默认参数</h3>
        <el-form-item label="默认订单状态">
          <el-select
            v-model="form.default_order_status"
            filterable
            allow-create
            default-first-option
            clearable
            :loading="enumsLoading"
            placeholder="从 OKKI 订单状态中选择"
            style="width: 280px"
          >
            <el-option v-for="s in statusOptions" :key="s.code" :label="`${s.name}（${s.code}）`" :value="s.code" />
          </el-select>
          <div class="field-hint">状态是企业专属 ID，来自 OKKI orderEnums；获取 Token 后自动加载。</div>
        </el-form-item>
        <el-form-item label="默认币种">
          <el-input v-model="form.default_currency" maxlength="8" placeholder="USD" style="width: 160px" />
        </el-form-item>

        <h3 class="section-title">API 凭证</h3>
        <el-form-item label="服务器凭证">
          <el-tag :type="current.client_configured ? 'success' : 'danger'" effect="plain">
            {{ current.client_configured ? 'OKKI_CLIENT_ID 已配置（backend/.env）' : '未配置 OKKI_CLIENT_ID / SECRET，请先配 backend/.env' }}
          </el-tag>
        </el-form-item>
        <el-form-item label="Access Token">
          <div class="inline-row">
            <el-button type="primary" :disabled="!current.client_configured" :loading="fetchingToken" @click="fetchToken">
              <el-icon><Refresh /></el-icon>
              {{ current.has_token ? '刷新 Token' : '获取 Token' }}
            </el-button>
            <el-tag v-if="current.has_token" type="success" effect="plain">
              {{ current.access_token_masked }}，{{ tokenExpiryText }}
            </el-tag>
            <el-tag v-else type="info" effect="plain">尚未获取</el-tag>
            <el-button
              v-if="current.has_token"
              link
              type="danger"
              @click="markClearToken"
            >
              <el-icon><Delete /></el-icon>
              清除
            </el-button>
          </div>
          <div class="field-hint">Token 约 8 小时有效，推单时后端会自动续期，正常无需手动刷新。</div>
          <div v-if="clearToken" class="field-hint danger">保存后将清除已存 token。</div>
        </el-form-item>
        <el-form-item label="手动覆盖">
          <el-input
            v-model="tokenInput"
            type="password"
            show-password
            clearable
            placeholder="特殊情况手动粘贴 token 覆盖，留空保持不变"
            style="width: 420px"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
          <span v-if="current.updated_at" class="field-hint">上次保存：{{ formatTime(current.updated_at) }}</span>
        </el-form-item>
      </el-form>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Refresh, Search } from '@element-plus/icons-vue'
import { msgSuccess } from '@/utils/feedback'
import {
  fetchXiaomanToken,
  getXiaomanEnums,
  getXiaomanSettings,
  resolveXiaomanProduct,
  updateXiaomanSettings,
} from '@/api/invoice'

const loading = ref(false)
const saving = ref(false)
const resolving = ref(false)
const fetchingToken = ref(false)
const enumsLoading = ref(false)

const current = ref({ has_token: false, client_configured: false })
const form = reactive({
  generic_product_no: '',
  generic_sku_id: null,
  default_order_status: '',
  default_currency: 'USD',
  token_expires_at: null,
})
const tokenInput = ref('')
const clearToken = ref(false)
const resolved = ref(null)
const skuOptions = ref([])
const statusOptions = ref([])

const tokenExpiryText = computed(() => {
  const iso = current.value.token_expires_at
  if (!iso) return '有效期未知'
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return '有效期未知'
  return d.getTime() > Date.now()
    ? `有效至 ${d.toLocaleString('zh-CN', { hour12: false })}`
    : '已过期，推单时会自动续期'
})

onMounted(async () => {
  await load()
  if (current.value.has_token && current.value.client_configured) loadEnums()
})

// 手动覆盖框输入新 token 时，取消之前点的「清除」意图
watch(tokenInput, (v) => {
  if (v && v.trim()) clearToken.value = false
})

async function load() {
  loading.value = true
  try {
    applySettings(await getXiaomanSettings())
  } finally {
    loading.value = false
  }
}

async function fetchToken() {
  fetchingToken.value = true
  try {
    // 失败（400 凭证/网络问题）由 axios 拦截器统一弹窗。
    // 只刷新 token 相关状态——不能整表单 applySettings，否则用户未保存的编辑被静默清空
    const data = await fetchXiaomanToken()
    current.value = data
    form.token_expires_at = data.token_expires_at
    clearToken.value = false
    msgSuccess('获取 Token')
    loadEnums()
  } finally {
    fetchingToken.value = false
  }
}

async function loadEnums() {
  enumsLoading.value = true
  try {
    const res = await getXiaomanEnums()
    statusOptions.value = res.order_status_list || []
  } catch {
    // 拦截器已弹窗；下拉保留 allow-create 手填兜底
  } finally {
    enumsLoading.value = false
  }
}

function applySettings(data) {
  current.value = data
  form.generic_product_no = data.generic_product_no || ''
  form.generic_sku_id = data.generic_sku_id
  form.default_order_status = data.default_order_status || ''
  form.default_currency = data.default_currency || 'USD'
  form.token_expires_at = data.token_expires_at
  tokenInput.value = ''
  clearToken.value = false
  resolved.value = null
  skuOptions.value = []
}

function onProductNoChange() {
  resolved.value = null
  skuOptions.value = []
  form.generic_sku_id = null
}

async function resolveProduct() {
  if (!form.generic_product_no) return
  resolving.value = true
  try {
    const res = await resolveXiaomanProduct({ product_no: form.generic_product_no.trim() })
    resolved.value = res
    skuOptions.value = res.found ? res.product.skus : []
    if (res.found && res.product.skus.length === 1) {
      form.generic_sku_id = res.product.skus[0]
    }
  } finally {
    resolving.value = false
  }
}

function markClearToken() {
  clearToken.value = true
  tokenInput.value = ''
}

async function save() {
  saving.value = true
  try {
    const payload = {
      generic_product_no: form.generic_product_no.trim() || null,
      generic_sku_id: form.generic_sku_id,
      default_order_status: form.default_order_status.trim() || null,
      default_currency: form.default_currency.trim() || 'USD',
      // null=不改，''=清除，非空=覆盖（与后端约定一致）
      access_token: clearToken.value ? '' : (tokenInput.value.trim() || null),
      token_expires_at: form.token_expires_at || null,
    }
    // 校验失败（400）由 axios 拦截器统一弹窗，这里不再重复 catch
    const data = await updateXiaomanSettings(payload)
    applySettings(data)
    msgSuccess('保存')
  } finally {
    saving.value = false
  }
}

// updated_at 是后端 UTC 时间，转本地时区显示
function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.okki-settings-page {
  padding: 24px 28px;
}

.page-header h2 {
  margin: 0 0 6px;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
}

.page-header p {
  margin: 0 0 18px;
  font-size: 14px;
  color: var(--text-secondary);
}

.table-card {
  padding: 20px 24px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--card-bg);
}

.settings-form {
  max-width: 720px;
}

.section-title {
  margin: 8px 0 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}

.section-title:not(:first-child) {
  margin-top: 26px;
}

.inline-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.field-hint {
  width: 100%;
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.field-hint.danger {
  color: var(--color-danger-text);
}

.clear-token-btn {
  margin-left: 10px;
}

.sku-warn {
  margin-left: 8px;
}
</style>
