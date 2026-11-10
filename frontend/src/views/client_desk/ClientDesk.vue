<template>
  <main class="client-desk" :class="{ reading }">
    <header class="desk-heading"><div><div class="eyebrow">MY PRIVATE SEA · 私海助理</div><h1>我的私海工作台</h1><p>先找到该联系的人，再把每一次沟通接起来。</p></div><span class="muted">{{ today.biz_date || currentBeijingDate() }} · 仅我的私海</span></header>
    <div class="desk-grid">
      <aside class="queue">
        <div class="queue-top"><div class="tabs" role="tablist" aria-label="客户范围"><button v-for="tab in tabs" :key="tab.key" role="tab" :aria-selected="mode === tab.key" :class="{ on: mode === tab.key }" @click="mode = tab.key; filter = ''">{{ tab.label }} <small>{{ tab.key === 'unlinked' ? today.unlinked_count ?? '—' : '' }}</small></button></div>
          <el-input v-model="keyword" clearable placeholder="搜索客户、联系人或国家" aria-label="搜索本人私海" :prefix-icon="Search" />
          <div class="chips"><template v-if="mode === 'suggested'"><button v-for="item in reasons" :key="item.value" :class="{ on: filter === item.value }" @click="filter = filter === item.value ? '' : item.value">{{ item.label }} {{ reasonCount(item.value) }}</button></template><template v-else-if="mode === 'all'"><button v-for="item in grades" :key="item.value" :class="{ on: filter === item.value }" @click="filter = filter === item.value ? '' : item.value">{{ item.label }}</button></template><template v-else><button :class="{ on: !scope }" @click="scope = ''">待关联</button><button :class="{ on: scope === 'ignored' }" @click="scope = 'ignored'">已忽略</button><button :class="{ on: scope === 'linked' }" @click="scope = 'linked'">已关联</button></template></div>
        </div>
        <div class="queue-rows" ref="queueEl" aria-live="polite"><p v-if="loading" class="empty">正在读取我的私海…</p><div v-else-if="error" class="empty"><h3>暂时无法读取</h3><p>{{ error }}</p><el-button @click="loadList">重试</el-button></div><template v-else><button v-for="row in rows" :key="row.company_id || row.conversation_uid" class="customer-row" :class="{ selected: mode === 'unlinked' ? selectedChat?.conversation_uid === row.conversation_uid : selected === String(row.company_id) }" @click="select(row)"><span class="avatar">{{ initials(row.name || row.display_name) }}</span><span class="row-copy"><span class="row-title"><strong>{{ row.name || row.display_name || 'WhatsApp 会话' }}</strong><span class="tag">{{ row.grade || (mode === 'unlinked' ? 'WA' : '未分级') }}</span></span><span class="row-reason">{{ row.reason || row.reason_text || row.phone_masked || '客户档案' }}</span><span class="muted">{{ row.country || '' }} · {{ row.channel || '可见渠道' }} · {{ row.last_touch_at ? shortTime(row.last_touch_at) : '暂无可见接触时间' }}</span></span></button><div v-if="!rows.length" class="empty"><h3>{{ mode === 'suggested' ? '今天没有需要特别跟进的客户' : '暂无匹配记录' }}</h3><p>试试其他筛选，或补全客户分级。</p><el-button v-if="mode === 'suggested'" @click="mode = 'all'; filter = 'ungraded'">查看未分级客户</el-button></div></template></div>
        <footer class="queue-footer"><span>{{ total }} {{ mode === 'unlinked' ? '个会话' : '位客户' }}</span><el-pagination v-if="total > 20" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" :total="total" /></footer>
      </aside>
      <article class="customer-detail" aria-live="polite"><button class="back link" @click="back">‹ 返回队列</button><p v-if="detailLoading" class="empty">正在读取客户档案…</p><div v-else-if="detailError && !detail" class="empty"><h3>当前档案不可用</h3><p>{{ detailError }}</p><el-button @click="selected && select({ company_id: selected }, false)">重试</el-button></div>
        <template v-else-if="selectedChat"><section class="identity"><div class="eyebrow">UNLINKED CONVERSATION</div><h2>{{ selectedChat.name || selectedChat.display_name || 'WhatsApp 会话' }}</h2><p class="muted">{{ selectedChat.phone_masked || selectedChat.masked_number }} · {{ selectedChat.last_at ? shortTime(selectedChat.last_at) : '时间未知' }}</p></section><section class="section"><h3>确认会话归属</h3><p>关联前不展示聊天正文，不进入客户画像。请选择本人私海里的客户。</p><div class="actions" v-permission="'client_desk:write'"><el-button type="primary" @click="open('link')">{{ scope === 'linked' ? '更换关联客户' : '关联到客户' }}</el-button><el-button :loading="saving" @click="ignoreChat">{{ scope ? '撤销处理' : '不是客户' }}</el-button></div><el-alert v-if="detailError" :title="detailError" type="error" :closable="false" /></section></template>
        <template v-else-if="detail">
          <section class="identity"><div class="customer-heading"><span class="avatar large">{{ initials(detail.card.name) }}</span><div><h2>{{ detail.card.name }}</h2><p class="muted">{{ detail.card.country || '国别待补充' }} · {{ detail.card.source || 'OKKI 私海' }}<span v-if="detail.contacts?.length"> · {{ detail.contacts.map(c => c.name).filter(Boolean).join('、') }}</span></p></div></div><div class="identity-meta"><span>分级 <b>{{ detail.grade || '未分级' }}</b></span><button class="link" v-permission="'client_desk:write'" @click="open('grade')">修改</button><span class="muted">公司共享 · {{ detail.grade_updated_by || '人工确认' }}</span><span>下次跟进 <b>{{ state.next_followup_date || '未安排' }}</b></span><button class="link" v-permission="'client_desk:write'" @click="open('date')">选日期</button></div><p class="human"><b>关键备注</b>　{{ state.remark || '补充你掌握的客户信息' }} <button class="link" v-permission="'client_desk:write'" @click="open('note')">编辑</button><small v-if="state.updated_by_name || state.updated_by"> · {{ state.updated_by_name || state.updated_by }} 写</small></p></section>
          <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
          <section class="advice"><div class="section-line"><span class="eyebrow">✦ 今日建议</span><span class="tag gold">{{ analysisLabel(suggestion?.status) }}</span></div><h3>{{ suggestion?.reason || '先了解客户，安排下一次沟通' }}</h3><div class="cites"><button v-for="cite in suggestion?.cites || []" :key="cite.key" class="link" @click="openEvidence(cite.event_key)">{{ cite.key }} ↘</button></div><div v-if="suggestion?.check_before_reply?.length" class="guide"><b>先查什么</b><span>{{ suggestion.check_before_reply.join('；') }}</span></div><div v-if="suggestion?.strategy" class="guide"><b>怎么跟</b><span>{{ suggestion.strategy }}</span></div><p v-if="suggestion?.needs_review" class="review-note">涉及报价、库存或交期，请先核对后再发送。</p><div v-if="suggestion?.draft" class="draft"><span class="eyebrow">回复草稿</span><p>{{ suggestion.draft }}</p></div><div v-if="suggestion?.draft" class="actions"><el-button type="primary" @click="waOpen = true" :disabled="!detail.wa_targets?.length">在 WhatsApp 打开 ↗</el-button><el-button @click="copyDraft">复制草稿</el-button></div><div class="feedback actions" v-if="suggestion" v-permission="'client_desk:write'"><el-button  :type="suggestion.quality_feedback === 'useful' ? 'primary' : ''" :loading="saving" @click="feedback('useful')">{{ suggestion.quality_feedback === 'useful' ? '✓ ' : '' }}有用</el-button><el-button  :type="suggestion.quality_feedback === 'useless' ? 'primary' : ''" :disabled="saving" @click="feedback('useless')">没用</el-button><el-button  :disabled="saving" @click="open('snooze')">稍后…</el-button><el-button  :disabled="saving || !!suggestion.done_at" @click="feedback('done')">{{ suggestion.done_at ? '已跟进' : '标记已跟进' }}</el-button><span v-if="suggestion.done_source" class="muted">来源：{{ suggestion.done_source }}</span></div><div v-if="suggestion?.grade_hint?.value" class="grade-hint"><span class="tag gold">AI 建议 {{ suggestion.grade_hint.value }}</span> <span class="muted">{{ suggestion.grade_hint.reason }}</span><button class="link" v-permission="'client_desk:write'" @click="adoptGrade">采纳分级</button></div><div class="analysis-action"><button class="link" v-permission="'client_desk:write'" :disabled="saving || busyAnalysis || detail.remaining_reanalyses === 0" @click="reanalyze">{{ busyAnalysis ? '分析处理中…' : '重新分析' }}</button><small>每日最多 3 次{{ detail.remaining_reanalyses != null ? ` · 剩余 ${detail.remaining_reanalyses} 次` : '' }}</small></div></section>
          <section class="section"><div class="section-line"><h3>客户画像</h3><span class="muted">{{ state.last_analyzed_at ? shortTime(state.last_analyzed_at) : '暂无 AI 画像' }}</span></div><p class="profile-text">{{ state.brief_md || '当前仅可查看已同步的客户档案。' }}</p><div class="summary-tiles"><div><span class="muted">历史订单</span><p><b>{{ detail.orders_summary?.count ?? '—' }} 单</b><span v-if="detail.orders_summary?.amount_usd != null"> · ${{ detail.orders_summary.amount_usd }}</span></p><small v-if="detail.orders_summary?.unknown_amount_count">{{ detail.orders_summary.unknown_amount_count }} 笔金额待确认</small><p class="muted">最近下单 {{ detail.orders_summary?.last_order_at || '暂无可见记录' }}</p></div><div><span class="muted">客户背调</span><p>{{ detail.research_summary ? readable(detail.research_summary.summary || detail.research_summary) : '暂无合格背调' }}</p><button v-if="detail.research_summary?.event_key" class="link" @click="openEvidence(detail.research_summary.event_key)">展开证据 ↘</button></div></div></section>
          <section class="section timeline">
            <div class="section-line">
              <h3>时间轴</h3>
              <el-button v-permission="'client_desk:write'" @click="open('record')">＋ 记一笔</el-button>
            </div>
            <div class="chips">
              <button v-for="(label, key) in SOURCES" :key="key" :class="{ on: source === key }" @click="source = key">{{ label }}</button>
            </div>
            <ul class="timeline-list">
              <li v-for="event in events" :key="event.event_key" class="timeline-row">
                <div class="timeline-copy">
                  <div class="timeline-meta">
                    <span class="tag">{{ timelineType(event) }}</span>
                    <span class="muted">{{ event.source === 'order' ? formatBeijingDate(event.occurred_at) : shortTime(event.occurred_at) }}</span>
                  </div>
                  <b>{{ timelineTitle(event) }}</b>
                  <p v-if="timelineSummary(event)" class="muted">{{ timelineSummary(event) }}</p>
                </div>
                <button class="link" :aria-label="`查看详情：${timelineTitle(event)}`" @click="openEvidence(event.event_key)">查看详情</button>
              </li>
            </ul>
            <p v-if="!events.length && !timelineLoading" class="muted">此渠道暂无可见记录。</p>
            <el-button v-if="cursor" :loading="timelineLoading" @click="loadTimeline(true)">加载更多</el-button>
            <p v-if="timelineLoading" class="muted">正在读取时间轴…</p>
          </section>
          <footer class="detail-footer">仅含方舟可见渠道 <span v-for="(time, channel) in detail.sync_times || {}" :key="channel"> · {{ channel }} 同步于 {{ shortTime(time) || '时间未知' }}</span></footer>
        </template><div v-else class="empty detail-empty"><span class="eyebrow">YOUR CUSTOMER STORY</span><h3>从左侧选择一位客户</h3><p>建议、人工备注和每次沟通，都在同一份档案里。</p></div>
      </article>
    </div>
    <el-dialog :model-value="!!dialog" @update:model-value="v => { if (!v && !saving) dialog = '' }" :title="dialogTitles[dialog]" width="480px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" destroy-on-close><el-form label-position="top" @submit.prevent="save"><template v-if="dialog === 'note'"><el-form-item label="关键备注 · 仅本人"><el-input v-model="form.remark" type="textarea" :rows="5" maxlength="600" show-word-limit /></el-form-item></template><template v-if="dialog === 'date'"><el-form-item label="下次跟进日期（可清空）"><el-date-picker v-model="form.next_followup_date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="跟进说明"><el-input v-model="form.next_followup_remark" type="textarea" /></el-form-item></template><template v-if="dialog === 'grade'"><el-alert title="分级为公司共享信息，其他归属业务员也会看到。" :closable="false" /><el-form-item label="客户等级"><el-select v-model="form.grade"><el-option v-for="grade in detail.grade_options || []" :key="grade.value || grade" :label="grade.label || grade" :value="grade.value || grade" /></el-select></el-form-item><p v-if="!detail.grade_options?.length">等级字典不可用，请联系管理员。</p></template><template v-if="dialog === 'snooze'"><el-form-item label="稍后提醒日期"><el-date-picker v-model="form.date" value-format="YYYY-MM-DD" :disabled-date="d => formatBeijingDate(d) <= currentBeijingDate()" /></el-form-item></template><template v-if="dialog === 'record'"><el-form-item label="渠道"><el-select v-model="form.channel" @change="sampleDate"><el-option v-for="(label,key) in CHANNELS" :key="key" :label="label" :value="key" /></el-select></el-form-item><el-form-item label="跟进内容" required><el-input v-model="form.content" type="textarea" :rows="4" maxlength="4000" /></el-form-item><el-form-item label="发生时间 · 北京时间" required><el-input v-model="form.happened_at" type="datetime-local" step="1" @change="sampleDate" /></el-form-item><el-form-item label="下次跟进（选填，可清空）"><el-date-picker v-model="form.next_followup_date" value-format="YYYY-MM-DD" /></el-form-item><p v-if="form.channel === 'sample'" class="muted">寄样默认 10 个工作日后跟进，可修改或清空。</p></template><template v-if="dialog === 'link'"><el-form-item label="搜索本人私海客户"><el-input v-model="linkKeyword" @input="searchLinks" clearable /></el-form-item><el-form-item label="手动确认客户" required><el-select v-model="form.company_id" filterable><el-option v-for="customer in linkOptions" :key="customer.company_id" :label="customer.name" :value="String(customer.company_id)" /></el-select></el-form-item></template><el-alert v-if="saveError" :title="saveError" type="error" :closable="false" /><div v-if="conflict" class="conflict"><p>记录已被更新。本地输入已保留，请核对最新版本后重试。</p><pre>{{ JSON.stringify(conflict, null, 2) }}</pre><el-button @click="reloadConflict">载入最新版本号，保留我的内容</el-button></div><div class="dialog-actions"><el-button :disabled="saving" @click="dialog = ''">取消</el-button><el-button type="primary" native-type="submit" :loading="saving" :disabled="dialog === 'grade' && !detail.grade_options?.length">保存</el-button></div></el-form></el-dialog>
    <DetailDrawer v-model="evidenceOpen" :title="evidence ? `${timelineType(evidence)}详情` : '时间轴详情'">
      <p v-if="evidenceLoading" role="status">正在核验来源权限…</p>
      <el-alert v-else-if="evidenceError" :title="evidenceError" type="error" :closable="false" />
      <TimelineEventDetails v-else-if="evidence" :event="evidence" />
    </DetailDrawer>
    <el-dialog v-model="waOpen" title="确认 WhatsApp 联系目标" width="480px"><p>草稿由你核对并亲自发送；打开聊天不会标记已跟进。</p><div v-for="target in detail?.wa_targets || []" :key="target.conversation_uid" class="wa-target"><span>{{ target.name || target.display_name || target.phone_masked }}</span><el-button @click="openWhatsApp(target)">打开 ↗</el-button></div><el-alert v-if="waError" :title="waError" type="error" :closable="false" /></el-dialog>
    <el-dialog v-model="copyOpen" title="复制草稿" width="480px"><el-input :model-value="copyText" type="textarea" :rows="7" readonly aria-label="请选中并复制草稿" /></el-dialog>
  </main>
</template>
<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { currentBeijingDate, formatBeijingDate, formatBeijingShortDateTime as shortTime } from '@/utils/datetime'
import { clientDeskApi } from '@/api/clientDesk'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { msgSuccessText } from '@/utils/feedback'
import { REASON_FILTERS as reasons, CHANNELS, SOURCES, analysisLabel, safeDestination, revalidatedDraft, copyOrFallback, timelineType, timelineTitle, timelineSummary } from './deskController'
import TimelineEventDetails from './TimelineEventDetails.vue'
import { useClientDesk } from './useClientDesk'
const route = useRoute()
const desk = useClientDesk(route)
const { mode, filter, keyword, page, pageSize, total, rows, today, selected, detail, reading, loading, detailLoading, error, detailError, source, events, cursor, timelineLoading, evidence, evidenceOpen, evidenceError, evidenceLoading, dialog, form, saving, saveError, conflict, linkOptions, linkKeyword, scope, selectedChat, suggestion, state, busyAnalysis, loadList, select, loadTimeline, openEvidence, open, save, feedback, reanalyze, ignoreChat, searchLinks } = desk
const tabs = [{ key: 'suggested', label: '今日建议' }, { key: 'all', label: '全部客户' }, { key: 'unlinked', label: '未关联会话' }]
const grades = [{ value: 'grade:S,A', label: 'S / A' }, { value: 'grade:B', label: 'B' }, { value: 'ungraded', label: '未分级' }]
const dialogTitles = { note: '关键备注', date: '下次跟进', grade: '客户分级', record: '记一笔', snooze: '稍后提醒', link: '关联到我的客户' }
const queueEl = ref(null), waOpen = ref(false), waError = ref(''), copyOpen = ref(false), copyText = ref('')
watch([selected, () => suggestion.value?.id], () => { copyOpen.value = false; copyText.value = '' })
const initials = name => String(name || 'WA').split(' ').map(s => s[0]).slice(0, 2).join('').toUpperCase()
async function back() { reading.value = false; await nextTick(); queueEl.value?.querySelector('.selected')?.focus({ preventScroll: true }) }
async function copyDraft() {
  const customer = selected.value, suggestionId = suggestion.value?.id
  copyOpen.value = false
  copyText.value = ''
  try {
    // Copy is a new disclosure boundary: re-read live dependencies, including
    // TM tombstones and revoked links, rather than copying the cached draft.
    const fresh = await revalidatedDraft(clientDeskApi.customer, customer, suggestionId,
      () => selected.value === customer && String(suggestion.value?.id) === String(suggestionId))
    detail.value = fresh
    const result = await copyOrFallback(fresh.suggestion.draft, text => navigator.clipboard.writeText(text),
      () => selected.value === customer && String(suggestion.value?.id) === String(suggestionId)
        && suggestion.value?.draft === fresh.suggestion.draft)
    if (result?.copied) msgSuccessText('草稿已复制')
    else if (result) { copyText.value = result.text; copyOpen.value = true }
  } catch {
    if (selected.value === customer && String(suggestion.value?.id) === String(suggestionId)) {
      detail.value = null
      detailError.value = '草稿、资料或授权已变化，请重新查看客户资料。'
    }
  }
}
async function openWhatsApp(target) {
  waError.value = ''
  // Reserve the user-initiated tab before awaiting live authorization to avoid popup blocking.
  const popup = window.open('about:blank', '_blank')
  if (popup) popup.opener = null
  try { const result = await clientDeskApi.waOpen(selected.value, { account_uid: target.account_uid, conversation_uid: target.conversation_uid, suggestion_id: suggestion.value?.id }); const destination = safeDestination(result.url); if (!destination) throw new Error('联系目标已失效'); if (popup) { popup.document.referrerPolicy = 'no-referrer'; popup.location.replace(destination) } else window.location.assign(destination) }
  catch { popup?.close(); waError.value = '联系目标或来源已变更，请刷新客户档案后重试。' }
}
function reasonCount(code) { return (today.value.items || []).filter(item => item.rule_codes?.includes(code)).length }
function readable(value) { return typeof value === 'string' ? value : value ? JSON.stringify(value, null, 2) : '' }
function adoptGrade() { open('grade'); form.value.grade = suggestion.value.grade_hint.value; form.value.suggestion_id = suggestion.value.id }
let sampleGeneration = 0
async function sampleDate() {
  const generation = ++sampleGeneration
  if (form.value.channel !== 'sample' || !form.value.happened_at) return
  const happened = form.value.happened_at
  try { const result = await clientDeskApi.sampleDate(happened.slice(0,10)); if (generation === sampleGeneration && dialog.value === 'record' && form.value.channel === 'sample' && form.value.happened_at === happened) form.value.next_followup_date = result.date }
  catch (e) { saveError.value = '寄样跟进日期暂时无法计算，请手动选择日期。' }
}
async function reloadConflict() {
  try { const current = await clientDeskApi.customer(selected.value); if (dialog.value === 'grade') form.value.expected_grade = current.grade; else form.value.expected_version = current.personal_state.manual_version; conflict.value = null; saveError.value = '' }
  catch { saveError.value = '最新版本读取失败，你的内容已保留，请稍后重试。' }
}
onMounted(desk.init)
</script>
<style src="./clientDesk.css" scoped></style>
<style scoped>
.timeline-list { list-style: none; padding: 0; margin: 10px 0 14px; }
.timeline-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--button-border); }
.timeline-copy { min-width: 0; overflow-wrap: anywhere; }
.timeline-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.timeline-copy p { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; margin: 2px 0 0; }
.timeline-row .link { flex: none; min-height: 38px; }
</style>
