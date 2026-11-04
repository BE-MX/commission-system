<template>
  <DetailDrawer :model-value="Boolean(record)" title="跟进记录详情" width="640px" @update:model-value="value => { if (!value) $emit('close') }">
    <template v-if="record">
      <dl class="record-meta">
        <div><dt>客户</dt><dd>{{ record.shop_name }}</dd></div>
        <div><dt>录入人</dt><dd>{{ record.author_name }}</dd></div>
        <div><dt>跟进日期</dt><dd>{{ record.followup_date }}</dd></div>
        <div><dt>沟通方式</dt><dd>{{ record.channel || '—' }}</dd></div>
      </dl>
      <section v-if="record.summary"><h3>摘要</h3><p>{{ record.summary }}</p></section>
      <section v-if="record.raw_text"><h3>跟进原文</h3><p>{{ record.raw_text }}</p></section>
      <section v-if="record.items?.length">
        <h3>跟进要点与异常意见</h3>
        <ul><li v-for="item in record.items" :key="item.id">
          <StatusBadge v-if="item.kind !== 'content'" :value="item.kind" :dictionary="ITEM_KIND_STATUS" size="small" />
          {{ item.text }}<span v-if="item.category"> · {{ item.category }}</span>
          <span v-if="item.severity"> · {{ item.severity }}</span>
          <span v-if="item.status"> · {{ ITEM_STATUS[item.status] || item.status }}</span>
          <p v-if="item.resolution">处理说明：{{ item.resolution }}</p>
        </li></ul>
      </section>
      <section v-if="record.state_changes?.length"><h3>客户变化</h3><p>{{ record.state_changes.join('、') }}</p></section>
      <section v-if="record.next_date || record.next_plan">
        <h3>下次跟进</h3><p>{{ [record.next_date, record.next_method, record.next_plan].filter(Boolean).join(' · ') }}</p>
      </section>
      <section v-if="record.attachments?.length">
        <h3>截图</h3>
        <GlassButton v-for="attachment in record.attachments" :key="attachment.id" variant="link" @click="preview(attachment)">截图 {{ attachment.seq }}</GlassButton>
      </section>
      <div class="record-actions">
        <GlassButton v-if="mayEditFollowup(auth.user, record)" v-permission="'domestic_followup:write'" variant="primary" left-icon="EditPen" @click="$emit('edit', record.id)">修改记录</GlassButton>
        <GlassButton variant="outline" @click="$emit('history', record.id)">修改记录历史</GlassButton>
        <GlassButton variant="outline" left-icon="View" @click="$emit('timeline', record.customer_id)">查看客户时间线</GlassButton>
      </div>
    </template>
    <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" teleported @close="closePreview" />
  </DetailDrawer>
</template>

<script setup>
import { onUnmounted, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'
import { ITEM_KIND_STATUS } from '../followupStatus'
import { useAuthStore } from '@/stores/auth'
import { mayEditFollowup } from '../followupEdit'

const props = defineProps({ record: { type: Object, default: null } })
defineEmits(['close', 'timeline', 'edit', 'history'])
const auth = useAuthStore()
const ITEM_STATUS = { open: '未处理', handling: '处理中', resolved: '已解决', closed_no_action: '无需处理' }
const previewUrl = ref('')
let previewRequest = 0
function closePreview() {
  previewRequest += 1
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}
async function preview(attachment) {
  closePreview()
  const request = previewRequest
  try {
    const url = await followupApi.attachmentUrl(attachment.id)
    if (request !== previewRequest) { URL.revokeObjectURL(url); return }
    previewUrl.value = url
  } catch (error) {
    if (request === previewRequest) msgError(apiError(error, '截图加载失败'), error)
  }
}
watch(() => props.record, closePreview)
onUnmounted(closePreview)
</script>

<style scoped>
.record-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 0 0 24px; }
.record-meta dt { color: var(--text-secondary); font-size: 12px; }
.record-meta dd { margin: 4px 0 0; overflow-wrap: anywhere; }
section { margin-bottom: 20px; }
h3 { margin: 0 0 8px; font-size: 14px; }
p, li { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
p { margin: 0; }
ul { padding-left: 20px; margin: 0; }
li + li { margin-top: 8px; }
.record-actions { display: flex; gap: 10px; flex-wrap: wrap; }
</style>
