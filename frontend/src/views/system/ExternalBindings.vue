<template>
  <div class="external-bindings">
    <div class="page-header">
      <h2>外部账号绑定候选</h2>
      <p>系统自动发现的未绑定外部账号，管理员可在此快速绑定到方舟用户。</p>
    </div>

    <div class="co-toolbar">
      <el-radio-group v-model="statusFilter" @change="loadCandidates">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="pending">待处理</el-radio-button>
        <el-radio-button label="bound">已绑定</el-radio-button>
        <el-radio-button label="ignored">已忽略</el-radio-button>
      </el-radio-group>
      <GlassButton variant="ghost" left-icon="Refresh" @click="loadCandidates">刷新</GlassButton>
      <GlassButton v-permission="'external_binding:write'" variant="ghost" left-icon="Connection" :loading="syncingOkki" @click="handleSyncOkki">同步 OKKI 用户</GlassButton>
    </div>

    <div class="table-card">
      <el-table :data="candidates" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column label="平台" min-width="120" max-width="180">
          <template #default="{ row }">{{ providerLabel(row.provider) }}</template>
        </el-table-column>
        <el-table-column label="外部账号 ID" prop="external_account_id" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column label="显示名" prop="external_display_name" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column label="状态" min-width="100" max-width="150">
          <template #default="{ row }">
            <el-tag :type="candidateStatusType(row.candidate_status)" size="small" effect="plain">
              {{ candidateStatusLabel(row.candidate_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="建议用户" min-width="120" max-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.suggested_user_name">{{ row.suggested_user_name }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="首次发现" min-width="160" max-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ formatTime(row.first_seen_at) }}</template>
        </el-table-column>
        <el-table-column label="出现次数" prop="seen_count" min-width="90" max-width="135" />
        <el-table-column label="操作" min-width="200" max-width="300" fixed="right">
          <template #default="{ row }">
            <template v-if="row.candidate_status === 'pending'">
              <GlassButton v-permission="'external_binding:write'" variant="link" left-icon="Connection" @click="openBindDialog(row)">绑定用户</GlassButton>
              <GlassButton v-permission="'external_binding:write'" variant="link" left-icon="Close" @click="handleIgnore(row)">忽略</GlassButton>
            </template>
            <span v-else class="text-muted">{{ candidateStatusLabel(row.candidate_status) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 绑定弹窗 -->
    <el-dialog v-model="bindDialogVisible" title="绑定到方舟用户" width="460px" :close-on-click-modal="false">
      <p style="margin-top: 0; color: #909399; font-size: 13px">
        将 <strong>{{ currentCandidate?.external_display_name }}</strong>
        ({{ currentCandidate?.external_account_id }}) 绑定到方舟用户：
      </p>
      <el-select v-model="selectedUserId" filterable remote reserve-keyword placeholder="搜索用户..."
        :remote-method="searchUsers" :loading="searchLoading" style="width: 100%">
        <el-option v-for="u in userOptions" :key="u.id" :label="`${u.real_name} (${u.username})`" :value="u.id" />
      </el-select>
      <template #footer>
        <GlassButton variant="ghost" @click="bindDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :disabled="!selectedUserId" @click="handleBind">确认绑定</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
// 统一 client：token 注入 / 401 跳转 / 错误提示由拦截器处理（宪法 11）
import { adminClient as authApi } from '@/api/clients'

const loading = ref(false)
const candidates = ref([])
const statusFilter = ref('')
const bindDialogVisible = ref(false)
const currentCandidate = ref(null)
const selectedUserId = ref(null)
const userOptions = ref([])
const searchLoading = ref(false)
const syncingOkki = ref(false)

async function handleSyncOkki() {
  syncingOkki.value = true
  try {
    const res = await authApi.post('/external-binding-candidates/sync-okki')
    ElMessage.success(res.message || '同步完成')
    loadCandidates()
  } catch (e) {
    // 拦截器已统一提示
  } finally {
    syncingOkki.value = false
  }
}

async function loadCandidates() {
  loading.value = true
  try {
    const params = statusFilter.value ? { status: statusFilter.value } : {}
    const res = await authApi.get('/external-binding-candidates', { params })
    candidates.value = res.data || []
  } catch (e) {
    ElMessage.error('加载候选列表失败')
  } finally {
    loading.value = false
  }
}

async function searchUsers(query) {
  if (!query) return
  searchLoading.value = true
  try {
    const res = await authApi.get('/users/list', { params: { keyword: query, page: 1, page_size: 20 } })
    userOptions.value = res.data?.items || []
  } catch { userOptions.value = [] }
  finally { searchLoading.value = false }
}

function openBindDialog(candidate) {
  currentCandidate.value = candidate
  selectedUserId.value = candidate.suggested_user_id || null
  if (candidate.suggested_user_id) {
    userOptions.value = candidate.suggested_user_name
      ? [{ id: candidate.suggested_user_id, real_name: candidate.suggested_user_name, username: '' }]
      : []
  } else {
    userOptions.value = []
  }
  bindDialogVisible.value = true
}

async function handleBind() {
  if (!currentCandidate.value || !selectedUserId.value) return
  try {
    await authApi.post(`/external-binding-candidates/${currentCandidate.value.id}/bind`, null, {
      params: { user_id: selectedUserId.value },
    })
    ElMessage.success('绑定成功')
    bindDialogVisible.value = false
    await loadCandidates()
  } catch { /* 拦截器已统一提示 */ }
}

async function handleIgnore(candidate) {
  try {
    await ElMessageBox.confirm('确认忽略该候选？', '提示', { type: 'warning' })
    await authApi.post(`/external-binding-candidates/${candidate.id}/ignore`)
    ElMessage.success('已忽略')
    await loadCandidates()
  } catch { /* cancelled */ }
}

function providerLabel(p) {
  return { alibaba_icbu: '阿里国际站', okki: 'OKKI', dingtalk: '钉钉', email: '邮箱' }[p] || p
}
function candidateStatusLabel(s) {
  return { pending: '待处理', bound: '已绑定', ignored: '已忽略' }[s] || s
}
function candidateStatusType(s) {
  return { pending: 'warning', bound: 'success', ignored: 'info' }[s] || 'info'
}
function formatTime(t) {
  return t ? new Date(t).toLocaleString('zh-CN') : '-'
}

onMounted(() => loadCandidates())
</script>

<style scoped>
.external-bindings { padding: 24px 28px; }
.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 20px; font-family: var(--font-display); color: var(--text-primary); }
.page-header p { margin: 4px 0 0; color: var(--text-muted); font-size: 13px; }
.co-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.text-muted { color: var(--text-muted); }
</style>
