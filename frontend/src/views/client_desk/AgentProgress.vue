<template>
  <div v-if="run" class="agent panel" :class="{ busy }" role="status" aria-live="polite">
    <div class="head">
      <span class="title"><span class="spark" aria-hidden="true">✦</span>{{ title }}</span>
      <span class="muted">第 {{ run.run_seq }} 次手动分析</span>
    </div>
    <ol v-if="steps.length">
      <li v-for="(step, index) in steps" :key="index" :class="step.status">
        <span class="mark" aria-hidden="true">{{ marks[step.status] || '·' }}</span>
        <span>{{ step.label }}<template v-if="step.target"> · 订单 {{ step.target }}</template></span>
        <span class="muted">{{ statusText[step.status] || '' }}</span>
      </li>
      <li v-if="busy" class="pending"><span class="mark spinner" aria-hidden="true" /><span>{{ run.status === 'queued' ? '等待模型空闲' : '正在思考下一步' }}</span></li>
    </ol>
    <p v-else-if="busy" class="muted">{{ run.status === 'queued' ? '已排队，稍后开始读取资料。' : '正在读取客户资料…' }}</p>
    <p v-if="note" class="note">{{ note }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ run: { type: Object, default: null } })
const marks = { ok: '✓', empty: '○', rejected: '×', limit: '!' }
const statusText = { empty: '无可用资料', rejected: '超出可读范围', limit: '资料已达上限' }
const NOTES = {
  ambiguous: '模型调用结果未确认，系统不会自动重试；本次次数已计入。',
  call_uncertain: '模型调用结果未确认，系统不会自动重试；本次次数已计入。',
  validation_failed: '模型结果未通过证据与安全检查，已保留规则提醒。',
  source_changed: '分析期间资料或授权发生变化，结果未采用，请重新分析。',
  personal_state_changed: '分析期间你修改了备注或跟进日期，结果未采用，请重新分析。',
  feedback_recorded: '你已处理今天的建议，本次结果未覆盖。',
  execution_failed: '分析失败，已保留规则提醒。',
}
const busy = computed(() => ['queued', 'running'].includes(props.run?.status))
const steps = computed(() => props.run?.steps || [])
const title = computed(() => busy.value ? 'Agent 正在分析' : props.run?.status === 'succeeded' ? 'Agent 已完成分析' : 'Agent 分析未完成')
const note = computed(() => props.run?.status === 'succeeded' || busy.value ? '' : NOTES[props.run?.status] || NOTES[props.run?.error_code] || '')
</script>

<style src="./board.css" scoped></style>
<style scoped>
.agent { border-color: var(--metric-violet-bg); background: linear-gradient(145deg, var(--metric-violet-bg), var(--card-bg) 70%); }
.head { display: flex; justify-content: space-between; gap: 10px; }
.title { display: inline-flex; align-items: center; gap: 6px; color: var(--metric-violet-ink); font: 700 14px var(--font-display); }
ol { display: grid; gap: 6px; margin: 10px 0 0; padding: 0; list-style: none; }
li { display: grid; grid-template-columns: 18px 1fr auto; align-items: center; gap: 8px; font-size: 13px; }
.mark { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; background: var(--tag-success-bg); color: var(--tag-success-text); font-size: 11px; font-weight: 700; }
.empty .mark, .limit .mark { background: var(--tag-neutral-bg); color: var(--tag-neutral-text); }
.rejected .mark { background: var(--tag-danger-bg); color: var(--tag-danger-text); }
.spinner { border: 2px solid var(--metric-violet-bg); border-top-color: var(--metric-violet-ink); background: transparent; animation: spin 900ms linear infinite; }
.note { margin: 10px 0 0; color: var(--button-warning-text); font-size: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
</style>
