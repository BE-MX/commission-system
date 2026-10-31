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
        <p>关联公司业务号，持续同步平台可提供的会话与消息；历史覆盖范围单独标明。</p>
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
          <GlassButton v-permission="'whatsapp:write'" variant="primary" left-icon="Connection" @click="openBind()">关联业务号</GlassButton>
          <TableTools
            v-model:visible-keys="visibleKeys"
            v-model:density="density"
            :columns="columnDefs"
            :fullscreen="isFullscreen"
            @refresh="loadAccounts"
            @fullscreen="toggleFullscreen"
          />
        </div>

        <ListPageStatus v-if="accountsResource.hasData.value" :paged="false" :error="accountsResource.errorMessage.value" :loading="loading" :has-data="true" @retry="loadAccounts" />
        <el-table :data="accounts" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
          <template #empty>
            <ListPageStatus :paged="false" :error="accountsResource.errorMessage.value" :loading="loading" @retry="loadAccounts"><el-empty v-if="accountsResource.isEmpty.value" :image-size="96" description="暂无数据" /></ListPageStatus>
          </template>
          <el-table-column :sort-by="row => row.display_name || row.phone_number || row.account_uid" v-if="visibleKeys.includes('account')" label="账号" min-width="180" max-width="270" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="account-cell">
                <span>{{ row.display_name || row.phone_number || row.account_uid }}</span>
                <small>{{ row.phone_number || row.account_uid }}</small>
                <small>{{ row.provider === 'baileys' ? 'Baileys' : '旧接入 · 待迁移' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column :sort-by="row => (arkUserText(row))" v-if="visibleKeys.includes('ark-user')" label="方舟用户" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="account-cell compact">
                <span>{{ arkUserText(row) }}</span>
                <small>ID {{ row.ark_user_id || '-' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="status" v-if="visibleKeys.includes('status')" label="状态" min-width="120" max-width="150">
            <template #default="{ row }">
              <StatusBadge :type="statusType(row.status)" size="small" effect="plain">{{ statusLabel(row.status) }}</StatusBadge>
            </template>
          </el-table-column>
          <el-table-column prop="connector_status" v-if="visibleKeys.includes('connector')" label="Connector" min-width="150" max-width="220">
            <template #default="{ row }">
              <el-tooltip
                :disabled="!row.last_error"
                :content="row.last_error"
                placement="top"
              >
                <StatusBadge :type="connectorStatusType(row.connector_status)" size="small" effect="plain">
                  {{ connectorStatusLabel(row.connector_status) }}
                </StatusBadge>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="last_sync_at" v-if="visibleKeys.includes('last-sync-at')" label="最后同步" min-width="160" max-width="240">
            <template #default="{ row }">{{ formatTime(row.last_sync_at) }}</template>
          </el-table-column>
          <el-table-column prop="last_message_pull_at" v-if="visibleKeys.includes('last-message-pull-at')" label="消息拉取" min-width="160" max-width="240">
            <template #default="{ row }">{{ formatTime(row.last_message_pull_at) }}</template>
          </el-table-column>
          <el-table-column label="同步与覆盖" min-width="160">
            <template #default="{ row }"><div class="account-cell"><span>{{ syncLabel(row.sync_state) }}</span><small>{{ historyLabel(row.history_state) }}</small><small v-if="row.gap_reason">缺口：{{ row.gap_reason }}</small></div></template>
          </el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="290" max-width="440" fixed="right">
            <template #default="{ row }">
              <GlassButton v-permission="'whatsapp:write'" variant="link" left-icon="Refresh" :disabled="!row.can_read_body || row.consent_state !== 'active' || syncBusy" @click="handlePull(row, 'messages')">同步消息</GlassButton>
              <GlassButton variant="link" left-icon="View" :disabled="!row.can_read_body" @click="selectAccount(row)">查看对话</GlassButton>
              <GlassButton v-permission="'whatsapp:write'" v-if="isOwner(row)" variant="link" @click="openBind(row)" left-icon="Edit">重新关联</GlassButton>
                <GlassButton v-permission="'whatsapp:write'" v-if="isOwner(row)" variant="link" @click="openConsent(row)" left-icon="Edit">授权范围</GlassButton>
                <GlassButton v-permission="'whatsapp:write'" v-if="isOwner(row) && row.status === 'protected' && row.consent_state === 'active'" variant="link" left-icon="VideoPlay" :disabled="resumeBusy" @click="handleResume(row)">恢复采集</GlassButton>
              <GlassButton v-permission="'whatsapp:write'" variant="link" link-tone="danger" left-icon="Close" :disabled="['revoking', 'revoked', 'revoke_pending'].includes(row.status)" @click="handleRevoke(row)">解绑</GlassButton>
              <GlassButton v-permission="'whatsapp:write'" v-if="isOwner(row) && row.status === 'revoke_pending'" variant="link" @click="confirmPhoneRemoval(row)" left-icon="Edit">确认手机已移除</GlassButton>
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
          <div v-if="selectedAccount">
            <GlassButton v-permission="'whatsapp:read'" variant="ghost" :disabled="!selectedAccount.can_read_body" @click="assistantVisible = true">AI消息助手</GlassButton>
            <GlassButton variant="ghost" left-icon="Refresh" @click="loadConversations">刷新</GlassButton>
          </div>
        </div>
        <el-empty v-if="!selectedAccount" description="选择一个账号查看记录" />
        <div v-else class="conversation-workspace">
          <div class="conversation-list" v-loading="conversationLoading && !conversations.length">
            <ListPageStatus :paged="false" :error="conversationsResource.errorMessage.value" :loading="conversationLoading" :has-data="conversationsResource.hasData.value" @retry="loadConversations" />
            <small v-if="conversationsResource.hasLoaded.value">本页 {{ conversations.length }} 条会话（共 {{ conversationTotal }} 条）</small>
            <el-pagination v-if="conversationTotal" v-model:current-page="conversationPage" v-model:page-size="conversationPageSize" :page-sizes="[20, 50, 100]" :total="conversationTotal" :pager-count="5" layout="total, sizes, prev, pager, next" @current-change="loadConversations" @size-change="conversationPage = 1; loadConversations()" />
            <el-empty v-if="conversationsResource.isEmpty.value" description="暂无会话" />
            <template v-if="conversations.length">
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
                <StatusBadge v-if="selectedConversation.is_group" size="small" effect="plain">群聊</StatusBadge>
              </div>
              <ListPageStatus :paged="false" :error="messagesResource.errorMessage.value" :loading="messageLoading" :has-data="messagesResource.hasData.value" @retry="loadMessages" />
              <small v-if="messagesResource.hasLoaded.value">本页 {{ messages.length }} 条消息（共 {{ messageTotal }} 条）</small>
              <p class="coverage-note">{{ historyLabel(selectedConversation.history_state) }}<template v-if="selectedConversation.gap_reason"> · {{ selectedConversation.gap_reason }}</template>。仅表示平台已提供范围。</p>
              <el-pagination v-if="messageTotal" v-model:current-page="messagePage" v-model:page-size="messagePageSize" :page-sizes="[20, 50, 100]" :total="messageTotal" :pager-count="5" layout="total, sizes, prev, pager, next" @current-change="loadMessages" @size-change="messagePage = 1; loadMessages()" />
              <el-empty v-if="messagesResource.isEmpty.value" description="暂无消息" />
              <div v-if="orderedMessages.length" class="message-list">
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
                    {{ item.deleted_at ? '[消息已撤回]' : (item.content_text || item.content_preview || '[非文本消息]') }}
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="bindDialogVisible" :title="bindingAccount ? '重新关联公司业务号' : '关联公司业务号'" width="640px" :close-on-click-modal="false">
      <div v-if="!bindSession" class="consent-form">
        <p v-if="bindingAccount">继续使用原业务账号，保留历史消息与客户绑定。需用手机重新扫码；重新关联后，正文可见员工与 AI 分析外发授权会清空，请在“授权范围”中重新设置。</p>
        <el-checkbox v-model="companyAccount">我确认这是公司专用业务号，允许同步全部会话（包含群聊）</el-checkbox>
        <el-checkbox v-model="shareCRM">允许将明确绑定的业务会话共享到客户工作台</el-checkbox>
        <p>管理员默认查看连接状态。聊天正文和 AI 分析外发需在授权范围中另外设置。</p>
      </div>
      <div v-if="bindSession?.qr_code_url" class="qr-box">
        <img :src="bindSession.qr_code_url" alt="WhatsApp QR Code">
        <StatusBadge :type="statusType(bindSession.status)" effect="plain">{{ statusLabel(bindSession.status) }}</StatusBadge>
      </div>
      <el-empty v-else-if="bindSession" :description="bindSession.status === 'active' ? '已关联，可关闭窗口' : `连接状态：${statusLabel(bindSession.status)}`" />
      <template #footer>
        <GlassButton variant="ghost" @click="bindDialogVisible = false">关闭</GlassButton>
        <GlassButton v-if="!bindSession" variant="primary" :loading="bindBusy" :disabled="!companyAccount || bindBusy" @click="createBinding">确认授权并关联</GlassButton>
        <GlassButton v-else variant="primary" left-icon="Refresh" @click="refreshBinding()">刷新状态</GlassButton>
      </template>
    </el-dialog>
    <el-dialog v-model="consentDialogVisible" title="账号授权范围" width="640px" :close-on-click-modal="false">
      <div class="consent-form">
        <el-checkbox v-model="consentForm.enabled">允许采集与正文访问</el-checkbox>
        <el-checkbox v-if="consentForm.enabled" v-model="consentForm.company_account">确认公司专用业务号允许全部会话（包含群聊）</el-checkbox>
        <el-checkbox v-model="consentForm.crm_shared" :disabled="!consentForm.enabled">允许客户工作台共享已绑定会话</el-checkbox>
        <el-checkbox v-model="consentForm.ai_egress_allowed" :disabled="!consentForm.enabled">允许主动调用已有 AI 供应商生成聊天摘要与跟进建议</el-checkbox>
        <label for="whatsapp-readers">正文可见员工（持有人始终可见）</label>
        <el-select id="whatsapp-readers" v-model="consentForm.reader_user_ids" multiple filterable remote :remote-method="searchReaders" :disabled="!consentForm.enabled" placeholder="搜索员工姓名" aria-label="正文可见员工">
          <el-option v-for="user in readerCandidates" :key="user.id" :label="`${user.name} · ${user.id}`" :value="user.id" />
        </el-select>
        <p>授权员工还需相应功能权限。关闭授权立即阻断方舟读取，连接器在授权检查周期内停止采集。</p>
      </div>
      <template #footer>
        <GlassButton variant="ghost" @click="consentDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="consentBusy" :disabled="consentBusy || (consentForm.enabled && !consentForm.company_account)" @click="saveConsent">保存授权</GlassButton>
      </template>
    </el-dialog>
    <WhatsAppAiAssistant v-model="assistantVisible" :account="selectedAccount" :conversation="selectedConversation" :access-key="assistantAccessKey" />
  </div>
</template>

<script setup>import { msgSuccessText, msgWarning, confirmAction } from '@/utils/feedback'
import { computed, onMounted, ref, watch } from 'vue'
import { formatBeijingDateTime } from '@/utils/datetime'

import {
  listWhatsAppAccounts,
  listWhatsAppConversations,
  listWhatsAppMessages,
  pullWhatsAppResource,
  revokeWhatsAppAccount,
  confirmWhatsAppDeviceRemoval,
  resumeWhatsAppCollection,
} from '@/api/whatsapp'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useAuthStore } from '@/stores/auth'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import WhatsAppAiAssistant from './components/WhatsAppAiAssistant.vue'
import { useWhatsAppBinding } from './composables/useWhatsAppBinding'
import { historyLabel, syncLabel, revokeFeedback } from './whatsappStatus'

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
const auth = useAuthStore()
const conversationTotal = ref(0), messageTotal = ref(0)
const conversationPage = ref(1), messagePage = ref(1), syncBusy = ref(false)
const conversationPageSize = ref(20), messagePageSize = ref(20)
const readOptions = signal => ({ signal, suppressToast: true, showLoading: false })
const accountsResource = useAsyncResource(async (_, { signal }) => (await listWhatsAppAccounts(readOptions(signal))).data || [], { initialData: [] })
const conversationsResource = useAsyncResource(async (params, { signal, isCurrent }) => {
  const data = (await listWhatsAppConversations({ ...params }, readOptions(signal))).data || {}
  if (isCurrent()) conversationTotal.value = data.total ?? (data.items || []).length
  return data.items || []
}, { initialData: [] })
const messagesResource = useAsyncResource(async (params, { signal, isCurrent }) => {
  const data = (await listWhatsAppMessages({ ...params }, readOptions(signal))).data || {}
  if (isCurrent()) messageTotal.value = data.total ?? (data.items || []).length
  return data.items || []
}, { initialData: [] })
const accounts = accountsResource.data, conversations = conversationsResource.data, messages = messagesResource.data
const loading = accountsResource.loading, conversationLoading = conversationsResource.loading, messageLoading = messagesResource.loading
const { bindDialogVisible, bindSession, bindBusy, bindingAccount, companyAccount, shareCRM,
  consentDialogVisible, consentForm, consentBusy, readerCandidates, openBind,
  create: createBinding, refresh: refreshBinding, openConsent, searchReaders, saveConsent, stop: stopBinding } = useWhatsAppBinding(loadAccounts)
const selectedAccount = ref(null)
const selectedConversation = ref(null)
const assistantVisible = ref(false)
const assistantAccessKey = computed(() => JSON.stringify([auth.user?.id, auth.roles, auth.permissions]))

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
  const success = await accountsResource.load()
  if (success && selectedAccount.value) {
    const current = accounts.value.find(item => item.account_uid === selectedAccount.value.account_uid)
    if (current?.can_read_body) selectedAccount.value = current
    else { selectedAccount.value = null; clearConversations() }
  }
  return success
}
function clearMessages() { messagesResource.clear(); messageTotal.value = 0; messagePage.value = 1 }
function clearConversations() { conversationsResource.clear(); conversationTotal.value = 0; conversationPage.value = 1; selectedConversation.value = null; clearMessages() }
watch(() => JSON.stringify([auth.user?.id, auth.roles, auth.permissions]), () => {
  accountsResource.clear(); selectedAccount.value = null; clearConversations()
  stopBinding()
  void loadAccounts()
})

async function handlePull(account, resource) {
  if (syncBusy.value) return
  syncBusy.value = true
  try {
  const res = await pullWhatsAppResource({ account_uid: account.account_uid, resource, limit: 100 })
  msgSuccessText(`本批已入库 ${res.data?.pulled || 0} 条消息；历史覆盖范围另行显示`)
  await loadAccounts()
  if (selectedAccount.value?.account_uid === account.account_uid) {
    await loadConversations()
  }
  } finally { syncBusy.value = false }
}

async function selectAccount(account) {
  if (!account.can_read_body) return
  if (selectedAccount.value?.account_uid !== account.account_uid) clearConversations()
  selectedAccount.value = account
  return loadConversations()
}
async function loadConversations() {
  if (!selectedAccount.value) return false
  const success = await conversationsResource.load({ account_uid: selectedAccount.value.account_uid, page: conversationPage.value, page_size: conversationPageSize.value })
  if (!success) return false
  const current = selectedConversation.value?.conversation_uid
  const next = conversations.value.find(item => item.conversation_uid === current) || conversations.value[0] || null
  if (next) await selectConversation(next)
  else { selectedConversation.value = null; clearMessages() }
  return true
}
async function selectConversation(conversation) {
  if (selectedConversation.value?.conversation_uid !== conversation.conversation_uid) clearMessages()
  selectedConversation.value = conversation
  return loadMessages()
}
function loadMessages() {
  if (!selectedAccount.value || !selectedConversation.value) return false
  return messagesResource.load({ account_uid: selectedAccount.value.account_uid, conversation_uid: selectedConversation.value.conversation_uid, page: messagePage.value, page_size: messagePageSize.value })
}

async function handleRevoke(account) {
  try {
    await confirmAction(`确认解绑 ${account.display_name || account.phone_number || account.account_uid}？`, '解绑确认', { type: 'warning' })
  } catch {
    return
  }
  const result = await revokeWhatsAppAccount(account.account_uid)
  const feedback = revokeFeedback(result.data)
  const notify = feedback.confirmed ? msgSuccessText : msgWarning
  notify(feedback.text)
  if (selectedAccount.value?.account_uid === account.account_uid) {
    selectedAccount.value = null
    clearConversations()
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
    reconnecting: '重连中', reconnect_required: '需重新关联', paused: '已暂停', blocked: '已阻断',
    protected: '保护性暂停',
    revoking: '解绑中', revoke_pending: '远端注销未确认', expired: '关联已过期',
  }[status] || status || '-'
}

function statusType(status) {
  return {
    pending: 'warning',
    binding: 'warning',
    active: 'success',
    revoked: 'info',
    error: 'danger',
    protected: 'warning',
  }[status] || 'info'
}

function connectorStatusLabel(status) {
  return {
    initializing: '初始化中',
    qr_ready: '等待扫码',
    connected: '已连接',
    restoring: '恢复中',
    online: '已连接', connecting: '连接中', reconnecting: '自动重连中',
    reauth_required: '需重新关联', protected_pause: '保护性暂停', blocked: '已阻断', paused: '已暂停',
    authorization_wait: '等待自动恢复',
    remote_unconfirmed: '请核对手机关联设备', revoked_confirmed: '远端注销已确认',
    owner_confirmed: '持有人已核对手机',
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
    authorization_wait: 'warning',
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

function isOwner(row) { return Number(row.ark_user_id) === Number(auth.user?.id) }

const resumeBusy = ref(false)
async function handleResume(row) {
  if (resumeBusy.value) return
  resumeBusy.value = true
  try {
    const result = await resumeWhatsAppCollection(row.account_uid)
    if (result.data?.status === 'reconnect_required') msgWarning('登录凭据已失效，请点击“重新关联”扫码')
    else msgSuccessText('已恢复采集，暂停期间的缺口会在同步状态中保留')
    await loadAccounts()
  } finally { resumeBusy.value = false }
}

async function confirmPhoneRemoval(row) {
  try {
    await confirmAction('请先在手机 WhatsApp 的“已关联设备”中确认该方舟设备已移除，再提交此确认。', '持有人确认', { confirmButtonText: '已核对并移除', cancelButtonText: '尚未核对' })
  } catch { return }
  await confirmWhatsAppDeviceRemoval(row.account_uid)
  msgSuccessText('已记录持有人核对结果'); await loadAccounts()
}

onMounted(loadAccounts)
</script>

<style scoped src="./whatsapp-connector.css"></style>
