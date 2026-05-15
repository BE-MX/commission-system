<template>
  <div class="daily-report-page">
    <!-- 深色头部 -->
    <div class="report-header-card">
      <div class="header-content">
        <div class="header-left">
          <div class="header-icon">
            <el-icon :size="24" color="#fff"><Document /></el-icon>
          </div>
          <div>
            <div class="header-title">安全库存日报</div>
            <div class="header-subtitle">每日 08:30 自动生成 · 库存状态总览</div>
          </div>
        </div>
        <div>
          <el-date-picker v-model="selectedDate" type="date" placeholder="选择日期" format="YYYY-MM-DD"
            value-format="YYYY-MM-DD" :clearable="false" style="width:160px" @change="loadData" />
        </div>
        <div v-if="reportData">
          <div class="dingtalk-status">
            <el-icon :size="16" :color="reportData.dingtalk_sent ? '#27ae60' : '#ccc'">
              <component :is="reportData.dingtalk_sent ? 'CircleCheckFilled' : 'WarningFilled'" />
            </el-icon>
            <span class="ding-label">钉钉推送</span>
            <el-tag :type="reportData.dingtalk_sent ? 'success' : 'info'" size="small" effect="dark">
              {{ reportData.dingtalk_sent ? '已发送' : '未发送' }}
            </el-tag>
            <span v-if="reportData.dingtalk_sent && reportData.sent_at" class="ding-time">
              {{ formatTime(reportData.sent_at) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 统计卡 -->
    <div v-if="reportData" class="stats-row">
      <div class="stat-card shortage">
        <div class="stat-bg-icon"><el-icon :size="60" color="rgba(231,76,60,0.06)"><WarningFilled /></el-icon></div>
        <div class="stat-inner">
          <div style="margin-bottom:8px;"><el-tag size="small" type="danger" effect="dark">● 紧缺</el-tag></div>
          <div class="stat-value">{{ reportData.shortage_count }}</div>
          <div class="stat-unit">个 SKU 低于安全库存</div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="stat-bg-icon"><el-icon :size="60" color="rgba(243,156,18,0.06)"><Timer /></el-icon></div>
        <div class="stat-inner">
          <div style="margin-bottom:8px;"><el-tag size="small" type="warning" effect="dark">● 预警</el-tag></div>
          <div class="stat-value">{{ reportData.warning_count }}</div>
          <div class="stat-unit">个 SKU 低于安全库存 × 1.5</div>
        </div>
      </div>
      <div class="stat-card sufficient">
        <div class="stat-bg-icon"><el-icon :size="60" color="rgba(39,174,96,0.06)"><CircleCheckFilled /></el-icon></div>
        <div class="stat-inner">
          <div style="margin-bottom:8px;"><el-tag size="small" type="success" effect="dark">● 充足</el-tag></div>
          <div class="stat-value">{{ reportData.sufficient_count }}</div>
          <div class="stat-unit">个 SKU 库存安全</div>
        </div>
      </div>
    </div>

    <!-- 空数据 -->
    <div v-else-if="!loading" class="no-data-card">
      <el-empty description="该日期暂无日报数据">
        <el-button v-if="authStore.hasPermission('stock:admin')" type="primary" @click="generateToday">
          手动生成日报
        </el-button>
      </el-empty>
    </div>

    <!-- 紧缺 SKU 表 -->
    <div v-if="reportData && reportData.shortage_skus?.length" class="table-section">
      <div class="section-header shortage-header">
        <div class="section-title">
          <el-icon :size="18" color="#e74c3c"><WarningFilled /></el-icon>
          <span>紧缺 SKU 列表</span>
          <el-tag size="small" type="danger">{{ reportData.shortage_skus.length }} 条</el-tag>
        </div>
      </div>
      <div class="card" style="border-radius:0 0 16px 16px;">
        <el-table :data="reportData.shortage_skus" style="width:100%" :header-cell-style="shortageHeaderStyle">
          <el-table-column type="index" label="#" width="50" align="center" />
          <el-table-column label="产品名" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="product-name-cell">
                <div class="product-name">{{ row.product_name }}</div>
                <div class="product-id">ID: {{ row.product_id }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="型号" prop="model" min-width="120" show-overflow-tooltip />
          <el-table-column label="可用库存" width="100" align="center">
            <template #default="{ row }"><span class="cell-danger">{{ Math.round(row.enable_count) }} 件</span></template>
          </el-table-column>
          <el-table-column label="安全库存" width="100" align="center">
            <template #default="{ row }"><span class="cell-normal">{{ row.safety_stock }} 件</span></template>
          </el-table-column>
          <el-table-column label="日均销量" width="100" align="center">
            <template #default="{ row }"><span class="cell-gold">{{ row.avg_daily_sales }}/天</span></template>
          </el-table-column>
          <el-table-column label="建议备货量" width="110" align="center">
            <template #default="{ row }"><span class="cell-suggest">{{ row.suggested_qty }} 件</span></template>
          </el-table-column>
          <el-table-column label="缺口" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="danger" effect="dark">-{{ row.safety_stock - row.enable_count }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 预警 SKU 表 -->
    <div v-if="reportData && reportData.warning_skus?.length" class="table-section">
      <div class="section-header warning-header">
        <div class="section-title">
          <el-icon :size="18" color="#f39c12"><Timer /></el-icon>
          <span>预警 SKU 列表</span>
          <el-tag size="small" type="warning">{{ reportData.warning_skus.length }} 条</el-tag>
        </div>
      </div>
      <div class="card" style="border-radius:0 0 16px 16px;">
        <el-table :data="reportData.warning_skus" style="width:100%" :header-cell-style="warningHeaderStyle">
          <el-table-column type="index" label="#" width="50" align="center" />
          <el-table-column label="产品名" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="product-name-cell">
                <div class="product-name">{{ row.product_name }}</div>
                <div class="product-id">ID: {{ row.product_id }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="型号" prop="model" min-width="120" show-overflow-tooltip />
          <el-table-column label="可用库存" width="100" align="center">
            <template #default="{ row }"><span class="cell-warning">{{ Math.round(row.enable_count) }} 件</span></template>
          </el-table-column>
          <el-table-column label="安全库存" width="100" align="center">
            <template #default="{ row }"><span class="cell-normal">{{ row.safety_stock }} 件</span></template>
          </el-table-column>
          <el-table-column label="日均销量" width="100" align="center">
            <template #default="{ row }"><span class="cell-gold">{{ row.avg_daily_sales }}/天</span></template>
          </el-table-column>
          <el-table-column label="建议备货量" width="110" align="center">
            <template #default="{ row }"><span class="cell-suggest">{{ row.suggested_qty }} 件</span></template>
          </el-table-column>
          <el-table-column label="余量" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="warning">{{ Math.round(row.enable_count - row.safety_stock) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, WarningFilled, Timer, CircleCheckFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { getLatestDailyReport, getDailyReportByDate, triggerDailyReport } from '@/api/stock'

const authStore = useAuthStore()
const loading = ref(false)
const selectedDate = ref('')
const reportData = ref(null)

function formatTime(iso) {
  try { return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) } catch { return iso }
}

function shortageHeaderStyle() {
  return { background: '#fef5f5', fontWeight: 600, color: '#5a2020' }
}
function warningHeaderStyle() {
  return { background: '#fefcf5', fontWeight: 600, color: '#5a3a10' }
}

async function loadData() {
  loading.value = true
  try {
    let res
    if (selectedDate.value) {
      res = await getDailyReportByDate(selectedDate.value)
    } else {
      res = await getLatestDailyReport()
    }
    reportData.value = res.data
  } catch (err) {
    // 404 为正常情况
    if (err.response?.status === 404) {
      reportData.value = null
    } else {
      ElMessage.error(err.message || '加载日报失败')
      reportData.value = null
    }
  } finally {
    loading.value = false
  }
}

async function generateToday() {
  try {
    const res = await triggerDailyReport({
      report_date: selectedDate.value || undefined,
      push_dingtalk: false,
    })
    ElMessage.success('日报已生成')
    reportData.value = res.data
  } catch (err) {
    ElMessage.error(err.message || '生成失败')
  }
}

onMounted(() => {
  selectedDate.value = new Date().toISOString().slice(0, 10)
  loadData()
})
</script>

<style scoped>
.daily-report-page { display: flex; flex-direction: column; gap: 20px; }

/* 深色头部 */
.report-header-card {
  background: linear-gradient(135deg, #1e1e2d 0%, #2d2b45 50%, #25253a 100%);
  border-radius: 16px; padding: 24px 28px; box-shadow: 0 4px 20px rgba(30,30,45,0.2);
  position: relative; overflow: hidden;
}
.report-header-card::after {
  content: ''; position: absolute; top: -50%; right: -10%; width: 300px; height: 300px;
  background: radial-gradient(circle, rgba(212,175,110,0.08) 0%, transparent 70%); pointer-events: none;
}
.header-content { display: flex; align-items: center; justify-content: space-between; position: relative; z-index: 1; }
.header-left { display: flex; align-items: center; gap: 14px; }
.header-icon { width: 48px; height: 48px; border-radius: 14px; background: linear-gradient(135deg, #d4af6e, #c9a05c); display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 15px rgba(212,175,110,0.3); }
.header-title { font-size: 20px; font-weight: 600; color: #fff; }
.header-subtitle { font-size: 13px; color: #8888a0; margin-top: 4px; }
.dingtalk-status { display: flex; align-items: center; gap: 8px; background: rgba(255,255,255,0.06); padding: 10px 18px; border-radius: 10px; }
.ding-label { font-size: 13px; color: #aaa; }
.ding-time { font-size: 12px; color: #8888a0; font-family: monospace; }

/* 统计卡 */
.stats-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.stat-card { background: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); display: flex; align-items: center; position: relative; overflow: hidden; }
.stat-bg-icon { position: absolute; right: 20px; top: 50%; transform: translateY(-50%); }
.stat-inner { position: relative; z-index: 1; }
.stat-value { font-size: 28px; font-weight: 700; color: #1e1e2d; line-height: 1.2; }
.stat-unit { font-size: 13px; color: #888; margin-top: 4px; }

/* 板块头 */
.table-section { display: flex; flex-direction: column; gap: 14px; }
.section-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-radius: 12px 12px 0 0; margin-bottom: -8px; }
.shortage-header { background: linear-gradient(90deg, #fef5f5, #fff); border-bottom: 2px solid #e74c3c; }
.warning-header { background: linear-gradient(90deg, #fefcf5, #fff); border-bottom: 2px solid #f39c12; }
.section-title { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 600; color: #1e1e2d; }

/* 空数据 */
.no-data-card { background: #ffffff; border-radius: 16px; padding: 60px 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); text-align: center; }

/* 卡片和表格通用 */
.card { background: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.product-name-cell { display: flex; flex-direction: column; }
.product-name { font-weight: 500; color: #1e1e2d; font-size: 14px; }
.product-id { font-size: 12px; color: #999; margin-top: 2px; }
.cell-danger { color: #e74c3c; font-weight: 600; }
.cell-warning { color: #f39c12; font-weight: 600; }
.cell-normal { color: #666; }
.cell-gold { color: #d4af6e; font-weight: 500; }
.cell-suggest { color: #e74c3c; font-weight: 600; }
</style>
