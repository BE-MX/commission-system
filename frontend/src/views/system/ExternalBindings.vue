<template>
  <div class="external-bindings">
    <div class="page-header">
      <h2>外部账号绑定候选</h2>
      <p>系统自动发现的未绑定外部账号，管理员可在此快速绑定到方舟用户。</p>
    </div>

    <div class="co-toolbar">
      <el-radio-group v-model="statusFilter" size="small" @change="loadCandidates">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="pending">待处理</el-radio-button>
        <el-radio-button label="bound">已绑定</el-radio-button>
        <el-radio-button label="ignored">已忽略</el-radio-button>
      </el-radio-group>
      <el-button size="small" @click="loadCandidates" :icon="Refresh">刷新</el-button>
    </div>

    <el-table :data="candidates" v-loading="loading" size="small" style="width: 100%">
      <el-table-column label="平台" width="120">
        <template #default="{ row }">{{ providerLabel(row.provider) }}</template>
      </el-table-column>
      <el-table-column label="外部账号 ID" prop="external_account_id" width="140" />
      <el-table-column label="显示名" prop="external_display_name" width="140" />
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="candidateStatusType(row.candidate_status)" size="small">{{ candidateStatusLabel(row.candidate_status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="建议用户" width="120">
        <template #default="{ row }">
          <span v-if="row.suggested_user_name">{{ row.suggested_user_name }}</span>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="首次发现" width="160">
        <template #default="{ row }">{{ formatTime(row.first_seen_at) }}</template>
      </el-table-column>
      <el-table-column label="出现次数" prop="seen_count" width="90" align="center" />
      <el-table-column label="操作" width="200" align="center">
        <template #default="{ row }">
          <template v-if="row.candidate_status === 'pending'">
            <el-button type="primary" size="small" @click="openBindDialog(row)">绑定用户</el-button>
            <el-button size="small" @click="handleIgnore(row)">忽略</el-button>
          </template>
          <span v-else class="text-muted">{{ candidateStatusLabel(row.candidate_status) }}</span>
        </template>
      </el-table-column>
    </el-table>

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
        <el-button @click="bindDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedUserId" @click="handleBind">确认绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

// 使用 authClient（/api/auth 前缀）
const authApi = axios.create({
  baseURL: '/api/auth',
  timeout: 30000,
  headers: { 'Authorization': `Bearer ${localStorage.getItem('ark_access_token')}` },
})

const loading = ref(false)
const candidates = ref([])
const statusFilter = ref('')
const bindDialogVisible = ref(false)
const currentCandidate = ref(null)
const selectedUserId = ref(null)
const userOptions = ref([])
const searchLoading = ref(false)

async function loadCandidates() {
  loading.value = true
  try {
    const params = statusFilter.value ? { status: statusFilter.value } : {}
    const res = await authApi.get('/external-binding-candidates', { params })
    candidates.value = res.data?.data || []
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
    userOptions.value = res.data?.data?.items || []
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
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '绑定失败')
  }
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
