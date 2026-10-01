<template>
  <div class="workspace-conversations">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <GlassButton variant="secondary" @click="loadAll">刷新沟通记录</GlassButton>
    <section class="lg-card panel">
      <h3>会话 <span class="hint">AI 摘要待启用</span></h3>
      <el-empty v-if="!conversations.length" description="暂无已绑定会话" :image-size="60" />
      <el-table class="list-table" v-else :data="conversations" size="small" border @row-click="selectConversation">
        <el-table-column prop="channel" label="渠道" min-width="110" />
        <el-table-column prop="contact_name" label="联系人" min-width="120" show-overflow-tooltip />
        <el-table-column prop="message_count" label="消息数" min-width="90" />
        <el-table-column label="最近消息（北京时间）" min-width="170"><template #default="{row}">{{ date(row.last_message_at) }}</template></el-table-column>
      </el-table>
    </section>

    <section v-if="activeConversation" class="lg-card panel">
      <h3>消息（游标分页）</h3>
      <div class="message-list">
        <div v-for="message in messages" :key="message.id" class="message-row" :class="message.direction">
          <span class="message-meta">{{ date(message.sent_at) }} · {{ message.sender_name || (message.direction === 'in' ? '客户' : '我方') }}</span>
          <span class="message-text">{{ message.text || message.content_preview || '（无文本）' }}</span>
          <span v-if="message.attachments_unread" class="message-warn">附件未读取</span>
        </div>
      </div>
      <el-button v-if="hasMore" @click="loadMoreMessages">加载更多</el-button>
    </section>

    <section class="lg-card panel">
      <h3>待绑定会话 <span class="hint">同名/相似手机号不自动归并</span></h3>
      <el-empty v-if="!pendingBindings.length" description="没有待绑定会话" :image-size="60" />
      <el-table class="list-table" v-else :data="pendingBindings" size="small" border>
        <el-table-column prop="contact_name" label="来源联系人" min-width="120" />
        <el-table-column prop="contact_phone" label="电话" min-width="130" />
        <el-table-column prop="message_count" label="消息数" min-width="90" />
        <el-table-column label="候选客户" min-width="140">
          <template #default="{ row }">
            <span v-if="row.candidate_customers?.length">{{ row.candidate_customers.map(c => c.customer_id).join(', ') }}</span>
            <span v-else class="hint">需人工核验</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="110" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" v-permission="'customer_pcw:write'" @click="openBinding(row)">核验并绑定本客户</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </section>
    <el-dialog v-model="bindingVisible" append-to-body title="核验会话归属" width="min(620px, calc(100vw - 24px))"><el-alert v-if="error" :title="error" type="error" :closable="false" /><p>请确认来源账号与会话确实属于这个客户；相似名称或号码不作为自动绑定依据。</p><p>{{ selectedBinding?.source_system }} · {{ selectedBinding?.source_account_key }} · {{ selectedBinding?.source_conversation_id }}</p><EvidencePicker v-model="bindingEvidence" :customer-id="customerId" references /><template #footer><GlassButton v-permission="'customer_pcw:write'" variant="primary" :loading="bindingSaving" :disabled="!bindingEvidence.length" @click="bind">确认归属并绑定</GlassButton></template></el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import {
  createConversationBinding, listConversationMessages, listCustomerConversations, listPendingBindings,
} from '@/api/customerHub'
import { msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { errorMessage } from '../workbenchV2Controller'
import { createSubmissionIdentity } from '../workbenchV2Controller'
import EvidencePicker from '../EvidencePicker.vue'
import { buildBindingPayload } from '../customerWorkspaceController'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const conversations = ref([])
const error = ref('')
const bindingVisible=ref(false),selectedBinding=ref(null),bindingEvidence=ref([]),bindingSaving=ref(false),bindingIdentity=createSubmissionIdentity('binding')
const date = value => value ? formatBeijingDateTime(value, {seconds:false}) : '未提供'
const pendingBindings = ref([])
const activeConversation = ref(null)
const messages = ref([])
const cursor = ref(null)
const hasMore = ref(false)

async function loadAll() {
  error.value = ''
  try {
    const [conversationRes, bindingRes] = await Promise.all([
      listCustomerConversations(props.customerId, {}),
      listPendingBindings({}),
    ])
    conversations.value = conversationRes.data?.items ?? []
    pendingBindings.value = bindingRes.data?.items ?? []
  } catch (caught) { error.value = errorMessage(caught) }
}

async function selectConversation(row) {
  activeConversation.value = row
  messages.value = []
  cursor.value = null
  await loadMoreMessages()
}

async function loadMoreMessages() {
  if (!activeConversation.value) return
  try {
    const response = await listConversationMessages(activeConversation.value.id, {
      cursor: cursor.value, limit: 20,
    })
    messages.value = messages.value.concat(response.data?.items ?? [])
    cursor.value = response.data?.next_cursor ?? null
    hasMore.value = Boolean(response.data?.has_more)
  } catch (caught) { error.value = errorMessage(caught) }
}

function openBinding(row){selectedBinding.value=row;bindingEvidence.value=[];bindingIdentity.reset();bindingVisible.value=true}
async function bind() {
  if(bindingSaving.value || !bindingEvidence.value.length)return
  bindingSaving.value=true
  try {
    const row=selectedBinding.value
    const payload=buildBindingPayload({
      source_system: row.source_system,
      source_account_key: row.source_account_key,
      source_conversation_id: row.source_conversation_id,
      customer_id: props.customerId,
      expected_binding_version: row.binding_version ?? 0,
      evidence_refs: bindingEvidence.value,
      share_scope: 'customer_team',
    })
    await createConversationBinding(payload, bindingIdentity.forPayload(payload))
    msgSuccess('会话已绑定')
    bindingVisible.value=false
    await loadAll()
  } catch (caught) { error.value = errorMessage(caught) }
  finally { bindingSaving.value=false }
}

onMounted(loadAll)
</script>

<style scoped>
.workspace-conversations { display: grid; gap: 14px; }
.panel { padding: 14px 16px; }
.panel h3 { margin: 0 0 10px; font-size: 14px; }
.hint { font-size: 12px; color: var(--text-muted); font-weight: normal; }
.message-list { display: grid; gap: 6px; margin-bottom: 8px; max-height: 320px; overflow-y: auto; }
.message-row { display: grid; gap: 2px; padding: 6px 8px; border-left: 3px solid var(--border-color); }
.message-row.out { border-left-color: var(--color-primary); }
.message-meta { font-size: 12px; color: var(--text-muted); }
.message-text { font-size: 13px; color: var(--text-primary); }
.message-warn { color: var(--color-danger); font-size: 12px; }
</style>
