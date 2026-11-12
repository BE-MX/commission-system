<template>
  <div class="overview">
    <AgentProgress :run="desk.agentRun.value" />
    <section class="advice panel">
      <div class="line"><span class="eyebrow">✦ 今日建议</span><span class="tag tone-gold">{{ analysisLabel(suggestion?.status) }}</span></div>
      <h3>{{ suggestion?.reason || '暂无今日建议，可查看画像后安排下一次沟通' }}</h3>
      <span class="cites"><button v-for="cite in suggestion?.cites || []" :key="cite.key" type="button" class="link-button" @click="$emit('evidence', cite.event_key)">{{ cite.key }} ↘</button></span>
      <div v-if="suggestion?.check_before_reply?.length" class="guide"><b>先查什么</b><span>{{ suggestion.check_before_reply.join('；') }}</span></div>
      <div v-if="suggestion?.strategy" class="guide"><b>怎么跟</b><span>{{ suggestion.strategy }}</span></div>
      <p v-if="suggestion?.needs_review" class="review">涉及报价、库存或交期，请先核对后再发送。</p>
      <div v-if="suggestion?.draft" class="draft"><span class="eyebrow">回复草稿</span><p>{{ suggestion.draft }}</p></div>
      <div v-if="suggestion?.draft" class="actions">
        <el-button type="primary" :disabled="!detail.wa_targets?.length" @click="$emit('whatsapp')">在 WhatsApp 打开 ↗</el-button>
        <el-button @click="$emit('copy')">复制草稿</el-button>
      </div>
      <div v-if="suggestion" v-permission="'client_desk:write'" class="actions feedback">
        <el-button :type="suggestion.quality_feedback === 'useful' ? 'primary' : ''" :loading="desk.saving.value" @click="desk.feedback('useful')">{{ suggestion.quality_feedback === 'useful' ? '✓ ' : '' }}有用</el-button>
        <el-button :type="suggestion.quality_feedback === 'useless' ? 'primary' : ''" :disabled="desk.saving.value" @click="desk.feedback('useless')">没用</el-button>
        <el-button :disabled="desk.saving.value" @click="desk.open('snooze')">稍后…</el-button>
        <el-button :disabled="desk.saving.value || !!suggestion.done_at" @click="desk.feedback('done')">{{ suggestion.done_at ? '已跟进' : '标记已跟进' }}</el-button>
      </div>
      <div v-if="suggestion?.grade_hint?.value" class="grade-hint">
        <span class="tag tone-gold">AI 建议 {{ suggestion.grade_hint.value }}</span>
        <span class="muted">{{ suggestion.grade_hint.reason }}</span>
        <button v-permission="'client_desk:write'" type="button" class="link-button" @click="adoptGrade">采纳分级</button>
      </div>
    </section>
    <section class="panel">
      <div class="line"><h4>客户画像</h4><span class="muted">{{ detail.last_analyzed_at ? formatBeijingShortDateTime(detail.last_analyzed_at) : '' }}</span></div>
      <p class="text">{{ desk.state.value.brief_md || '还没有 AI 画像。' }}</p>
    </section>
    <section class="tiles">
      <div class="panel"><span class="muted">历史订单</span><b>{{ detail.orders_summary?.count ?? 0 }} 单</b><span class="muted">{{ amount }}</span></div>
      <div class="panel"><span class="muted">客户阶段</span><b>{{ detail.stage?.label || '—' }}</b><span class="muted">按订单与接触时间计算</span></div>
      <div class="panel"><span class="muted">背调</span><b>{{ detail.research_report?.status === 'ready' ? '已审核' : '无背调结果' }}</b><span class="muted">{{ detail.research_report?.verdict || '' }}</span></div>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatMoney } from '@/utils/money'
import { formatBeijingShortDateTime } from '@/utils/datetime'
import { analysisLabel } from './deskController'
import AgentProgress from './AgentProgress.vue'

const props = defineProps({ desk: { type: Object, required: true }, detail: { type: Object, required: true } })
defineEmits(['evidence', 'copy', 'whatsapp'])
const suggestion = computed(() => props.desk.suggestion.value)
const amount = computed(() => formatMoney(props.detail.orders_summary?.amount_usd, { currency: 'USD', missing: '金额待同步' }))
function adoptGrade() {
  props.desk.open('grade')
  props.desk.form.value.grade = suggestion.value.grade_hint.value
  props.desk.form.value.suggestion_id = suggestion.value.id
}
</script>

<style src="./board.css" scoped></style>
<style scoped>
.overview { display: grid; gap: 12px; }
.panel + .panel { margin-top: 0; }
.line { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.eyebrow { color: var(--button-primary-text); font: 700 11px var(--font-display); letter-spacing: 0.1em; }
.advice { border-color: var(--button-primary-border); background: linear-gradient(145deg, var(--button-primary-soft), var(--card-bg) 70%); }
.advice h3 { margin: 8px 0 4px; font: 700 17px/1.45 var(--font-display); }
.guide { display: grid; grid-template-columns: 65px 1fr; gap: 8px; margin: 8px 0; font-size: 13px; }
.guide b { color: var(--text-secondary); }
.review { color: var(--button-warning-text); font-size: 12px; }
.draft { margin: 12px 0; padding: 12px 14px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--card-bg); }
.draft p, .text { margin: 5px 0 0; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.actions .el-button + .el-button { margin-left: 0; }
.feedback { padding-top: 12px; border-top: 1px solid var(--button-primary-border); }
.grade-hint { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; }
.tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.tiles .panel { display: grid; gap: 4px; align-content: start; }
.tiles b { font: 700 17px var(--font-display); font-variant-numeric: tabular-nums; }
.tiles .muted { overflow: hidden; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
@media (max-width: 720px) { .tiles { grid-template-columns: 1fr; } }
</style>
