<template>
  <div class="pg-dd-card">
    <div class="pg-dd-head" :style="{ background: headColor }">
      <span class="pg-dd-robot">🤖</span>
      <div class="pg-dd-app">绩效战报<small>工作通知 · {{ scopeLabel }}</small></div>
      <span class="pg-dd-time">{{ report?.slot || '' }}</span>
    </div>
    <div class="pg-dd-body">
      <h3>{{ title }}</h3>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div class="pg-dd-md" v-html="html"></div>
    </div>
    <div class="pg-dd-foot">
      <template v-if="report?.deliveries?.length">
        <span v-for="(d, i) in report.deliveries" :key="i" :class="deliveryClass(d)">
          {{ deliveryText(d) }}
        </span>
      </template>
      <span v-else>暂无投递记录</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { formatBeijingDateTime } from '@/utils/datetime'

marked.setOptions({ gfm: true, breaks: true })

const props = defineProps({
  report: { type: Object, default: null },
})
const scopeLabel = computed(() => ({ person: '业务员版', team: '组长版', company: '管理层版' }[props.report?.scope] || props.report?.scope || '报告'))
const headColor = computed(() => ({ person: 'var(--pg-dd-blue)', team: 'var(--pg-purple)', company: 'var(--pg-teal)' }[props.report?.scope] || 'var(--pg-dd-blue)'))
const title = computed(() => {
  const r = props.report
  if (!r) return '绩效战报'
  return `绩效战报 · ${r.user_name || r.team_name || '公司整体'} · ${r.slot || ''}`
})
const html = computed(() => DOMPurify.sanitize(marked.parse(props.report?.content_md || '*暂无内容*')))

const STATUS_TEXT = { sent: '已送达', failed: '失败', pending: '待发送', sending: '发送中', degraded: '降级群@', uncertain: '状态未知' }
function deliveryText(d) {
  const text = STATUS_TEXT[d.status] || d.status || '未知'
  const channel = { work_notice: '钉钉工作通知', group: '战报群', webhook: '群机器人' }[d.channel] || d.channel || '通道'
  const at = d.sent_at ? ` ${formatBeijingDateTime(d.sent_at)}` : ''
  const retry = d.attempts > 1 ? `（第 ${d.attempts} 次）` : ''
  return `${d.status === 'sent' ? '✓' : '⚠'} ${channel} · ${text}${retry}${at}`
}
const deliveryClass = d => (d.status === 'sent' ? 'pg-ok' : 'pg-warn')
</script>
