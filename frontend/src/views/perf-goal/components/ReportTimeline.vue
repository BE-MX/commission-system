<template>
  <div class="pg-card" style="margin-bottom:0">
    <div class="pg-card-title"><h2>推送时间线</h2><span class="pg-note">最近期次</span></div>
    <div class="pg-timeline">
      <div v-for="(s, i) in items" :key="i" class="pg-tl-item">
        <span class="pg-tl-dot" :class="{ 'pg-warn': s.kind === 'warn', 'pg-next': s.kind === 'next' }"></span>
        <div class="pg-tl-body">
          <b>{{ s.title }}</b>　{{ s.text }}
          <div class="pg-tl-meta">{{ s.meta }}</div>
        </div>
      </div>
      <div v-if="!items.length" class="pg-empty">暂无推送记录</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatBeijingDateTime } from '@/utils/datetime'

const props = defineProps({
  schedule: { type: Object, default: null },
})
const items = computed(() => {
  const out = (props.schedule?.recent_slots || []).map(s => {
    const failed = (s.failed || 0) + (s.degraded || 0)
    return {
      kind: failed ? 'warn' : 'done',
      title: s.slot,
      text: failed ? `部分未送达（成功 ${s.sent ?? '—'} / 共 ${s.total ?? '—'}）` : `全部送达（${s.sent ?? s.total ?? '—'} 条）`,
      meta: [
        s.failed ? `失败 ${s.failed}` : null,
        s.degraded ? `降级群@ ${s.degraded}` : null,
        `共 ${s.total ?? '—'} 条`,
      ].filter(Boolean).join(' · '),
    }
  })
  if (props.schedule?.next_run_at) {
    out.push({
      kind: 'next',
      title: formatBeijingDateTime(props.schedule.next_run_at),
      text: '下一期 · 待推送',
      meta: '将按期末快照生成',
    })
  }
  return out
})
</script>
