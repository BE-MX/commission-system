<template>
  <div class="timeline">
    <ul v-if="events.length" class="rows">
      <li v-for="event in events" :key="event.event_key" class="row">
        <div class="copy">
          <div class="meta"><span class="tag">{{ timelineType(event) }}</span><span class="muted">{{ when(event) }}</span></div>
          <b>{{ timelineTitle(event) }}</b>
          <p v-if="timelineSummary(event)" class="muted">{{ timelineSummary(event) }}</p>
        </div>
        <button type="button" class="link-button" :aria-label="`查看详情：${timelineTitle(event)}`" @click="$emit('evidence', event.event_key)">查看详情</button>
      </li>
    </ul>
    <el-alert v-if="error" :title="error" type="error" :closable="false"><el-button text @click="$emit('retry')">重试</el-button></el-alert>
    <p v-if="!events.length && !loading && !error" class="muted">{{ emptyLabel }}</p>
    <el-button v-if="cursor" :loading="loading" @click="$emit('more')">加载更多</el-button>
    <p v-if="loading" class="muted" role="status">正在读取记录…</p>
  </div>
</template>

<script setup>
import { formatBeijingDate, formatBeijingShortDateTime } from '@/utils/datetime'
import { timelineSummary, timelineTitle, timelineType } from './deskController'

defineProps({
  events: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  cursor: { type: [String, Number], default: null },
  emptyLabel: { type: String, default: '暂无可见记录。' },
})
defineEmits(['evidence', 'more', 'retry'])
const when = event => event.source === 'order' ? formatBeijingDate(event.occurred_at) : formatBeijingShortDateTime(event.occurred_at)
</script>

<style src="./board.css" scoped></style>
<style scoped>
.rows { margin: 0 0 12px; padding: 0; list-style: none; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border-color); }
.copy { min-width: 0; overflow-wrap: anywhere; }
.meta { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.copy p { display: -webkit-box; margin: 2px 0 0; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.row .link-button { flex: none; min-height: 32px; }
</style>
