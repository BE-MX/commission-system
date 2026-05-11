<template>
  <div class="insight-page report-page">
    <div class="insight-toolbar" v-if="canAdmin">
      <GlassButton variant="link" left-icon="Setting" @click="goSources">信源配置</GlassButton>
      <GlassButton variant="link" left-icon="RefreshRight" @click="refreshAll">刷新列表</GlassButton>
      <span class="toolbar-tip">本期信源抓取尚未实现,可由管理员从外部手动导入。</span>
    </div>

    <div class="insight-body">
      <aside class="report-tree">
        <div class="tree-header">
          <el-icon><Calendar /></el-icon>
          <span>历史日报</span>
          <span class="tree-count">{{ totalCount }}</span>
        </div>
        <div class="tree-content">
          <el-empty v-if="!loading && monthGroups.length === 0" description="暂无日报" :image-size="64" />
          <div v-for="grp in monthGroups" :key="grp.label" class="month-group">
            <button class="month-toggle" @click="toggleMonth(grp.label)">
              <el-icon class="month-arrow" :class="{ open: expandedMonths[grp.label] }"><ArrowRight /></el-icon>
              <span>{{ grp.label }}</span>
              <span class="month-count">{{ grp.children.length }}</span>
            </button>
            <div v-if="expandedMonths[grp.label]" class="day-list">
              <button
                v-for="d in grp.children"
                :key="d.id"
                class="day-item"
                :class="{ active: selectedId === d.id }"
                @click="selectReport(d.id)"
              >
                <el-icon><Document /></el-icon>
                <span>{{ d.label }}</span>
                <el-tag v-if="d.is_today" type="warning" size="small" effect="light">今日</el-tag>
              </button>
            </div>
          </div>
        </div>
      </aside>

      <section class="report-content">
        <div v-if="loading" class="content-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>加载中...</span>
        </div>
        <iframe
          v-else-if="selectedHtmlUrl"
          :key="selectedId"
          :src="selectedHtmlUrl"
          class="report-iframe"
          title="行业情报日报"
          sandbox="allow-same-origin"
        />
        <div v-else class="content-empty">
          <el-icon size="40"><Document /></el-icon>
          <p>选择左侧日期查看日报</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Calendar, ArrowRight, Document, Loading } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { listReports, getReportHtmlUrl } from '@/api/insight'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const router = useRouter()

const reports = ref([])
const totalCount = ref(0)
const loading = ref(false)
const selectedId = ref(null)
const expandedMonths = ref({})

const canAdmin = computed(() => authStore.hasPermission('insight:admin'))

const monthGroups = computed(() => {
  const groups = new Map()
  const todayStr = new Date().toISOString().slice(0, 10)
  for (const r of reports.value) {
    if (!r.report_date) continue
    const [y, m, d] = r.report_date.split('-')
    const key = `${y}年${parseInt(m, 10)}月`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push({
      id: r.id,
      label: `${m}-${d}${r.report_date === todayStr ? ' (今日)' : ''}`,
      is_today: r.report_date === todayStr,
      raw_date: r.report_date,
    })
  }
  return Array.from(groups.entries()).map(([label, children]) => ({ label, children }))
})

const selectedHtmlUrl = computed(() => (selectedId.value ? getReportHtmlUrl(selectedId.value) : ''))

async function refreshAll() {
  loading.value = true
  try {
    const res = await listReports({ report_type: 'industry_daily', page: 1, page_size: 200 })
    reports.value = res.data.items || []
    totalCount.value = res.data.total || 0
    if (monthGroups.value.length > 0) {
      const firstMonth = monthGroups.value[0].label
      expandedMonths.value[firstMonth] = true
      const firstReport = monthGroups.value[0].children[0]
      if (firstReport && !selectedId.value) selectedId.value = firstReport.id
    }
  } finally {
    loading.value = false
  }
}

function toggleMonth(label) {
  expandedMonths.value[label] = !expandedMonths.value[label]
}

function selectReport(id) {
  selectedId.value = id
}

function goSources() {
  router.push('/insight/sources')
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

.insight-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 0 12px;
  flex-shrink: 0;
}

.toolbar-tip {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  font-style: italic;
}

.insight-body {
  display: flex;
  gap: 16px;
  flex: 1;
  min-height: 0;
}

.report-tree {
  width: 240px;
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
  flex-shrink: 0;
}

.tree-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
  font-weight: 500;
  background: #f5f2ee;
  padding: 1px 8px;
  border-radius: 8px;
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.month-group {
  margin-bottom: 4px;
}

.month-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #4a5568);
  transition: background 0.15s;
}

.month-toggle:hover {
  background: #f5f2ee;
}

.month-arrow {
  transition: transform 0.2s;
  font-size: 12px;
}

.month-arrow.open {
  transform: rotate(90deg);
}

.month-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
  font-weight: 500;
}

.day-list {
  margin-left: 14px;
  padding-left: 8px;
  border-left: 1px solid var(--border-color, #e5dfd6);
  margin-top: 2px;
}

.day-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  transition: all 0.15s;
  text-align: left;
}

.day-item:hover {
  background: #fafbfe;
  color: var(--text-secondary, #4a5568);
}

.day-item.active {
  background: rgba(212, 175, 110, 0.1);
  color: var(--color-gold, #b08d4f);
  font-weight: 600;
}

.report-content {
  flex: 1;
  background: #fff;
  border: 1px solid var(--border-color, #e5dfd6);
  border-radius: 12px;
  overflow: hidden;
  position: relative;
}

.report-iframe {
  width: 100%;
  height: 100%;
  border: none;
}

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
</style>
