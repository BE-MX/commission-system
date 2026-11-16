<template>
  <section class="fact-groups">
    <div v-for="group in visibleGroups" :key="group.key" class="fact-group">
      <details open>
        <summary>{{ group.label }} <span>{{ group.rows.length }}</span></summary>
        <article v-for="row in group.rows" :key="row.index" class="fact-item">
          <el-input v-if="!readonly" :model-value="row.item.text" type="textarea" :rows="2" @update:model-value="value => updateFact(row.index, { text: value })" />
          <p v-else>{{ row.item.text }}</p>
          <div class="fact-meta">
            <el-tag v-if="row.item.speaker" size="small" effect="plain">{{ row.item.speaker }}</el-tag>
            <el-select v-if="!readonly" :model-value="row.item.nature" placeholder="未分类" @update:model-value="value => updateFact(row.index, { nature: value || null })">
              <el-option v-for="nature in natures" :key="nature.key" :label="nature.label" :value="nature.key" />
            </el-select>
            <span v-if="row.item.product_ref">{{ row.item.product_ref }}</span>
            <span>{{ row.item.source?.label || (row.item.nature ? '出处待补' : '未分类') }}</span>
          </div>
          <details v-if="row.item.source?.excerpt" class="fact-source"><summary>看出处</summary><blockquote>{{ row.item.source.kind === 'attachment' ? `截图 ${Number(row.item.source.attachment_index) + 1} 转写` : '原文' }}：「{{ row.item.source.excerpt }}」</blockquote></details>
        </article>
      </details>
    </div>
    <GlassButton v-if="!readonly" variant="link" left-icon="Plus" @click="$emit('add')">添加要点</GlassButton>

    <section v-if="!readonly && questions.length" class="clarifications">
      <h3>AI 想再确认 <span>最多 3 个，可跳过</span></h3>
      <article v-for="(question, index) in questions" :key="`${question.target_ref}-${index}`" class="clarification">
        <p>{{ question.q }}</p>
        <div v-if="question.options?.length" class="clarification-options">
          <GlassButton v-for="option in question.options" :key="option" :variant="question.answer === option ? 'primary' : 'outline'" @click="answer(question, index, option)">{{ option }}</GlassButton>
        </div>
        <el-input v-else :model-value="question.answer" placeholder="填写答案" @update:model-value="value => answer(question, index, value)" />
        <GlassButton variant="link" @click="skip(index)">跳过</GlassButton>
      </article>
    </section>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps({
  contents: { type: Array, default: () => [] }, questions: { type: Array, default: () => [] },
  nextSteps: { type: Array, default: () => [] }, readonly: Boolean,
})
const emit = defineEmits(['update:contents', 'update:questions', 'update:nextSteps', 'add'])
const natures = [
  { key: 'customer_said', label: '客户说的' }, { key: 'business_fact', label: '业务事实' },
  { key: 'assessment', label: '我的判断' }, { key: 'to_confirm', label: '待确认' },
]
const visibleGroups = computed(() => {
  const groups = [...natures, { key: null, label: '未分类' }].map(group => ({
    ...group, rows: props.contents.map((item, index) => ({ item, index })).filter(row => (row.item.nature || null) === group.key),
  }))
  return groups.filter(group => group.rows.length)
})
function updateFact(index, changes) {
  emit('update:contents', props.contents.map((row, i) => i === index ? { ...row, ...changes } : row))
}
function answer(question, index, value) {
  emit('update:questions', props.questions.map((row, i) => i === index ? { ...row, answer: value } : row))
  const ref = String(question.target_ref || '')
  const factMatch = /^(?:fact|content):(\d+)$/.exec(ref)
  if (factMatch) {
    const index = Number(factMatch[1])
    if (!props.contents[index]) return
    const nature = value.includes('客户') ? 'customer_said' : value.includes('判断') ? 'assessment'
      : value.includes('事实') ? 'business_fact' : 'to_confirm'
    updateFact(index, { nature, clarification: value })
    return
  }
  const stepKey = ref.replace(/^(?:next_steps?|step):/, '')
  const stepIndex = props.nextSteps.findIndex(row => row.step_key === stepKey)
  if (stepIndex >= 0) {
    const basis = value.includes('客户') ? 'customer_agreed' : value.includes('我') ? 'our_commitment'
      : value.includes('计划') ? 'our_plan' : 'ai_suggestion'
    emit('update:nextSteps', props.nextSteps.map((row, i) => i === stepIndex ? { ...row, basis, clarification: value } : row))
  }
}
function skip(index) { emit('update:questions', props.questions.filter((_, i) => i !== index)) }
</script>

<style scoped>
.fact-groups, .clarifications { display: flex; flex-direction: column; gap: 10px; }
.fact-group details { border: 1px solid var(--border-color); border-radius: var(--radius-md); }
.fact-group summary { padding: 10px 12px; font-weight: 600; cursor: pointer; }
.fact-group summary span { margin-left: 6px; color: var(--text-secondary); font-size: 12px; }
.fact-item { margin: 0 12px 8px; padding: 10px; border-radius: var(--radius-sm); background: var(--tag-neutral-bg); }
.fact-item > p { margin: 0; line-height: 1.6; }
.fact-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px; margin-top: 7px; color: var(--text-secondary); font-size: 12px; }
.fact-meta .el-select { width: 130px; }
.fact-source { margin-top: 6px; color: var(--text-secondary); font-size: 12px; }
.fact-source summary { padding: 0; font-weight: 400; }
.fact-source blockquote { margin: 6px 0 0; padding: 6px 10px; border-left: 3px solid var(--border-color); }
.clarifications h3 { margin: 0; font-size: 14px; }
.clarifications h3 span { margin-left: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.clarification { padding: 10px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-md); }
.clarification p { margin: 0 0 8px; font-weight: 600; }
.clarification-options { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
