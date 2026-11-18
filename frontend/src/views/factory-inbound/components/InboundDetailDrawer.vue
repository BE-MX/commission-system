<template>
  <DetailDrawer :model-value="Boolean(id)" title="工厂到货单详情" :width="720" :loading="waiting"
    @update:model-value="open => { if (!open) $emit('close') }">
    <div v-if="readError" role="alert">
      <p>{{ readError }}</p><GlassButton @click="open(id)">重新读取</GlassButton>
    </div>
    <template v-else-if="note">
      <header class="note-meta">
        <div>
          <h2>{{ note.inbound_no }}</h2>
          <p>{{ deliveryDate(note) }} · {{ noteStatus(note) }} · {{ note.creator || note.created_by }}</p>
          <p>工厂单据 {{ note.delivery_no || note.recognized_delivery_no || '待核对' }}</p>
        </div>
        <InboundPhoto :note="note" />
      </header>
      <p v-if="note.duplicate" class="warning">疑似重复 {{ note.duplicate.inbound_no }} · {{ note.duplicate.creator }}</p>
      <p v-if="note.recognition_error" role="alert">{{ note.recognition_error }}</p>
      <p v-if="delayed" role="status">识别仍在进行 <GlassButton variant="link" @click="open(id, { clear: false })">刷新</GlassButton></p>
      <InboundBatchStatus :note-id="note.id" />
      <section v-for="group in groups" :key="group.ref" class="detail-group">
        <h3>{{ group.ref }}</h3>
        <InboundReviewLine v-for="line in group.items" :key="line.id" :line="line" />
      </section>
      <section v-if="note.logs.length">
        <h3>核对记录</h3>
        <details v-for="(entry, index) in note.logs" :key="index" class="entry">
          <summary>{{ formatBeijingDateTime(entry.created_at) }} · {{ actions[entry.action] || entry.action }}{{ entry.line_id ? ' · 明细 ID ' + entry.line_id : '' }} · 操作人 {{ entry.created_by }}</summary>
          <dl><dt v-if="entry.before">修改前</dt><dd v-if="entry.before">{{ describe(entry.before) }}</dd>
            <dt v-if="entry.after">修改后</dt><dd v-if="entry.after">{{ describe(entry.after) }}</dd></dl>
        </details>
      </section>
    </template>
    <template #footer>
      <GlassButton v-if="note?.editable" v-any-permission="['factory_inbound:write', 'factory_inbound:admin']"
        variant="primary" @click="router.push({ path: '/factory-inbound/scan', query: { note: id } })">继续核对</GlassButton>
    </template>
  </DetailDrawer>
</template>

<script setup>
import { computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { formatBeijingDateTime } from '@/utils/datetime'
import InboundPhoto from './InboundPhoto.vue'
import InboundBatchStatus from './InboundBatchStatus.vue'
import InboundReviewLine from './InboundReviewLine.vue'
import { deliveryDate, groupLines, noteStatus } from '../inboundLabels'
import { useInboundRecognition } from '../composables/useInboundRecognition'

const props = defineProps({ id: Number })
defineEmits(['close'])
const router = useRouter()
const { note, waiting, delayed, readError, open } = useInboundRecognition()
const groups = computed(() => groupLines(note.value?.lines || []))
const actions = {
  recognize: '重新识别', confirm_delivery: '确认编号', duplicate_check: '重复核对',
  line_edit: '修改明细', line_create: '手工录入', void: '作废', confirm_batch: '确认入库批次',
}
const labels = {
  delivery_no: '工厂单据编号', reason: '原因', duplicate: '同一张单据', original: '使用原图',
  order_ref_raw: '生产单号', grade_raw: '等级', process_raw: '工艺', length_raw: '长度',
  color_raw: '颜色', weight_raw: '克重', quantity: '数量', quantity_unit: '单位', line_type: '行类型',
  writeback_enabled: '回写或对应', selected: '勾选', sku_id: 'SKU', route: '办理意图',
  batch_no: '批次号',
}
const describe = snapshot => Object.entries({ ...snapshot, ...snapshot.values, ...snapshot.decision })
  .filter(([key]) => labels[key]).map(([key, value]) => labels[key] + ' ' + (typeof value === 'boolean' ? (value ? '是' : '否') : value ?? '空')).join(' · ')
watch(() => props.id, id => open(id), { immediate: true })
</script>

<style scoped>
.note-meta { display: flex; justify-content: space-between; gap: 10px; }
.note-meta h2 { margin: 0; font-size: 18px; }
.note-meta p { margin: 4px 0; }
.detail-group { display: grid; gap: 8px; margin-top: 12px; }
.detail-group h3 { margin: 0; }
.warning { color: var(--el-color-warning); }
.entry { border-bottom: 1px solid var(--el-border-color); padding: 8px 0; }
.entry dd { margin: 4px 0 8px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
</style>
