<!--
  培训速递 · 详情页（AI HOT 日报式排版）
  元信息头 → 锚点目录 → 分区卡片 → 原始资料下载区（axios blob，浏览器直链不带 JWT）
-->
<template>
  <div class="page" v-loading="loading">
    <template v-if="detail">
      <div class="back-row">
        <GlassButton variant="link" left-icon="ArrowLeft" @click="router.push('/training/digests')">返回培训速递</GlassButton>
      </div>

      <!-- 元信息头 -->
      <header class="digest-header">
        <div class="header-top">
          <el-tag size="small" effect="plain" type="warning">培训速递</el-tag>
          <el-tag v-if="detail.status === 'draft'" size="small" type="info" effect="plain">草稿 · 未发布</el-tag>
        </div>
        <h1 class="digest-title">{{ detail.title }}</h1>
        <div class="meta-row">
          <span>{{ detail.trained_at }}</span>
          <span v-if="detail.org">{{ detail.org }}</span>
          <span v-if="detail.lecturer">讲师 · {{ detail.lecturer }}</span>
          <span>参训 · {{ attendeeText }}</span>
          <span>约 {{ detail.read_minutes || 1 }} 分钟读完</span>
          <span class="muted">阅 {{ detail.view_count }}</span>
        </div>
        <div v-if="detail.tags.length" class="tags-row">
          <el-tag v-for="t in detail.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
        </div>
        <div class="action-row">
          <GlassButton
            v-if="detail.status === 'published'"
            :variant="detail.my_useful ? 'primary' : 'outline'"
            left-icon="Star"
            @click="onToggleUseful"
          >有用 {{ detail.useful_count }}</GlassButton>
          <template v-if="detail.can_edit">
            <GlassButton variant="secondary" left-icon="Edit" @click="router.push(`/training/digests/${detail.id}/edit`)">编辑</GlassButton>
            <GlassButton
              v-if="detail.status === 'published'"
              variant="secondary"
              left-icon="Promotion"
              @click="onPush"
            >重推钉钉群</GlassButton>
          </template>
        </div>
      </header>

      <!-- 锚点目录 -->
      <nav class="toc" v-if="tocItems.length">
        <a v-for="(item, i) in tocItems" :key="item.id" class="toc-item" @click="scrollTo(item.id)">
          <span class="toc-num">{{ String(i + 1).padStart(2, '0') }}</span>{{ item.label }}
        </a>
      </nav>

      <!-- 一句话总结 -->
      <section v-if="detail.summary" class="section summary-box" id="sec-summary">
        <p>{{ detail.summary }}</p>
      </section>

      <!-- 重点 -->
      <section v-if="sections.highlights.length" class="section" id="sec-highlights">
        <h2 class="section-title">重点</h2>
        <ol class="highlight-list">
          <li v-for="(h, i) in sections.highlights" :key="i" class="highlight-item">
            <div class="highlight-title">{{ h.title }}</div>
            <p v-if="h.detail" class="highlight-detail">{{ h.detail }}</p>
          </li>
        </ol>
      </section>

      <!-- 亮点 / 新知 -->
      <section v-if="sections.new_insights.length" class="section" id="sec-insights">
        <h2 class="section-title">亮点 / 新知</h2>
        <ul class="insight-list">
          <li v-for="(s, i) in sections.new_insights" :key="i">{{ s }}</li>
        </ul>
      </section>

      <!-- 可应用点 -->
      <section v-if="sections.applications.length" class="section" id="sec-apps">
        <h2 class="section-title">可应用点</h2>
        <div v-for="(a, i) in sections.applications" :key="i" class="app-card">
          <div class="app-point">{{ a.point }}</div>
          <div class="app-meta">
            <el-tag v-for="r in a.roles" :key="r" size="small" type="warning" effect="plain">{{ r }}</el-tag>
          </div>
          <div v-if="a.first_step" class="app-step">第一步：{{ a.first_step }}</div>
        </div>
      </section>

      <!-- 方法与技巧 -->
      <section v-if="sections.methods.length" class="section" id="sec-methods">
        <h2 class="section-title">方法与技巧</h2>
        <div v-for="(m, i) in sections.methods" :key="i" class="method-item">
          <div class="method-name">{{ m.name }}</div>
          <p class="method-steps">{{ m.steps }}</p>
        </div>
      </section>

      <!-- 参训人点评 -->
      <section v-if="sections.review" class="section review-box" id="sec-review">
        <h2 class="section-title">参训人点评</h2>
        <blockquote class="review-quote">{{ sections.review }}</blockquote>
        <div class="review-author">—— {{ detail.creator_name || '参训人' }}</div>
      </section>

      <!-- 原始资料 -->
      <section v-if="detail.files.length" class="section" id="sec-files">
        <h2 class="section-title">原始资料</h2>
        <div v-for="f in detail.files" :key="f.id" class="file-row">
          <el-tag size="small" effect="plain" class="file-type-tag">{{ FILE_TYPE_LABELS[f.file_type] || '未分类' }}</el-tag>
          <span class="file-name">{{ f.file_name }}</span>
          <span v-if="f.remark" class="file-remark" :title="f.remark">{{ f.remark }}</span>
          <span class="file-size">{{ formatSize(f.file_size) }}</span>
          <GlassButton
            variant="link"
            left-icon="Download"
            :disabled="downloadingId === f.id"
            @click="onDownload(f)"
          >{{ downloadingId === f.id ? '下载中…' : '下载' }}</GlassButton>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDigest, toggleUseful, pushDigest, downloadDigestFile, FILE_TYPE_LABELS } from '@/api/training'
import { msgSuccess, msgError } from '@/utils/feedback'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const detail = ref(null)
const downloadingId = ref(null)

const sections = computed(() => detail.value?.sections || {
  highlights: [], new_insights: [], applications: [], methods: [], review: '',
})

const attendeeText = computed(() => {
  const names = detail.value?.attendees || []
  const creator = detail.value?.creator_name
  const all = names.length ? names : (creator ? [creator] : [])
  return all.join('、') || '—'
})

const tocItems = computed(() => {
  if (!detail.value) return []
  const items = []
  if (sections.value.highlights.length) items.push({ id: 'sec-highlights', label: '重点' })
  if (sections.value.new_insights.length) items.push({ id: 'sec-insights', label: '亮点新知' })
  if (sections.value.applications.length) items.push({ id: 'sec-apps', label: '可应用点' })
  if (sections.value.methods.length) items.push({ id: 'sec-methods', label: '方法技巧' })
  if (sections.value.review) items.push({ id: 'sec-review', label: '参训人点评' })
  if (detail.value.files.length) items.push({ id: 'sec-files', label: '原始资料' })
  return items
})

async function fetchDetail() {
  loading.value = true
  try {
    const res = await getDigest(route.params.id)
    detail.value = res.data
  } finally {
    loading.value = false
  }
}

async function onToggleUseful() {
  const res = await toggleUseful(detail.value.id)
  detail.value.my_useful = res.data.my_useful
  detail.value.useful_count = res.data.useful_count
}

async function onPush() {
  await pushDigest(detail.value.id)
  msgSuccess('推送')
}

async function onDownload(f) {
  downloadingId.value = f.id
  try {
    // blob 响应拦截器返回完整 response，blob 在 res.data
    const res = await downloadDigestFile(f.id)
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = f.file_name
    a.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    // blob 错误响应体是 Blob，拦截器读不出中文 detail；404 已 suppress，由这里给唯一提示
    if (err?.response?.status === 404) msgError('附件文件缺失，请联系发布人重新上传')
  } finally {
    downloadingId.value = null
  }
}

function scrollTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

onMounted(fetchDetail)
</script>

<style scoped>
.page {
  max-width: 860px;
  margin: 0 auto;
  padding: 16px 16px 48px;
}

.back-row {
  margin-bottom: 4px;
}

.digest-header {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 24px;
  margin-bottom: 16px;
}

.header-top {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.digest-title {
  margin: 0 0 12px;
  font-size: 24px;
  line-height: 1.35;
  color: var(--text-primary);
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  font-size: 13px;
  color: var(--text-secondary);
}

.meta-row .muted {
  color: var(--text-muted);
}

.tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.toc {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  padding: 12px 16px;
  margin-bottom: 16px;
  background: var(--toolbar-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
}

.toc-item {
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 150ms ease;
}

.toc-item:hover {
  color: var(--color-primary);
}

.toc-num {
  color: var(--color-primary);
  font-weight: 600;
  margin-right: 4px;
}

.section {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 20px 24px;
  margin-bottom: 16px;
  animation: section-in 200ms cubic-bezier(0.23, 1, 0.32, 1) both;
}

@media (prefers-reduced-motion: reduce) {
  .section {
    animation: none;
  }
}

@keyframes section-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.section-title {
  margin: 0 0 14px;
  font-size: 16px;
  color: var(--text-primary);
}

.summary-box {
  border-left: 3px solid var(--color-primary);
  background: var(--color-gold-soft);
}

.summary-box p {
  margin: 0;
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-primary);
}

.highlight-list {
  margin: 0;
  padding-left: 22px;
}

.highlight-item {
  margin-bottom: 14px;
}

.highlight-item:last-child {
  margin-bottom: 0;
}

.highlight-title {
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.5;
}

.highlight-detail {
  margin: 4px 0 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.insight-list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
  color: var(--text-secondary);
}

.app-card {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  margin-bottom: 10px;
}

.app-card:last-child {
  margin-bottom: 0;
}

.app-point {
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.5;
}

.app-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.app-step {
  margin-top: 8px;
  font-size: 13px;
  color: var(--color-primary);
}

.method-item {
  margin-bottom: 14px;
}

.method-item:last-child {
  margin-bottom: 0;
}

.method-name {
  font-weight: 600;
  color: var(--text-primary);
}

.method-steps {
  margin: 4px 0 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

.review-quote {
  margin: 0;
  padding: 4px 0 4px 16px;
  border-left: 3px solid var(--color-gold);
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-primary);
}

.review-author {
  margin-top: 8px;
  text-align: right;
  font-size: 13px;
  color: var(--text-muted);
}

.file-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--border-color);
}

.file-row:last-child {
  border-bottom: none;
}

.file-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}

.file-type-tag {
  flex-shrink: 0;
}

.file-remark {
  max-width: 260px;
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex-shrink: 0;
}

.file-size {
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .digest-header {
    padding: 16px;
  }

  .digest-title {
    font-size: 20px;
  }

  .section {
    padding: 16px;
  }
}
</style>
