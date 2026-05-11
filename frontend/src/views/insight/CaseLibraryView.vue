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
        <GlassButton variant="primary" left-icon="Plus" @click="openAddDialog">添加案例</GlassButton>
      </div>
    </div>

    <div v-loading="loading" class="cases-area">
      <el-empty v-if="!loading && cases.length === 0" description="暂无案例" :image-size="80">
        <p class="empty-tip">业务员可分享谈判技巧、客户开发、纠纷处理等成功经验</p>
        <GlassButton variant="primary" left-icon="Plus" @click="openAddDialog">添加第一个案例</GlassButton>
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
        </div>
      </div>
    </div>

    <!-- 详情 Drawer -->
    <el-drawer v-model="detailVisible" :size="640" direction="rtl" :with-header="false">
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
            <el-button v-if="canDelete(currentCase)" link type="danger" :icon="Delete" @click="deleteCurrentCase">归档</el-button>
            <el-button link :icon="Close" @click="detailVisible = false" />
          </div>
        </div>
        <h2 class="detail-title">{{ currentCase.title }}</h2>
        <div class="detail-meta">
          <span>分享人: <strong>{{ currentCase.share_person }}</strong></span>
          <span>日期: {{ currentCase.share_date || formatDateOnly(currentCase.created_at) }}</span>
          <span v-if="currentCase.customer_name">客户: {{ currentCase.customer_name }}</span>
        </div>

        <div class="detail-section section-scenario">
          <h5><el-icon><Comment /></el-icon> 场景背景</h5>
          <p>{{ currentCase.scenario || '—' }}</p>
        </div>
        <div class="detail-section section-action">
          <h5><el-icon><Operation /></el-icon> 我做了什么</h5>
          <p>{{ currentCase.what_was_done || '—' }}</p>
        </div>
        <div class="detail-section section-result">
          <h5><el-icon><CircleCheck /></el-icon> 结果</h5>
          <p>{{ currentCase.result || '—' }}</p>
        </div>

        <div v-if="currentCase.highlights && currentCase.highlights.length" class="detail-section section-highlights">
          <h5><el-icon><MagicStick /></el-icon> 核心亮点</h5>
          <ul>
            <li v-for="(h, i) in currentCase.highlights" :key="i">{{ h }}</li>
          </ul>
        </div>

        <div v-if="currentCase.key_phrases && currentCase.key_phrases.length" class="detail-section">
          <h5><el-icon><ChatLineRound /></el-icon> 关键话术</h5>
          <div class="phrase-list">
            <span v-for="(p, i) in currentCase.key_phrases" :key="i" class="phrase">{{ p }}</span>
          </div>
        </div>

        <div v-if="currentCase.image_path" class="detail-section">
          <h5><el-icon><PictureFilled /></el-icon> 原始截图</h5>
          <img :src="currentCase.image_path" alt="case screenshot" class="case-image" />
        </div>

        <div v-if="currentCase.original_content" class="detail-section">
          <h5><el-icon><Document /></el-icon> 原始内容</h5>
          <pre class="raw-text">{{ currentCase.original_content }}</pre>
        </div>
      </div>
    </el-drawer>

    <!-- 添加 Dialog -->
    <el-dialog v-model="addDialogVisible" title="添加案例" width="640px" :close-on-click-modal="false" destroy-on-close>
      <el-tabs v-model="addTab">
        <el-tab-pane label="表单填写" name="manual">
          <el-form ref="manualFormRef" :model="manualForm" :rules="manualRules" label-width="100px">
            <el-form-item label="标题" prop="title">
              <el-input v-model="manualForm.title" placeholder="一句话概括案例" maxlength="100" show-word-limit />
            </el-form-item>
            <el-form-item label="标签">
              <el-checkbox-group v-model="manualForm.tags">
                <el-checkbox v-for="t in TAGS" :key="t" :value="t" :label="t" />
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="客户名称">
              <el-input v-model="manualForm.customer_name" placeholder="可选" />
            </el-form-item>
            <el-form-item label="场景背景" prop="scenario">
              <el-input v-model="manualForm.scenario" type="textarea" :rows="2" placeholder="客户背景 / 遇到的问题" maxlength="500" show-word-limit />
            </el-form-item>
            <el-form-item label="我做了什么" prop="what_was_done">
              <el-input v-model="manualForm.what_was_done" type="textarea" :rows="4" placeholder="详细执行过程" maxlength="2000" show-word-limit />
            </el-form-item>
            <el-form-item label="结果" prop="result">
              <el-input v-model="manualForm.result" type="textarea" :rows="2" placeholder="最终达成什么结果" maxlength="500" show-word-limit />
            </el-form-item>
            <el-form-item label="分享人">
              <el-input v-model="manualForm.share_person" placeholder="留空将使用当前用户" />
            </el-form-item>
            <el-form-item label="分享日期">
              <el-date-picker v-model="manualForm.share_date" type="date" value-format="YYYY-MM-DD" placeholder="默认今日" />
            </el-form-item>
          </el-form>
          <template #footer-extra>
            <span></span>
          </template>
        </el-tab-pane>

        <el-tab-pane label="文本粘贴(AI 整理)" name="text">
          <el-form>
            <el-form-item label="原始文本">
              <el-input
                v-model="aiText"
                type="textarea"
                :rows="10"
                placeholder="粘贴聊天记录 / 邮件往来 / 电话纪要等。AI 将自动整理为案例字段,你确认后发布。"
              />
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
          <el-upload
            class="screenshot-upload"
            drag
            :auto-upload="false"
            :on-change="handleFileChange"
            :limit="1"
            accept=".png,.jpg,.jpeg,.webp,.gif"
          >
            <el-icon class="el-icon--upload"><Upload /></el-icon>
            <div class="el-upload__text">将图片拖拽到此处,或<em>点击上传</em></div>
            <template #tip>
              <div class="el-upload__tip">支持 PNG / JPG / WEBP / GIF,最大 5MB</div>
            </template>
          </el-upload>
          <el-form style="margin-top: 16px">
            <el-form-item label="分享人">
              <el-input v-model="aiSharePerson" placeholder="留空将使用当前用户" />
            </el-form-item>
            <el-form-item label="分享日期">
              <el-date-picker v-model="aiShareDate" type="date" value-format="YYYY-MM-DD" placeholder="默认今日" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <GlassButton variant="ghost" @click="addDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="submitting" @click="submitCase">{{ submitButtonText }}</GlassButton>
      </template>
    </el-dialog>

    <!-- AI 草稿确认 Dialog -->
    <el-dialog v-model="draftDialogVisible" title="AI 整理结果 - 请确认" width="700px" :close-on-click-modal="false">
      <el-alert v-if="draftCase && draftCase.error_msg" :title="draftCase.error_msg" type="warning" show-icon :closable="false" style="margin-bottom: 12px" />
      <el-form v-if="draftCase" :model="draftCase" label-width="100px">
        <el-form-item label="标题">
          <el-input v-model="draftCase.title" />
        </el-form-item>
        <el-form-item label="标签">
          <el-checkbox-group v-model="draftTagsArr">
            <el-checkbox v-for="t in TAGS" :key="t" :value="t" :label="t" />
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="客户名称">
          <el-input v-model="draftCase.customer_name" />
        </el-form-item>
        <el-form-item label="场景背景">
          <el-input v-model="draftCase.scenario" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="我做了什么">
          <el-input v-model="draftCase.what_was_done" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="结果">
          <el-input v-model="draftCase.result" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="原始内容" v-if="draftCase.original_content">
          <el-input v-model="draftCase.original_content" type="textarea" :rows="3" disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="draftDialogVisible = false">稍后处理</GlassButton>
        <GlassButton variant="primary" :loading="publishing" @click="confirmPublishDraft">确认发布</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search, Plus, Star, StarFilled, Paperclip, Comment, Operation,
  CircleCheck, MagicStick, ChatLineRound, PictureFilled, Document,
  Delete, Close, Upload,
} from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  listCases, getCaseDetail, manualCreateCase, uploadCase, publishCase,
  deleteCase, toggleCaseLike,
} from '@/api/insight'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const TAGS = ['开发跟进', '谈判技巧', '定制流程', '物流处理', '纠纷解决', '竞品应对']

const cases = ref([])
const loading = ref(false)
const search = ref('')
const tagFilter = ref('all')
const sortBy = ref('date')
const viewMode = ref('grid')
const localLikes = ref({})

const detailVisible = ref(false)
const currentCase = ref(null)

const addDialogVisible = ref(false)
const addTab = ref('manual')
const submitting = ref(false)

const manualFormRef = ref()
const manualForm = reactive({
  title: '',
  customer_name: '',
  scenario: '',
  what_was_done: '',
  result: '',
  tags: [],
  share_person: '',
  share_date: '',
})
const manualRules = {
  title: [{ required: true, message: '请填写标题', trigger: 'blur' }],
  scenario: [{ required: true, message: '请填写场景背景', trigger: 'blur' }],
  what_was_done: [{ required: true, message: '请填写执行过程', trigger: 'blur' }],
  result: [{ required: true, message: '请填写结果', trigger: 'blur' }],
}

const aiText = ref('')
const aiSharePerson = ref('')
const aiShareDate = ref('')
const aiFile = ref(null)

const draftDialogVisible = ref(false)
const draftCase = ref(null)
const draftTagsArr = ref([])
const publishing = ref(false)

const submitButtonText = computed(() => {
  if (addTab.value === 'manual') return '发布'
  return 'AI 整理'
})

function reload() {
  loading.value = true
  const params = {
    page: 1,
    page_size: 60,
    sort: sortBy.value,
  }
  if (search.value) params.q = search.value
  if (tagFilter.value !== 'all') params.tag = tagFilter.value
  listCases(params).then((res) => {
    cases.value = res.data.items || []
  }).finally(() => {
    loading.value = false
  })
}

async function openDetail(c) {
  detailVisible.value = true
  try {
    const res = await getCaseDetail(c.id)
    currentCase.value = res.data
  } catch (e) {
    currentCase.value = c
  }
}

function openAddDialog() {
  addDialogVisible.value = true
  addTab.value = 'manual'
  Object.assign(manualForm, { title: '', customer_name: '', scenario: '', what_was_done: '', result: '', tags: [], share_person: '', share_date: '' })
  aiText.value = ''
  aiSharePerson.value = ''
  aiShareDate.value = ''
  aiFile.value = null
}

function handleFileChange(file) {
  aiFile.value = file.raw
}

async function submitCase() {
  if (addTab.value === 'manual') {
    if (!manualFormRef.value) return
    const valid = await manualFormRef.value.validate().catch(() => false)
    if (!valid) return
    submitting.value = true
    try {
      await manualCreateCase({ ...manualForm, share_date: manualForm.share_date || undefined })
      ElMessage.success('案例已发布')
      addDialogVisible.value = false
      reload()
    } finally {
      submitting.value = false
    }
  } else if (addTab.value === 'text') {
    if (!aiText.value || aiText.value.trim().length < 10) {
      ElMessage.warning('请粘贴至少 10 个字符的原始文本')
      return
    }
    submitting.value = true
    try {
      const fd = new FormData()
      fd.append('source_type', 'text_paste')
      fd.append('text', aiText.value)
      if (aiSharePerson.value) fd.append('share_person', aiSharePerson.value)
      if (aiShareDate.value) fd.append('share_date', aiShareDate.value)
      const res = await uploadCase(fd)
      const caseId = res.data.case_id
      await loadDraft(caseId)
      addDialogVisible.value = false
    } finally {
      submitting.value = false
    }
  } else if (addTab.value === 'screenshot') {
    if (!aiFile.value) {
      ElMessage.warning('请先上传图片')
      return
    }
    submitting.value = true
    try {
      const fd = new FormData()
      fd.append('source_type', 'screenshot')
      fd.append('file', aiFile.value)
      if (aiSharePerson.value) fd.append('share_person', aiSharePerson.value)
      if (aiShareDate.value) fd.append('share_date', aiShareDate.value)
      const res = await uploadCase(fd)
      const caseId = res.data.case_id
      await loadDraft(caseId)
      addDialogVisible.value = false
    } finally {
      submitting.value = false
    }
  }
}

async function loadDraft(caseId) {
  const res = await getCaseDetail(caseId)
  draftCase.value = { ...res.data }
  draftTagsArr.value = Array.isArray(res.data.tags) ? [...res.data.tags] : []
  draftDialogVisible.value = true
}

async function confirmPublishDraft() {
  if (!draftCase.value) return
  publishing.value = true
  try {
    const payload = {
      title: draftCase.value.title,
      customer_name: draftCase.value.customer_name,
      scenario: draftCase.value.scenario,
      what_was_done: draftCase.value.what_was_done,
      result: draftCase.value.result,
      tags: draftTagsArr.value,
    }
    await publishCase(draftCase.value.id, payload)
    ElMessage.success('已发布')
    draftDialogVisible.value = false
    reload()
  } finally {
    publishing.value = false
  }
}

async function toggleLike(c) {
  const liked = !!localLikes.value[c.id]
  const delta = liked ? -1 : 1
  try {
    const res = await toggleCaseLike(c.id, delta)
    localLikes.value[c.id] = !liked
    c.like_count = res.data.like_count
    if (currentCase.value && currentCase.value.id === c.id) {
      currentCase.value.like_count = res.data.like_count
    }
  } catch (e) {
    // ignore
  }
}

function canDelete(c) {
  return c && (c.is_owner || authStore.hasPermission('insight:admin'))
}

async function deleteCurrentCase() {
  if (!currentCase.value) return
  await ElMessageBox.confirm('确认归档此案例?归档后不在列表中显示。', '请确认', {
    confirmButtonText: '归档',
    cancelButtonText: '取消',
    type: 'warning',
  })
  await deleteCase(currentCase.value.id)
  ElMessage.success('已归档')
  detailVisible.value = false
  reload()
}

function formatDateOnly(s) {
  if (!s) return ''
  return s.slice(0, 10)
}

onMounted(reload)
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

.card-actions { display: flex; align-items: center; gap: 12px; }

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

.detail-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-color, #f0ece5);
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

.phrase-list { display: flex; flex-wrap: wrap; gap: 6px; }
.phrase {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
}

.case-image {
  max-width: 100%;
  border-radius: 8px;
  border: 1px solid var(--border-color, #e5dfd6);
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
