<template>
  <div class="insight-page report-page">
    <div class="insight-body">
      <aside class="report-tree">
        <div class="tree-header">
          <el-icon><DataAnalysis /></el-icon>
          <span>历史报告</span>
          <span class="tree-count">{{ totalCount }}</span>
        </div>
        <div class="tree-content">
          <el-empty v-if="!loading && reports.length === 0" description="暂无内部报告" :image-size="64">
            <p class="empty-tip">由 ACCIO WORK 自动推送或管理员导入</p>
          </el-empty>
          <div v-for="grp in groupedReports" :key="grp.label" class="type-group">
            <button class="type-toggle" @click="toggleType(grp.key)">
              <el-icon class="type-arrow" :class="{ open: expandedTypes[grp.key] }"><ArrowRight /></el-icon>
              <span>{{ grp.label }}</span>
              <span class="type-count">{{ grp.children.length }}</span>
            </button>
            <div v-if="expandedTypes[grp.key]" class="month-list">
              <div v-for="m in grp.children" :key="m.label" class="month-sub">
                <div class="month-label">{{ m.label }}</div>
                <button
                  v-for="r in m.reports"
                  :key="r.id"
                  class="day-item"
                  :class="{ active: selectedId === r.id }"
                  @click="selectReport(r.id)"
                >
                  <el-icon><Document /></el-icon>
                  <div class="day-info">
                    <div>{{ r.title || r.report_date }}</div>
                    <div class="day-sub">{{ r.report_date }}</div>
                  </div>
                </button>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <section class="report-content">
        <div v-if="htmlLoading" class="content-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>加载中...</span>
        </div>
        <div
          v-else-if="htmlContent"
          :key="selectedId"
          class="report-html"
          v-html="htmlContent"
        />
        <div v-else class="content-empty">
          <el-icon size="40"><DataAnalysis /></el-icon>
          <p>选择左侧报告查看</p>
          <p class="empty-tip-small">含店铺经营、竞品分析、询盘分析三类</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { DataAnalysis, ArrowRight, Document, Loading } from '@element-plus/icons-vue'
import { listReports, getReportHtml } from '@/api/insight'

const TYPE_LABELS = {
  shop_analysis: '店铺经营报告',
  competitor_analysis: '竞品追踪分析',
  inquiry_analysis: '询盘分析报告',
}

const reports = ref([])
const totalCount = ref(0)
const loading = ref(false)
const selectedId = ref(null)
const expandedTypes = ref({})
const htmlContent = ref('')
const htmlLoading = ref(false)

const groupedReports = computed(() => {
  const byType = new Map()
  for (const r of reports.value) {
    if (!byType.has(r.report_type)) byType.set(r.report_type, [])
    byType.get(r.report_type).push(r)
  }
  return Array.from(byType.entries()).map(([typeKey, items]) => {
    // 按月份再分组
    const monthMap = new Map()
    for (const r of items) {
      if (!r.report_date) continue
      const [y, m] = r.report_date.split('-')
      const monthKey = `${y}年${parseInt(m, 10)}月`
      if (!monthMap.has(monthKey)) monthMap.set(monthKey, [])
      monthMap.get(monthKey).push(r)
    }
    return {
      key: typeKey,
      label: TYPE_LABELS[typeKey] || typeKey,
      children: Array.from(monthMap.entries()).map(([label, reports]) => ({ label, reports })),
    }
  })
})

async function loadHtml() {
  if (!selectedId.value) {
    htmlContent.value = ''
    return
  }
  htmlLoading.value = true
  try {
    const res = await getReportHtml(selectedId.value)
    htmlContent.value = res || ''
  } catch (e) {
    htmlContent.value = `<p style="color:#999;padding:20px;">加载失败: ${e.message || '未知错误'}</p>`
  } finally {
    htmlLoading.value = false
  }
}

async function refreshAll() {
  loading.value = true
  try {
    const res = await listReports({
      report_type: 'shop_analysis,competitor_analysis,inquiry_analysis',
      page: 1,
      page_size: 200,
    })
    reports.value = res.data.items || []
    totalCount.value = res.data.total || 0
    // 默认展开所有类型
    for (const t of Object.keys(TYPE_LABELS)) expandedTypes.value[t] = true
    if (reports.value.length > 0 && !selectedId.value) {
      selectedId.value = reports.value[0].id
      await loadHtml()
    }
  } finally {
    loading.value = false
  }
}

function toggleType(key) {
  expandedTypes.value[key] = !expandedTypes.value[key]
}

function selectReport(id) {
  selectedId.value = id
  loadHtml()
}

onMounted(refreshAll)
</script>

<style scoped>
.insight-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 130px);
  min-height: 540px;
}

.insight-body {
  display: flex;
  gap: 16px;
  flex: 1;
  min-height: 0;
}

.report-tree {
  width: 280px;
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.tree-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #e5dfd6);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
}

.tree-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
  background: #f5f2ee;
  padding: 1px 8px;
  border-radius: 8px;
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.empty-tip {
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  margin-top: 6px;
}

.type-group { margin-bottom: 6px; }

.type-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #4a5568);
  transition: background 0.15s;
}

.type-toggle:hover { background: #f5f2ee; }

.type-arrow { transition: transform 0.2s; font-size: 12px; }
.type-arrow.open { transform: rotate(90deg); }

.type-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
}

.month-list { margin-left: 14px; padding-left: 8px; border-left: 1px solid var(--border-color, #e5dfd6); margin-top: 2px; }

.month-sub { margin-bottom: 4px; }

.month-label {
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
  padding: 4px 10px;
  font-weight: 500;
}

.day-item {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 10px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
  color: var(--text-tertiary, #8b95a5);
}

.day-item:hover { background: #fafbfe; color: var(--text-secondary, #4a5568); }

.day-item.active {
  background: rgba(212, 175, 110, 0.1);
  color: var(--color-gold, #b08d4f);
}

.day-info { flex: 1; min-width: 0; }
.day-info > div:first-child {
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.day-sub { font-size: 10px; opacity: 0.7; margin-top: 1px; }

.report-content {
  flex: 1;
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 12px;
  overflow: hidden;
  position: relative;
}

.report-html {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  padding: 24px;
  box-sizing: border-box;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  line-height: 1.7;
  color: #1a1a2e;
  word-break: break-word;
  overflow-wrap: break-word;
  min-width: 0;
}
.report-html :deep(h1) { font-size: 22px; font-weight: 700; margin-bottom: 6px; color: #1a1a2e; }
.report-html :deep(.meta) { font-size: 12px; color: #8b95a5; margin-bottom: 20px; }
.report-html :deep(h2) { font-size: 18px; font-weight: 700; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 2px solid #d4af6e; color: #1a1a2e; }
.report-html :deep(table) { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
.report-html :deep(th), .report-html :deep(td) { padding: 8px 12px; text-align: left; border-bottom: 1px solid #e2e5ef; word-break: break-word; }
.report-html :deep(th) { background: #fafbfe; font-weight: 600; color: #5a6372; font-size: 12px; }
.report-html :deep(.card) { border: 1px solid #e2e5ef; border-radius: 10px; padding: 14px; margin: 10px 0; background: #fafbfe; }
.report-html :deep(.card h4) { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: #1a1a2e; }
.report-html :deep(.card p) { font-size: 12px; color: #8b95a5; line-height: 1.6; }
.report-html :deep(.source) { font-size: 11px; color: #a0aec0; margin-top: 8px; word-break: break-all; }

.content-loading,
.content-empty {
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

.empty-tip-small {
  font-size: 11px;
  opacity: 0.8;
}
</style>
