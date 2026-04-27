<template>
  <div>
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- Tab 1: 待确认任务 -->
      <el-tab-pane label="待确认任务" name="pending">
        <el-table
          ref="pendingTableRef"
          :data="pendingData"
          v-loading="pendingLoading"
          stripe
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="request_no" label="预约编号" width="160" show-overflow-tooltip />
          <el-table-column prop="customer_name" label="客户名称" width="130" show-overflow-tooltip />
          <el-table-column prop="salesperson_name" label="业务员" width="90" />
          <el-table-column label="拍摄类型" width="100">
            <template #default="{ row }">{{ SHOOT_TYPE_MAP[row.shoot_type] || row.shoot_type }}</template>
          </el-table-column>
          <el-table-column label="期望日期" width="200">
            <template #default="{ row }">{{ row.expect_start_date }} ~ {{ row.expect_end_date }}</template>
          </el-table-column>
          <el-table-column label="优先级" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" size="small" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="170" show-overflow-tooltip />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openConfirmDialog(row)">确认排期</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="pagination"
          v-model:current-page="pendingPage"
          v-model:page-size="pendingPageSize"
          :total="pendingTotal"
          layout="total, prev, pager, next"
          @current-change="fetchPending"
        />
      </el-tab-pane>

      <!-- Tab 2: 排期任务 -->
      <el-tab-pane label="排期任务" name="scheduled">
        <el-table
          ref="scheduledTableRef"
          :data="scheduledData"
          v-loading="scheduledLoading"
          stripe
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="request_no" label="预约编号" width="160" show-overflow-tooltip />
          <el-table-column prop="customer_name" label="客户名称" width="130" show-overflow-tooltip />
          <el-table-column label="拍摄类型" width="100">
            <template #default="{ row }">{{ SHOOT_TYPE_MAP[row.shoot_type] || row.shoot_type }}</template>
          </el-table-column>
          <el-table-column prop="designer_name" label="设计师" width="100" />
          <el-table-column label="排期日期" width="200">
            <template #default="{ row }">{{ row.scheduled_start || '-' }} ~ {{ row.scheduled_end || '-' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="TASK_STATUS_TAG[row.status]" size="small" effect="plain">
                {{ TASK_STATUS_MAP[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'scheduled'"
                link type="primary" size="small"
                @click="handleTaskAction(row, 'start')"
              >开始</el-button>
              <el-button
                v-if="row.status === 'in_progress'"
                link type="success" size="small"
                @click="handleTaskAction(row, 'complete')"
              >完成</el-button>
              <el-button
                v-if="['scheduled', 'in_progress'].includes(row.status)"
                link type="danger" size="small"
                @click="handleTaskAction(row, 'cancel')"
              >取消</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="pagination"
          v-model:current-page="scheduledPage"
          v-model:page-size="scheduledPageSize"
          :total="scheduledTotal"
          layout="total, prev, pager, next"
          @current-change="fetchScheduled"
        />
      </el-tab-pane>

      <!-- Tab 3: 设计师管理 -->
      <el-tab-pane label="设计师管理" name="designers">
        <el-table
          :data="designerData"
          v-loading="designerLoading"
          stripe
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="name" label="姓名" width="120" />
          <el-table-column prop="skills" label="技能" min-width="200">
            <template #default="{ row }">
              <el-tag
                v-for="skill in (row.skills || [])"
                :key="skill"
                size="small"
                effect="plain"
                style="margin-right: 4px"
              >{{ SHOOT_TYPE_MAP[skill] || skill }}</el-tag>
              <span v-if="!row.skills?.length" class="text-muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="max_daily_tasks" label="日最大任务数" width="120" align="center" />
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small" effect="plain">
                {{ row.is_active ? '在职' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab 4: 不可用日期 -->
      <el-tab-pane label="不可用日期" name="unavailable" lazy>
        <DesignCalendarConfig />
      </el-tab-pane>

      <!-- Tab 5: 容量配置 -->
      <el-tab-pane label="容量配置" name="capacity" lazy>
        <DesignCapacityConfig />
      </el-tab-pane>
    </el-tabs>

    <!-- Confirm scheduling dialog -->
    <el-dialog
      v-model="confirmVisible"
      title="确认排期"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form :model="confirmForm" label-width="90px">
        <el-form-item label="客户">
          <span>{{ confirmRow?.customer_name }}</span>
        </el-form-item>
        <el-form-item label="设计师" required>
          <el-select v-model="confirmForm.designer_id" placeholder="请选择设计师" style="width: 100%">
            <el-option
              v-for="d in designerData"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="排期日期" required>
          <el-date-picker
            v-model="confirmForm.dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="confirmForm.comment" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="confirmVisible = false">取消</el-button>
        <el-button type="primary" @click="submitConfirm" :loading="confirming">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getRequests, getTaskList, getDesigners, actionRequest, rescheduleTask } from '@/api/design'
import DesignCalendarConfig from '@/components/design/DesignCalendarConfig.vue'
import DesignCapacityConfig from '@/components/design/DesignCapacityConfig.vue'

const SHOOT_TYPE_MAP = {
  product_photo: '产品图',
  model_photo: '模特图',
  video: '视频',
  product_video: '产品视频',
  other: '其他',
}
const TASK_STATUS_MAP = {
  scheduled: '已排期',
  in_progress: '进行中',
  completed: '已完成',
  cancelled: '已取消',
}
const TASK_STATUS_TAG = {
  scheduled: '',
  in_progress: '',
  completed: 'success',
  cancelled: 'info',
}

const activeTab = ref('pending')
const tabMaxHeight = ref(500)

// --- Pending tab ---
const pendingTableRef = ref()
const pendingData = ref([])
const pendingLoading = ref(false)
const pendingPage = ref(1)
const pendingPageSize = ref(20)
const pendingTotal = ref(0)

async function fetchPending() {
  pendingLoading.value = true
  try {
    const res = await getRequests({
      status: 'pending_design',
      page: pendingPage.value,
      page_size: pendingPageSize.value,
      operator_id: 1,
      operator_role: 'design_staff',
    })
    const data = res.data
    pendingData.value = data?.items || data || []
    pendingTotal.value = data?.total || 0
  } finally {
    pendingLoading.value = false
  }
}

// --- Scheduled tab ---
const scheduledTableRef = ref()
const scheduledData = ref([])
const scheduledLoading = ref(false)
const scheduledPage = ref(1)
const scheduledPageSize = ref(20)
const scheduledTotal = ref(0)

async function fetchScheduled() {
  scheduledLoading.value = true
  try {
    const res = await getTaskList({
      status: 'scheduled,in_progress',
      page: scheduledPage.value,
      page_size: scheduledPageSize.value,
      operator_id: 1,
      operator_role: 'design_staff',
    })
    const data = res.data
    scheduledData.value = data?.items || data || []
    scheduledTotal.value = data?.total || 0
  } finally {
    scheduledLoading.value = false
  }
}

// --- Designers tab ---
const designerData = ref([])
const designerLoading = ref(false)

async function fetchDesigners() {
  designerLoading.value = true
  try {
    const res = await getDesigners()
    designerData.value = res.data || []
  } finally {
    designerLoading.value = false
  }
}

// --- Tab change ---
function onTabChange(tab) {
  if (tab === 'pending') fetchPending()
  else if (tab === 'scheduled') fetchScheduled()
  else if (tab === 'designers') fetchDesigners()
}

// --- Confirm scheduling dialog ---
const confirmVisible = ref(false)
const confirmRow = ref(null)
const confirming = ref(false)
const confirmForm = reactive({
  designer_id: null,
  dateRange: null,
  comment: '',
})

function openConfirmDialog(row) {
  confirmRow.value = row
  confirmForm.designer_id = null
  confirmForm.dateRange = row.expect_start_date && row.expect_end_date
    ? [row.expect_start_date, row.expect_end_date]
    : null
  confirmForm.comment = ''
  confirmVisible.value = true
  // Ensure designers loaded for the select
  if (!designerData.value.length) fetchDesigners()
}

async function submitConfirm() {
  if (!confirmForm.designer_id) {
    ElMessage.warning('请选择设计师')
    return
  }
  if (!confirmForm.dateRange || confirmForm.dateRange.length !== 2) {
    ElMessage.warning('请选择排期日期')
    return
  }
  confirming.value = true
  try {
    await actionRequest(confirmRow.value.id, {
      action: 'confirm',
      designer_id: confirmForm.designer_id,
      scheduled_start: confirmForm.dateRange[0],
      scheduled_end: confirmForm.dateRange[1],
      comment: confirmForm.comment,
      operator_id: 1,
      operator_name: '管理员',
      operator_role: 'design_staff',
    })
    ElMessage.success('排期确认成功')
    confirmVisible.value = false
    fetchPending()
  } finally {
    confirming.value = false
  }
}

// --- Task actions ---
async function handleTaskAction(row, action) {
  const labels = { start: '开始执行', complete: '标记完成', cancel: '取消任务' }
  try {
    await ElMessageBox.confirm(`确定${labels[action]}？`, '确认', {
      type: action === 'cancel' ? 'warning' : 'info',
    })
  } catch { return }

  try {
    await actionRequest(row.request_id || row.id, {
      action,
      operator_id: 1,
      operator_name: '管理员',
      operator_role: 'design_staff',
    })
    ElMessage.success('操作成功')
    fetchScheduled()
  } catch { /* handled by interceptor */ }
}

// --- Gantt reschedule handler ---
async function handleReschedule({ taskId, planStartDate, planEndDate, task }) {
  try {
    await ElMessageBox.confirm(
      `确定将任务 "${task.task_name || task.task_no}" 的排期调整为 ${planStartDate} ~ ${planEndDate}？`,
      '调整排期',
      { type: 'warning' }
    )
  } catch { return }

  try {
    await rescheduleTask(taskId, {
      plan_start_date: planStartDate,
      plan_end_date: planEndDate,
      operator_id: 1,
      operator_name: '管理员',
      operator_role: 'design_staff',
    })
    ElMessage.success('排期已调整')
    fetchScheduled()
  } catch { /* handled by interceptor */ }
}

// --- Recalculate table height ---
function updateTabMaxHeight() {
  tabMaxHeight.value = Math.max(300, window.innerHeight - 260)
}

onMounted(() => {
  updateTabMaxHeight()
  window.addEventListener('resize', updateTabMaxHeight)
  fetchPending()
  fetchDesigners()
})
</script>

<style scoped>
.pagination { margin-top: 16px; justify-content: flex-end; }
.text-muted { color: var(--text-secondary); font-size: 12px; }

:deep(.el-tabs__header) {
  margin-bottom: 16px;
}
</style>
