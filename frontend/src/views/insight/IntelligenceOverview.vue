<template>
  <div class="page-wrapper">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="insight-overview-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <div>
        <h1>行业情报速览</h1>
        <p>按日期范围汇总行业情报条目，支持定时生成与置顶查看。</p>
      </div>
    </div>

    <!-- 列表卡片：操作行 + 报告卡片 + 分页（Action Bar Spec；内容物为卡片流而非表格） -->
    <section ref="panelRef" class="table-card overview-panel">
      <div class="action-bar">
        <GlassButton variant="primary" :left-icon="Plus" @click="showGenerateDialog = true" v-if="authStore.hasPermission('insight:admin')">
          新建速览
        </GlassButton>
        <GlassButton variant="secondary" :left-icon="Setting" @click="showScheduleDialog = true" v-if="authStore.hasPermission('insight:admin')">
          定时设置
        </GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="loadReports"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus :error="listPageState.errorMessage.value" :loading="loading" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="loadReports" />
      <!-- 报告卡片列表 -->
      <div class="report-cards" v-loading="loading">
        <el-empty v-if="!loading && !listPageState.error.value && reports.length === 0" :image-size="96" description="暂无数据" />

      <div v-for="report in reports" :key="report.id" class="report-card lg-card" :class="{ pinned: report.is_pinned }">
        <div class="card-header">
          <div class="card-title">
            <el-icon v-if="report.is_pinned" class="pin-icon"><Top /></el-icon>
            <span>{{ report.report_title }}</span>
          </div>
          <StatusBadge :type="statusType(report.status)" size="small">{{ statusLabel(report.status) }}</StatusBadge>
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
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </section>

    <!-- 新建速览弹窗 -->
    <el-dialog v-model="showGenerateDialog" title="新建行业情报速览" width="640px">
      <el-form label-position="top" :model="generateForm">
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
    <el-dialog v-model="showScheduleDialog" title="定时生成规则" width="760px">
      <ListPageStatus :error="rulesResource.errorMessage.value" :loading="rulesResource.loading.value" :has-data="rulesResource.hasData.value" @retry="loadScheduleRules" />
      <div class="schedule-header">
        <el-button type="primary" @click="showAddRule = true">+ 新建规则</el-button>
      </div>
      <el-table :data="scheduleRules" border class="list-table">
        <el-table-column prop="rule_name" label="规则名" />
        <el-table-column prop="cron_expression" label="Cron" />
        <el-table-column label="状态" min-width="110">
          <template #default="{ row }">
            <StatusBadge :value="row.is_active" :dictionary="ENABLED_STATUS" size="small" />
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="120">
          <template #default="{ row }">
            <el-button link @click="toggleRule(row.id)">{{ row.is_active ? '停用' : '启用' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { useAsyncResource } from '@/composables/useAsyncResource'

import { ENABLED_STATUS } from '@/utils/status'
import { msgWarning, msgSuccessText, msgError, confirmAction } from '@/utils/feedback'
import { ref, reactive, onMounted } from 'vue'

import { Plus, Setting, Top } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
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
const listPageState = useListPage(async (params, { signal }) => (await listIntelligenceReports(params, { signal, suppressToast: true })).data)
const { loading, list: reports, total, page, pageSize, fetchList: loadReports, handlePageChange, handleSizeChange } = listPageState
const expandedId = ref(null)

// 卡片流列表无可隐藏列，列设置图标不渲染；密度/全屏偏好仍按页面键持久化
const columnDefs = []
const { density, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('intelligence-overview', columnDefs)

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
const rulesResource = useAsyncResource(async (_, { signal }) => (await listScheduleRules(undefined, { signal, suppressToast: true })).data, { initialData: [] })
const scheduleRules = rulesResource.data

// 加载报告


// 分页：每页条数变化先回第 1 页


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
    msgWarning('请选择日期范围')
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
    if (res.code === 200) {
      msgSuccessText('报告生成中，请稍后查看')
      showGenerateDialog.value = false
      await listPageState.refreshCreate()
    }
  } catch (error) {
    msgError('生成失败', error)
  } finally {
    generating.value = false
  }
}

// 删除
async function deleteReport(id) {
  try {
    await confirmAction('确定删除此报告？', '确认', { type: 'warning' })
    await deleteIntelligenceReport(id)
    msgSuccessText('已删除')
    await listPageState.refreshRemove()
  } catch {
    // 取消
  }
}

// 置顶
async function pinReport(id, isPinned) {
  try {
    await pinIntelligenceReport(id, isPinned)
    msgSuccessText(isPinned ? '已置顶' : '已取消置顶')
    await listPageState.refreshUpdate()
  } catch (error) {
    msgError('操作失败', error)
  }
}

// 定时规则
function loadScheduleRules() { return rulesResource.load() }

async function toggleRule(id) {
  try {
    await toggleScheduleRule(id)
    loadScheduleRules()
  } catch (error) {
    msgError('操作失败', error)
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
  loadScheduleRules()
})
</script>

<style scoped>
.page-wrapper {
  padding: 24px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.insight-overview-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   会覆盖就地渲染的 el-dialog 的 .el-overlay position: fixed */
.page-wrapper .page-header,
.page-wrapper .overview-panel {
  position: relative;
  z-index: 1;
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
.page-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}
/* 列表面板：同款渐变玻璃（scoped 覆盖全局 .table-card 白底）；
   操作行/分页均为全局规范类（app.css .table-card > …），本页不覆写 */
.overview-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}
/* 全屏态：面板自身滚动（.table-card 默认 overflow:hidden） */
.overview-panel:fullscreen {
  overflow: auto;
}
.report-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 14px;
}
/* 玻璃质感由 .lg-card 提供（渐变磨砂 + 暖金彩色阴影 + hover 上浮），这里只留布局 */
.report-card {
  padding: 20px 24px;
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
.schedule-header {
  margin-bottom: 12px;
  text-align: right;
}
</style>
