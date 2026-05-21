<template>
  <div class="page-wrapper">
    <div class="page-header">
      <h1>行业情报速览</h1>
      <div class="header-actions">
        <el-button type="primary" @click="showGenerateDialog = true" v-if="authStore.hasPermission('insight:admin')">
          <el-icon><Plus /></el-icon> 新建速览
        </el-button>
        <el-button @click="showScheduleDialog = true" v-if="authStore.hasPermission('insight:admin')">
          <el-icon><Setting /></el-icon> 定时设置
        </el-button>
      </div>
    </div>

    <!-- 报告卡片列表 -->
    <div class="report-cards" v-loading="loading">
      <el-empty v-if="reports.length === 0" description="暂无速览报告" />

      <div v-for="report in reports" :key="report.id" class="report-card" :class="{ pinned: report.is_pinned }">
        <div class="card-header">
          <div class="card-title">
            <el-icon v-if="report.is_pinned" class="pin-icon"><Top /></el-icon>
            <span>{{ report.report_title }}</span>
          </div>
          <el-tag :type="statusType(report.status)" size="small">{{ statusLabel(report.status) }}</el-tag>
        </div>
        <div class="card-meta">
          <span>日期范围: {{ report.date_range_start || '-' }} ~ {{ report.date_range_end || '-' }}</span>
          <span>条目: {{ report.item_count }} 条</span>
          <span>{{ report.trigger_type === 'scheduled' ? '自动生成' : '手动生成' }}</span>
        </div>
        <div class="card-actions">
          <el-button link type="primary" @click="toggleExpand(report)">
            {{ expandedId === report.id ? '收起' : '展开预览' }}
          </el-button>
          <el-button link type="primary" @click="openInNewTab(report)">独立打开</el-button>
          <el-button link type="danger" @click="deleteReport(report.id)" v-if="authStore.hasPermission('insight:admin')">删除</el-button>
          <el-button link @click="pinReport(report.id, !report.is_pinned)" v-if="authStore.hasPermission('insight:admin')">
            {{ report.is_pinned ? '取消置顶' : '置顶' }}
          </el-button>
        </div>
        <div v-if="expandedId === report.id" class="preview-area">
          <iframe v-if="report.status === 'completed'" :src="`/api/insight/reports/intelligence/${report.id}/html`" class="report-iframe" />
          <div v-else class="preview-loading">
            <el-skeleton :rows="6" animated />
          </div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      @change="loadReports"
      class="pagination"
    />

    <!-- 新建速览弹窗 -->
    <el-dialog v-model="showGenerateDialog" title="新建行业情报速览" width="600px">
      <el-form :model="generateForm" label-width="100px">
        <el-form-item label="标题">
          <el-input v-model="generateForm.report_title" placeholder="行业情报速览 YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker
            v-model="generateDateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
          />
        </el-form-item>
        <el-form-item label="选材模式">
          <el-radio-group v-model="generateForm.mode">
            <el-radio-button label="rule_based">规则选材</el-radio-button>
            <el-radio-button label="manual_select">手动选材</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="generateForm.mode === 'rule_based'">
          <el-form-item label="最低可信度">
            <el-slider v-model="generateForm.min_credibility_score" :min="1" :max="5" :step="1" show-stops />
          </el-form-item>
          <el-form-item label="条目上限">
            <el-input-number v-model="generateForm.max_items_total" :min="5" :max="100" />
          </el-form-item>
          <el-form-item label="仅精选">
            <el-switch v-model="generateForm.include_featured_only" />
          </el-form-item>
        </template>
        <el-form-item label="报告深度">
          <el-select v-model="generateForm.report_depth">
            <el-option label="快报 (500字内)" value="brief" />
            <el-option label="标准 (1000-1500字)" value="standard" />
            <el-option label="深度 (2000字+)" value="deep" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGenerateDialog = false">取消</el-button>
        <el-button type="primary" @click="submitGenerate" :loading="generating">开始生成</el-button>
      </template>
    </el-dialog>

    <!-- 定时设置弹窗 (简化版) -->
    <el-dialog v-model="showScheduleDialog" title="定时生成规则" width="700px">
      <div class="schedule-header">
        <el-button type="primary" size="small" @click="showAddRule = true">+ 新建规则</el-button>
      </div>
      <el-table :data="scheduleRules" size="small">
        <el-table-column prop="rule_name" label="规则名" />
        <el-table-column prop="cron_expression" label="Cron" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link size="small" @click="toggleRule(row.id)">{{ row.is_active ? '停用' : '启用' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Setting, Top } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  listIntelligenceReports,
  generateIntelligence,
  deleteIntelligenceReport,
  pinIntelligenceReport,
  listScheduleRules,
  toggleScheduleRule,
} from '@/api/insight'

const authStore = useAuthStore()

// 状态
const loading = ref(false)
const reports = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const expandedId = ref(null)

// 生成弹窗
const showGenerateDialog = ref(false)
const generating = ref(false)
const generateDateRange = ref([])
const generateForm = reactive({
  report_title: '',
  mode: 'rule_based',
  min_credibility_score: 3,
  max_items_total: 30,
  include_featured_only: false,
  report_depth: 'standard',
  output_language: 'zh-CN',
})

// 定时规则
const showScheduleDialog = ref(false)
const showAddRule = ref(false)
const scheduleRules = ref([])

// 加载报告
async function loadReports() {
  loading.value = true
  try {
    const res = await listIntelligenceReports({
      page: page.value,
      page_size: pageSize.value,
    })
    if (res.data?.code === 200) {
      reports.value = res.data.data.items
      total.value = res.data.data.total
    }
  } finally {
    loading.value = false
  }
}

// 展开/收起
function toggleExpand(report) {
  expandedId.value = expandedId.value === report.id ? null : report.id
}

// 独立打开
function openInNewTab(report) {
  window.open(`/api/insight/reports/intelligence/${report.id}/html`, '_blank')
}

// 生成
async function submitGenerate() {
  if (generateDateRange.value?.length !== 2) {
    ElMessage.warning('请选择日期范围')
    return
  }
  generating.value = true
  try {
    const data = {
      ...generateForm,
      date_range_start: generateDateRange.value[0],
      date_range_end: generateDateRange.value[1],
    }
    if (!data.report_title) {
      data.report_title = `行业情报速览 ${data.date_range_start}`
    }
    const res = await generateIntelligence(data)
    if (res.data?.code === 200) {
      ElMessage.success('报告生成中，请稍后查看')
      showGenerateDialog.value = false
      loadReports()
    }
  } catch {
    ElMessage.error('生成失败')
  } finally {
    generating.value = false
  }
}

// 删除
async function deleteReport(id) {
  try {
    await ElMessageBox.confirm('确定删除此报告？', '确认', { type: 'warning' })
    await deleteIntelligenceReport(id)
    ElMessage.success('已删除')
    loadReports()
  } catch {
    // 取消
  }
}

// 置顶
async function pinReport(id, isPinned) {
  try {
    await pinIntelligenceReport(id, isPinned)
    ElMessage.success(isPinned ? '已置顶' : '已取消置顶')
    loadReports()
  } catch {
    ElMessage.error('操作失败')
  }
}

// 定时规则
async function loadScheduleRules() {
  try {
    const res = await listScheduleRules()
    if (res.data?.code === 200) {
      scheduleRules.value = res.data.data
    }
  } catch {
    // ignore
  }
}

async function toggleRule(id) {
  try {
    await toggleScheduleRule(id)
    loadScheduleRules()
  } catch {
    ElMessage.error('操作失败')
  }
}

// 辅助
function statusType(status) {
  const map = { pending: 'info', generating: 'warning', completed: 'success', failed: 'danger' }
  return map[status] || 'info'
}
function statusLabel(status) {
  const map = { pending: '待生成', generating: '生成中', completed: '已完成', failed: '失败' }
  return map[status] || status
}

onMounted(() => {
  loadReports()
  loadScheduleRules()
})
</script>

<style scoped>
.page-wrapper {
  padding: 24px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h1 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.report-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.report-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  border: 1px solid transparent;
}
.report-card.pinned {
  border-color: #f59e0b;
  background: #fffbeb;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.card-title {
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.pin-icon {
  color: #f59e0b;
}
.card-meta {
  font-size: 13px;
  color: #909399;
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}
.card-actions {
  display: flex;
  gap: 8px;
}
.preview-area {
  margin-top: 16px;
  border-top: 1px solid #e4e7ed;
  padding-top: 16px;
}
.report-iframe {
  width: 100%;
  height: 600px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
}
.preview-loading {
  padding: 24px;
}
.pagination {
  margin-top: 24px;
  justify-content: flex-end;
}
.schedule-header {
  margin-bottom: 12px;
  text-align: right;
}
</style>
