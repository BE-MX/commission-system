<template>
  <div class="insight-page tools-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="ai-tools-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="tools-toolbar">
      <FilterBar :loading="loading" :pending="pendingFilters" @search="searchTools" @reset="resetFilters">
        <el-input
          v-model="searchQuery"
          placeholder="搜索工具名 / 标签 / 简介..."
          :prefix-icon="Search"
          clearable
          class="filter-w-lg"
        />
        <el-select v-model="tagFilter" placeholder="全部分类" class="filter-w-md">
          <el-option label="全部分类" value="all" />
          <el-option v-for="t in tagOptions" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="dateFilter" placeholder="全部时间" class="filter-w-md">
          <el-option label="全部时间" value="all" />
          <el-option v-for="d in dateOptions" :key="d.value" :label="d.label" :value="d.value" />
        </el-select>
        <template #summary>
        <span class="result-count">{{ filteredTools.length }} 项</span>
        <GlassButton
          v-if="canAdmin"
          variant="primary"
          left-icon="MagicStick"
          :loading="generating"
          @click="generateToday"
        >
          拉取今日速递
        </GlassButton>
        </template>
      </FilterBar>
    </div>

    <ListPageStatus :error="toolsResource.errorMessage.value" :loading="loading" :has-data="toolsResource.hasData.value" @retry="loadAll" />
    <div v-loading="loading" class="tools-grid">
      <el-empty v-if="!toolsResource.error.value && !loading && tools.length === 0" description="暂无 AI 工具速递" :image-size="80">
        <p class="empty-tip">点击右上角「拉取今日速递」或等待每日 08:35 自动生成</p>
      </el-empty>
      <el-empty v-else-if="!toolsResource.error.value && !loading && filteredTools.length === 0" description="未匹配到工具" :image-size="80" />

      <div v-for="grp in groupedFilteredTools" :key="grp.date" class="week-section">
        <div class="week-title">{{ grp.label }}</div>
        <div class="card-grid">
          <article
            v-for="(tool, idx) in grp.tools"
            :key="`${grp.date}-${idx}-${tool.title || tool.name}`"
            class="tool-card lg-card"
          >
            <div class="card-head">
              <div class="card-title-row">
                <h4>{{ tool.title || tool.name }}</h4>
                <span v-if="tool.tag || tool.category_label" class="card-tag">{{ tool.tag || tool.category_label }}</span>
              </div>
              <button class="star-btn" :class="{ active: isStarred(tool) }" @click="toggleStar(tool)">
                <el-icon><StarFilled v-if="isStarred(tool)" /><Star v-else /></el-icon>
              </button>
            </div>
            <p class="card-summary">{{ tool.summary || tool.description }}</p>
            <a
              v-if="tool.url || tool.source_url"
              class="card-link"
              :href="tool.url || tool.source_url"
              target="_blank"
              rel="noopener noreferrer"
            >
              <el-icon><Link /></el-icon>
              访问官网
            </a>
          </article>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useAsyncResource } from '@/composables/useAsyncResource'

import { ref, reactive, computed, onMounted, toRef } from 'vue'
import { Search, Link, Star, StarFilled } from '@element-plus/icons-vue'
import { listReports, getReport, triggerReportGeneration } from '@/api/insight'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'

const authStore = useAuthStore()

const CATEGORY_LABELS = {
  model: '模型发布',
  product: '产品发布',
  industry: '行业动态',
  paper: '论文研究',
  tips: '技巧与观点',
}

const STAR_KEY = 'insight:ai_tools:starred'

const toolsResource = useAsyncResource(async (_, { signal }) => {
  const config = { signal, suppressToast: true }
  const reports = (await listReports({ report_type: 'ai_tools', page: 1, page_size: 30 }, config)).data.items || []
  const flat = []
  const details = await Promise.all(reports.map(report => getReport(report.id, config)))
  reports.forEach((report, index) => {
    const grouped = (details[index].data?.source_data || report.source_data || {}).grouped || {}
    for (const [category, items] of Object.entries(grouped)) {
      for (const item of items || []) flat.push({ ...item, _report_date: report.report_date, category, category_label: CATEGORY_LABELS[category] || '其他' })
    }
  })
  return { reports, tools: flat }
})
const reports = computed(() => toolsResource.data.value?.reports || [])
const tools = computed(() => toolsResource.data.value?.tools || [])
const loading = toolsResource.loading
const generating = ref(false)
const filterDraft = reactive({ query: '', tag: 'all', date: 'all' })
const appliedFilters = ref({ ...filterDraft })
const searchQuery = toRef(filterDraft, 'query'), tagFilter = toRef(filterDraft, 'tag'), dateFilter = toRef(filterDraft, 'date')
const pendingFilters = computed(() => JSON.stringify(filterDraft) !== JSON.stringify(appliedFilters.value))
function searchTools() { appliedFilters.value = { ...filterDraft } }
function resetFilters() { Object.assign(filterDraft, { query: '', tag: 'all', date: 'all' }); searchTools() }

const starredKeys = ref(new Set(JSON.parse(localStorage.getItem(STAR_KEY) || '[]')))

const canAdmin = computed(() => authStore.hasPermission('insight:admin'))

const tagOptions = computed(() => {
  const s = new Set()
  for (const t of tools.value) {
    if (t.tag) s.add(t.tag)
    else if (t.category_label) s.add(t.category_label)
  }
  return Array.from(s)
})

const dateOptions = computed(() => {
  const s = new Set()
  for (const r of reports.value) if (r.report_date) s.add(r.report_date)
  return Array.from(s).sort().reverse().map((d) => ({ value: d, label: d }))
})

const filteredTools = computed(() => {
  let list = tools.value
  if (appliedFilters.value.date !== 'all') list = list.filter((t) => t._report_date === appliedFilters.value.date)
  if (appliedFilters.value.tag !== 'all') list = list.filter((t) => (t.tag || t.category_label) === appliedFilters.value.tag)
  if (appliedFilters.value.query) {
    const q = appliedFilters.value.query.toLowerCase()
    list = list.filter((t) =>
      [(t.title || t.name), t.summary, t.description, t.tag, t.category_label]
        .filter(Boolean)
        .some((s) => String(s).toLowerCase().includes(q))
    )
  }
  return list
})

const groupedFilteredTools = computed(() => {
  const map = new Map()
  for (const t of filteredTools.value) {
    const key = t._report_date || 'unknown'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(t)
  }
  return Array.from(map.entries())
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([date, list]) => ({
      date,
      label: date === 'unknown' ? '未分组' : `${date} 速递`,
      tools: list,
    }))
})

function toolKey(t) {
  return t.url || t.source_url || `${t.title || t.name || ''}|${t._report_date}`
}

function isStarred(t) {
  return starredKeys.value.has(toolKey(t))
}

function toggleStar(t) {
  const k = toolKey(t)
  if (starredKeys.value.has(k)) starredKeys.value.delete(k)
  else starredKeys.value.add(k)
  localStorage.setItem(STAR_KEY, JSON.stringify(Array.from(starredKeys.value)))
  // 触发响应式
  starredKeys.value = new Set(starredKeys.value)
}

function loadAll() { return toolsResource.load() }

async function generateToday() {
  generating.value = true
  try {
    await triggerReportGeneration('ai_tools')
    await loadAll()
  } finally {
    generating.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.insight-page {
  display: flex;
  flex-direction: column;
  min-height: 540px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.ai-tools-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配 */
.insight-page .tools-toolbar,
.insight-page .tools-grid {
  position: relative;
  z-index: 1;
}

/* 工具栏面板：同款渐变玻璃（覆盖原白底） */
.tools-toolbar {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  padding: 12px 16px;
  margin-bottom: 16px;
}

.search-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.result-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
}

.tools-grid { min-height: 200px; }

.empty-tip {
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  margin-top: 6px;
}

.week-section { margin-bottom: 24px; }

.week-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--text-tertiary, #8b95a5);
  text-transform: uppercase;
  margin-bottom: 10px;
  padding: 0 4px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}

/* 玻璃质感由 .lg-card 提供（渐变磨砂 + 暖金彩色阴影 + hover 上浮），
   这里只留布局与本页专属 hover 描边 */
.tool-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.tool-card:hover {
  border-color: var(--color-gold, #d4af6e);
  box-shadow: 0 4px 14px rgba(176, 141, 79, 0.08);
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.card-title-row {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.card-title-row h4 {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #1a1a2e);
  margin: 0;
}

.card-tag {
  font-size: 11px;
  font-weight: 500;
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  padding: 2px 8px;
  border-radius: 6px;
}

.star-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  color: #d0d5dd;
  transition: color 0.15s, background-color 0.15s;
}

.star-btn:hover { background: #f5f2ee; }
.star-btn.active { color: var(--color-gold, #d4af6e); }

.card-summary {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary, #4a5568);
  margin: 0;
}

.card-link {
  font-size: 12px;
  color: var(--color-gold, #b08d4f);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  text-decoration: none;
  margin-top: 4px;
}

.card-link:hover { text-decoration: underline; }
</style>
