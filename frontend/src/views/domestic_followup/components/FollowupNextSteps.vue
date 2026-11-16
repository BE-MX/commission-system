<template>
  <section class="next-steps">
    <div class="section-head"><h3>下一步 <span>勾选的会生成待办</span></h3><GlassButton variant="link" left-icon="Plus" @click="addStep">添加</GlassButton></div>
    <el-empty v-if="!rows.length" description="暂无下一步，可不安排或手动添加" :image-size="56" />
    <article v-for="(row, index) in rows" :key="row.step_key" class="step-card" :class="{ selected: row.selected }">
      <el-checkbox :model-value="row.selected" aria-label="采纳下一步" @change="value => selectRow(index, value)" />
      <div class="step-content">
        <el-input v-if="row.custom" v-model="row.text" maxlength="500" placeholder="要做什么" />
        <p v-else class="step-text">{{ row.text }}</p>
        <div class="step-meta"><el-tag size="small" effect="plain">{{ basisLabels[row.basis] || 'AI 建议' }}</el-tag><span v-if="row.trigger === 'event'">事件：{{ row.event || '待补充' }}</span><span v-if="row.done_criteria">完成标准：{{ row.done_criteria }}</span></div>
        <p v-if="row.commitment_advice && !row.selected" class="advice">原文里你已向客户承诺，建议采纳</p>
        <details v-if="row.source?.excerpt" class="source"><summary>{{ row.source.label || '出处待核' }}</summary><blockquote>{{ row.source.kind === 'attachment' ? `截图 ${Number(row.source.attachment_index) + 1} 转写：` : '原文：' }}「{{ row.source.excerpt }}」</blockquote></details>
        <p v-if="row.owner === 'named' && !hasResponsibility" class="advice">建议由 {{ row.owner_hint || '他人' }} 承办；当前客户无跟进责任，已降为「我」，请转告对方</p>
        <div v-if="row.selected" class="step-editor">
          <el-date-picker v-model="row.due_date" type="date" value-format="YYYY-MM-DD" :placeholder="row.trigger === 'event' ? '选择核实日期' : '选择日期'" />
          <el-select v-model="row.method" clearable placeholder="方式"><el-option v-for="value in channels" :key="value" :value="value" :label="value" /></el-select>
          <el-select v-if="hasResponsibility" v-model="row.assignee_user_id" clearable placeholder="我">
            <el-option label="我" :value="null" /><el-option v-for="person in assignees" :key="person.user_id" :label="person.name" :value="person.user_id" />
          </el-select>
        </div>
        <div v-if="row.selected" class="primary-row">
          <el-radio :model-value="Boolean(row.is_primary)" class="primary-radio" @change="selectPrimary(index)">主下一步</el-radio>
          <el-select v-if="hasResponsibility && row.is_primary" v-model="row.plan_purpose" placeholder="计划用途（必选）" class="purpose">
            <el-option label="开发" value="development" /><el-option label="维护" value="maintenance" /><el-option label="其他" value="other" />
          </el-select>
          <span class="task-kind">{{ row.is_primary ? '→ 约定跟进' : '→ 行动' }}</span>
          <GlassButton v-if="row.custom" variant="link" link-tone="danger" @click="removeRow(index)">删除</GlassButton>
        </div>
        <p v-if="row.selected && !row.due_date" class="missing">请选择{{ row.trigger === 'event' ? '核实' : '' }}日期，否则不能提交</p>
      </div>
    </article>
    <div v-if="!validation.primary" class="disposition">
      <p>不安排下一步的话，现在是什么状态？（选填）</p>
      <el-radio-group :model-value="disposition" @update:model-value="value => $emit('update:disposition', value)">
        <el-radio-button value="waiting_customer">等待客户</el-radio-button><el-radio-button value="paused">暂停</el-radio-button><el-radio-button value="closed">关闭</el-radio-button>
      </el-radio-group>
      <el-input :model-value="dispositionNote" maxlength="200" placeholder="一句理由，例如：客户说等顾客回店再定" @update:model-value="value => $emit('update:dispositionNote', value)" />
    </div>
    <p class="summary" :class="{ invalid: !validation.valid }">{{ validation.missingDates ? `有 ${validation.missingDates} 条下一步还没选日期` : validation.missingPurpose ? '主下一步还没选计划用途' : validation.summary }}</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { nextStepValidation, normalizeNextSteps } from '../followupNextSteps'

const props = defineProps({
  modelValue: { type: Array, default: () => [] }, hasResponsibility: Boolean,
  assignees: { type: Array, default: () => [] }, channels: { type: Array, default: () => [] },
  disposition: { type: String, default: null }, dispositionNote: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'update:disposition', 'update:dispositionNote'])
const rows = computed(() => props.modelValue)
const validation = computed(() => nextStepValidation(rows.value, props.hasResponsibility))
const basisLabels = { customer_agreed: '客户约定', our_commitment: '我方承诺', our_plan: '我方计划', ai_suggestion: 'AI 建议' }
function update(next) { emit('update:modelValue', normalizeNextSteps(next)) }
function selectRow(index, selected) { update(rows.value.map((row, i) => i === index ? { ...row, selected } : row)) }
function selectPrimary(index) { update(rows.value.map((row, i) => ({ ...row, is_primary: i === index }))) }
function removeRow(index) { update(rows.value.filter((_, i) => i !== index)) }
function addStep() {
  update([...rows.value, { step_key: `custom-${Date.now()}`, text: '', selected: true, is_primary: false, basis: 'our_plan', trigger: 'date', due_date: null, method: null, custom: true, source: { label: '业务员填写' } }])
}
</script>

<style scoped>
.next-steps { display: flex; flex-direction: column; gap: 10px; }
.section-head { display: flex; align-items: center; justify-content: space-between; }
.section-head h3 { margin: 0; font-size: 14px; }
.section-head h3 span { margin-left: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.step-card { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 8px; padding: 12px; border: 1px solid var(--border-color); border-radius: var(--radius-md); transition: border-color 120ms ease, background-color 120ms ease; }
.step-card.selected { border-color: var(--color-primary); background: var(--tag-gold-bg); }
.step-content { min-width: 0; }
.step-text { margin: 2px 0 0; font-weight: 600; line-height: 1.55; }
.step-meta { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-top: 8px; color: var(--text-secondary); font-size: 12px; }
.step-editor { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
.step-editor > :last-child:nth-child(3) { grid-column: 1 / -1; }
.primary-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 8px; }
.purpose { max-width: 170px; }
.task-kind { margin-left: auto; color: var(--color-primary-text); font-size: 12px; font-weight: 600; }
.advice, .missing { margin: 6px 0 0; color: var(--color-warning-text); font-size: 12px; }
.source { margin-top: 6px; color: var(--text-secondary); font-size: 12px; }
.source summary { cursor: pointer; }
.source blockquote { margin: 6px 0 0; padding: 6px 10px; border-left: 3px solid var(--border-color); }
.disposition { display: flex; flex-direction: column; gap: 10px; padding: 12px; border-radius: var(--radius-md); background: var(--tag-neutral-bg); }
.disposition p { margin: 0; color: var(--text-secondary); font-size: 12px; }
.summary { margin: 0; color: var(--text-secondary); font-size: 12px; }
.summary.invalid { color: var(--color-warning-text); }
@media (max-width: 600px) { .step-editor { grid-template-columns: 1fr; } .step-editor > :last-child:nth-child(3) { grid-column: auto; } .step-card .primary-radio { flex-wrap: wrap; } }
</style>
