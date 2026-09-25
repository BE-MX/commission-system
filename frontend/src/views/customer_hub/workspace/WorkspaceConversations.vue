<template>
  <div class="workspace-conversations">
    <section class="lg-card panel">
      <h3>会话 <span class="hint">AI 摘要待启用</span></h3>
      <el-empty v-if="!conversations.length" description="暂无已绑定会话" :image-size="60" />
      <el-table class="list-table" v-else :data="conversations" size="small" border @row-click="selectConversation">
        <el-table-column prop="channel" label="渠道" min-width="110" />
        <el-table-column prop="contact_name" label="联系人" min-width="120" show-overflow-tooltip />
        <el-table-column prop="message_count" label="消息数" min-width="90" />
        <el-table-column prop="last_message_at" label="最近消息" min-width="170" />
      </el-table>
    </section>

    <section v-if="activeConversation" class="lg-card panel">
      <h3>消息（游标分页）</h3>
      <div class="message-list">
        <div v-for="message in messages" :key="message.id" class="message-row" :class="message.direction">
          <span class="message-meta">{{ message.sent_at }} · {{ message.sender_name || (message.direction === 'in' ? '客户' : '我方') }}</span>
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
            <GlassButton variant="link" v-permission="'customer_pcw:write'" @click="bind(row)">绑定本客户</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import {
  createConversationBinding, listConversationMessages, listCustomerConversations, listPendingBindings,
} from '@/api/customerHub'
import { msgSuccess } from '@/utils/feedback'
import { buildBindingPayload } from '../customerWorkspaceController'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const conversations = ref([])
const pendingBindings = ref([])
const activeConversation = ref(null)
const messages = ref([])
const cursor = ref(null)
const hasMore = ref(false)

async function loadAll() {
  try {
    const [conversationRes, bindingRes] = await Promise.all([
      listCustomerConversations(props.customerId, {}),
      listPendingBindings({}),
    ])
    conversations.value = conversationRes.data?.items ?? []
    pendingBindings.value = bindingRes.data?.items ?? []
  } catch { /* 拦截器已提示 */ }
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
  } catch { /* 拦截器已提示 */ }
}

async function bind(row) {
  try {
    await createConversationBinding(buildBindingPayload({
      source_system: row.source_system,
      source_account_key: row.source_account_key,
      source_conversation_id: row.source_conversation_id,
      customer_id: props.customerId,
      evidence_refs: row.candidate_customers?.length
        ? [{ type: 'verified_contact_point', id: row.candidate_customers[0].contact_point_id }]
        : [{ type: 'manual_verification', id: 1 }],
      share_scope: 'customer_team',
    }), `bind-${row.source_conversation_id}-${Date.now()}`)
    msgSuccess('会话已绑定')
    await loadAll()
  } catch { /* 拦截器已提示 */ }
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
