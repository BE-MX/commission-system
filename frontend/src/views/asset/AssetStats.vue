<template>
  <div class="asset-stats-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="asset-stats-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="toolbar">
      <h2 class="page-title">
        <el-icon><TrendCharts /></el-icon>
        素材下载统计
      </h2>
    </div>

    <div v-if="loading" class="loading-wrap">
      <el-skeleton :rows="5" animated />
    </div>

    <template v-else>
      <!-- 概览卡片 -->
      <div class="stats-cards">
        <div class="stat-card emphasis lg-card">
          <div class="stat-label">总下载量</div>
          <div class="stat-value">{{ stats.total_downloads }}</div>
        </div>
        <div class="stat-card lg-card">
          <div class="stat-label">今日下载</div>
          <div class="stat-value">{{ stats.today_downloads }}</div>
        </div>
        <div class="stat-card lg-card">
          <div class="stat-label">素材总数</div>
          <div class="stat-value">{{ stats.total_assets }}</div>
        </div>
      </div>

      <div class="stats-layout">
        <!-- 热门素材 -->
        <div class="stats-panel">
          <div class="panel-title">
            <el-icon><Trophy /></el-icon>
            热门素材 Top 10
          </div>
          <el-table :data="stats.top_assets" size="small" class="stats-table">
            <el-table-column type="index" width="40" />
            <el-table-column label="文件名" prop="file_name" show-overflow-tooltip sortable />
            <el-table-column label="类型" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="fileTypeTag(row.file_type)">
                  {{ fileTypeLabel(row.file_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="下载量" width="80" prop="download_count" sortable />
          </el-table>
        </div>

        <!-- 下载趋势 -->
        <div class="stats-panel">
          <div class="panel-title">
            <el-icon><TrendCharts /></el-icon>
            下载趋势（近14天）
          </div>
          <div class="trend-chart">
            <div class="trend-bars">
              <div
                v-for="item in stats.trend"
                :key="item.date"
                class="trend-bar-item"
              >
                <div class="trend-bar-wrap">
                  <div
                    class="trend-bar"
                    :style="{ height: getBarHeight(item.count) + '%' }"
                  >
                    <span class="trend-bar-value">{{ item.count }}</span>
                  </div>
                </div>
                <div class="trend-bar-label">{{ formatDateLabel(item.date) }}</div>
              </div>
            </div>
            <div v-if="stats.trend.length === 0" class="trend-empty">
              <el-empty description="暂无数据" />
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { TrendCharts, Trophy } from '@element-plus/icons-vue'
import { getDownloadStats } from '@/api/asset'

const loading = ref(false)
const stats = ref({
  total_downloads: 0,
  total_assets: 0,
  today_downloads: 0,
  top_assets: [],
  trend: [],
})

const maxTrendCount = ref(1)

async function loadStats() {
  loading.value = true
  try {
    const res = await getDownloadStats()
    const data = res.data || {}
    stats.value = {
      total_downloads: data.total_downloads || 0,
      total_assets: data.total_assets || 0,
      today_downloads: data.today_downloads || 0,
      top_assets: data.top_assets || [],
      trend: data.trend || [],
    }
    maxTrendCount.value = Math.max(
      1,
      ...(data.trend || []).map(t => t.count)
    )
  } catch (e) {
    ElMessage.error('加载统计数据失败')
  } finally {
    loading.value = false
  }
}

function getBarHeight(count) {
  if (!count) return 0
  return Math.max(5, (count / maxTrendCount.value) * 100)
}

function formatDateLabel(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function fileTypeLabel(type) {
  return { image: '图片', video: '视频', document: '文档' }[type] || type
}

function fileTypeTag(type) {
  return { image: 'success', video: 'warning', document: 'info' }[type] || ''
}

onMounted(() => {
  loadStats()
})
</script>

<style scoped>
.asset-stats-page {
  padding: 20px 28px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环 */
.asset-stats-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上（点名内容块） */
.asset-stats-page .toolbar,
.asset-stats-page .loading-wrap,
.asset-stats-page .stats-cards,
.asset-stats-page .stats-layout {
  position: relative;
  z-index: 1;
}

.toolbar {
  margin-bottom: 20px;
}

.page-title {
  font-size: 17px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.loading-wrap {
  padding: 40px;
}

/* 概览卡片 */
.stats-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

/* 概览卡片：玻璃质感由 .lg-card 提供（渐变磨砂 + 暖金彩色阴影 + hover 上浮），
   这里只留布局 */
.stat-card {
  padding: 24px;
  text-align: center;
}

/* 强调卡（总下载量）：金调渐变玻璃（scoped 优先级高于全局 .lg-card） */
.stat-card.emphasis {
  background: linear-gradient(165deg, rgba(255, 255, 255, 0.8) 0%, rgba(245, 203, 92, 0.16) 100%);
  border-color: rgba(212, 148, 28, 0.4);
}

.stat-label {
  font-size: 13px;
  color: #999;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: #d4941c;
}

/* 布局 */
.stats-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

/* 统计面板：同款渐变玻璃（覆盖原白底卡片） */
.stats-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  padding: 20px;
  overflow: hidden;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a2e;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.stats-table {
  width: 100%;
}

/* 表格融进玻璃：行/表头半透明，透出极光（本表无固定列） */
.stats-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 趋势图 */
.trend-chart {
  min-height: 300px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.trend-bars {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  height: 260px;
  padding-bottom: 30px;
}

.trend-bar-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
}

.trend-bar-wrap {
  width: 100%;
  height: 220px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.trend-bar {
  width: 100%;
  max-width: 32px;
  background: linear-gradient(180deg, #f5cb5c, #d4941c);
  border-radius: 4px 4px 0 0;
  min-height: 4px;
  position: relative;
  transition: height 0.3s ease;
}

.trend-bar-value {
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: #666;
  white-space: nowrap;
}

.trend-bar-label {
  font-size: 11px;
  color: #999;
  margin-top: 6px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
}

.trend-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (max-width: 1024px) {
  .stats-layout {
    grid-template-columns: 1fr;
  }
}
</style>
