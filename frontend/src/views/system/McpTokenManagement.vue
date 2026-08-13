<template>
  <main class="token-page">
    <section class="endpoint-card" aria-labelledby="mcp-page-title">
      <div class="endpoint-copy">
        <div class="eyebrow">MCP GATEWAY</div>
        <h1 id="mcp-page-title">Agent 接入凭证</h1>
        <p>为外部 Agent 绑定方舟账号，访问范围随账号权限实时变化。</p>
      </div>
      <div class="endpoint-actions">
        <div class="endpoint-value">
          <span>服务地址</span>
          <code>{{ MCP_ENDPOINT }}</code>
        </div>
        <GlassButton left-icon="CopyDocument" @click="copyText(MCP_ENDPOINT, '服务地址已复制')">复制地址</GlassButton>
        <GlassButton variant="primary" left-icon="Plus" @click="openIssueDialog">发放凭证</GlassButton>
      </div>
    </section>

    <section class="metrics" aria-label="凭证概览">
      <article><span>有效凭证</span><strong>{{ metrics.active }}</strong></article>
      <article><span>已吊销</span><strong>{{ metrics.revoked }}</strong></article>
      <article><span>知识库可用凭证账号</span><strong>{{ metrics.readyOwners }}</strong></article>
    </section>

    <section class="table-card">
      <div class="table-toolbar">
        <div>
          <h2>已发放凭证</h2>
          <p>明文不可找回；遗失时请重新发放。</p>
        </div>
        <div class="filters">
          <el-input v-model="filters.keyword" clearable placeholder="搜索账号或 Agent 用途" :prefix-icon="Search" />
          <el-select v-model="filters.status" aria-label="凭证状态">
            <el-option label="全部状态" value="all" />
            <el-option label="有效" value="active" />
            <el-option label="已吊销" value="revoked" />
          </el-select>
          <GlassButton left-icon="Refresh" :loading="loading" @click="loadTokens">刷新</GlassButton>
        </div>
      </div>

      <el-table v-if="filteredRows.length || loading" v-loading="loading" :data="filteredRows" class="token-table list-table" border>
        <el-table-column label="Agent 用途" min-width="170">
          <template #default="{ row }"><strong class="purpose">{{ row.label }}</strong></template>
        </el-table-column>
        <el-table-column label="绑定账号" min-width="180">
          <template #default="{ row }">
            <div class="account-cell"><span>{{ row.real_name }}</span><small>@{{ row.username }}</small></div>
          </template>
        </el-table-column>
        <el-table-column label="知识库访问" min-width="210">
          <template #default="{ row }">
            <div class="access-tags">
              <el-tag :type="row.has_knowledge_read ? 'success' : 'danger'" effect="plain" size="small">
                {{ row.has_knowledge_read ? '有读取权限' : '缺读取权限' }}
              </el-tag>
              <el-tag :type="row.knowledge_library_count ? 'info' : 'warning'" effect="plain" size="small">
                {{ row.knowledge_library_count }} 个知识库
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }">
            <span :class="['status', row.is_active ? 'is-active' : 'is-revoked']">
              <i />{{ row.is_active ? '有效' : '已吊销' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最近使用" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.last_used_at) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="190" fixed="right">
          <template #default="{ row }">
            <template v-if="row.is_active">
              <GlassButton variant="link" left-icon="Refresh" @click="rotateToken(row)">重新发放</GlassButton>
              <GlassButton variant="link" link-tone="danger" left-icon="Close" @click="revokeToken(row)">吊销</GlassButton>
            </template>
            <span v-else class="muted">不可恢复</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-else description="还没有符合条件的凭证">
        <GlassButton v-if="!rows.length" variant="primary" left-icon="Plus" @click="openIssueDialog">发放首个凭证</GlassButton>
      </el-empty>
    </section>

    <el-dialog v-model="issueVisible" title="发放 Agent 接入凭证" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="绑定账号" required>
          <el-select
            v-model="issueForm.userId"
            filterable remote clearable
            placeholder="输入姓名或用户名搜索"
            :remote-method="searchCandidates"
            :loading="candidateLoading"
            style="width: 100%"
            @change="selectCandidate"
          >
            <el-option v-for="item in candidates" :key="item.user_id" :value="item.user_id" :label="`${item.real_name} · @${item.username}`">
              <div class="candidate-option">
                <span>{{ item.real_name }} <small>@{{ item.username }}</small></span>
                <el-tag :type="isKnowledgeReady(item) ? 'success' : 'warning'" size="small" effect="plain">
                  {{ isKnowledgeReady(item) ? '知识库可用' : '待配置' }}
                </el-tag>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <div v-if="selectedCandidate" class="readiness-panel">
          <div><el-icon :class="{ ok: selectedCandidate.has_knowledge_read }"><CircleCheck /></el-icon><span>平台读取权限</span><strong>{{ selectedCandidate.has_knowledge_read ? '已配置' : '未配置' }}</strong></div>
          <div><el-icon :class="{ ok: selectedCandidate.knowledge_library_count > 0 }"><Collection /></el-icon><span>已加入知识库</span><strong>{{ selectedCandidate.knowledge_library_count }} 个</strong></div>
          <div><el-icon><Key /></el-icon><span>当前有效凭证</span><strong>{{ selectedCandidate.active_token_count }} 个</strong></div>
          <p v-if="!isKnowledgeReady(selectedCandidate)" class="readiness-warning">
            该账号暂不能调用知识库。请先到
            <router-link to="/system/roles">角色权限</router-link>
            配置读取权限，并在 <router-link to="/knowledge">知识工作台</router-link> 加入知识库。
          </p>
        </div>

        <el-form-item label="Agent 用途" required>
          <el-input v-model="issueForm.label" maxlength="100" show-word-limit placeholder="例如：销售报价 Agent / 客服知识助手" />
          <div class="field-hint">用途会显示在审计列表中，请填写可识别的名称。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="issueVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="issuing" :disabled="!canIssue" @click="submitIssue">生成一次性凭证</GlassButton>
      </template>
    </el-dialog>

    <el-dialog
      v-model="secretVisible"
      title="凭证已生成"
      width="620px"
      :close-on-click-modal="false"
      class="secret-dialog"
      @closed="clearIssuedSecret"
    >
      <div v-if="issuedSecret" class="secret-content">
        <div class="security-notice">
          <el-icon><WarningFilled /></el-icon>
          <div><strong>这是唯一一次显示明文</strong><p>关闭后无法找回。请立即复制到 Agent 的安全配置中。</p></div>
        </div>
        <label>Access Token</label>
        <div class="secret-value"><code>{{ issuedSecret.token }}</code></div>
        <div class="secret-meta">{{ issuedSecret.label }} · {{ issuedSecret.real_name || issuedSecret.username }}</div>
        <div class="copy-actions">
          <GlassButton left-icon="CopyDocument" @click="copyText(issuedSecret.token, 'Token 已复制')">复制 Token</GlassButton>
          <GlassButton variant="primary" left-icon="DocumentCopy" @click="copyText(buildAgentConfig(issuedSecret.token), 'Agent 配置已复制')">复制完整配置</GlassButton>
        </div>
      </div>
      <template #footer><GlassButton variant="primary" @click="secretVisible = false">我已保存，关闭</GlassButton></template>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, Collection, Key, Search, WarningFilled } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { issueMcpToken, listMcpTokens, revokeMcpToken, rotateMcpToken, searchMcpTokenCandidates } from '@/api/mcpTokens'
import { MCP_ENDPOINT, buildAgentConfig, copyToClipboard, filterTokens, formatDateTime, isKnowledgeReady } from './mcpTokenManagement'

const loading = ref(false)
const rows = ref([])
const filters = reactive({ keyword: '', status: 'all' })
const issueVisible = ref(false)
const issuing = ref(false)
const issueForm = reactive({ userId: null, label: '' })
const candidates = ref([])
const candidateLoading = ref(false)
const selectedCandidate = ref(null)
const secretVisible = ref(false)
const issuedSecret = ref(null)

const filteredRows = computed(() => filterTokens(rows.value, filters))
const metrics = computed(() => ({
  active: rows.value.filter((row) => row.is_active).length,
  revoked: rows.value.filter((row) => !row.is_active).length,
  readyOwners: new Set(rows.value.filter(isKnowledgeReady).map((row) => row.user_id)).size,
}))
const canIssue = computed(() => isKnowledgeReady(selectedCandidate.value) && issueForm.label.trim().length >= 2)

async function loadTokens() {
  loading.value = true
  try {
    const response = await listMcpTokens()
    rows.value = response.data.items || []
  } finally {
    loading.value = false
  }
}

async function searchCandidates(query = '') {
  candidateLoading.value = true
  try {
    const response = await searchMcpTokenCandidates({ q: query, limit: 20 })
    candidates.value = response.data.items || []
  } finally {
    candidateLoading.value = false
  }
}

function selectCandidate(userId) {
  selectedCandidate.value = candidates.value.find((item) => item.user_id === userId) || null
}

function openIssueDialog() {
  issueForm.userId = null
  issueForm.label = ''
  selectedCandidate.value = null
  issueVisible.value = true
  searchCandidates()
}

async function submitIssue() {
  if (!canIssue.value) return
  issuing.value = true
  try {
    const response = await issueMcpToken({ user_id: issueForm.userId, label: issueForm.label.trim() })
    issueVisible.value = false
    showIssuedSecret(response.data)
    await loadTokens()
  } finally {
    issuing.value = false
  }
}

async function rotateToken(row) {
  try {
    await ElMessageBox.confirm(
      `重新发放“${row.label}”后，当前 Token 会立即失效。`,
      '确认重新发放',
      { confirmButtonText: '确认并生成新 Token', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  const response = await rotateMcpToken(row.id)
  showIssuedSecret(response.data)
  await loadTokens()
}

async function revokeToken(row) {
  try {
    await ElMessageBox.confirm(
      `吊销“${row.label}”后，使用该 Token 的 Agent 会立即断开。`,
      '确认吊销',
      { confirmButtonText: '吊销凭证', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  await revokeMcpToken(row.id)
  ElMessage.success('凭证已吊销')
  await loadTokens()
}

function showIssuedSecret(secret) {
  issuedSecret.value = secret
  secretVisible.value = true
}

function clearIssuedSecret() {
  issuedSecret.value = null
}

async function copyText(value, successMessage) {
  if (await copyToClipboard(value)) {
    ElMessage.success(successMessage)
  } else {
    ElMessage.error('自动复制失败，请手动选择复制')
  }
}

onMounted(loadTokens)
</script>

<style scoped>
.token-page { padding: 20px; color: var(--text-primary); }
.endpoint-card, .table-card, .metrics article { background: rgba(255,255,255,.88); border: 1px solid rgba(30,42,62,.1); box-shadow: 0 8px 28px rgba(42,55,78,.06); }
.endpoint-card { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 20px 22px; border-radius: 14px; }
.eyebrow { color: var(--color-gold-muted); font-size: 10px; font-weight: 800; letter-spacing: .16em; }
h1 { margin: 4px 0 5px; font-size: 23px; letter-spacing: -.02em; }
.endpoint-copy p, .table-toolbar p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.endpoint-actions { display: flex; align-items: center; gap: 10px; }
.endpoint-value { min-width: 270px; padding: 8px 11px; background: var(--toolbar-bg); border: 1px solid var(--border-color); border-radius: 8px; }
.endpoint-value span { display: block; color: var(--text-tertiary); font-size: 10px; margin-bottom: 2px; }
.endpoint-value code { color: var(--text-primary); font-size: 12px; }
.metrics { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px; margin: 12px 0; }
.metrics article { display: flex; align-items: baseline; justify-content: space-between; padding: 14px 16px; border-radius: 10px; }
.metrics span { color: var(--text-secondary); font-size: 12px; }.metrics strong { font-size: 23px; font-variant-numeric: tabular-nums; }
.table-card { border-radius: 14px; overflow: hidden; }
.table-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 18px 13px; border-bottom: 1px solid var(--border-color); }
.table-toolbar h2 { margin: 0 0 3px; font-size: 16px; }.filters { display: flex; align-items: center; gap: 8px; }.filters .el-input { width: 230px; }.filters .el-select { width: 120px; }
.purpose { font-size: 13px; }.account-cell { display: flex; flex-direction: column; line-height: 1.35; }.account-cell small, .candidate-option small, .muted { color: var(--text-tertiary); }
.access-tags { display: flex; flex-wrap: wrap; gap: 5px; }.status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }.status i { width: 7px; height: 7px; border-radius: 50%; }.is-active i { background: var(--color-success); box-shadow: 0 0 0 3px var(--color-success-bg); }.is-revoked { color: var(--text-tertiary); }.is-revoked i { background: var(--text-muted); }
.candidate-option { display: flex; align-items: center; justify-content: space-between; width: 100%; }.readiness-panel { margin: -2px 0 18px; padding: 12px 14px; background: var(--toolbar-bg); border: 1px solid var(--border-color); border-radius: 9px; }.readiness-panel > div { display: grid; grid-template-columns: 20px 1fr auto; align-items: center; padding: 5px 0; font-size: 13px; }.readiness-panel .el-icon { color: var(--text-muted); }.readiness-panel .el-icon.ok { color: var(--color-success); }.readiness-warning { margin: 8px 0 0; padding-top: 9px; border-top: 1px solid var(--border-color); color: var(--color-warning-text); font-size: 12px; line-height: 1.65; }.readiness-warning a { color: var(--color-gold-muted); font-weight: 700; }.field-hint { color: var(--text-tertiary); font-size: 11px; margin-top: 4px; }
.security-notice { display: flex; gap: 10px; padding: 12px; background: var(--color-warning-bg); border: 1px solid var(--color-gold-soft-2); border-radius: 9px; color: var(--color-warning-text); }.security-notice .el-icon { margin-top: 2px; font-size: 18px; }.security-notice p { margin: 3px 0 0; font-size: 12px; }.secret-content > label { display: block; margin: 16px 0 6px; color: var(--text-secondary); font-size: 11px; font-weight: 700; text-transform: uppercase; }.secret-value { padding: 13px; background: var(--sidebar-bg-to); color: var(--text-on-dark); border-radius: 8px; overflow-wrap: anywhere; line-height: 1.6; }.secret-value code { font-size: 12px; }.secret-meta { margin-top: 7px; color: var(--text-tertiary); font-size: 12px; }.copy-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
:deep(.token-table .el-table__cell) { padding: 9px 0; }:deep(.token-table th.el-table__cell) { background: var(--table-header-bg); color: var(--text-secondary); font-size: 11px; font-weight: 700; }
@media (max-width: 900px) { .endpoint-card, .table-toolbar { align-items: flex-start; flex-direction: column; }.endpoint-actions, .filters { width: 100%; flex-wrap: wrap; }.endpoint-value { flex: 1; }.metrics { grid-template-columns: 1fr; }.filters .el-input { flex: 1; min-width: 210px; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; } }
</style>
