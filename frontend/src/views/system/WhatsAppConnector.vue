<template>
  <div class="whatsapp-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="whatsapp-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <div>
        <h2>WhatsApp 同步</h2>
        <p>扫码绑定后，方舟从独立 Connector 拉取会话与消息记录。</p>
      </div>
    </div>

    <div class="metric-strip">
      <div class="metric-item lg-card is-static">
        <span class="metric-label">已绑定</span>
        <strong>{{ activeCount }}</strong>
      </div>
      <div class="metric-item lg-card is-static">
        <span class="metric-label">异常</span>
        <strong>{{ errorCount }}</strong>
      </div>
      <div class="metric-item lg-card is-static">
        <span class="metric-label">最近同步</span>
        <strong>{{ latestSyncText }}</strong>
      </div>
    </div>

    <div class="content-grid">
      <div ref="panelRef" class="table-card whatsapp-panel">
        <!-- 操作行（本页账号列表无筛选区）：主操作 + TableTools（Action Bar Spec） -->
        <div class="action-bar">
          <GlassButton v-permission="'whatsapp:write'" variant="primary" left-icon="Connection" @click="handleCreateBindSession">扫码绑定</GlassButton>
          <TableTools
            v-model:visible-keys="visibleKeys"
            v-model:density="density"
            :columns="columnDefs"
            :fullscreen="isFullscreen"
            @refresh="loadAccounts"
            @fullscreen="toggleFullscreen"
          />
        </div>

        <el-table :data="accounts" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
          <template #empty>
            <el-empty :image-size="96" description="暂无数据" />
          </template>
          <el-table-column v-if="visibleKeys.includes('account')" label="账号" min-width="180" max-width="270" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="account-cell">
                <span>{{ row.display_name || row.phone_number || row.account_uid }}</span>
                <small>{{ row.phone_number || row.account_uid }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="visibleKeys.includes('ark-user')" label="方舟用户" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="account-cell compact">
                <span>{{ arkUserText(row) }}</span>
                <small>ID {{ row.ark_user_id || '-' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="100" max-width="150">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small" effect="plain">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="visibleKeys.includes('connector')" label="Connector" min-width="150" max-width="220">
            <template #default="{ row }">
              <el-tooltip
                :disabled="!row.last_error"
                :content="row.last_error"
                placement="top"
              >
                <el-tag :type="connectorStatusType(row.connector_status)" size="small" effect="plain">
                  {{ connectorStatusLabel(row.connector_status) }}
                </el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column v-if="visibleKeys.includes('last-sync-at')" label="最后同步" min-width="160" max-width="240">
            <template #default="{ row }">{{ formatTime(row.last_sync_at) }}</template>
          </el-table-column>
          <el-table-column v-if="visibleKeys.includes('last-message-pull-at')" label="消息拉取" min-width="160" max-width="240">
            <template #default="{ row }">{{ formatTime(row.last_message_pull_at) }}</template>
          </el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="260" max-width="390" fixed="right">
            <template #default="{ row }">
              <GlassButton v-permission="'whatsapp:write'" variant="link" left-icon="Refresh" @click="handlePull(row, 'messages')">拉取消息</GlassButton>
              <GlassButton variant="link" left-icon="View" @click="selectAccount(row)">查看对话</GlassButton>
              <GlassButton v-permission="'whatsapp:write'" variant="link" link-tone="danger" left-icon="Close" @click="handleRevoke(row)">解绑</GlassButton>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="conversation-panel lg-card is-static">
        <div class="panel-title">
          <div>
            <span>对话记录</span>
            <small v-if="selectedAccount">{{ selectedAccountTitle }}</small>
          </div>
          <GlassButton v-if="selectedAccount" variant="ghost" left-icon="Refresh" @click="loadConversations">刷新</GlassButton>
        </div>
        <el-empty v-if="!selectedAccount" description="选择一个账号查看记录" />
        <div v-else class="conversation-workspace">
          <div class="conversation-list" v-loading="conversationLoading">
            <el-empty v-if="!conversations.length" description="暂无会话" />
            <template v-else>
              <button
                v-for="item in conversations"
                :key="item.conversation_uid"
                type="button"
                class="conversation-row"
                :class="{ active: selectedConversation?.conversation_uid === item.conversation_uid }"
                @click="selectConversation(item)"
              >
                <span class="conversation-name">{{ conversationTitle(item) }}</span>
                <span class="conversation-time">{{ formatTime(item.last_message_at) }}</span>
                <span class="conversation-preview">{{ item.last_message_preview || '暂无消息内容' }}</span>
              </button>
            </template>
          </div>

          <div class="message-thread" v-loading="messageLoading">
            <el-empty v-if="!selectedConversation" description="选择左侧会话查看消息" />
            <template v-else>
              <div class="thread-header">
                <div>
                  <strong>{{ conversationTitle(selectedConversation) }}</strong>
                  <span>{{ selectedConversation.contact_phone || selectedConversation.chat_id }}</span>
                </div>
                <el-tag v-if="selectedConversation.is_group" size="small" effect="plain">群聊</el-tag>
              </div>
              <el-empty v-if="!orderedMessages.length" description="暂无消息" />
              <div v-else class="message-list">
                <div
                  v-for="item in orderedMessages"
                  :key="item.message_uid"
                  class="message-item"
                  :class="{ outbound: item.direction === 'outbound' }"
                >
                  <div class="message-meta">
                    <span>{{ item.direction === 'outbound' ? '发出' : messageSenderText(item) }}</span>
                    <time>{{ formatTime(item.sent_at || item.received_at) }}</time>
                  </div>
                  <div class="message-bubble">
                    {{ item.content_text || item.content_preview || '[非文本消息]' }}
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>
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
import { formatBeijingDateTime } from '@/utils/datetime'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createWhatsAppBindSession,
  getWhatsAppBindSession,
  listWhatsAppAccounts,
  listWhatsAppConversations,
  listWhatsAppMessages,
  pullWhatsAppResource,
  revokeWhatsAppAccount,
} from '@/api/whatsapp'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'

// 列显隐元数据（TableTools 面板数据源，不驱动列渲染）
const columnDefs = [
  { key: 'account', label: '账号' },
  { key: 'ark-user', label: '方舟用户' },
  { key: 'status', label: '状态' },
  { key: 'connector', label: 'Connector' },
  { key: 'last-sync-at', label: '最后同步' },
  { key: 'last-message-pull-at', label: '消息拉取' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('whatsapp-connector', columnDefs)
const accounts = ref([])
const conversations = ref([])
const messages = ref([])
const loading = ref(false)
const conversationLoading = ref(false)
const messageLoading = ref(false)
const bindDialogVisible = ref(false)
const bindSession = ref(null)
const selectedAccount = ref(null)
const selectedConversation = ref(null)

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
const selectedAccountTitle = computed(() => {
  const account = selectedAccount.value
  return account ? account.display_name || account.phone_number || account.account_uid : ''
})
const orderedMessages = computed(() => [...messages.value].reverse())

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
    await loadConversations()
  }
}

async function selectAccount(account) {
  selectedAccount.value = account
  selectedConversation.value = null
  messages.value = []
  await loadConversations()
}

async function loadConversations() {
  if (!selectedAccount.value) return
  conversationLoading.value = true
  try {
    const currentConversationUid = selectedConversation.value?.conversation_uid
    const res = await listWhatsAppConversations({
      account_uid: selectedAccount.value.account_uid,
      page: 1,
      page_size: 50,
    })
    conversations.value = res.data?.items || []
    selectedConversation.value = conversations.value.find(item => item.conversation_uid === currentConversationUid) || conversations.value[0] || null
    if (selectedConversation.value) {
      await loadMessages()
    } else {
      messages.value = []
    }
  } finally {
    conversationLoading.value = false
  }
}

async function selectConversation(conversation) {
  selectedConversation.value = conversation
  await loadMessages()
}

async function loadMessages() {
  if (!selectedAccount.value || !selectedConversation.value) return
  messageLoading.value = true
  try {
    const res = await listWhatsAppMessages({
      account_uid: selectedAccount.value.account_uid,
      conversation_uid: selectedConversation.value.conversation_uid,
      page: 1,
      page_size: 50,
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
    selectedConversation.value = null
    conversations.value = []
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

function connectorStatusLabel(status) {
  return {
    initializing: '初始化中',
    qr_ready: '等待扫码',
    connected: '已连接',
    restoring: '恢复中',
    sync_error: '同步失败',
    qr_required: '需重新扫码',
    revoked: '已解绑',
    expired: '已过期',
    error: '连接异常',
  }[status] || status || '-'
}

function connectorStatusType(status) {
  return {
    connected: 'success',
    initializing: 'warning',
    qr_ready: 'warning',
    restoring: 'warning',
    sync_error: 'danger',
    qr_required: 'danger',
    error: 'danger',
    revoked: 'info',
    expired: 'info',
  }[status] || 'info'
}

function formatTime(value) {
  return formatBeijingDateTime(value)
}

function arkUserText(row) {
  return row.ark_user_name || row.ark_username || '-'
}

function messageSenderText(row) {
  return row.sender_name || row.sender_phone || row.sender_wa_id || '-'
}

function conversationTitle(row) {
  return row.contact_name || row.contact_phone || row.chat_id || '未命名会话'
}

onMounted(loadAccounts)
</script>

<style scoped src="./whatsapp-connector.css"></style>
