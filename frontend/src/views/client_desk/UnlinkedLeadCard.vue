<template>
  <article class="lead panel" :class="{ focus: String(leads.focusId.value) === String(card.id) }" :data-thread-id="card.id">
    <header class="row1">
      <span class="tag tone-info">{{ card.channelLabel }}</span>
      <b class="name">{{ card.name }}</b>
      <span v-if="card.hint" class="muted">{{ card.hint }}</span>
      <span v-if="card.clock" class="clock" :class="{ off: !card.clock.working }">{{ card.clock.text }}</span>
      <span v-if="card.urgency" class="tag" :class="'urgency-' + card.urgency.level">紧急度 {{ card.urgency.label }}</span>
      <span class="spacer" />
      <span v-if="card.lastAt" class="muted">最后入站 {{ formatBeijingShortDateTime(card.lastAt) }}</span>
    </header>

    <template v-if="variant === 'pending'">
      <div v-if="card.analysisStale" class="actions">
        <p class="muted pending">之前的分析依据已更新。收到新的买家消息后会重新分析。</p>
        <el-button v-permission="'client_desk:write'" :disabled="leads.busyId.value === card.id" @click="leads.analyze(card.id)">重新分析</el-button>
      </div>
      <p v-else-if="card.analysisPending" class="muted pending">尚未生成分析。系统每天 06:45 扫描新入站消息。</p>
      <template v-else>
        <div class="label">一句话前情</div><p class="body">{{ card.summary || '暂无' }}</p>
        <div class="label">遗漏与下一步</div><p class="body">{{ card.nextAction || '暂无' }}</p>
        <div class="label">沟通突破点</div><p class="body">{{ card.angle || '暂无' }}</p>
        <div v-if="card.draft" class="draft">
          <pre class="draft-text">{{ card.draft }}</pre>
          <p class="muted">{{ card.draftHint }}</p>
          <p v-if="card.draftWarning" class="warn">{{ card.draftWarning }}</p>
          <el-button @click="leads.copyDraft(card.draft)">复制草稿</el-button>
        </div>
      </template>
    </template>

    <p v-else class="muted followup-line">下次跟进 {{ card.followup?.date || '未设置' }} · 承诺：{{ card.followup?.remark || '未填写' }}</p>

    <div v-if="card.match" class="match">
      <span>疑似私海客户：<b>{{ card.match.name }}</b>（{{ card.match.hint }}）</span>
      <el-button v-permission="'client_desk:write'" type="primary" :loading="leads.busyId.value === card.id" :disabled="leads.busyId.value === card.id" @click="leads.bind(card.id, card.match.companyId)">确认绑定</el-button>
    </div>

    <form v-if="leads.prospectId.value === card.id" class="prospect-form" novalidate @submit.prevent="leads.submitProspect(card.id)">
      <label class="field">
        <span>下次跟进日期</span>
        <el-date-picker v-model="leads.prospectForm.next_followup_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" aria-label="下次跟进日期" />
        <small v-if="leads.prospectErrors.value.next_followup_date" class="field-error" role="alert">{{ leads.prospectErrors.value.next_followup_date }}</small>
      </label>
      <label class="field">
        <span>跟进说明</span>
        <el-input v-model="leads.prospectForm.next_followup_remark" type="textarea" :rows="2" maxlength="300" show-word-limit placeholder="例如：周五前发实拍视频" aria-label="跟进说明" />
        <small v-if="leads.prospectErrors.value.next_followup_remark" class="field-error" role="alert">{{ leads.prospectErrors.value.next_followup_remark }}</small>
      </label>
      <div class="actions">
        <el-button type="primary" native-type="submit" :loading="leads.busyId.value === card.id" :disabled="leads.busyId.value === card.id">保存跟进</el-button>
        <el-button @click="leads.closeProspect">取消</el-button>
      </div>
    </form>

    <div class="actions">
      <el-button v-permission="'client_desk:write'" :disabled="leads.busyId.value === card.id" @click="leads.openProspect(card.id, card.followup || {})">{{ variant === 'prospect' ? '修改跟进' : '未建档先跟踪' }}</el-button>
      <el-button v-permission="'client_desk:write'" :disabled="leads.busyId.value === card.id" @click="leads.handled(card.id)">已在其他渠道处理</el-button>
      <el-button v-permission="'client_desk:write'" type="danger" plain :disabled="leads.busyId.value === card.id" @click="leads.ignore(card.id)">不是客户</el-button>
    </div>
  </article>
</template>

<script setup>
import { formatBeijingShortDateTime } from '@/utils/datetime'

defineProps({
  card: { type: Object, required: true },
  leads: { type: Object, required: true },
  variant: { type: String, default: 'pending' },
})
</script>

<style src="./board.css" scoped></style>
<style scoped>
.lead { display: grid; gap: 8px; }
.lead.focus { border-color: var(--button-primary-border); box-shadow: 0 0 0 3px var(--button-primary-soft); }
.row1 { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.name { font: 700 15px var(--font-display); }
.spacer { flex: 1; }
.clock { color: var(--tag-success-text); font-size: 12px; }
.clock.off { color: var(--text-secondary); }
.urgency-high { background: var(--tag-danger-bg); border-color: var(--tag-danger-border); color: var(--tag-danger-text); }
.urgency-medium { background: var(--tag-warning-bg); border-color: var(--tag-warning-border); color: var(--tag-warning-text); }
.urgency-low { background: var(--tag-neutral-bg); border-color: var(--tag-neutral-border); color: var(--tag-neutral-text); }
.label { color: var(--text-secondary); font-size: 12px; font-weight: 600; }
.body, .pending, .followup-line { margin: 0; line-height: 1.7; }
.draft { display: grid; gap: 6px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--tag-neutral-bg); }
.draft-text { margin: 0; white-space: pre-wrap; font: 500 13px/1.7 var(--font-body); }
.draft p { margin: 0; }
.warn { margin: 0; color: var(--tag-danger-text); font-size: 12px; font-weight: 600; }
.match { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; border-radius: 10px; background: var(--tag-gold-bg); border: 1px solid var(--tag-gold-border); color: var(--tag-gold-text); }
.prospect-form { display: grid; gap: 10px; padding: 12px; border: 1px dashed var(--border-color); border-radius: 10px; }
.field { display: grid; gap: 4px; }
.field > span { color: var(--text-secondary); font-size: 12px; }
.field-error { color: var(--button-danger-text); font-size: 12px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
