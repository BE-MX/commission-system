<template>
  <div>
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- Tab 1: 待确认任务 -->
      <el-tab-pane label="待确认任务" name="pending">
        <div class="table-card">
        <el-table
          ref="pendingTableRef"
          :data="pendingData"
          v-loading="pendingLoading"
          class="list-table"
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="request_no" label="预约编号" min-width="160" max-width="240" show-overflow-tooltip />
          <el-table-column prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
          <el-table-column prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
          <el-table-column label="拍摄类型" min-width="100" max-width="150">
            <template #default="{ row }">{{ SHOOT_TYPE_MAP[row.shoot_type] || row.shoot_type }}</template>
          </el-table-column>
          <el-table-column label="期望日期" min-width="280" max-width="420">
            <template #default="{ row }">{{ row.expect_start_date }} {{ periodLabel(row.expect_start_period) }} ~ {{ row.expect_end_date }} {{ periodLabel(row.expect_end_period) }}</template>
          </el-table-column>
          <el-table-column label="优先级" min-width="80" max-width="120">
            <template #default="{ row }">
              <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column label="操作" min-width="130" max-width="200" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="Calendar" @click="openConfirmDialog(row)">确认排期</GlassButton>
            </template>
          </el-table-column>
        </el-table>
        </div>

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
        <div class="table-card">
        <el-table
          ref="scheduledTableRef"
          :data="scheduledData"
          v-loading="scheduledLoading"
          class="list-table"
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="task_no" label="任务编号" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
          <el-table-column prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
          <el-table-column label="拍摄类型" min-width="100" max-width="150">
            <template #default="{ row }">{{ SHOOT_TYPE_MAP[row.shoot_type] || row.shoot_type }}</template>
          </el-table-column>
          <el-table-column label="设计师" min-width="100" max-width="150">
            <template #default="{ row }">{{ getDesignerName(row.designer_id) }}</template>
          </el-table-column>
          <el-table-column label="排期日期" min-width="280" max-width="420">
            <template #default="{ row }">{{ row.plan_start_date || '-' }} {{ periodLabel(row.plan_start_period) }} ~ {{ row.plan_end_date || '-' }} {{ periodLabel(row.plan_end_period) }}</template>
          </el-table-column>
          <el-table-column label="优先级" min-width="80" max-width="120">
            <template #default="{ row }">
              <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="100" max-width="150">
            <template #default="{ row }">
              <el-tag :type="TASK_STATUS_TAG[row.status]" effect="plain">
                {{ TASK_STATUS_MAP[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="200" max-width="300" fixed="right">
            <template #default="{ row }">
              <GlassButton
                v-if="row.status === 'scheduled'"
                variant="link" left-icon="VideoPlay"
                @click="handleTaskAction(row, 'start')"
              >开始执行</GlassButton>
              <GlassButton
                v-if="row.status === 'in_progress'"
                variant="link" link-tone="success" left-icon="CircleCheck"
                @click="handleTaskAction(row, 'complete')"
              >标记完成</GlassButton>
              <GlassButton
                v-if="['scheduled', 'in_progress'].includes(row.status)"
                variant="link" link-tone="danger" left-icon="CircleClose"
                @click="handleTaskAction(row, 'cancel')"
              >取消</GlassButton>
            </template>
          </el-table-column>
        </el-table>
        </div>

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
        <el-row style="margin-bottom: 12px" justify="end">
          <GlassButton variant="primary" left-icon="Plus" @click="openDesignerDialog(null)">新建设计师</GlassButton>
        </el-row>
        <div class="table-card">
        <el-table
          :data="designerData"
          v-loading="designerLoading"
          class="list-table"
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="id" label="ID" min-width="80" max-width="120" show-overflow-tooltip />
          <el-table-column prop="name" label="姓名" min-width="120" max-width="180" show-overflow-tooltip />
          <el-table-column prop="email" label="邮箱" min-width="180" max-width="270" show-overflow-tooltip />
          <el-table-column prop="dingtalk_id" label="钉钉ID" min-width="140" max-width="210" show-overflow-tooltip />
          <el-table-column label="状态" min-width="100" max-width="150">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" effect="plain">
                {{ row.is_active ? '在职' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column label="操作" min-width="150" max-width="230" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="Edit" @click="openDesignerDialog(row)">编辑</GlassButton>
              <GlassButton
                variant="link"
                :link-tone="row.is_active ? 'danger' : 'success'"
                left-icon="SwitchButton"
                @click="toggleDesignerActive(row)"
              >{{ row.is_active ? '停用' : '启用' }}</GlassButton>
            </template>
          </el-table-column>
        </el-table>
        </div>
      </el-tab-pane>

      <!-- Tab 4: 不可用日期 -->
      <el-tab-pane label="不可用日期" name="unavailable" lazy>
        <DesignCalendarConfig />
      </el-tab-pane>

      <!-- Tab 5: 容量配置 -->
      <el-tab-pane label="容量配置" name="capacity" lazy>
        <DesignCapacityConfig />
      </el-tab-pane>

      <!-- Tab 6: 批量导入 -->
      <el-tab-pane label="批量导入" name="import" lazy>
        <div class="import-section">
          <el-alert
            title="Excel 格式要求"
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          >
            <template #default>
              列顺序: 客户名称, 业务员姓名, 拍摄类型, 期望开始日期, 期望结束日期, 优先级, 备注<br/>
              拍摄类型: 产品图/模特图/视频/产品视频/其他 | 优先级: 普通/加急 | 日期格式: YYYY-MM-DD
            </template>
          </el-alert>
          <el-upload
            ref="uploadRef"
            action=""
            :auto-upload="false"
            :limit="1"
            accept=".xlsx,.xls"
            :on-change="onFileChange"
            :on-remove="() => importFile = null"
          >
            <template #trigger>
              <GlassButton variant="primary" :icon="Upload">选择文件</GlassButton>
            </template>
            <template #tip>
              <div class="el-upload__tip">仅支持 .xlsx / .xls 文件</div>
            </template>
          </el-upload>
          <GlassButton
            variant="success"
            style="margin-top: 12px"
            :disabled="!importFile"
            :loading="importing"
            @click="submitImport"
          >开始导入</GlassButton>
        </div>

        <!-- Import results dialog -->
        <el-dialog v-model="importResultVisible" title="导入结果" width="560px">
          <div v-if="importResult">
            <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
              <el-descriptions-item label="总行数">{{ importResult.total }}</el-descriptions-item>
              <el-descriptions-item label="成功">
                <el-tag type="success" size="small">{{ importResult.success }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="失败">
                <el-tag type="danger" size="small">{{ importResult.failed }}</el-tag>
              </el-descriptions-item>
            </el-descriptions>
            <el-table v-if="importResult.errors?.length" :data="importResult.errors" border size="small" max-height="300">
              <el-table-column prop="row" label="行号" width="80" />
              <el-table-column prop="reason" label="失败原因" />
            </el-table>
          </div>
        </el-dialog>
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
          <DatePeriodPicker
            v-model:start-date="confirmForm.startDate"
            v-model:start-period="confirmForm.startPeriod"
            v-model:end-date="confirmForm.endDate"
            v-model:end-period="confirmForm.endPeriod"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="confirmForm.comment" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="confirmVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitConfirm" :loading="confirming">确认</GlassButton>
      </template>
    </el-dialog>

    <!-- Designer create/edit dialog -->
    <el-dialog
      v-model="designerDialogVisible"
      :title="designerForm.id ? '编辑设计师' : '新建设计师'"
      width="460px"
      :close-on-click-modal="false"
    >
      <el-form :model="designerForm" label-width="80px">
        <el-form-item label="姓名" required>
          <el-input v-model="designerForm.name" placeholder="请输入设计师姓名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="designerForm.email" placeholder="选填" />
        </el-form-item>
        <el-form-item label="钉钉ID">
          <el-input v-model="designerForm.dingtalk_id" placeholder="选填" />
        </el-form-item>
        <el-form-item label="状态" v-if="designerForm.id">
          <el-switch v-model="designerForm.is_active" active-text="在职" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="designerDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitDesigner" :loading="designerSaving">保存</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Plus, Calendar, VideoPlay, CircleCheck, CircleClose, Edit, SwitchButton } from '@element-plus/icons-vue'
import { getRequests, getTaskList, getDesigners, createDesigner, updateDesigner, actionRequest, rescheduleTask, importRequests } from '@/api/design'
import DesignCalendarConfig from '@/components/design/DesignCalendarConfig.vue'
import DesignCapacityConfig from '@/components/design/DesignCapacityConfig.vue'
import DatePeriodPicker from '@/components/design/DatePeriodPicker.vue'

const PERIOD_LABELS = { am: '上午', pm: '下午' }
function periodLabel(p) { return PERIOD_LABELS[p] || '' }

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

function getDesignerName(id) {
  const d = designerData.value.find(d => d.id === id)
  return d ? d.name : id || '-'
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

// --- Designer create/edit ---
const designerDialogVisible = ref(false)
const designerSaving = ref(false)
const designerForm = reactive({
  id: null,
  name: '',
  email: '',
  dingtalk_id: '',
  is_active: true,
})

function openDesignerDialog(row) {
  if (row) {
    designerForm.id = row.id
    designerForm.name = row.name
    designerForm.email = row.email || ''
    designerForm.dingtalk_id = row.dingtalk_id || ''
    designerForm.is_active = row.is_active
  } else {
    designerForm.id = null
    designerForm.name = ''
    designerForm.email = ''
    designerForm.dingtalk_id = ''
    designerForm.is_active = true
  }
  designerDialogVisible.value = true
}

async function submitDesigner() {
  if (!designerForm.name.trim()) {
    ElMessage.warning('请输入设计师姓名')
    return
  }
  designerSaving.value = true
  try {
    const payload = {
      name: designerForm.name.trim(),
      email: designerForm.email || null,
      dingtalk_id: designerForm.dingtalk_id || null,
      is_active: designerForm.is_active,
    }
    if (designerForm.id) {
      await updateDesigner(designerForm.id, payload)
    } else {
      await createDesigner(payload)
    }
    ElMessage.success('保存成功')
    designerDialogVisible.value = false
    fetchDesigners()
  } finally {
    designerSaving.value = false
  }
}

async function toggleDesignerActive(row) {
  const action = row.is_active ? '停用' : '启用'
  try {
    await ElMessageBox.confirm(`确定${action}设计师「${row.name}」？`, '确认', { type: 'warning' })
  } catch { return }

  try {
    await updateDesigner(row.id, { is_active: !row.is_active })
    ElMessage.success(`${action}成功`)
    fetchDesigners()
  } catch { /* handled */ }
}

// --- Confirm scheduling dialog ---
const confirmVisible = ref(false)
const confirmRow = ref(null)
const confirming = ref(false)
const confirmForm = reactive({
  designer_id: null,
  startDate: '',
  startPeriod: 'am',
  endDate: '',
  endPeriod: 'pm',
  comment: '',
})

function openConfirmDialog(row) {
  confirmRow.value = row
  confirmForm.designer_id = null
  confirmForm.startDate = row.expect_start_date || ''
  confirmForm.startPeriod = row.expect_start_period || 'am'
  confirmForm.endDate = row.expect_end_date || ''
  confirmForm.endPeriod = row.expect_end_period || 'pm'
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
  if (!confirmForm.startDate || !confirmForm.endDate) {
    ElMessage.warning('请选择排期日期')
    return
  }
  confirming.value = true
  try {
    await actionRequest(confirmRow.value.id, {
      action: 'confirm',
      designer_id: confirmForm.designer_id,
      plan_start_date: confirmForm.startDate,
      plan_start_period: confirmForm.startPeriod,
      plan_end_date: confirmForm.endDate,
      plan_end_period: confirmForm.endPeriod,
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
async function handleReschedule({ taskId, planStartDate, planStartPeriod, planEndDate, planEndPeriod, task }) {
  const pLabels = { am: '上午', pm: '下午' }
  try {
    await ElMessageBox.confirm(
      `确定将任务 "${task.task_name || task.task_no}" 的排期调整为 ${planStartDate} ${pLabels[planStartPeriod] || ''} ~ ${planEndDate} ${pLabels[planEndPeriod] || ''}？`,
      '调整排期',
      { type: 'warning' }
    )
  } catch { return }

  try {
    await rescheduleTask(taskId, {
      plan_start_date: planStartDate,
      plan_start_period: planStartPeriod || 'am',
      plan_end_date: planEndDate,
      plan_end_period: planEndPeriod || 'pm',
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

// --- Import ---
const uploadRef = ref()
const importFile = ref(null)
const importing = ref(false)
const importResultVisible = ref(false)
const importResult = ref(null)

function onFileChange(file) {
  importFile.value = file.raw
}

async function submitImport() {
  if (!importFile.value) return
  importing.value = true
  try {
    const formData = new FormData()
    formData.append('file', importFile.value)
    const res = await importRequests(formData, {
      operator_id: 1,
      operator_name: '管理员',
      operator_role: 'salesperson',
    })
    importResult.value = res.data
    importResultVisible.value = true
    // Reset upload
    importFile.value = null
    if (uploadRef.value) uploadRef.value.clearFiles()
    // Refresh pending list if on that tab
    if (activeTab.value === 'pending') fetchPending()
  } catch {
    // handled by interceptor
  } finally {
    importing.value = false
  }
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
.import-section { max-width: 600px; }

:deep(.el-tabs__header) {
  margin-bottom: 16px;
}
</style>
