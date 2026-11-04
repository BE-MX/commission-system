<template>
  <DetailDrawer v-model="visible" :title="data?.customer.shop_name || '客户跟进'" width="640px" :loading="!data">
    <div v-if="data" class="timeline">
      <dl class="tl-head">
        <div><dt>等级</dt><dd>{{ data.customer.customer_level || '—' }}</dd></div>
        <div><dt>上次跟进</dt><dd :class="{ overdue: isOverdue }">{{ lastLabel }}</dd></div>
        <div><dt>跟进频率</dt><dd>{{ data.customer.frequency_days ? `每 ${data.customer.frequency_days} 天` : '未设' }}</dd></div>
        <div><dt>未结异常</dt><dd>{{ data.open_items.length }}</dd></div>
      </dl>
      <GlassButton v-if="data.customer.writable" v-permission="'domestic_followup:write'" variant="primary" class="tl-record"
                   @click="$emit('record', data.customer)">记一条跟进</GlassButton>
      <el-timeline>
        <el-timeline-item v-for="e in data.events" :key="`${e.type}-${e.data.id}`" :timestamp="e.date"
                          :type="e.type === 'shipment' ? 'info' : 'primary'" placement="top">
          <!-- 不可读时后端只返回本人写过/被派任务的记录（readable=false），这里照常渲染 -->
          <template v-if="e.type === 'shipment'">
            发货 {{ e.data.shipment_no }} · {{ e.data.quantity }} 件<span v-if="e.data.received_date">（{{ e.data.received_date }} 签收）</span>
          </template>
          <template v-else>
            <p class="tl-summary">{{ e.data.summary || e.data.raw_text }}</p>
            <ul class="tl-items">
              <li v-for="i in e.data.items" :key="i.id" :class="`kind-${i.kind}`">
                <StatusBadge v-if="i.kind !== 'content'" :value="i.kind" :dictionary="ITEM_KIND_STATUS" :label="i.category || undefined" size="small" />
                {{ i.text }}<span v-if="i.status === 'resolved'" class="resolved">已解决</span>
              </li>
            </ul>
            <p class="tl-meta">{{ e.data.author_name }} · {{ e.data.channel || '—' }}<span v-if="e.data.next_date"> · 下次 {{ e.data.next_date }}</span></p>
            <div v-if="e.data.attachments.length" class="tl-shots">
              <GlassButton v-for="a in e.data.attachments" :key="a.id" variant="link" @click="preview(a)">截图 {{ a.seq }}</GlassButton>
            </div>
            <div class="tl-actions">
              <GlassButton v-if="mayEditFollowup(auth.user, e.data)" v-permission="'domestic_followup:write'" variant="link" @click="recordAction('edit', e.data.id)">修改</GlassButton>
              <GlassButton variant="link" @click="recordAction('history', e.data.id)">修改历史</GlassButton>
            </div>
          </template>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!data.events.length" description="还没有跟进记录" />
    </div>
    <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" teleported @close="closePreview" />
  </DetailDrawer>
</template>

<script setup>
import { computed, ref } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'
import { ITEM_KIND_STATUS } from '../followupStatus'
import { useAuthStore } from '@/stores/auth'
import { mayEditFollowup } from '../followupEdit'

const emit = defineEmits(['record', 'edit', 'history'])
const auth = useAuthStore()
const visible = ref(false)
const data = ref(null)
const previewUrl = ref('')
function recordAction(action, id) { visible.value = false; emit(action, id) }

const isOverdue = computed(() => {
  const c = data.value?.customer
  return Boolean(c?.frequency_days && c.days_since_followup != null && c.days_since_followup > c.frequency_days)
})
const lastLabel = computed(() => {
  const c = data.value?.customer
  if (!c?.last_followup_date) return '从未'
  return `${c.days_since_followup} 天前`
})

async function open(customerId) {
  visible.value = true
  data.value = null
  try { data.value = await followupApi.timeline(customerId) } catch (e) {
    visible.value = false
    msgError(apiError(e, '时间线加载失败'), e)
  }
}

async function preview(att) {
  try { previewUrl.value = await followupApi.attachmentUrl(att.id) } catch (e) { msgError(apiError(e, '截图加载失败'), e) }
}

function closePreview() {
  URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

defineExpose({ open })
</script>

<style scoped>
.tl-head { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 0 0 12px; }
.tl-head dt { font-size: 12px; color: var(--text-secondary); }
.tl-head dd { margin: 2px 0 0; font-weight: 600; }
.tl-head dd.overdue { color: var(--color-warning-text); }
.tl-record { margin-bottom: 12px; }
.tl-summary { margin: 0 0 4px; font-weight: 600; }
.tl-items { margin: 0 0 4px; padding-left: 16px; }
.resolved { margin-left: 6px; font-size: 12px; color: var(--color-success); }
.tl-meta { margin: 0; font-size: 12px; color: var(--text-secondary); }
@media (max-width: 768px) { .tl-head { grid-template-columns: repeat(2, 1fr); } }
</style>
