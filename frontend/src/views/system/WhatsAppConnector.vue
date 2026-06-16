<template>
  <div class="whatsapp-page">
    <div class="page-header">
      <div>
        <h2>WhatsApp 同步</h2>
        <p>扫码绑定后，方舟从独立 Connector 拉取会话与消息记录。</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="ghost" left-icon="Refresh" @click="loadAccounts">刷新</GlassButton>
        <GlassButton variant="primary" left-icon="Connection" @click="handleCreateBindSession">扫码绑定</GlassButton>
      </div>
    </div>

    <div class="metric-strip">
      <div class="metric-item">
        <span class="metric-label">已绑定</span>
        <strong>{{ activeCount }}</strong>
      </div>
      <div class="metric-item">
        <span class="metric-label">异常</span>
        <strong>{{ errorCount }}</strong>
      </div>
      <div class="metric-item">
        <span class="metric-label">最近同步</span>
        <strong>{{ latestSyncText }}</strong>
      </div>
    </div>

    <div class="content-grid">
      <div class="table-card">
        <el-table :data="accounts" v-loading="loading" border class="list-table" style="width: 100%">
          <el-table-column label="账号" min-width="180" max-width="270" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="account-cell">
                <span>{{ row.display_name || row.phone_number || row.account_uid }}</span>
                <small>{{ row.phone_number || row.account_uid }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="100" max-width="150">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small" effect="plain">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Connector" prop="connector_status" min-width="120" max-width="180" show-overflow-tooltip />
          <el-table-column label="最后同步" min-width="160" max-width="240">
            <template #default="{ row }">{{ formatTime(row.last_sync_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="260" max-width="390" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="Refresh" @click="handlePull(row, 'messages')">拉取消息</GlassButton>
              <GlassButton variant="link" left-icon="View" @click="selectAccount(row)">查看记录</GlassButton>
              <GlassButton variant="link" link-tone="danger" left-icon="Close" @click="handleRevoke(row)">解绑</GlassButton>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="message-panel">
        <div class="panel-title">
          <span>最近消息</span>
          <GlassButton v-if="selectedAccount" variant="ghost" left-icon="Refresh" @click="loadMessages">刷新</GlassButton>
        </div>
        <el-empty v-if="!selectedAccount" description="选择一个账号查看记录" />
        <el-table v-else :data="messages" v-loading="messageLoading" border class="list-table" style="width: 100%">
          <el-table-column label="时间" min-width="150" max-width="220">
            <template #default="{ row }">{{ formatTime(row.sent_at || row.received_at) }}</template>
          </el-table-column>
          <el-table-column label="方向" min-width="80" max-width="120">
            <template #default="{ row }">{{ row.direction === 'outbound' ? '发出' : '收到' }}</template>
          </el-table-column>
          <el-table-column label="发送方" min-width="150" max-width="240" show-overflow-tooltip>
            <template #default="{ row }">{{ messageSenderText(row) }}</template>
          </el-table-column>
          <el-table-column label="内容" prop="content_preview" min-width="220" max-width="420" show-overflow-tooltip />
        </el-table>
      </div>
    </div>

    <el-dialog v-model="bindDialogVisible" title="扫码绑定 WhatsApp" width="520px" :close-on-click-modal="false">
      <div v-if="bindSession?.qr_code_url" class="qr-box">
        <img :src="bindSession.qr_code_url" alt="WhatsApp QR Code">
        <el-tag :type="statusType(bindSession.status)" effect="plain">{{ statusLabel(bindSession.status) }}</el-tag>
      </div>
      <el-empty v-else description="等待 Connector 返回二维码" />
      <template #footer>
        <GlassButton variant="ghost" @click="bindDialogVisible = false">关闭</GlassButton>
        <GlassButton variant="primary" left-icon="Refresh" :disabled="!bindSession" @click="refreshBindSession">刷新状态</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createWhatsAppBindSession,
  getWhatsAppBindSession,
  listWhatsAppAccounts,
  listWhatsAppMessages,
  pullWhatsAppResource,
  revokeWhatsAppAccount,
} from '@/api/whatsapp'

const accounts = ref([])
const messages = ref([])
const loading = ref(false)
const messageLoading = ref(false)
const bindDialogVisible = ref(false)
const bindSession = ref(null)
const selectedAccount = ref(null)

const activeCount = computed(() => accounts.value.filter(item => item.status === 'active').length)
const errorCount = computed(() => accounts.value.filter(item => item.status === 'error' || item.last_error).length)
const latestSyncText = computed(() => {
  const latest = accounts.value
    .map(item => item.last_sync_at)
    .filter(Boolean)
    .sort()
    .at(-1)
  return latest ? formatTime(latest) : '-'
})

async function loadAccounts() {
  loading.value = true
  try {
    const res = await listWhatsAppAccounts()
    accounts.value = res.data || []
  } finally {
    loading.value = false
  }
}

async function handleCreateBindSession() {
  const res = await createWhatsAppBindSession({})
  bindSession.value = res.data
  bindDialogVisible.value = true
}

async function refreshBindSession() {
  if (!bindSession.value?.bind_session_uid) return
  const res = await getWhatsAppBindSession(bindSession.value.bind_session_uid)
  bindSession.value = res.data
  if (bindSession.value?.status === 'active') {
    ElMessage.success('绑定成功')
    await loadAccounts()
  }
}

async function handlePull(account, resource) {
  const res = await pullWhatsAppResource({ account_uid: account.account_uid, resource, limit: 100 })
  ElMessage.success(`同步完成：${res.data?.pulled || 0} 条`)
  await loadAccounts()
  if (selectedAccount.value?.account_uid === account.account_uid) {
    await loadMessages()
  }
}

async function selectAccount(account) {
  selectedAccount.value = account
  await loadMessages()
}

async function loadMessages() {
  if (!selectedAccount.value) return
  messageLoading.value = true
  try {
    const res = await listWhatsAppMessages({
      account_uid: selectedAccount.value.account_uid,
      page: 1,
      page_size: 20,
    })
    messages.value = res.data?.items || []
  } finally {
    messageLoading.value = false
  }
}

async function handleRevoke(account) {
  try {
    await ElMessageBox.confirm(`确认解绑 ${account.display_name || account.phone_number || account.account_uid}？`, '解绑确认', { type: 'warning' })
  } catch {
    return
  }
  await revokeWhatsAppAccount(account.account_uid)
  ElMessage.success('已解绑')
  if (selectedAccount.value?.account_uid === account.account_uid) {
    selectedAccount.value = null
    messages.value = []
  }
  await loadAccounts()
}

function statusLabel(status) {
  return {
    pending: '待扫码',
    binding: '绑定中',
    active: '正常',
    revoked: '已解绑',
    error: '异常',
  }[status] || status || '-'
}

function statusType(status) {
  return {
    pending: 'warning',
    binding: 'warning',
    active: 'success',
    revoked: 'info',
    error: 'danger',
  }[status] || 'info'
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function messageSenderText(row) {
  return row.sender_name || row.sender_phone || row.sender_wa_id || '-'
}

onMounted(loadAccounts)
</script>

<style scoped>
.whatsapp-page { padding: 24px 28px; }
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0; font-size: 20px; font-family: var(--font-display); color: var(--text-primary); }
.page-header p { margin: 4px 0 0; color: var(--text-muted); font-size: 13px; }
.header-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.metric-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.metric-item {
  min-height: 64px;
  border: 1px solid rgba(212, 148, 28, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
  padding: 12px 14px;
}
.metric-label { display: block; color: var(--text-muted); font-size: 12px; margin-bottom: 6px; }
.metric-item strong { color: var(--text-primary); font-size: 20px; font-family: var(--font-display); }
.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  gap: 14px;
}
.message-panel {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.88);
  padding: 14px;
}
.panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  font-weight: 600;
}
.account-cell { display: flex; flex-direction: column; gap: 2px; }
.account-cell small { color: var(--text-muted); font-size: 12px; }
.qr-box { display: flex; flex-direction: column; align-items: center; gap: 14px; }
.qr-box img {
  width: 260px;
  height: 260px;
  object-fit: contain;
  border: 1px solid rgba(15, 23, 42, 0.1);
  border-radius: 8px;
  background: #fff;
}
@media (max-width: 1100px) {
  .content-grid { grid-template-columns: 1fr; }
}
@media (max-width: 720px) {
  .page-header { flex-direction: column; }
  .metric-strip { grid-template-columns: 1fr; }
}
</style>
