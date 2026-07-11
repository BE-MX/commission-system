<template>
  <div class="insight-page case-page">
    <!-- 工具栏 -->
    <div class="toolbar-card">
      <div class="toolbar-left">
        <el-input
          v-model="search"
          placeholder="搜索标题 / 客户 / 分享人..."
          :prefix-icon="Search"
          clearable
          @keyup.enter="reload"
          style="width: 240px"
        />
        <el-select v-model="tagFilter" placeholder="全部标签" style="width: 140px">
          <el-option label="全部标签" value="all" />
          <el-option v-for="t in TAGS" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="sortBy" style="width: 130px">
          <el-option label="最新分享" value="date" />
          <el-option label="最多认可" value="likes" />
        </el-select>
        <el-button-group class="view-toggle">
          <el-button :type="viewMode === 'grid' ? 'primary' : ''" @click="viewMode = 'grid'">卡片</el-button>
          <el-button :type="viewMode === 'list' ? 'primary' : ''" @click="viewMode = 'list'">列表</el-button>
        </el-button-group>
      </div>
      <div class="toolbar-right">
        <GlassButton v-any-permission="['insight_case:write', 'insight:admin']" variant="primary" left-icon="Plus" @click="openAddDialog">添加案例</GlassButton>
      </div>
    </div>

    <div v-loading="loading" class="cases-area">
      <el-empty v-if="!loading && cases.length === 0" description="暂无案例" :image-size="80">
        <p class="empty-tip">业务员可分享谈判技巧、客户开发、纠纷处理等成功经验</p>
        <GlassButton v-any-permission="['insight_case:write', 'insight:admin']" variant="primary" left-icon="Plus" @click="openAddDialog">添加第一个案例</GlassButton>
      </el-empty>

      <!-- 卡片网格 -->
      <div v-else-if="viewMode === 'grid'" class="card-grid">
        <article
          v-for="c in cases"
          :key="c.id"
          class="case-card"
          @click="openDetail(c)"
        >
          <div class="card-head-row">
            <div class="card-tags">
              <el-tag v-for="t in (c.tags || []).slice(0, 3)" :key="t" size="small" effect="light" type="info">{{ t }}</el-tag>
            </div>
            <span class="card-date">{{ c.share_date || formatDateOnly(c.created_at) }}</span>
          </div>
          <h4 class="card-title">{{ c.title }}</h4>
          <p v-if="c.customer_name" class="card-customer">客户: {{ c.customer_name }}</p>
          <p class="card-scenario">{{ c.scenario }}</p>
          <div class="card-foot">
            <span class="card-author">{{ c.share_person || '匿名' }}</span>
            <div class="card-actions">
              <span v-if="(c.attachments || []).length" class="atc-count"><el-icon><Paperclip /></el-icon>{{ c.attachments.length }}</span>
              <button class="like-btn" :class="{ liked: localLikes[c.id] }" @click.stop="toggleLike(c)">
                <el-icon><Star v-if="!localLikes[c.id]" /><StarFilled v-else /></el-icon>
                <span>{{ c.like_count || 0 }}</span>
              </button>
              <!-- 编辑/删除 -->
              <template v-if="canEdit(c)">
                <el-button link type="primary" size="small" :icon="Edit" @click.stop="openEdit(c)">编辑</el-button>
                <el-button link type="danger" size="small" :icon="Delete" @click.stop="handleDelete(c)">删除</el-button>
              </template>
            </div>
          </div>
        </article>
      </div>

      <!-- 列表视图 -->
      <div v-else class="list-view">
        <div
          v-for="c in cases"
          :key="c.id"
          class="list-item"
          :class="{ active: detailVisible && currentCase && currentCase.id === c.id }"
          @click="openDetail(c)"
        >
          <div class="list-meta">
            <div class="card-tags">
              <el-tag v-for="t in (c.tags || []).slice(0, 3)" :key="t" size="small" effect="light" type="info">{{ t }}</el-tag>
            </div>
            <span class="card-date">{{ c.share_date || formatDateOnly(c.created_at) }}</span>
          </div>
          <h4 class="card-title">{{ c.title }}</h4>
          <p class="card-customer">客户: {{ c.customer_name || '—' }} · 分享人: {{ c.share_person || '匿名' }}</p>
          <div v-if="canEdit(c)" class="list-actions" @click.stop>
            <el-button link type="primary" size="small" :icon="Edit" @click="openEdit(c)">编辑</el-button>
            <el-button link type="danger" size="small" :icon="Delete" @click="handleDelete(c)">删除</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 详情 Drawer -->
    <el-drawer v-model="detailVisible" :size="720" direction="rtl" :with-header="false">
      <div v-if="currentCase" class="case-detail">
        <div class="detail-header">
          <div class="detail-tags">
            <el-tag v-for="t in (currentCase.tags || [])" :key="t" size="small" effect="light" type="info">{{ t }}</el-tag>
          </div>
          <div class="detail-actions">
            <button class="like-btn" :class="{ liked: localLikes[currentCase.id] }" @click="toggleLike(currentCase)">
              <el-icon><Star v-if="!localLikes[currentCase.id]" /><StarFilled v-else /></el-icon>
              <span>{{ currentCase.like_count || 0 }} 认可</span>
            </button>
            <template v-if="canEdit(currentCase)">
              <el-button link type="primary" :icon="Edit" @click="openEditFromDetail">编辑</el-button>
              <el-button link type="danger" :icon="Delete" @click="deleteCurrentCase">删除</el-button>
            </template>
            <el-button link :icon="Close" @click="detailVisible = false" />
          </div>
        </div>
        <h2 class="detail-title">{{ currentCase.title }}</h2>

        <!-- 基本信息 -->
        <div class="detail-section info-section">
          <table class="info-table">
            <tr><td>分享人</td><td><strong>{{ currentCase.share_person }}</strong></td><td>日期</td><td>{{ currentCase.share_date || formatDateOnly(currentCase.created_at) }}</td></tr>
            <tr><td>客户</td><td>{{ currentCase.customer_name || '—' }}</td><td>国家</td><td>{{ currentCase.customer_country || '—' }}</td></tr>
            <tr><td>客户类型</td><td>{{ currentCase.customer_type || '—' }}</td><td>沟通渠道</td><td>{{ currentCase.communication_channel || '—' }}</td></tr>
            <tr><td>沟通时段</td><td>{{ currentCase.communication_period || '—' }}</td><td>总回合</td><td>{{ currentCase.total_rounds || '—' }}</td></tr>
            <tr><td>最终结果</td><td><el-tag :type="resultTagType(currentCase.final_result)" size="small">{{ currentCase.final_result || '—' }}</el-tag></td><td>背调</td><td>{{ currentCase.background_check_status || '—' }}</td></tr>
          </table>
        </div>

        <!-- 场景背景 -->
        <div class="detail-section section-scenario">
          <h5><el-icon><Comment /></el-icon> 场景背景</h5>
          <p>{{ currentCase.scenario || '—' }}</p>
        </div>

        <!-- 做了什么 / 结果 -->
        <div class="detail-section section-action">
          <h5><el-icon><Operation /></el-icon> 做了什么</h5>
          <p>{{ currentCase.what_was_done || '—' }}</p>
        </div>
        <div class="detail-section section-result">
          <h5><el-icon><CircleCheck /></el-icon> 结果</h5>
          <p>{{ currentCase.result || '—' }}</p>
        </div>

        <!-- 六维度评分 -->
        <div v-if="currentCase.dimension_scores" class="detail-section">
          <h5><el-icon><Histogram /></el-icon> 六维度综合评分</h5>
          <div class="dimension-grid">
            <div v-for="(item, key) in dimensionMap" :key="key" class="dimension-card">
              <div class="dimension-name">{{ item.label }}</div>
              <div class="dimension-score">{{ currentCase.dimension_scores?.[key]?.score || '—' }}</div>
              <div class="dimension-comment">{{ currentCase.dimension_scores?.[key]?.comment || '' }}</div>
            </div>
            <div class="dimension-card overall">
              <div class="dimension-name">综合得分</div>
              <div class="dimension-score">{{ currentCase.dimension_scores?.overall || '—' }}</div>
            </div>
          </div>
        </div>

        <!-- 回合拆解 -->
        <div v-if="currentCase.rounds_analysis?.length" class="detail-section">
          <h5><el-icon><ChatDotRound /></el-icon> 回合拆解</h5>
          <div class="round-list">
            <div v-for="r in currentCase.rounds_analysis" :key="r.round_no" class="round-item">
              <div class="round-head">
                <span class="round-no">{{ r.round_no }}</span>
                <span class="round-time">{{ r.time }}</span>
                <el-tag size="small" type="info">{{ r.customer_action }}</el-tag>
                <el-rate :model-value="r.score" disabled :max="5" />
              </div>
              <p class="round-summary">{{ r.summary }}</p>
              <p v-if="r.comment" class="round-comment">{{ r.comment }}</p>
            </div>
          </div>
        </div>

        <!-- 关键话术 -->
        <div v-if="currentCase.golden_phrases?.length || currentCase.red_flags?.length" class="detail-section">
          <h5><el-icon><ChatLineRound /></el-icon> 关键话术</h5>
          <div v-if="currentCase.golden_phrases?.length" class="phrase-block">
            <div class="phrase-label golden">亮点话术 (Golden Phrases)</div>
            <div v-for="(p, i) in currentCase.golden_phrases" :key="i" class="phrase-item golden-item">
              <span class="phrase-scene">[{{ p.scene }}]</span>
              <q>{{ p.phrase }}</q>
              <span class="phrase-why">— {{ p.why }}</span>
            </div>
          </div>
          <div v-if="currentCase.red_flags?.length" class="phrase-block">
            <div class="phrase-label red">问题话术 (Red Flags)</div>
            <div v-for="(p, i) in currentCase.red_flags" :key="i" class="phrase-item red-item">
              <span class="phrase-scene">[{{ p.issue_type }}]</span>
              <q>{{ p.phrase }}</q>
              <span class="phrase-why">问题: {{ p.problem }} → 修正: {{ p.suggestion }}</span>
            </div>
          </div>
        </div>

        <!-- 核心亮点 -->
        <div v-if="currentCase.core_strengths?.length" class="detail-section section-highlights">
          <h5><el-icon><MagicStick /></el-icon> 核心亮点</h5>
          <ul>
            <li v-for="(h, i) in currentCase.core_strengths" :key="i">{{ h }}</li>
          </ul>
        </div>

        <!-- 结果归因 -->
        <div v-if="currentCase.result_analysis?.length" class="detail-section">
          <h5><el-icon><TrendCharts /></el-icon> 结果归因</h5>
          <div v-for="(r, i) in currentCase.result_analysis" :key="i" class="result-item">
            <span class="result-factor">{{ r.factor }}</span>
            <span class="result-evidence">{{ r.evidence }}</span>
          </div>
        </div>

        <!-- 不足与优化 -->
        <div v-if="currentCase.improvements?.length" class="detail-section">
          <h5><el-icon><WarnTriangleFilled /></el-icon> 不足与优化方向</h5>
          <table class="improve-table">
            <thead><tr><th>优先级</th><th>问题</th><th>影响</th><th>修正方案</th><th>预期收益</th></tr></thead>
            <tbody>
              <tr v-for="(imp, i) in currentCase.improvements" :key="i">
                <td><span class="priority-tag">{{ imp.priority }}</span></td>
                <td>{{ imp.problem }}</td>
                <td>{{ imp.impact }}</td>
                <td>{{ imp.fix }}</td>
                <td>{{ imp.benefit }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 下一步行动 -->
        <div v-if="currentCase.next_actions?.length" class="detail-section">
          <h5><el-icon><List /></el-icon> 下一步行动清单</h5>
          <div class="action-list">
            <div v-for="(a, i) in currentCase.next_actions" :key="i" class="action-item">
              <span class="priority-tag">{{ a.priority }}</span>
              <span class="action-text">{{ a.action }}</span>
              <span v-if="a.owner" class="action-owner">→ {{ a.owner }}</span>
              <span v-if="a.deadline" class="action-deadline">(截止: {{ a.deadline }})</span>
            </div>
          </div>
        </div>

        <!-- AI 原始输出 vs 用户评价修正 -->
        <div v-if="currentCase.ai_draft || currentCase.user_corrections" class="detail-section section-corrections">
          <h5><el-icon><Cpu /></el-icon> AI 整理 vs 评价修正</h5>
          <el-collapse>
            <el-collapse-item title="AI 原始输出">
              <pre class="json-preview">{{ JSON.stringify(currentCase.ai_draft, null, 2) }}</pre>
            </el-collapse-item>
            <el-collapse-item v-if="currentCase.user_corrections" title="用户评价修正">
              <div v-for="(v, k) in currentCase.user_corrections" :key="k" class="correction-item">
                <div class="correction-key">{{ correctionLabel(k) }}</div>
                <div class="correction-val">{{ v }}</div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>

        <!-- 原始内容 -->
        <div v-if="currentCase.original_content" class="detail-section">
          <h5><el-icon><Document /></el-icon> 原始内容</h5>
          <pre class="raw-text">{{ currentCase.original_content }}</pre>
        </div>
      </div>
    </el-drawer>

    <!-- 添加/编辑 Dialog -->
    <el-dialog v-model="formDialogVisible" :title="formMode === 'edit' ? '编辑案例' : '添加案例'" width="720px" :close-on-click-modal="false" destroy-on-close>
      <el-tabs v-if="formMode === 'add'" v-model="addTab">
        <el-tab-pane label="表单填写" name="manual">
          <CaseForm v-model="formData" :is-edit="false" />
        </el-tab-pane>
        <el-tab-pane label="文本粘贴(AI 整理)" name="text">
          <el-form>
            <el-form-item label="原始文本">
              <el-input v-model="aiText" type="textarea" :rows="10" placeholder="粘贴聊天记录 / 邮件往来 / 电话纪要等。AI 将自动整理为案例字段,你确认后发布。" />
            </el-form-item>
            <el-form-item label="分享人">
              <el-input v-model="aiSharePerson" placeholder="留空将使用当前用户" />
            </el-form-item>
            <el-form-item label="分享日期">
              <el-date-picker v-model="aiShareDate" type="date" value-format="YYYY-MM-DD" placeholder="默认今日" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="截图上传(OCR + AI)" name="screenshot">
          <el-upload class="screenshot-upload" drag :auto-upload="false" :on-change="handleFileChange" :limit="1" accept=".png,.jpg,.jpeg,.webp,.gif">
            <el-icon class="el-icon--upload"><Upload /></el-icon>
            <div class="el-upload__text">将图片拖拽到此处,或<em>点击上传</em></div>
            <template #tip><div class="el-upload__tip">支持 PNG / JPG / WEBP / GIF,最大 5MB</div></template>
          </el-upload>
          <el-form style="margin-top: 16px">
            <el-form-item label="分享人"><el-input v-model="aiSharePerson" placeholder="留空将使用当前用户" /></el-form-item>
            <el-form-item label="分享日期"><el-date-picker v-model="aiShareDate" type="date" value-format="YYYY-MM-DD" placeholder="默认今日" /></el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <CaseForm v-else v-model="formData" :is-edit="true" />

      <template #footer>
        <GlassButton variant="ghost" @click="formDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="submitting" @click="submitCase">{{ formMode === 'edit' ? '保存' : submitButtonText }}</GlassButton>
      </template>
    </el-dialog>

    <!-- AI 草稿确认 Dialog -->
    <el-dialog v-model="draftDialogVisible" title="AI 整理结果 - 请确认并评价修正" width="780px" :close-on-click-modal="false" class="draft-dialog">
      <el-alert v-if="draftCase && draftCase.error_msg" :title="draftCase.error_msg" type="warning" show-icon :closable="false" style="margin-bottom: 12px" />

      <div v-if="draftCase" class="draft-form">
        <!-- 基本信息 -->
        <div class="draft-group">
          <h4>基本信息</h4>
          <DraftField label="标题" v-model="draftCase.title" v-model:correction="draftCorrections.title" />
          <DraftField label="客户名称" v-model="draftCase.customer_name" v-model:correction="draftCorrections.customer_name" />
          <DraftField label="客户国家" v-model="draftCase.customer_country" v-model:correction="draftCorrections.customer_country" />
          <DraftField label="客户类型" v-model="draftCase.customer_type" v-model:correction="draftCorrections.customer_type" />
          <DraftField label="沟通渠道" v-model="draftCase.communication_channel" v-model:correction="draftCorrections.communication_channel" />
          <DraftField label="沟通时段" v-model="draftCase.communication_period" v-model:correction="draftCorrections.communication_period" />
          <DraftField label="总回合数" v-model="draftCase.total_rounds" v-model:correction="draftCorrections.total_rounds" />
          <DraftField label="最终结果" v-model="draftCase.final_result" v-model:correction="draftCorrections.final_result" />
        </div>

        <!-- 场景与过程 -->
        <div class="draft-group">
          <h4>场景与过程</h4>
          <DraftField label="场景背景" v-model="draftCase.scenario" type="textarea" :rows="3" v-model:correction="draftCorrections.scenario" />
          <DraftField label="做了什么" v-model="draftCase.what_was_done" type="textarea" :rows="4" v-model:correction="draftCorrections.what_was_done" />
          <DraftField label="结果" v-model="draftCase.result" type="textarea" :rows="2" v-model:correction="draftCorrections.result" />
        </div>

        <!-- 六维度评分 -->
        <div class="draft-group">
          <h4>六维度评分</h4>
          <DraftField label="响应时效" v-model="draftCase.dimension_scores.response_speed.score" v-model:correction="draftCorrections['dimension_scores.response_speed']" />
          <DraftField label="话术专业度" v-model="draftCase.dimension_scores.talk_track_quality.score" v-model:correction="draftCorrections['dimension_scores.talk_track_quality']" />
          <DraftField label="需求匹配度" v-model="draftCase.dimension_scores.needs_alignment.score" v-model:correction="draftCorrections['dimension_scores.needs_alignment']" />
          <DraftField label="谈判推进力" v-model="draftCase.dimension_scores.deal_momentum.score" v-model:correction="draftCorrections['dimension_scores.deal_momentum']" />
          <DraftField label="情感连接度" v-model="draftCase.dimension_scores.emotional_engagement.score" v-model:correction="draftCorrections['dimension_scores.emotional_engagement']" />
          <DraftField label="合规与风控" v-model="draftCase.dimension_scores.compliance_risk.score" v-model:correction="draftCorrections['dimension_scores.compliance_risk']" />
        </div>

        <!-- 标签 -->
        <div class="draft-group">
          <h4>标签</h4>
          <el-form-item label="标签">
            <el-checkbox-group v-model="draftTagsArr">
              <el-checkbox v-for="t in TAGS" :key="t" :value="t" :label="t" />
            </el-checkbox-group>
          </el-form-item>
        </div>
      </div>

      <template #footer>
        <GlassButton variant="ghost" @click="draftDialogVisible = false">稍后处理</GlassButton>
        <GlassButton variant="primary" :loading="publishing" @click="confirmPublishDraft">确认发布</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import {
  Search, Plus, Star, StarFilled, Paperclip, Comment, Operation,
  CircleCheck, MagicStick, ChatLineRound, ChatDotRound, PictureFilled, Document,
  Delete, Close, Upload, Edit, Histogram, TrendCharts, WarnTriangleFilled, List, Cpu,
} from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import CaseForm from './CaseForm.vue'
import DraftField from './DraftField.vue'

import { useCaseLibrary, TAGS, dimensionMap, resultTagType, correctionLabel, formatDateOnly } from './composables/useCaseLibrary'

const {
  cases, loading, search, tagFilter, sortBy, viewMode, localLikes,
  detailVisible, currentCase,
  formDialogVisible, formMode, addTab, submitting,
  formData,
  aiText, aiSharePerson, aiShareDate, aiFile,
  draftDialogVisible, draftCase, draftTagsArr, draftCorrections, publishing,
  submitButtonText,
  reload, openDetail, canEdit,
  openAddDialog, openEdit, openEditFromDetail,
  handleFileChange, submitCase,
  confirmPublishDraft,
  toggleLike, handleDelete, deleteCurrentCase,
} = useCaseLibrary()
</script>

<style scoped>
.case-page { display: flex; flex-direction: column; gap: 16px; }

.toolbar-card {
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 12px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.toolbar-right { display: flex; align-items: center; gap: 8px; }

.cases-area { min-height: 300px; }

.empty-tip {
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  margin: 8px 0 12px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.case-card {
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.case-card:hover {
  border-color: var(--color-gold, #d4af6e);
  box-shadow: 0 4px 14px rgba(176, 141, 79, 0.08);
  transform: translateY(-1px);
}

.card-head-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.card-tags { display: flex; gap: 4px; flex-wrap: wrap; }

.card-date {
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
  flex-shrink: 0;
}

.card-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #1a1a2e);
  margin: 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-customer {
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  margin: 0;
}

.card-scenario {
  font-size: 12px;
  color: var(--text-secondary, #4a5568);
  line-height: 1.6;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  border-top: 1px solid var(--border-color, #f0ece5);
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
}

.card-actions { display: flex; align-items: center; gap: 8px; }

.atc-count { display: inline-flex; align-items: center; gap: 3px; }

.like-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
  padding: 2px 6px;
  border-radius: 6px;
  transition: all 0.15s;
}

.like-btn:hover { background: #fafbfe; }
.like-btn.liked { color: #ef4444; }

.list-view { display: flex; flex-direction: column; gap: 8px; }

.list-item {
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 10px;
  padding: 12px 16px;
  cursor: pointer;
  transition: all 0.15s;
}

.list-item:hover { border-color: var(--color-gold, #d4af6e); }
.list-item.active { border-color: var(--color-gold, #d4af6e); background: rgba(212, 175, 110, 0.04); }

.list-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.list-actions { display: flex; gap: 8px; margin-top: 8px; }

/* Detail */
.case-detail { padding: 24px; height: 100%; overflow-y: auto; }

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.detail-tags { display: flex; gap: 6px; flex-wrap: wrap; }

.detail-actions { display: flex; align-items: center; gap: 8px; }

.detail-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary, #1a1a2e);
  margin: 0 0 8px;
}

.detail-section { margin-bottom: 18px; }

.detail-section h5 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
  margin: 0 0 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.detail-section p {
  font-size: 13px;
  color: var(--text-secondary, #4a5568);
  line-height: 1.7;
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.info-section { margin-bottom: 14px; }
.info-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.info-table td { padding: 4px 8px; border-bottom: 1px solid var(--border-color, #f0ece5); }
.info-table td:first-child { color: var(--text-tertiary, #8b95a5); width: 70px; }
.info-table td:nth-child(3) { color: var(--text-tertiary, #8b95a5); width: 70px; padding-left: 16px; }

.section-scenario p {
  background: #fef9f0;
  border-left: 3px solid var(--color-gold, #d4af6e);
  padding: 12px 14px;
  border-radius: 0 8px 8px 0;
}

.section-action p {
  background: #fafbfe;
  border: 1px solid var(--border-color, #e5dfd6);
  padding: 12px 14px;
  border-radius: 8px;
}

.section-result p {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #047857;
  padding: 12px 14px;
  border-radius: 8px;
}

.section-highlights ul { list-style: none; padding: 0; margin: 0; }
.section-highlights li {
  font-size: 13px;
  color: var(--text-secondary, #4a5568);
  padding: 6px 0 6px 16px;
  position: relative;
}
.section-highlights li::before {
  content: '★';
  position: absolute;
  left: 0;
  color: var(--color-gold, #d4af6e);
}

/* 六维度评分 */
.dimension-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.dimension-card {
  background: #fafbfe;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 8px;
  padding: 10px 12px;
  text-align: center;
}
.dimension-card.overall {
  background: #fef9f0;
  border-color: var(--color-gold, #d4af6e);
  grid-column: span 3;
}
.dimension-name { font-size: 11px; color: var(--text-tertiary, #8b95a5); margin-bottom: 4px; }
.dimension-score { font-size: 20px; font-weight: 700; color: var(--text-primary, #1a1a2e); }
.dimension-comment { font-size: 11px; color: var(--text-tertiary, #8b95a5); margin-top: 4px; }

/* 回合拆解 */
.round-list { display: flex; flex-direction: column; gap: 10px; }
.round-item {
  background: #fafbfe;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 8px;
  padding: 10px 12px;
}
.round-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.round-no { font-weight: 700; font-size: 12px; color: var(--color-gold, #d4af6e); }
.round-time { font-size: 11px; color: var(--text-tertiary, #8b95a5); }
.round-summary { font-size: 12px; color: var(--text-secondary, #4a5568); margin: 0; }
.round-comment { font-size: 11px; color: var(--text-tertiary, #8b95a5); margin: 4px 0 0; font-style: italic; }

/* 话术 */
.phrase-block { margin-bottom: 12px; }
.phrase-label { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.phrase-label.golden { color: #047857; }
.phrase-label.red { color: #dc2626; }
.phrase-item { font-size: 12px; padding: 6px 0; border-bottom: 1px dashed var(--border-color, #f0ece5); }
.phrase-item:last-child { border-bottom: none; }
.phrase-scene { font-weight: 600; margin-right: 4px; }
.golden-item .phrase-scene { color: #047857; }
.red-item .phrase-scene { color: #dc2626; }
.phrase-item q { font-style: italic; color: var(--text-secondary, #4a5568); }
.phrase-why { color: var(--text-tertiary, #8b95a5); margin-left: 4px; }

/* 结果归因 */
.result-item { font-size: 12px; padding: 6px 0; border-bottom: 1px dashed var(--border-color, #f0ece5); }
.result-factor { font-weight: 600; color: var(--text-primary, #1a1a2e); }
.result-evidence { color: var(--text-secondary, #4a5568); margin-left: 8px; }

/* 优化表格 */
.improve-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.improve-table th { text-align: left; padding: 6px 8px; background: #fafbfe; border-bottom: 1px solid var(--border-color, #e5dfd6); font-weight: 600; }
.improve-table td { padding: 6px 8px; border-bottom: 1px solid var(--border-color, #f0ece5); vertical-align: top; }
.priority-tag { font-size: 14px; }

/* 行动清单 */
.action-list { display: flex; flex-direction: column; gap: 6px; }
.action-item { font-size: 12px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.action-text { color: var(--text-secondary, #4a5568); }
.action-owner { color: var(--text-tertiary, #8b95a5); }
.action-deadline { font-size: 11px; color: var(--text-tertiary, #8b95a5); }

/* 评价修正 */
.section-corrections { background: #fafbfe; border-radius: 8px; padding: 12px; }
.json-preview {
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 6px;
  padding: 10px;
  font-size: 11px;
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.correction-item { margin-bottom: 8px; }
.correction-key { font-size: 11px; font-weight: 600; color: var(--text-primary, #1a1a2e); margin-bottom: 2px; }
.correction-val { font-size: 12px; color: var(--text-secondary, #4a5568); background: #fff; padding: 6px 8px; border-radius: 4px; }

/* 草稿弹窗 */
.draft-form { max-height: 60vh; overflow-y: auto; padding-right: 8px; }
.draft-group { margin-bottom: 20px; }
.draft-group h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
  margin: 0 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-color, #f0ece5);
}

.raw-text {
  background: #fafbfe;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.screenshot-upload :deep(.el-upload-dragger) {
  border-radius: 12px;
  border-color: var(--border-color, #e5dfd6);
}
</style>
