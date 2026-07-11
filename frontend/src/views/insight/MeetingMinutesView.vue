<template>
  <div class="insight-page minutes-page">
    <div class="minutes-toolbar">
      <h3 class="page-subtitle">周会纪要</h3>
      <GlassButton v-if="canWrite" variant="primary" left-icon="Plus" @click="openUpload">上传本周纪要</GlassButton>
    </div>

    <div class="minutes-body">
      <!-- 时间线 -->
      <aside class="timeline-panel">
        <div class="timeline-header">
          <el-icon><Calendar /></el-icon>
          <span>历史纪要</span>
          <span class="count-pill">{{ minutes.length }}</span>
        </div>
        <div class="timeline-content">
          <el-empty v-if="!loading && minutes.length === 0" description="暂无纪要" :image-size="60" />
          <div class="timeline-line" v-else>
            <div
              v-for="(m, idx) in minutes"
              :key="m.id"
              class="timeline-item"
              :class="{ active: selectedId === m.id }"
              @click="selectMinutes(m.id)"
            >
              <div class="dot" />
              <div class="item-content">
                <div class="item-date">
                  {{ m.meeting_date }}
                  <el-tag v-if="idx === 0" type="warning" size="small" effect="light">最新</el-tag>
                  <el-tag v-if="m.status === 'processing'" type="info" size="small">处理中</el-tag>
                  <el-tag v-if="m.status === 'failed'" type="danger" size="small">失败</el-tag>
                </div>
                <div class="item-title">{{ m.title }}</div>
                <div class="item-meta">
                  <span v-if="m.duration">{{ m.duration }}</span>
                  <span v-if="m.pending_tasks > 0" class="pending-badge">{{ m.pending_tasks }} 项待办</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <!-- 详情 -->
      <section class="detail-panel">
        <div v-if="loadingDetail" class="detail-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>加载中...</span>
        </div>
        <div v-else-if="!current" class="detail-empty">
          <el-icon size="40"><Calendar /></el-icon>
          <p>选择左侧纪要查看详情</p>
        </div>
        <div v-else class="detail-content">
          <header class="detail-header">
            <div>
              <h2>{{ current.title || '会议纪要' }}</h2>
              <p class="detail-sub">{{ current.meeting_date }} <span v-if="current.duration">· {{ current.duration }}</span></p>
              <p v-if="current.participants" class="participants">参与人: {{ current.participants }}</p>
            </div>
            <div class="header-actions">
              <a v-if="current.source_url" :href="current.source_url" target="_blank" rel="noopener" class="link">
                <el-icon><Link /></el-icon> 原文链接
              </a>
              <GlassButton variant="link" left-icon="Download" @click="exportTasks">导出任务 CSV</GlassButton>
            </div>
          </header>

          <el-alert
            v-if="current.status === 'failed' && current.error_msg"
            :title="`AI 处理失败: ${current.error_msg}`"
            type="error"
            show-icon
            :closable="false"
            style="margin-bottom: 16px"
          />

          <div class="content-grid">
            <!-- 主要内容 -->
            <div class="main-col">
              <!-- 主要讨论点 -->
              <section class="card-block">
                <h4><el-icon><ChatLineRound /></el-icon> 主要讨论点</h4>
                <ol v-if="topics.length" class="numbered-list">
                  <li v-for="(t, i) in topics" :key="i">{{ t }}</li>
                </ol>
                <p v-else class="empty-line">{{ current.summary_md ? '从精要中未提取出讨论点' : '暂无' }}</p>
              </section>

              <!-- 已确认事项 -->
              <section class="card-block decisions">
                <h4><el-icon><Aim /></el-icon> 已确认事项</h4>
                <ul v-if="decisions.length" class="check-list">
                  <li v-for="(d, i) in decisions" :key="i">
                    <el-icon><CircleCheckFilled /></el-icon> {{ d }}
                  </li>
                </ul>
                <p v-else class="empty-line">暂无明确决策</p>
              </section>

              <!-- 精要原文 -->
              <details v-if="current.summary_md" class="raw-summary">
                <summary>查看 AI 精要(Markdown)</summary>
                <pre>{{ current.summary_md }}</pre>
              </details>

              <!-- 原文 -->
              <details v-if="current.original_text" class="raw-summary">
                <summary>查看会议原文</summary>
                <pre>{{ current.original_text }}</pre>
              </details>
            </div>

            <!-- 任务清单 -->
            <aside class="task-col">
              <section class="card-block tasks">
                <h4>
                  <el-icon><List /></el-icon>
                  任务执行清单
                  <span class="count-pill">{{ tasks.length }}</span>
                </h4>
                <p v-if="!tasks.length" class="empty-line">暂无任务</p>
                <ul v-else class="task-list">
                  <li v-for="t in tasks" :key="t.id" class="task-item" :class="`status-${t.status}`">
                    <el-checkbox
                      :model-value="t.status === 'completed'"
                      :disabled="!canWrite"
                      @change="(v) => onTaskCheck(t, v)"
                    />
                    <div class="task-body">
                      <div class="task-line">
                        <span class="task-assignee">{{ t.assignee }}</span>
                        <span :class="`prio-tag prio-${t.priority}`">{{ priorityLabel(t.priority) }}</span>
                        <span v-if="t.deadline" class="task-deadline" :class="{ overdue: isOverdue(t) }">
                          {{ t.deadline }}{{ isOverdue(t) ? ' (逾期)' : '' }}
                        </span>
                      </div>
                      <div class="task-desc">{{ t.description }}</div>
                      <div v-if="t.source_quote" class="task-quote">原文: {{ t.source_quote }}</div>
                      <el-input
                        v-if="t.status === 'completed' && canWrite"
                        :model-value="t.notes || ''"
                        size="small"
                        placeholder="可选: 添加完成备注"
                        @change="(v) => onTaskNotes(t, v)"
                      />
                    </div>
                  </li>
                </ul>
              </section>
            </aside>
          </div>
        </div>
      </section>
    </div>

    <!-- 上传 Dialog -->
    <el-dialog v-model="uploadVisible" title="上传周会纪要" width="640px" :close-on-click-modal="false" destroy-on-close>
      <el-form ref="uploadFormRef" :model="uploadForm" :rules="uploadRules" label-width="100px">
        <el-form-item label="会议日期" prop="meeting_date">
          <el-date-picker v-model="uploadForm.meeting_date" type="date" value-format="YYYY-MM-DD" placeholder="选择会议日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="会议主题" prop="title">
          <el-input v-model="uploadForm.title" placeholder="如: 2026 W19 周会" />
        </el-form-item>
        <el-form-item label="时长">
          <el-input v-model="uploadForm.duration" placeholder="如: 90min" />
        </el-form-item>
        <el-form-item label="参与人">
          <el-input v-model="uploadForm.participants" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="原始转录" prop="original_text">
          <el-input v-model="uploadForm.original_text" type="textarea" :rows="10" placeholder="粘贴钉钉 AI 转录全文。AI 将自动整理精要 + 任务清单。" />
        </el-form-item>
        <el-form-item label="原文链接">
          <el-input v-model="uploadForm.source_url" placeholder="可选: 钉钉文档链接" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="uploadVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="uploading" @click="submitUpload">上传并 AI 处理</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Calendar, Loading, Plus, Link, Download, ChatLineRound, Aim,
  CircleCheckFilled, List,
} from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  listMinutes, getMinutesDetail, uploadMinutes, updateTask, exportTasksCsv,
} from '@/api/insight'
import { downloadBlob } from '@/utils/download'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const canWrite = computed(() => authStore.hasAnyPermission(['insight_minutes:write', 'insight:admin']))

const minutes = ref([])
const loading = ref(false)
const selectedId = ref(null)
const current = ref(null)
const loadingDetail = ref(false)

const uploadVisible = ref(false)
const uploading = ref(false)
const uploadFormRef = ref()
const uploadForm = ref({
  meeting_date: '',
  title: '',
  duration: '',
  participants: '',
  original_text: '',
  source_url: '',
})
const uploadRules = {
  meeting_date: [{ required: true, message: '请选择会议日期', trigger: 'change' }],
  original_text: [
    { required: true, message: '请粘贴会议原文', trigger: 'blur' },
    { min: 10, message: '至少 10 字符', trigger: 'blur' },
  ],
}

const topics = computed(() => current.value?.structured_summary?.topics || [])
const decisions = computed(() => current.value?.structured_summary?.decisions || [])
const tasks = computed(() => current.value?.tasks || [])

async function refreshList() {
  loading.value = true
  try {
    const res = await listMinutes({ page: 1, page_size: 50 })
    minutes.value = res.data.items || []
    if (minutes.value.length > 0 && !selectedId.value) {
      await selectMinutes(minutes.value[0].id)
    }
  } finally {
    loading.value = false
  }
}

async function selectMinutes(id) {
  selectedId.value = id
  loadingDetail.value = true
  try {
    const res = await getMinutesDetail(id)
    current.value = res.data
  } finally {
    loadingDetail.value = false
  }
}

function openUpload() {
  uploadVisible.value = true
  uploadForm.value = {
    meeting_date: new Date().toISOString().slice(0, 10),
    title: '',
    duration: '',
    participants: '',
    original_text: '',
    source_url: '',
  }
}

async function submitUpload() {
  if (!uploadFormRef.value) return
  const valid = await uploadFormRef.value.validate().catch(() => false)
  if (!valid) return
  uploading.value = true
  try {
    const res = await uploadMinutes(uploadForm.value)
    ElMessage.success('上传成功,AI 已处理完毕')
    uploadVisible.value = false
    await refreshList()
    if (res.data?.id) await selectMinutes(res.data.id)
  } finally {
    uploading.value = false
  }
}

async function onTaskCheck(task, isChecked) {
  const newStatus = isChecked ? 'completed' : 'pending'
  try {
    await updateTask(task.id, { status: newStatus })
    task.status = newStatus
    if (newStatus === 'completed') {
      task.completed_at = new Date().toISOString()
    } else {
      task.completed_at = null
      task.notes = ''
    }
  } catch (e) {
    ElMessage.error('更新任务状态失败')
  }
}

async function onTaskNotes(task, notes) {
  try {
    await updateTask(task.id, { notes })
    task.notes = notes
  } catch (e) {}
}

function priorityLabel(p) {
  return { high: '高', medium: '中', low: '低' }[p] || p
}

function isOverdue(t) {
  if (!t.deadline) return false
  if (t.status === 'completed') return false
  const today = new Date().toISOString().slice(0, 10)
  return t.deadline < today
}

async function exportTasks() {
  if (!selectedId.value) return
  const res = await exportTasksCsv(selectedId.value)
  downloadBlob(res)
}

onMounted(refreshList)
</script>

<style scoped>
.minutes-page { display: flex; flex-direction: column; gap: 16px; height: calc(100vh - 130px); min-height: 540px; }

.minutes-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.page-subtitle { font-size: 14px; font-weight: 600; color: var(--text-primary, #1a1a2e); margin: 0; }

.minutes-body { display: flex; gap: 16px; flex: 1; min-height: 0; }

.timeline-panel {
  width: 280px;
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.timeline-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #e5dfd6);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
}

.count-pill {
  margin-left: auto;
  background: #f5f2ee;
  color: var(--text-tertiary, #8b95a5);
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 8px;
}

.timeline-content { flex: 1; overflow-y: auto; padding: 12px; }

.timeline-line { position: relative; padding-left: 14px; }
.timeline-line::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-color, #e5dfd6);
}

.timeline-item {
  position: relative;
  padding: 10px 8px 10px 14px;
  margin-bottom: 4px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.timeline-item:hover { background: #fafbfe; }

.timeline-item.active { background: rgba(212, 175, 110, 0.08); }

.dot {
  position: absolute;
  left: -12px;
  top: 16px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid var(--border-color, #e5dfd6);
  z-index: 1;
}

.timeline-item.active .dot {
  background: var(--color-gold, #d4af6e);
  border-color: var(--color-gold, #d4af6e);
}

.item-date {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
  display: flex;
  align-items: center;
  gap: 6px;
}

.timeline-item.active .item-date { color: var(--color-gold, #b08d4f); }

.item-title {
  font-size: 12px;
  color: var(--text-secondary, #4a5568);
  margin-top: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-meta {
  display: flex;
  gap: 8px;
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
}

.pending-badge {
  background: #fef2f2;
  color: #dc2626;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.detail-panel {
  flex: 1;
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 12px;
  overflow: auto;
  position: relative;
}

.detail-loading,
.detail-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-tertiary, #8b95a5);
  font-size: 13px;
}

.detail-content { padding: 24px; }

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-color, #f0ece5);
}

.detail-header h2 { font-size: 18px; font-weight: 700; color: var(--text-primary, #1a1a2e); margin: 0 0 4px; }

.detail-sub { font-size: 12px; color: var(--text-tertiary, #8b95a5); margin: 0; }

.participants { font-size: 12px; color: var(--text-secondary, #4a5568); margin: 6px 0 0; }

.header-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-gold, #b08d4f);
  text-decoration: none;
}
.link:hover { text-decoration: underline; }

.content-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 16px;
}

@media (max-width: 1100px) {
  .content-grid { grid-template-columns: 1fr; }
}

.card-block {
  background: #fafbfe;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}

.card-block h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
  margin: 0 0 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.card-block.decisions { background: #fef9f0; border-color: #f5e0b5; }
.card-block.decisions h4 { color: var(--color-gold, #b08d4f); }

.card-block.tasks { background: #fff; }

.numbered-list {
  list-style: none;
  padding: 0;
  margin: 0;
  counter-reset: section;
}
.numbered-list li {
  font-size: 13px;
  color: var(--text-secondary, #4a5568);
  line-height: 1.7;
  padding: 6px 0 6px 28px;
  position: relative;
  counter-increment: section;
}
.numbered-list li::before {
  content: counter(section);
  position: absolute;
  left: 0;
  top: 7px;
  width: 20px;
  height: 20px;
  background: #eff6ff;
  color: #2563eb;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.check-list { list-style: none; padding: 0; margin: 0; }
.check-list li {
  font-size: 13px;
  color: var(--text-secondary, #4a5568);
  line-height: 1.6;
  padding: 5px 0;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.check-list li .el-icon { color: #16a34a; margin-top: 2px; flex-shrink: 0; }

.empty-line { font-size: 12px; color: var(--text-tertiary, #8b95a5); margin: 0; font-style: italic; }

.raw-summary {
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 8px;
}

.raw-summary summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  font-weight: 500;
  user-select: none;
}

.raw-summary pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 12px;
  color: var(--text-secondary, #4a5568);
  padding-top: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  max-height: 240px;
  overflow: auto;
}

.task-list { list-style: none; padding: 0; margin: 0; }

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 0;
  border-top: 1px solid var(--border-color, #f0ece5);
}
.task-item:first-child { border-top: none; }

.task-item.status-completed .task-desc {
  text-decoration: line-through;
  color: var(--text-tertiary, #8b95a5);
}

.task-body { flex: 1; min-width: 0; }

.task-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.task-assignee {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
}

.prio-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
}
.prio-high { background: #fef2f2; color: #dc2626; }
.prio-medium { background: #fffbeb; color: #d97706; }
.prio-low { background: #f0f9ff; color: #2563eb; }

.task-deadline { font-size: 11px; color: var(--text-tertiary, #8b95a5); }
.task-deadline.overdue { color: #dc2626; font-weight: 600; }

.task-desc {
  font-size: 13px;
  color: var(--text-secondary, #4a5568);
  margin-top: 4px;
}

.task-quote {
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
  margin-top: 4px;
  font-style: italic;
  background: #fafbfe;
  padding: 4px 8px;
  border-radius: 4px;
}
</style>
