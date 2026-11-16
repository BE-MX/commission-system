<template>
  <div class="template-page">
    <div class="template-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
    </div>
    <header class="page-head">
      <div><h1>跟进模板</h1><p>每次保存生成新版本，历史准备卡和记录仍按当时版本展示。</p></div>
      <GlassButton variant="outline" left-icon="Refresh" :loading="t.loading.value" @click="t.load()">刷新</GlassButton>
    </header>
    <div v-loading="t.loading.value" class="template-layout">
      <nav class="template-nav lg-card is-static" aria-label="场景模板">
        <button v-for="row in t.templates.value" :key="row.code" type="button" :aria-current="row.code === t.selectedCode.value"
                @click="t.select(row.code)">
          <span class="code">{{ row.code }}</span><span>{{ row.name }}</span><small>v{{ row.version }}</small>
        </button>
      </nav>
      <main v-if="t.draft.value" class="template-editor lg-card is-static">
        <div class="editor-head">
          <div><h2>{{ t.draft.value.code }} {{ t.draft.value.name }}</h2><StatusBadge value="生效中" type="success" size="small" /></div>
          <div class="head-actions">
            <GlassButton variant="outline" left-icon="Clock" @click="t.openHistory">版本历史</GlassButton>
            <GlassButton v-permission="'domestic_followup:admin'" variant="primary" left-icon="Check" :loading="t.saving.value" @click="t.save">保存为新版本</GlassButton>
          </div>
        </div>
        <el-form label-position="top" class="editor-form">
          <el-form-item label="场景名称"><el-input v-model="t.draft.value.name" maxlength="60" /></el-form-item>
          <el-form-item label="给 AI 的场景要点"><el-input v-model="t.draft.value.guidance" type="textarea" :rows="3" maxlength="10000" /></el-form-item>
          <section class="editor-section">
            <div class="section-head"><h3>字段定义</h3><span>字段只提示，不拦截真实记录提交</span></div>
            <el-tabs v-model="fieldTab">
              <el-tab-pane :label="`录入字段（${t.draft.value.record_fields.length}）`" name="record_fields" />
              <el-tab-pane :label="`准备字段（${t.draft.value.prep_fields.length}）`" name="prep_fields" />
            </el-tabs>
            <el-table :data="t.draft.value[fieldTab]" border class="list-table" v-sticky-scrollbar>
              <el-table-column prop="label" label="名称" min-width="140" />
              <el-table-column prop="key" label="key" min-width="130" />
              <el-table-column label="类型" min-width="110"><template #default="{ row }">{{ kindLabels[row.kind] || row.kind }}</template></el-table-column>
              <el-table-column label="展示" min-width="90"><template #default="{ row }"><el-tag :type="row.emphasis === 'key' ? 'warning' : 'info'" effect="plain">{{ row.emphasis === 'key' ? '重点' : '折叠' }}</el-tag></template></el-table-column>
              <el-table-column label="默认性质" min-width="110"><template #default="{ row }">{{ natureLabels[row.nature] || '未分类' }}</template></el-table-column>
              <el-table-column label="操作" min-width="130" fixed="right"><template #default="{ row, $index }">
                <GlassButton variant="link" @click="t.openField(fieldTab, $index)">编辑</GlassButton>
                <GlassButton variant="link" link-tone="danger" @click="t.removeField(fieldTab, $index)">删除</GlassButton>
              </template></el-table-column>
            </el-table>
            <GlassButton variant="outline" left-icon="Plus" class="add-button" @click="t.openField(fieldTab)">添加字段</GlassButton>
          </section>
          <section class="editor-section">
            <div class="section-head"><h3>时间与沟通预算</h3><span>仅用于规划，不作为绩效口径</span></div>
            <div class="param-grid">
              <el-form-item v-for="param in params" :key="param.key" :label="param.label">
                <div class="range-input"><el-input-number v-model="t.draft.value.params[param.key][0]" :min="1" :max="999" controls-position="right" class="param-number" /><span>—</span><el-input-number v-model="t.draft.value.params[param.key][1]" :min="1" :max="999" controls-position="right" class="param-number" /></div>
              </el-form-item>
            </div>
          </section>
          <section class="editor-section">
            <div class="section-head"><h3>不能补成</h3><span>命中关键词的 AI 句子会标黄并提示核实</span></div>
            <div v-for="(rule, index) in t.draft.value.avoid" :key="index" class="avoid-row">
              <el-input v-model="rule.rule" placeholder="规则，例如：客户说贵 ≠ 预算不足" />
              <el-input :model-value="rule.keywords.join('，')" placeholder="关键词，用逗号分隔" @update:model-value="value => rule.keywords = value.split(/[，,]/).map(v => v.trim()).filter(Boolean)" />
              <GlassButton variant="link" link-tone="danger" @click="t.draft.value.avoid.splice(index, 1)">删除</GlassButton>
            </div>
            <GlassButton variant="outline" left-icon="Plus" @click="t.addAvoid">添加规则</GlassButton>
          </section>
          <el-form-item label="最短写法"><el-input v-model="t.draft.value.short_form" maxlength="300" show-word-limit /></el-form-item>
        </el-form>
      </main>
    </div>

    <el-dialog v-model="t.fieldVisible.value" :title="t.fieldIndex.value >= 0 ? '编辑字段' : '添加字段'" width="480px">
      <el-form label-position="top">
        <div class="form-grid"><el-form-item label="显示名称"><el-input v-model="t.fieldForm.value.label" /></el-form-item><el-form-item label="字段 key"><el-input v-model="t.fieldForm.value.key" :disabled="t.fieldIndex.value >= 0" /></el-form-item></div>
        <div class="form-grid"><el-form-item label="类型"><el-select v-model="t.fieldForm.value.kind" class="full"><el-option v-for="(label, key) in kindLabels" :key="key" :label="label" :value="key" /></el-select></el-form-item><el-form-item label="默认性质"><el-select v-model="t.fieldForm.value.nature" class="full"><el-option v-for="(label, key) in natureLabels" :key="key" :label="label" :value="key" /></el-select></el-form-item></div>
        <el-form-item label="展示方式"><el-radio-group v-model="t.fieldForm.value.emphasis"><el-radio-button value="key">重点展开</el-radio-button><el-radio-button value="more">更多折叠</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="选项（逗号分隔，留空则自由填写）"><el-input v-model="t.fieldOptionsText.value" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="填写提示"><el-input v-model="t.fieldForm.value.hint" /></el-form-item>
      </el-form>
      <template #footer><GlassButton @click="t.fieldVisible.value = false">取消</GlassButton><GlassButton variant="primary" @click="t.saveField">确定</GlassButton></template>
    </el-dialog>

    <el-drawer v-model="t.historyVisible.value" title="模板版本历史" size="640px">
      <div class="history-layout">
        <button v-for="row in t.historyRows.value" :key="row.id" type="button" class="history-row" @click="t.previewVersion(row)">
          <strong>v{{ row.version }}</strong><span>{{ row.status === 'active' ? '生效中' : '历史版本' }}</span><small>{{ row.created_at }}</small>
        </button>
        <el-descriptions v-if="t.historyPreview.value" :title="`${t.historyPreview.value.code} · v${t.historyPreview.value.version}`" :column="1" border>
          <el-descriptions-item label="名称">{{ t.historyPreview.value.name }}</el-descriptions-item>
          <el-descriptions-item label="场景要点">{{ t.historyPreview.value.guidance || '—' }}</el-descriptions-item>
          <el-descriptions-item label="录入字段">{{ t.historyPreview.value.record_fields.map(f => f.label).join('、') || '—' }}</el-descriptions-item>
          <el-descriptions-item label="最短写法">{{ t.historyPreview.value.short_form || '—' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useFollowupTemplates } from './composables/useFollowupTemplates'

const t = useFollowupTemplates()
const fieldTab = ref('record_fields')
const kindLabels = { text: '文本', textarea: '长文本', select: '单选', multiselect: '多选', amount: '金额三件套', date: '日期', event: '事件' }
const natureLabels = { customer_said: '客户陈述', business_fact: '业务事实', assessment: '业务员判断', to_confirm: '待确认' }
const params = [
  { key: 'prep_minutes', label: '准备时长（分钟）' }, { key: 'talk_minutes', label: '通话预算（分钟）' },
  { key: 'wechat_sentences', label: '微信句数' }, { key: 'recontact_workdays', label: '再联系工作日' },
]
onMounted(() => t.load())
</script>

<style scoped>
.template-page { position: relative; min-width: 0; }
.template-aurora { inset: -24px -28px; pointer-events: none; }
.page-head, .template-layout { position: relative; z-index: 1; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.page-head h1, .editor-head h2 { margin: 0; font-size: 20px; }
.page-head p { margin: 6px 0 0; color: var(--text-secondary); }
.template-layout { display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 18px; align-items: start; }
.template-nav { display: flex; flex-direction: column; gap: 4px; padding: 10px; }
.template-nav button { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 11px 10px; border: 0; border-radius: var(--radius-sm); color: var(--text-primary); background: transparent; text-align: left; cursor: pointer; transition: background-color 140ms ease, color 140ms ease; }
.template-nav button[aria-current="true"] { color: var(--color-primary-text); background: var(--tag-gold-bg); font-weight: 600; }
.template-nav .code { color: var(--color-primary-text); font-size: 12px; font-weight: 700; }
.template-nav small { color: var(--text-secondary); }
.template-editor { min-width: 0; padding: 20px; }
.editor-head, .editor-head > div, .head-actions, .section-head { display: flex; align-items: center; gap: 10px; }
.editor-head { justify-content: space-between; flex-wrap: wrap; padding-bottom: 16px; border-bottom: 1px solid var(--border-color); }
.editor-form { margin-top: 16px; }
.editor-section { margin: 4px 0 22px; }
.section-head { justify-content: space-between; flex-wrap: wrap; margin-bottom: 10px; }
.section-head h3 { margin: 0; font-size: 15px; }
.section-head span { color: var(--text-secondary); font-size: 12px; }
.add-button { margin-top: 10px; }
.param-grid, .form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.range-input { display: flex; align-items: center; gap: 8px; width: 100%; }
.range-input .param-number { width: 110px; }
.avoid-row { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) auto; gap: 8px; margin-bottom: 8px; }
.full { width: 100%; }
.history-layout { display: flex; flex-direction: column; gap: 10px; }
.history-row { display: grid; grid-template-columns: 50px 1fr auto; gap: 8px; padding: 10px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: var(--dash-glass-bg); cursor: pointer; }
.history-row small { color: var(--text-secondary); }
@media (max-width: 900px) { .template-layout { grid-template-columns: 1fr; } .template-nav { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .template-editor { padding: 14px; } .param-grid, .form-grid, .avoid-row { grid-template-columns: 1fr; } .head-actions { width: 100%; } .head-actions :deep(button) { flex: 1; min-height: 44px; } }
</style>
