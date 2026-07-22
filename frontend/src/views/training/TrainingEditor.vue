<!--
  培训速递 · 四步向导编辑器（薄壳，全部 state/方法在 composables/useTrainingEditor.js）
  强引导：★分区不过校验发布按钮禁用，并逐条指出缺什么
-->
<template>
  <div class="page" v-loading="loading">
    <div class="editor-head">
      <div class="head-left">
        <GlassButton variant="link" left-icon="ArrowLeft" @click="router.back()">返回</GlassButton>
        <span class="head-title">{{ digestId ? '编辑培训速递' : '发布培训速递' }}</span>
        <el-tag v-if="status === 'published'" size="small" type="success" effect="plain">已发布</el-tag>
      </div>
      <GlassButton variant="secondary" left-icon="Document" :loading="saving" @click="saveDraft()">保存草稿</GlassButton>
    </div>

    <el-steps :active="step - 1" finish-status="success" align-center class="wizard-steps">
      <el-step v-for="t in STEP_TITLES" :key="t" :title="t" />
    </el-steps>

    <!-- ① 基本信息 -->
    <div v-show="step === 1" class="panel">
      <el-form label-position="top">
        <el-form-item label="培训名称 *">
          <el-input v-model="basic.title" maxlength="200" placeholder="例：TikTok 跨境电商 AI 投流实战营" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="培训日期 *">
            <el-date-picker v-model="basic.trained_at" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="主办机构 / 平台">
            <el-input v-model="basic.org" maxlength="120" placeholder="例：某跨境学院" />
          </el-form-item>
          <el-form-item label="讲师">
            <el-input v-model="basic.lecturer" maxlength="120" placeholder="讲师姓名" />
          </el-form-item>
        </div>
        <el-form-item label="参训人（默认是你自己，可补充同行同事）">
          <el-select v-model="basic.attendees" multiple filterable allow-create default-first-option
            placeholder="输入姓名回车添加" style="width: 100%" />
        </el-form-item>
        <el-form-item label="标签（平台 / 主题，方便同事按需检索）">
          <el-select v-model="basic.tags" multiple filterable allow-create default-first-option
            placeholder="选择或输入新标签" style="width: 100%">
            <el-option v-for="t in TAG_SUGGESTIONS" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
      </el-form>
    </div>

    <!-- ② 丢材料 + AI 提炼 -->
    <div v-show="step === 2" class="panel">
      <p class="panel-hint">把手头材料全丢进来——现场拍的 PPT 照片、PDF 讲义、钉钉闪记转写的文字、自己的零散笔记。AI 按模板起草，你只负责下一步校对。</p>
      <el-form label-position="top">
        <el-form-item label="文字材料（笔记 / 录音转写 / 群聊摘录，直接粘贴）">
          <el-input v-model="textMaterials" type="textarea" :rows="8" maxlength="60000"
            placeholder="粘贴任何文字材料。录音建议先用钉钉 AI 听记转文字再贴入。" />
        </el-form-item>
        <el-form-item label="文件材料（照片会走多模态识别，PDF 自动抽文本；PPT 请导出 PDF 或拍照）">
          <AttachFilesPanel :files="files" :attach="attach" :files-model="filesModel"
            :upload-fn="uploadFn" :remove-file="removeFile" :save-file-meta="saveFileMeta" />
        </el-form-item>
      </el-form>
      <div class="ai-box">
        <GlassButton variant="primary" left-icon="MagicStick" :loading="drafting" @click="runDraft">
          {{ drafting ? 'AI 提炼中，多模态识别约需 1~2 分钟…' : 'AI 提炼生成草稿' }}
        </GlassButton>
        <GlassButton variant="ghost" @click="step = 3">跳过，手动填写</GlassButton>
        <span v-if="draftDone" class="draft-done">已生成草稿，可再次提炼覆盖</span>
      </div>
    </div>

    <!-- ③ 逐区校对 -->
    <div v-show="step === 3" class="panel">
      <p class="panel-hint">AI 只是起草，你是把关人——尤其「可应用点」的岗位与第一步、以及「参训人点评」，必须你来拍板。</p>

      <div class="sec-block">
        <div class="sec-head"><span class="sec-title">一句话总结 ★</span><span class="sec-req">{{ summary.trim().length }}/{{ MAX_SUMMARY_CHARS }} 字</span></div>
        <el-input v-model="summary" :maxlength="MAX_SUMMARY_CHARS" show-word-limit placeholder="这场培训到底讲了什么？一句话。" />
      </div>

      <div class="sec-block">
        <div class="sec-head"><span class="sec-title">重点 ★</span><span class="sec-req">{{ MIN_HIGHLIGHTS }}~{{ MAX_HIGHLIGHTS }} 条，按重要性排</span></div>
        <div v-for="(h, i) in sections.highlights" :key="i" class="item-card">
          <div class="item-row">
            <el-input v-model="h.title" placeholder="重点一句话" maxlength="100" />
            <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="removeAt(sections.highlights, i)">删除</GlassButton>
          </div>
          <el-input v-model="h.detail" type="textarea" :rows="2" maxlength="800" placeholder="一段展开说明（可留空）" class="item-detail" />
        </div>
        <GlassButton v-if="sections.highlights.length < MAX_HIGHLIGHTS" variant="outline" left-icon="Plus" @click="addHighlight">加一条重点</GlassButton>
      </div>

      <div class="sec-block">
        <div class="sec-head"><span class="sec-title">亮点 / 新知</span><span class="sec-req">只放「和我们已知不一样」的信息</span></div>
        <div v-for="(s, i) in sections.new_insights" :key="i" class="item-row">
          <el-input v-model="sections.new_insights[i]" maxlength="300" placeholder="一条新知" />
          <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="removeAt(sections.new_insights, i)">删除</GlassButton>
        </div>
        <GlassButton variant="outline" left-icon="Plus" @click="addInsight">加一条</GlassButton>
      </div>

      <div class="sec-block">
        <div class="sec-head"><span class="sec-title">可应用点 ★</span><span class="sec-req">每条必选岗位 + 写落地第一步</span></div>
        <div v-for="(a, i) in sections.applications" :key="i" class="item-card">
          <div class="item-row">
            <el-input v-model="a.point" maxlength="300" placeholder="对我们业务可落地的点" />
            <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="removeAt(sections.applications, i)">删除</GlassButton>
          </div>
          <div class="app-grid">
            <el-select v-model="a.roles" multiple placeholder="适用岗位 *" style="width: 100%">
              <el-option v-for="r in ROLE_OPTIONS" :key="r" :label="r" :value="r" />
            </el-select>
            <el-input v-model="a.first_step" maxlength="300" placeholder="落地第一步：一个当天就能做的动作 *" />
          </div>
        </div>
        <GlassButton variant="outline" left-icon="Plus" @click="addApplication">加一条可应用点</GlassButton>
      </div>

      <div class="sec-block">
        <div class="sec-head"><span class="sec-title">方法与技巧</span><span class="sec-req">可复现的步骤 / 参数 / 话术 / 工具用法</span></div>
        <div v-for="(m, i) in sections.methods" :key="i" class="item-card">
          <div class="item-row">
            <el-input v-model="m.name" maxlength="100" placeholder="方法名" />
            <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="removeAt(sections.methods, i)">删除</GlassButton>
          </div>
          <el-input v-model="m.steps" type="textarea" :rows="3" maxlength="800" placeholder="怎么做：步骤 / 口诀 / 参数" class="item-detail" />
        </div>
        <GlassButton variant="outline" left-icon="Plus" @click="addMethod">加一条方法</GlassButton>
      </div>

      <div class="sec-block">
        <div class="sec-head"><span class="sec-title">参训人点评 ★</span><span class="sec-req">AI 不代写：值不值、哪部分水、建议谁重点看（≥{{ MIN_REVIEW_CHARS }} 字）</span></div>
        <el-input v-model="sections.review" type="textarea" :rows="3" maxlength="1000" show-word-limit
          placeholder="你的真实判断——这是同事最想看的部分" />
      </div>
    </div>

    <!-- ④ 预览发布 -->
    <div v-show="step === 4" class="panel">
      <el-alert v-if="publishProblems.length" type="warning" :closable="false" class="problems-alert">
        <template #title>还差 {{ publishProblems.length }} 项才能发布</template>
        <ul class="problem-list">
          <li v-for="(p, i) in publishProblems" :key="i" @click="step = p.includes('培训名称') || p.includes('培训日期') ? 1 : 3" class="problem-item">{{ p }}</li>
        </ul>
      </el-alert>
      <el-alert v-else type="success" :closable="false" class="problems-alert" title="校验通过，发布后将自动推送钉钉群" />

      <div class="preview">
        <h2 class="pv-title">{{ basic.title || '（未填写标题）' }}</h2>
        <div class="pv-meta">{{ basic.trained_at }} · {{ [basic.org, basic.lecturer].filter(Boolean).join(' / ') || '—' }} · 附件 {{ files.length }} 个</div>
        <p v-if="summary" class="pv-summary">{{ summary }}</p>
        <ol class="pv-list">
          <li v-for="(h, i) in sections.highlights.filter(x => x.title.trim())" :key="i">{{ h.title }}</li>
        </ol>
        <div v-for="(a, i) in sections.applications.filter(x => x.point.trim())" :key="'a' + i" class="pv-app">
          <span>{{ a.point }}</span>
          <el-tag v-for="r in a.roles" :key="r" size="small" type="warning" effect="plain">{{ r }}</el-tag>
        </div>
        <blockquote v-if="sections.review" class="pv-review">{{ sections.review }}</blockquote>
      </div>
    </div>

    <!-- 步骤导航 -->
    <div class="wizard-nav">
      <GlassButton v-if="step > 1" variant="secondary" left-icon="ArrowLeft" @click="prevStep">上一步</GlassButton>
      <span class="nav-spacer" />
      <GlassButton v-if="step < 4" variant="primary" :loading="saving" @click="nextStep">下一步</GlassButton>
      <GlassButton v-else variant="primary" left-icon="Promotion" :loading="publishing"
        :disabled="publishProblems.length > 0" @click="publish">
        {{ status === 'published' ? '更新并重新发布' : '发布并推送钉钉群' }}
      </GlassButton>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AttachFilesPanel from './components/AttachFilesPanel.vue'
import { useTrainingEditor } from './composables/useTrainingEditor'

const router = useRouter()
const {
  STEP_TITLES, ROLE_OPTIONS, TAG_SUGGESTIONS,
  MIN_HIGHLIGHTS, MAX_HIGHLIGHTS, MIN_REVIEW_CHARS, MAX_SUMMARY_CHARS,
  digestId, step, status, loading, saving, drafting, publishing, draftDone,
  basic, summary, sections, files, textMaterials, filesModel, attach,
  publishProblems,
  load, saveDraft, nextStep, prevStep, uploadFn, removeFile, saveFileMeta, runDraft, publish,
  addHighlight, addInsight, addApplication, addMethod, removeAt,
} = useTrainingEditor()

onMounted(load)
</script>

<style scoped>
.page {
  max-width: 860px;
  margin: 0 auto;
  padding: 16px 16px 80px;
}

.editor-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  gap: 12px;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.head-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.wizard-steps {
  margin-bottom: 20px;
}

.panel {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 20px 24px;
}

.panel-hint {
  margin: 0 0 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  background: var(--toolbar-bg);
  border-radius: var(--radius-md);
  padding: 10px 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0 16px;
}

.ai-box {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
  padding-top: 16px;
  border-top: 1px dashed var(--border-color);
}

.draft-done {
  font-size: 13px;
  color: var(--color-success);
}

.sec-block {
  margin-bottom: 24px;
}

.sec-block:last-child {
  margin-bottom: 0;
}

.sec-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.sec-title {
  font-weight: 600;
  color: var(--text-primary);
}

.sec-req {
  font-size: 12px;
  color: var(--text-muted);
}

.item-card {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  margin-bottom: 10px;
}

.item-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.item-row:last-child {
  margin-bottom: 0;
}

.item-detail {
  margin-top: 6px;
}

.app-grid {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(200px, 2fr);
  gap: 8px;
}

.problems-alert {
  margin-bottom: 16px;
}

.problem-list {
  margin: 6px 0 0;
  padding-left: 18px;
}

.problem-item {
  cursor: pointer;
  line-height: 1.8;
}

.problem-item:hover {
  text-decoration: underline;
}

.preview {
  border: 1px dashed var(--border-color);
  border-radius: var(--card-radius);
  padding: 20px;
}

.pv-title {
  margin: 0 0 6px;
  font-size: 20px;
  color: var(--text-primary);
}

.pv-meta {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.pv-summary {
  padding: 10px 14px;
  background: var(--color-gold-soft);
  border-left: 3px solid var(--color-primary);
  border-radius: var(--radius-sm);
  margin: 0 0 12px;
}

.pv-list {
  margin: 0 0 12px;
  padding-left: 22px;
  line-height: 1.9;
}

.pv-app {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 14px;
}

.pv-review {
  margin: 12px 0 0;
  padding-left: 14px;
  border-left: 3px solid var(--color-gold);
  color: var(--text-secondary);
  line-height: 1.7;
}

.wizard-nav {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

.nav-spacer {
  flex: 1;
}

@media (max-width: 640px) {
  .panel {
    padding: 14px;
  }

  .app-grid {
    grid-template-columns: 1fr;
  }

  .wizard-steps :deep(.el-step__title) {
    font-size: 12px;
  }
}
</style>
