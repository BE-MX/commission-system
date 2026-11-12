<template>
  <el-drawer :model-value="open" size="760" class="customer-drawer" append-to-body :with-header="false" @update:model-value="v => !v && $emit('close')" @closed="$emit('closed')">
    <div class="drawer">
      <p v-if="desk.detailLoading.value && !detail" class="loading" role="status">正在读取客户档案…</p>
      <div v-else-if="desk.detailError.value && !detail" class="empty-state"><h3>当前档案不可用</h3><p>{{ desk.detailError.value }}</p><el-button @click="retry">重试</el-button></div>
      <template v-else-if="detail">
        <header class="head">
          <div class="who">
            <span class="avatar large" aria-hidden="true">{{ initials(detail.card.name) }}</span>
            <div>
              <h2>{{ detail.card.name }}</h2>
              <p class="muted">{{ [detail.card.country, contactNames, lastTouch].filter(Boolean).join(' · ') }}</p>
            </div>
            <button type="button" class="close board-focus" aria-label="关闭客户详情" @click="$emit('close')">×</button>
          </div>
          <TagEditor :fixed-tags="detail.fixed_tags" :ai-tags="detail.ai_tags" :removed-tags="detail.removed_tags" :busy="desk.saving.value" @toggle="desk.toggleTag" />
          <div class="actions" v-permission="'client_desk:write'">
            <el-button @click="desk.open('record')">＋ 记一笔</el-button>
            <el-button @click="desk.open('grade')">修改等级</el-button>
            <el-button @click="desk.open('date')">选跟进日期</el-button>
            <el-button class="agent-button" :loading="desk.busyAnalysis.value" :disabled="desk.saving.value || detail.remaining_reanalyses === 0" @click="desk.reanalyze">
              ✦ {{ desk.busyAnalysis.value ? '分析中' : '重新分析' }}
            </el-button>
            <span class="muted">今日剩余 {{ detail.remaining_reanalyses ?? 0 }} / 3 次</span>
          </div>
          <el-alert v-if="desk.detailError.value" :title="desk.detailError.value" type="error" :closable="false" />
        </header>
        <el-tabs v-model="tab" class="tabs">
          <el-tab-pane label="概览" name="overview">
            <OverviewTab :desk="desk" :detail="detail" @evidence="desk.openEvidence" @copy="$emit('copy')" @whatsapp="$emit('whatsapp')" />
          </el-tab-pane>
          <el-tab-pane label="背调报告" name="research"><ResearchReport :report="detail.research_report" @evidence="desk.openEvidence" /></el-tab-pane>
          <el-tab-pane label="客户画像" name="profile"><ProfilePanel :detail="detail" @evidence="desk.openEvidence" /></el-tab-pane>
          <el-tab-pane label="订单" name="orders">
            <TimelineList v-if="tab === 'orders'" :events="desk.events.value" :loading="desk.timelineLoading.value" :error="desk.timelineError.value" :cursor="desk.cursor.value" empty-label="暂无已同步的有效订单。" @evidence="desk.openEvidence" @more="desk.loadTimeline(true)" @retry="desk.loadTimeline(false)" />
          </el-tab-pane>
          <el-tab-pane label="沟通记录" name="messages">
            <div v-if="tab === 'messages'" class="chips" role="group" aria-label="沟通渠道">
              <button v-for="item in messageSources" :key="item.key" type="button" class="chip board-focus" :class="{ on: desk.source.value === item.key }" @click="desk.source.value = item.key">{{ item.label }}</button>
            </div>
            <TimelineList v-if="tab === 'messages'" :events="messageEvents" :loading="desk.timelineLoading.value" :error="desk.timelineError.value" :cursor="desk.cursor.value" empty-label="暂无可见沟通记录。询盘需在 TM 资料中关联后显示。" @evidence="desk.openEvidence" @more="desk.loadTimeline(true)" @retry="desk.loadTimeline(false)" />
          </el-tab-pane>
          <el-tab-pane label="跟进与备注" name="followups">
            <section class="panel note">
              <div class="note-head"><h4>关键备注 · 仅本人</h4><button v-permission="'client_desk:write'" type="button" class="link-button" @click="desk.open('note')">编辑</button></div>
              <p>{{ desk.state.value.remark || '还没有备注。' }}</p>
              <p class="muted">下次跟进：{{ desk.state.value.next_followup_date || '未安排' }}<template v-if="desk.state.value.next_followup_remark"> · {{ desk.state.value.next_followup_remark }}</template></p>
            </section>
            <TimelineList v-if="tab === 'followups'" :events="desk.events.value" :loading="desk.timelineLoading.value" :error="desk.timelineError.value" :cursor="desk.cursor.value" empty-label="还没有手工跟进记录。" @evidence="desk.openEvidence" @more="desk.loadTimeline(true)" @retry="desk.loadTimeline(false)" />
          </el-tab-pane>
        </el-tabs>
        <footer class="sync muted">仅含方舟可见渠道<span v-for="(time, channel) in detail.sync_times || {}" :key="channel"> · {{ SYNC_LABELS[channel] || channel }} 同步于 {{ time ? formatBeijingShortDateTime(time) : '时间未知' }}</span></footer>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { formatBeijingShortDateTime } from '@/utils/datetime'
import { initials } from './boardModel'
import TagEditor from './TagEditor.vue'
import OverviewTab from './OverviewTab.vue'
import ResearchReport from './ResearchReport.vue'
import ProfilePanel from './ProfilePanel.vue'
import TimelineList from './TimelineList.vue'

const props = defineProps({ desk: { type: Object, required: true }, open: { type: Boolean, default: false } })
defineEmits(['close', 'closed', 'copy', 'whatsapp'])
const SYNC_LABELS = { customer: '客户资料', whatsapp: 'WhatsApp' }
const TAB_SOURCES = { orders: 'order', messages: 'all', followups: 'followup' }
const messageSources = [{ key: 'all', label: '全部' }, { key: 'whatsapp', label: 'WhatsApp' }, { key: 'alibaba_feed', label: '询盘' }]
const tab = ref('overview')
const detail = computed(() => props.desk.detail.value)
const contactNames = computed(() => (detail.value?.contacts || []).map(c => c.name).filter(Boolean).slice(0, 2).join('、'))
const lastTouch = computed(() => detail.value?.personal_state?.last_touch_at ? `最近接触 ${formatBeijingShortDateTime(detail.value.personal_state.last_touch_at)}` : '')
// The "all" timeline also carries orders and follow-ups; the messages tab shows conversations only.
const messageEvents = computed(() => props.desk.events.value.filter(e => ['whatsapp', 'alibaba_feed'].includes(e.source)))

watch(tab, value => {
  const wanted = TAB_SOURCES[value]
  if (wanted && props.desk.source.value !== wanted) props.desk.source.value = wanted
  else if (wanted) props.desk.loadTimeline(false)
})
watch(() => props.desk.selected.value, () => { tab.value = 'overview' })
function retry() { const id = props.desk.selected.value; if (id) props.desk.select({ company_id: id }, false) }
</script>

<style src="./board.css" scoped></style>
<style scoped>
.drawer { display: flex; flex-direction: column; min-height: 100%; font-family: var(--font-body); color: var(--text-primary); }
.loading { padding: 40px; color: var(--text-secondary); text-align: center; }
.head { display: grid; gap: 12px; margin: -20px -20px 0; padding: 22px 24px 14px; border-bottom: 1px solid var(--border-color); background: linear-gradient(160deg, var(--tag-gold-bg), var(--card-bg) 60%); }
.who { display: flex; align-items: flex-start; gap: 12px; }
.who > div { flex: 1; min-width: 0; }
.avatar.large { width: 44px; height: 44px; font-size: 15px; }
h2 { margin: 0; font: 700 22px/1.3 var(--font-display); overflow-wrap: anywhere; }
.who p { margin: 2px 0 0; }
.close { width: 34px; height: 34px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--card-bg); color: var(--text-secondary); font-size: 20px; line-height: 1; cursor: pointer; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.actions .el-button + .el-button { margin-left: 0; }
.agent-button { border-color: var(--metric-violet-bg); background: var(--metric-violet-bg); color: var(--metric-violet-ink); }
.tabs { flex: 1; margin-top: 6px; }
.chips { display: flex; gap: 6px; margin: 0 0 6px; }
.chip { padding: 3px 10px; border: 1px solid var(--border-color); border-radius: 999px; background: var(--card-bg); color: var(--text-secondary); font-size: 12px; cursor: pointer; }
.chip.on { border-color: var(--tag-gold-border); background: var(--tag-gold-bg); color: var(--tag-gold-text); }
.note { margin-bottom: 8px; }
.note-head { display: flex; justify-content: space-between; align-items: center; }
.note p { margin: 0 0 4px; white-space: pre-wrap; overflow-wrap: anywhere; }
.sync { margin-top: 18px; padding-top: 10px; border-top: 1px solid var(--border-color); }
@media (max-width: 720px) {
  .head { padding: 18px 16px 12px; }
  .actions .el-button { min-height: 38px; }
}
</style>
<style>
.el-drawer.customer-drawer { max-width: 100vw; border-radius: 16px 0 0 16px; }
@media (max-width: 720px) { .el-drawer.customer-drawer { width: 100vw !important; border-radius: 0; } }
</style>
