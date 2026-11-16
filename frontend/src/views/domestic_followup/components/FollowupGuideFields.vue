<template>
  <section class="guide-fields">
    <div v-if="g.quick.value" class="quick-banner">
      <span>已切到一句话写法，没有新信息就不用多写。</span>
      <GlassButton v-if="form.raw_text?.trim() && g.template.value?.short_form" variant="link" :disabled="readonly" @click="g.useShortForm">用一句话写法替换原文</GlassButton>
    </div>
    <template v-if="!g.quick.value">
      <div v-if="showScenario" class="scenario-select">
        <el-select :model-value="form.template_code" clearable placeholder="选择跟进场景（可选）" :disabled="readonly || Boolean(form.prep_id)" @update:model-value="g.selectTemplate">
          <el-option v-for="row in g.templates.value" :key="row.code" :label="`${row.code} ${row.name}`" :value="row.code" />
        </el-select>
        <span v-if="form.prep_id">已关联准备卡，场景由准备卡确定</span>
      </div>
      <template v-if="form.template_code">
        <section v-if="showQuestions && form.template_answers?.questions?.length" class="question-section">
          <h3>准备的问题 <span>选一下就行</span></h3>
          <article v-for="(question, index) in form.template_answers.questions" :key="`${question.q}-${index}`" class="question-card">
            <p>{{ index + 1 }}. {{ question.q }}</p>
            <el-radio-group v-model="question.state" :disabled="readonly" class="question-states">
              <el-radio-button value="asked">问到了</el-radio-button><el-radio-button value="not_asked">没问到</el-radio-button><el-radio-button value="no_reply">客户没回</el-radio-button>
            </el-radio-group>
            <el-input v-if="question.state === 'asked'" v-model="question.answer" :readonly="readonly" placeholder="客户怎么说" />
          </article>
        </section>
        <el-form v-if="g.template.value" label-position="top" :disabled="readonly" class="template-fields">
          <h3>{{ g.template.value.code }} {{ g.template.value.name }} <span>字段只做提示，不拦截提交</span></h3>
          <FollowupDynamicField v-for="field in g.keyFields.value" :key="field.key" :field="field" v-model="form.template_answers.fields[field.key]" />
          <details v-if="g.moreFields.value.length"><summary>更多字段</summary><FollowupDynamicField v-for="field in g.moreFields.value" :key="field.key" :field="field" v-model="form.template_answers.fields[field.key]" /></details>
        </el-form>
        <el-alert v-else-if="readonly" type="info" :closable="false" title="模板版本暂不可读取，答案仍按原记录保留" />
      </template>
      <p v-else-if="readonly" class="uncategorized">未分类</p>
    </template>
  </section>
</template>

<script setup>
import FollowupDynamicField from './FollowupDynamicField.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useFollowupGuide } from '../composables/useFollowupGuide'
import { toRef } from 'vue'

const props = defineProps({
  form: { type: Object, required: true }, readonly: Boolean, showScenario: { type: Boolean, default: true },
  showQuestions: { type: Boolean, default: true },
})
const g = useFollowupGuide(toRef(props, 'form'))
</script>

<style scoped>
.guide-fields { display: flex; flex-direction: column; gap: 12px; }
.quick-banner, .scenario-select { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 10px 12px; border-radius: var(--radius-md); color: var(--text-secondary); background: var(--tag-neutral-bg); font-size: 12px; }
.scenario-select .el-select { min-width: 260px; flex: 1; }
.question-section, .template-fields { display: flex; flex-direction: column; gap: 10px; }
.question-section h3, .template-fields h3 { margin: 0; font-size: 14px; }
.question-section h3 span, .template-fields h3 span { margin-left: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.question-card { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-md); }
.question-card p { margin: 0; font-weight: 600; }
details summary { margin-bottom: 10px; color: var(--color-primary-text); cursor: pointer; }
.uncategorized { margin: 0; color: var(--text-secondary); }
@media (max-width: 600px) { .question-card .question-states { flex-wrap: wrap; } }
</style>
