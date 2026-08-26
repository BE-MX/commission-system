<template>
  <main class="integration-page">
    <section class="endpoint-card" aria-labelledby="integration-page-title">
      <div class="endpoint-copy">
        <div class="eyebrow">INVOICE API</div>
        <h1 id="integration-page-title">站点接入凭证</h1>
        <p>为 Codex 站点绑定方舟账号，生成订单发票后由站点服务端直接写入方舟。</p>
      </div>
      <div class="endpoint-actions">
        <div class="endpoint-value">
          <span>生产服务地址</span>
          <code>{{ INVOICE_API_ENDPOINT }}</code>
          <strong>服务端调用，禁止放浏览器</strong>
        </div>
        <GlassButton left-icon="CopyDocument" @click="copyText(INVOICE_API_ENDPOINT, '服务地址已复制')">
          复制地址
        </GlassButton>
        <GlassButton
          v-permission="'integration:admin'"
          variant="primary"
          left-icon="Plus"
          @click="openCreateDialog"
        >
          新建站点凭证
        </GlassButton>
      </div>
    </section>

    <section class="metrics" aria-label="站点凭证概览">
      <article><span>有效凭证</span><strong>{{ metrics.active }}</strong></article>
      <article><span>已过期</span><strong>{{ metrics.expired }}</strong></article>
      <article><span>已吊销</span><strong>{{ metrics.revoked }}</strong></article>
    </section>

    <section class="table-card">
      <div class="table-toolbar">
        <div>
          <h2>已接入站点</h2>
          <p>明文 Token 不可找回；遗失时请轮换，旧 Token 会立即失效。</p>
        </div>
        <div class="filters">
          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="搜索站点、账号或 Token 尾号"
            :prefix-icon="Search"
          />
          <el-select v-model="filters.status" aria-label="凭证状态">
            <el-option label="全部状态" value="all" />
            <el-option label="有效" value="active" />
            <el-option label="已过期" value="expired" />
            <el-option label="已吊销" value="revoked" />
          </el-select>
          <GlassButton left-icon="Refresh" :loading="loading" @click="loadApps">刷新</GlassButton>
        </div>
      </div>

      <el-table
        v-if="filteredRows.length || loading"
        v-loading="loading"
        :data="filteredRows"
        class="integration-table list-table"
        border
      >
        <el-table-column label="站点名称" min-width="180" show-overflow-tooltip>
          <template #default="{ row }"><strong class="site-name">{{ row.name }}</strong></template>
        </el-table-column>
        <el-table-column label="绑定账号" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="account-cell">
              <span>{{ row.owner_real_name || row.owner_username || '-' }}</span>
              <small v-if="row.owner_username">@{{ row.owner_username }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="授权范围" min-width="140">
          <template #default="{ row }">
            <el-tag v-for="scope in row.scopes" :key="scope" type="info" effect="plain" size="small">
              {{ scope }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Token 尾号" min-width="120">
          <template #default="{ row }"><code class="suffix">••••••{{ row.token_suffix }}</code></template>
        </el-table-column>
        <el-table-column label="到期时间" min-width="170">
          <template #default="{ row }">{{ formatCredentialTime(row.expires_at, '长期有效') }}</template>
        </el-table-column>
        <el-table-column label="最近使用" min-width="170">
          <template #default="{ row }">{{ formatCredentialTime(row.last_used_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }">
            <el-tag :type="statusFor(row).type" effect="plain" size="small">
              {{ statusFor(row).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="190" fixed="right">
          <template #default="{ row }">
            <template v-if="row.is_active">
              <GlassButton
                v-if="canRotateIntegrationApp(row, currentNow)"
                v-permission="'integration:admin'"
                variant="link"
                left-icon="Refresh"
                @click="rotateCredential(row)"
              >
                轮换
              </GlassButton>
              <span v-else class="expired-note">已过期，请新建凭证</span>
              <GlassButton
                v-permission="'integration:admin'"
                variant="link"
                link-tone="danger"
                left-icon="Close"
                @click="revokeCredential(row)"
              >
                吊销
              </GlassButton>
            </template>
            <span v-else class="muted">不可恢复</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-else description="还没有符合条件的站点凭证">
        <GlassButton
          v-if="!rows.length"
          v-permission="'integration:admin'"
          variant="primary"
          left-icon="Plus"
          @click="openCreateDialog"
        >
          新建首个凭证
        </GlassButton>
      </el-empty>
    </section>

    <el-dialog v-model="createVisible" title="新建站点接入凭证" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="站点名称" required>
          <el-input
            v-model="createForm.name"
            maxlength="100"
            show-word-limit
            placeholder="例如：LeShine 独立站"
          />
          <div class="field-hint">填写用户能识别的站点名称，便于后续审计和吊销。</div>
        </el-form-item>
        <el-form-item label="绑定方舟账号" required>
          <el-select
            v-model="createForm.ownerUserId"
            filterable
            remote
            clearable
            placeholder="输入姓名或用户名搜索"
            :remote-method="searchCandidates"
            :loading="candidateLoading"
            class="full-width"
          >
            <el-option
              v-for="item in candidates"
              :key="item.user_id"
              :value="item.user_id"
              :label="`${item.real_name || item.username} · @${item.username}`"
              :disabled="!item.has_invoice_write"
            >
              <div class="candidate-option">
                <span>{{ item.real_name || item.username }} <small>@{{ item.username }}</small></span>
                <el-tag :type="item.has_invoice_write ? 'success' : 'warning'" size="small" effect="plain">
                  {{ item.has_invoice_write ? '可创建发票' : '缺少 invoice:write' }}
                </el-tag>
              </div>
            </el-option>
          </el-select>
          <div class="field-hint">站点创建的发票将归属这个账号；权限会在每次调用时重新校验。</div>
        </el-form-item>
        <el-form-item label="到期时间（可选）">
          <el-date-picker
            v-model="createForm.expiresAt"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="不设置则长期有效"
            class="full-width"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="createVisible = false">取消</GlassButton>
        <GlassButton
          v-permission="'integration:admin'"
          variant="primary"
          :loading="creating"
          :disabled="!canCreate"
          @click="submitCreate"
        >
          生成一次性 Token
        </GlassButton>
      </template>
    </el-dialog>

    <el-dialog
      v-model="secretVisible"
      title="站点凭证已生成"
      width="660px"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="clearIssuedSecret"
    >
      <div v-if="issuedSecret" class="secret-content">
        <div class="security-notice">
          <el-icon><WarningFilled /></el-icon>
          <div>
            <strong>这是唯一一次显示明文 Token</strong>
            <p>关闭后无法找回。只保存到站点服务端环境变量，禁止放入浏览器代码、网页或日志。</p>
          </div>
        </div>
        <label>Access Token</label>
        <div class="secret-value"><code>{{ issuedSecret.token }}</code></div>
        <label>服务端环境变量</label>
        <div class="secret-value env-value"><code>{{ buildServerEnvSnippet(issuedSecret.token) }}</code></div>
        <div class="copy-actions">
          <GlassButton left-icon="CopyDocument" @click="copyText(issuedSecret.token, 'Token 已复制')">
            复制 Token
          </GlassButton>
          <GlassButton
            variant="primary"
            left-icon="DocumentCopy"
            @click="copyText(buildServerEnvSnippet(issuedSecret.token), '服务端环境变量已复制')"
          >
            复制环境变量
          </GlassButton>
        </div>
      </div>
      <template #footer>
        <GlassButton variant="primary" @click="secretVisible = false">我已保存，关闭</GlassButton>
      </template>
    </el-dialog>
  </main>
</template>

<script setup>
import {
  computed,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  reactive,
  ref,
} from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, WarningFilled } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  createIntegrationApp,
  listIntegrationApps,
  revokeIntegrationApp,
  rotateIntegrationApp,
  searchIntegrationAppCandidates,
} from '@/api/integrationApps'
import { copyToClipboard } from './mcpTokenManagement'
import {
  INVOICE_API_ENDPOINT,
  buildServerEnvSnippet,
  canRotateIntegrationApp,
  createOneTimeSecretState,
  filterIntegrationApps,
  formatCredentialTime,
  getIntegrationAppStatus,
} from './integrationAppManagement'

const loading = ref(false)
const rows = ref([])
const filters = reactive({ keyword: '', status: 'all' })
const createVisible = ref(false)
const creating = ref(false)
const createForm = reactive({ name: '', ownerUserId: null, expiresAt: null })
const candidates = ref([])
const candidateLoading = ref(false)
const secretVisible = ref(false)
const issuedSecret = ref(null)
const secretState = createOneTimeSecretState((value) => { issuedSecret.value = value })
const currentNow = ref(new Date())
let nowTimer = null

const filteredRows = computed(() => filterIntegrationApps(rows.value, filters, currentNow.value))
const metrics = computed(() => rows.value.reduce((result, row) => {
  result[getIntegrationAppStatus(row, currentNow.value).key] += 1
  return result
}, { active: 0, expired: 0, revoked: 0 }))
const selectedCandidate = computed(() => candidates.value.find(
  (item) => item.user_id === createForm.ownerUserId,
))
const canCreate = computed(() => (
  createForm.name.trim().length >= 2
  && Boolean(selectedCandidate.value?.has_invoice_write)
))

async function loadApps() {
  loading.value = true
  try {
    const response = await listIntegrationApps()
    rows.value = response.data.items || []
  } finally {
    loading.value = false
  }
}

async function searchCandidates(query = '') {
  candidateLoading.value = true
  try {
    const response = await searchIntegrationAppCandidates({ q: query, limit: 20 })
    candidates.value = response.data.items || []
  } finally {
    candidateLoading.value = false
  }
}

function openCreateDialog() {
  createForm.name = ''
  createForm.ownerUserId = null
  createForm.expiresAt = null
  createVisible.value = true
  searchCandidates()
}

function showIssuedSecret(secret) {
  secretState.show(secret)
  secretVisible.value = true
}

function clearIssuedSecret() {
  secretVisible.value = false
  secretState.clear()
}

function statusFor(row) {
  return getIntegrationAppStatus(row, currentNow.value)
}

function startClock() {
  if (nowTimer !== null) return
  currentNow.value = new Date()
  nowTimer = setInterval(() => {
    currentNow.value = new Date()
  }, 60_000)
}

function stopClock() {
  if (nowTimer === null) return
  clearInterval(nowTimer)
  nowTimer = null
}

function cleanupPage() {
  stopClock()
  clearIssuedSecret()
}

async function submitCreate() {
  if (!canCreate.value) return
  creating.value = true
  try {
    const payload = {
      name: createForm.name.trim(),
      owner_user_id: createForm.ownerUserId,
    }
    if (createForm.expiresAt) payload.expires_at = createForm.expiresAt
    const response = await createIntegrationApp(payload)
    createVisible.value = false
    showIssuedSecret(response.data)
    await loadApps()
  } finally {
    creating.value = false
  }
}

async function rotateCredential(row) {
  try {
    await ElMessageBox.confirm(
      `轮换“${row.name}”后，当前 Token 会立即失效。`,
      '确认轮换凭证',
      { confirmButtonText: '确认并生成新 Token', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  const response = await rotateIntegrationApp(row.id, row.token_suffix)
  showIssuedSecret(response.data)
  await loadApps()
}

async function revokeCredential(row) {
  try {
    await ElMessageBox.confirm(
      `吊销“${row.name}”后，该站点会立即无法向方舟发送发票。`,
      '确认吊销凭证',
      { confirmButtonText: '吊销凭证', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await revokeIntegrationApp(row.id)
  ElMessage.success('站点凭证已吊销')
  await loadApps()
}

async function copyText(value, successMessage) {
  if (await copyToClipboard(value)) ElMessage.success(successMessage)
  else ElMessage.error('自动复制失败，请手动选择复制')
}

onMounted(() => {
  loadApps()
  startClock()
})
onActivated(startClock)
onDeactivated(cleanupPage)
onBeforeUnmount(cleanupPage)
</script>

<style scoped>
.integration-page { padding: 20px; color: var(--text-primary); }
.endpoint-card,
.table-card,
.metrics article { background: var(--card-bg); border: 1px solid var(--border-color); box-shadow: var(--card-shadow); }
.endpoint-card { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 20px 22px; border-radius: var(--radius-xl); }
.eyebrow { color: var(--color-gold-muted); font-size: 10px; font-weight: 800; letter-spacing: .16em; }
h1 { margin: 4px 0 5px; font-size: 23px; letter-spacing: -.02em; }
.endpoint-copy p,
.table-toolbar p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.endpoint-actions { display: flex; align-items: center; gap: 10px; }
.endpoint-value { min-width: 330px; padding: 8px 11px; background: var(--toolbar-bg); border: 1px solid var(--border-color); border-radius: var(--radius-md); }
.endpoint-value span,
.endpoint-value strong { display: block; font-size: 10px; }
.endpoint-value span { margin-bottom: 2px; color: var(--text-tertiary); }
.endpoint-value strong { margin-top: 3px; color: var(--color-warning-text); }
.endpoint-value code { color: var(--text-primary); font-size: 12px; }
.metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 12px 0; }
.metrics article { display: flex; align-items: baseline; justify-content: space-between; padding: 14px 16px; border-radius: var(--radius-lg); }
.metrics span { color: var(--text-secondary); font-size: 12px; }
.metrics strong { font-size: 23px; font-variant-numeric: tabular-nums; }
.table-card { overflow: hidden; border-radius: var(--radius-xl); }
.table-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 18px 13px; border-bottom: 1px solid var(--border-color); }
.table-toolbar h2 { margin: 0 0 3px; font-size: 16px; }
.filters { display: flex; align-items: center; gap: 8px; }
.filters .el-input { width: 260px; }
.filters .el-select { width: 120px; }
.site-name { font-size: 13px; }
.account-cell { display: flex; flex-direction: column; line-height: 1.35; }
.account-cell small,
.candidate-option small,
.muted { color: var(--text-tertiary); }
.expired-note { margin-right: 8px; color: var(--color-warning-text); font-size: 12px; }
.suffix { color: var(--text-secondary); font-size: 12px; }
.candidate-option { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.field-hint { margin-top: 4px; color: var(--text-tertiary); font-size: 11px; }
.full-width { width: 100%; }
.security-notice { display: flex; gap: 10px; padding: 12px; color: var(--color-warning-text); background: var(--color-warning-bg); border: 1px solid var(--color-gold-soft-2); border-radius: var(--radius-md); }
.security-notice .el-icon { flex: 0 0 auto; margin-top: 2px; font-size: 18px; }
.security-notice p { margin: 3px 0 0; font-size: 12px; line-height: 1.6; }
.secret-content > label { display: block; margin: 16px 0 6px; color: var(--text-secondary); font-size: 11px; font-weight: 700; text-transform: uppercase; }
.secret-value { padding: 13px; overflow-wrap: anywhere; color: var(--text-on-dark); background: var(--sidebar-bg-to); border-radius: var(--radius-md); line-height: 1.6; }
.secret-value code { font-size: 12px; }
.env-value { white-space: pre-wrap; }
.copy-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }

@media (max-width: 1000px) {
  .endpoint-card,
  .table-toolbar { align-items: flex-start; flex-direction: column; }
  .endpoint-actions,
  .filters { width: 100%; flex-wrap: wrap; }
  .endpoint-value { flex: 1; min-width: 260px; }
  .filters .el-input { flex: 1; min-width: 220px; }
}

@media (max-width: 700px) {
  .metrics { grid-template-columns: 1fr; }
}

</style>
