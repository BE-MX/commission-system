<template>
  <div class="workspace-conversations">
    <section class="lg-card panel">
      <h3>会话与摘要</h3>
      <el-empty v-if="!conversations.length" description="暂无已绑定会话" :image-size="60" />
      <el-table class="list-table" v-else :data="conversations" size="small" border @row-click="selectConversation">
        <el-table-column prop="channel" label="渠道" min-width="110" />
        <el-table-column prop="contact_name" label="联系人" min-width="120" show-overflow-tooltip />
        <el-table-column prop="message_count" label="消息数" min-width="90" />
        <el-table-column prop="last_message_at" label="最近消息" min-width="170" />
        <el-table-column label="操作" min-width="130" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" v-permission="'customer_pcw:write'" @click.stop="triggerAnalysis(row)">生成摘要</GlassButton>
          </template>
        </el-table-column>
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

    <section v-if="analysisJob" class="lg-card panel">
      <h3>分析任务 <el-tag size="small">{{ analysisJob.status }}</el-tag></h3>
      <p v-if="analysisJob.failure_reason" class="message-warn">{{ analysisJob.failure_reason }}</p>
      <template v-if="analysisJob.result">
        <p><strong>摘要：</strong>{{ analysisJob.result.summary }}</p>
        <div v-for="(items, section) in analysisSections" :key="section">
          <strong>{{ sectionLabels[section] || section }}</strong>
          <ul>
            <li v-for="(item, index) in items" :key="index">
              {{ item.text }}
              <span v-if="item.evidence_message_ids?.length" class="hint">（消息 {{ item.evidence_message_ids.join(', ') }}）</span>
            </li>
          </ul>
        </div>
      </template>
      <p v-if="analysisJob.coverage" class="hint">
        覆盖：{{ analysisJob.coverage.sync_from }} ~ {{ analysisJob.coverage.sync_to }}
        <span v-if="analysisJob.coverage.attachments_unread"> · {{ analysisJob.coverage.attachments_unread }} 个附件未读取</span>
      </p>
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
import { computed, onMounted, ref } from 'vue'
import {
  createAnalysisJob, createConversationBinding,
  getAnalysisJob, listConversationMessages, listCustomerConversations, listPendingBindings,
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
const analysisJob = ref(null)
const sectionLabels = {
  demands: '需求', objections: '异议', commitments: '双方承诺',
  open_questions: '未决问题', next_steps: '建议下一步', profile_candidates: '画像候选',
}
const analysisSections = computed(() => {
  const result = analysisJob.value?.result
  if (!result) return {}
  return Object.fromEntries(
    Object.entries(result).filter(([key, value]) => Array.isArray(value) && key !== 'evidence_message_ids'),
  )
})

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

async function triggerAnalysis(row) {
  try {
    const response = await createAnalysisJob(row.id, `analysis-${row.id}-${Date.now()}`)
    const jobId = response.data?.job_id ?? response.data?.id
    msgSuccess('分析任务已创建')
    if (jobId) await pollJob(jobId)
  } catch { /* 拦截器已提示 */ }
}

async function pollJob(jobId, attempts = 5) {
  for (let index = 0; index < attempts; index += 1) {
    try {
      const response = await getAnalysisJob(jobId)
      analysisJob.value = response.data
      if (['succeeded', 'failed', 'stale', 'cancelled'].includes(response.data?.status)) return
      await new Promise(resolve => setTimeout(resolve, 2000))
    } catch { return }
  }
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
