<template>
  <div class="asset-stats-page">
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
        <div class="stat-card">
          <div class="stat-label">总下载量</div>
          <div class="stat-value">{{ stats.total_downloads }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">今日下载</div>
          <div class="stat-value">{{ stats.today_downloads }}</div>
        </div>
        <div class="stat-card">
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

.stat-card {
  background: #fff;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  text-align: center;
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

.stats-panel {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
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
