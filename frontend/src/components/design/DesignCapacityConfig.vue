<template>
  <div class="capacity-config" v-loading="loading">
    <!-- Global default capacity -->
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-header">
          <span>全局默认容量</span>
        </div>
      </template>
      <div class="config-row">
        <span class="config-label">每日最大并行任务数</span>
        <el-input-number
          v-model="globalCapacity"
          :min="1"
          :max="50"
          :step="1"
          size="default"
          style="width: 160px;"
        />
        <el-button type="primary" size="default" @click="saveGlobalCapacity" :loading="saving">
          保存
        </el-button>
      </div>
    </el-card>

    <!-- Scheduling mode -->
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-header">
          <span>排期模式</span>
        </div>
      </template>
      <div class="config-row">
        <el-radio-group v-model="schedulingMode" @change="saveSchedulingMode">
          <el-radio value="pool">
            <div class="mode-option">
              <strong>团队模式 (Pool)</strong>
              <span class="mode-desc">任务分配到设计组统一调度</span>
            </div>
          </el-radio>
          <el-radio value="individual">
            <div class="mode-option">
              <strong>个人模式 (Individual)</strong>
              <span class="mode-desc">任务分配到具体设计师</span>
            </div>
          </el-radio>
        </el-radio-group>
      </div>
    </el-card>

    <!-- Specific date capacity overrides -->
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-header">
          <span>特定日期容量</span>
        </div>
      </template>

      <!-- Add new entry -->
      <div class="add-row">
        <el-date-picker
          v-model="newEntry.date"
          type="date"
          placeholder="选择日期"
          value-format="YYYY-MM-DD"
          :disabled-date="isDateAlreadyConfigured"
          style="width: 180px;"
        />
        <el-input-number
          v-model="newEntry.capacity"
          :min="0"
          :max="50"
          :step="1"
          placeholder="容量"
          style="width: 140px;"
        />
        <el-button type="primary" @click="addSpecificDate" :disabled="!newEntry.date">
          添加
        </el-button>
      </div>

      <!-- Table of existing specific dates -->
      <el-table :data="specificDates" stripe border style="width: 100%; margin-top: 12px;" empty-text="暂无特定日期容量配置">
        <el-table-column prop="config_date" label="日期" width="160" sortable />
        <el-table-column label="星期" width="100">
          <template #default="{ row }">
            {{ getWeekday(row.config_date) }}
          </template>
        </el-table-column>
        <el-table-column prop="max_parallel_tasks" label="最大并行任务" width="140" align="center" />
        <el-table-column label="与默认值差异" width="140" align="center">
          <template #default="{ row }">
            <el-tag
              v-if="row.max_parallel_tasks !== globalCapacity"
              :type="row.max_parallel_tasks > globalCapacity ? 'success' : 'warning'"
              size="small"
              effect="plain"
            >
              {{ row.max_parallel_tasks > globalCapacity ? '+' : '' }}{{ row.max_parallel_tasks - globalCapacity }}
            </el-tag>
            <span v-else class="text-muted">同默认</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button type="danger" link size="small" @click="removeSpecificDate(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getCapacity, updateCapacity, getSchedulingMode, updateSchedulingMode } from '@/api/design'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const operatorParams = { operator_id: 1, operator_name: '设计部', operator_role: 'design_staff' }

const loading = ref(false)
const saving = ref(false)

const globalCapacity = ref(3)
const schedulingMode = ref('pool')
const capacityEntries = ref([]) // raw entries from API

const newEntry = reactive({
  date: '',
  capacity: 3,
})

// --- Computed ---
const specificDates = computed(() =>
  capacityEntries.value
    .filter(e => e.config_date)
    .sort((a, b) => a.config_date.localeCompare(b.config_date))
)

// --- Helpers ---
function getWeekday(dateStr) {
  if (!dateStr) return ''
  const [y, m, d] = dateStr.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  return WEEKDAYS[date.getDay()]
}

function isDateAlreadyConfigured(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const str = `${y}-${m}-${d}`
  return specificDates.value.some(e => e.config_date === str)
}

// --- Data loading ---
async function fetchAll() {
  loading.value = true
  try {
    const [capRes, modeRes] = await Promise.all([
      getCapacity(),
      getSchedulingMode(),
    ])

    const entries = capRes.data || []
    capacityEntries.value = Array.isArray(entries) ? entries : []

    // Find global default (config_date is null and designer_id is null)
    const globalEntry = capacityEntries.value.find(e => !e.config_date && !e.designer_id)
    if (globalEntry) {
      globalCapacity.value = globalEntry.max_parallel_tasks || 3
    }

    const modeData = modeRes.data
    schedulingMode.value = modeData?.scheduling_mode || modeData?.mode || 'pool'
  } finally {
    loading.value = false
  }
}

// --- Save actions ---
async function saveGlobalCapacity() {
  saving.value = true
  try {
    await updateCapacity(
      { entries: [{ config_date: null, designer_id: null, max_parallel_tasks: globalCapacity.value }] },
      { params: operatorParams }
    )
    ElMessage.success('全局容量已更新')
  } finally {
    saving.value = false
  }
}

async function saveSchedulingMode(mode) {
  try {
    await updateSchedulingMode(
      { scheduling_mode: mode },
      { params: operatorParams }
    )
    ElMessage.success('排期模式已切换为' + (mode === 'pool' ? '团队模式' : '个人模式'))
  } catch {
    // Revert on failure
    schedulingMode.value = mode === 'pool' ? 'individual' : 'pool'
  }
}

async function addSpecificDate() {
  if (!newEntry.date) {
    ElMessage.warning('请选择日期')
    return
  }
  saving.value = true
  try {
    await updateCapacity(
      { entries: [{ config_date: newEntry.date, designer_id: null, max_parallel_tasks: newEntry.capacity }] },
      { params: operatorParams }
    )
    ElMessage.success('已添加特定日期容量')
    newEntry.date = ''
    newEntry.capacity = globalCapacity.value
    await fetchAll()
  } finally {
    saving.value = false
  }
}

async function removeSpecificDate(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除 ${row.config_date} 的容量配置？删除后将使用全局默认值。`,
      '确认删除',
      { type: 'warning' }
    )
  } catch { return }

  saving.value = true
  try {
    // Set to 0 or use global default to effectively remove
    await updateCapacity(
      { entries: [{ config_date: row.config_date, designer_id: null, max_parallel_tasks: globalCapacity.value, delete: true }] },
      { params: operatorParams }
    )
    ElMessage.success('已删除')
    await fetchAll()
  } finally {
    saving.value = false
  }
}

onMounted(fetchAll)
</script>

<style scoped>
.capacity-config {
  max-width: 800px;
}

.config-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  font-size: 15px;
}

.config-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.config-label {
  font-size: 14px;
  color: #606266;
}

.mode-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mode-option strong {
  font-size: 14px;
}

.mode-desc {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}

.add-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.text-muted {
  color: #909399;
  font-size: 12px;
}

:deep(.el-radio-group) {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

:deep(.el-radio) {
  height: auto;
}
</style>
