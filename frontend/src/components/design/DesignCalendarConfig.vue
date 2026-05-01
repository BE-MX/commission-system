<template>
  <div class="calendar-config" v-loading="loading">
    <!-- Batch mode toggle -->
    <div class="toolbar">
      <el-checkbox v-model="batchMode">批量选择模式</el-checkbox>
      <template v-if="batchMode">
        <GlassButton
          variant="primary"
          size="small"
          left-icon="Setting"
          :disabled="!batchSelected.length"
          @click="openBatchDialog"
        >
          批量设置 ({{ batchSelected.length }})
        </GlassButton>
        <GlassButton variant="ghost" size="small" left-icon="Close" @click="batchSelected = []">清除选择</GlassButton>
      </template>
    </div>

    <!-- Calendar -->
    <el-calendar v-model="calendarValue">
      <template #date-cell="{ data }">
        <div
          class="date-cell"
          :class="{
            'unavailable-cell': isUnavailable(data.day),
            'today-cell': isToday(data.day),
            'batch-selected': batchMode && batchSelected.includes(data.day),
          }"
          @click.stop="handleDateClick(data.day)"
        >
          <span class="date-num">{{ data.day.split('-')[2] }}</span>
          <span v-if="isUnavailable(data.day)" class="unavailable-dot"></span>
          <el-icon v-if="batchMode && batchSelected.includes(data.day)" class="batch-check" :size="12">
            <Check />
          </el-icon>
        </div>
      </template>
    </el-calendar>

    <!-- Upcoming unavailable dates list -->
    <div class="upcoming-section">
      <h4>即将到来的不可用日期</h4>
      <el-empty v-if="!upcomingDates.length" description="暂无不可用日期" :image-size="60" />
      <div v-else class="upcoming-list">
        <div v-for="(item, idx) in upcomingDates" :key="idx" class="upcoming-item">
          <div class="upcoming-info">
            <span class="upcoming-date">{{ item.date }}</span>
            <span class="upcoming-weekday">{{ getWeekday(item.date) }}</span>
            <el-tag v-if="item.period" size="small" effect="plain" style="margin-left: 4px">{{ item.period === 'am' ? '上午' : '下午' }}</el-tag>
            <el-tag v-else size="small" type="info" effect="plain" style="margin-left: 4px">全天</el-tag>
            <span v-if="item.reason" class="upcoming-reason">{{ item.reason }}</span>
          </div>
          <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="handleRemove(item.date, item.period)">删除</GlassButton>
        </div>
      </div>
    </div>

    <!-- Add single date dialog -->
    <el-dialog v-model="addDialogVisible" title="设置不可用日期" width="400px" :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="日期">
          <span>{{ addForm.date }}</span>
        </el-form-item>
        <el-form-item label="时段">
          <el-radio-group v-model="addForm.period">
            <el-radio :value="null">全天</el-radio>
            <el-radio value="am">上午</el-radio>
            <el-radio value="pm">下午</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="原因" required>
          <el-input v-model="addForm.reason" placeholder="请输入不可用原因" maxlength="100" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="addDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="submitting" @click="submitAdd">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- Batch dialog -->
    <el-dialog v-model="batchDialogVisible" title="批量设置不可用日期" width="400px" :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="日期">
          <div class="batch-dates">
            <el-tag v-for="d in batchSelected" :key="d" size="small" style="margin: 2px;">{{ d }}</el-tag>
          </div>
        </el-form-item>
        <el-form-item label="时段">
          <el-radio-group v-model="batchForm.period">
            <el-radio :value="null">全天</el-radio>
            <el-radio value="am">上午</el-radio>
            <el-radio value="pm">下午</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="原因" required>
          <el-input v-model="batchForm.reason" placeholder="请输入不可用原因" maxlength="100" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="batchDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="submitting" @click="submitBatch">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- Remove confirmation dialog -->
    <el-dialog v-model="removeDialogVisible" title="移除不可用日期" width="360px" :close-on-click-modal="false">
      <p>确定移除 <strong>{{ removeDate }}</strong> 的不可用标记？</p>
      <template #footer>
        <GlassButton variant="ghost" @click="removeDialogVisible = false">取消</GlassButton>
        <GlassButton variant="danger" left-icon="Delete" :loading="submitting" @click="submitRemove">确定移除</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import { getUnavailableDates, createUnavailableDates, deleteUnavailableDate } from '@/api/design'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const operatorParams = { operator_id: 1, operator_name: '设计部', operator_role: 'design_staff' }

const calendarValue = ref(new Date())
const loading = ref(false)
const submitting = ref(false)
const unavailableList = ref([]) // [{ date, reason }]

// --- Batch mode ---
const batchMode = ref(false)
const batchSelected = ref([])
const batchDialogVisible = ref(false)
const batchForm = ref({ period: null, reason: '' })

// --- Add dialog ---
const addDialogVisible = ref(false)
const addForm = ref({ date: '', period: null, reason: '' })

// --- Remove dialog ---
const removeDialogVisible = ref(false)
const removeDate = ref('')

// --- Computed ---
const unavailableSet = computed(() => new Set(unavailableList.value.map(d => d.date || d)))

const todayStr = computed(() => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
})

const upcomingDates = computed(() => {
  const today = todayStr.value
  return unavailableList.value
    .filter(item => {
      const d = item.date || item
      return d >= today
    })
    .sort((a, b) => {
      const da = a.date || a
      const db = b.date || b
      return da.localeCompare(db)
    })
    .slice(0, 30)
})

// --- Helpers ---
function isUnavailable(dateStr) {
  return unavailableSet.value.has(dateStr)
}

function isToday(dateStr) {
  return dateStr === todayStr.value
}

function getWeekday(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  return WEEKDAYS[date.getDay()]
}

function getReasonForDate(dateStr) {
  const item = unavailableList.value.find(d => (d.date || d) === dateStr)
  return item?.reason || ''
}

// --- Actions ---
function handleDateClick(dateStr) {
  if (batchMode.value) {
    // In batch mode: toggle selection
    const idx = batchSelected.value.indexOf(dateStr)
    if (idx >= 0) {
      batchSelected.value.splice(idx, 1)
    } else {
      if (!isUnavailable(dateStr)) {
        batchSelected.value.push(dateStr)
      }
    }
    return
  }

  if (isUnavailable(dateStr)) {
    removeDate.value = dateStr
    removeDialogVisible.value = true
  } else {
    addForm.value = { date: dateStr, period: null, reason: '' }
    addDialogVisible.value = true
  }
}

const removePeriod = ref(null)

function handleRemove(dateStr, period = null) {
  removeDate.value = dateStr
  removePeriod.value = period
  removeDialogVisible.value = true
}

function openBatchDialog() {
  if (!batchSelected.value.length) return
  batchForm.value = { period: null, reason: '' }
  batchDialogVisible.value = true
}

// --- API calls ---
async function fetchDates() {
  loading.value = true
  try {
    const res = await getUnavailableDates()
    unavailableList.value = res.data || []
  } finally {
    loading.value = false
  }
}

async function submitAdd() {
  if (!addForm.value.reason.trim()) {
    ElMessage.warning('请输入不可用原因')
    return
  }
  submitting.value = true
  try {
    await createUnavailableDates(
      { dates: [addForm.value.date], period: addForm.value.period, reason: addForm.value.reason },
      { params: operatorParams }
    )
    ElMessage.success('设置成功')
    addDialogVisible.value = false
    await fetchDates()
  } finally {
    submitting.value = false
  }
}

async function submitBatch() {
  if (!batchForm.value.reason.trim()) {
    ElMessage.warning('请输入不可用原因')
    return
  }
  submitting.value = true
  try {
    await createUnavailableDates(
      { dates: [...batchSelected.value], period: batchForm.value.period, reason: batchForm.value.reason },
      { params: operatorParams }
    )
    ElMessage.success('批量设置成功')
    batchDialogVisible.value = false
    batchSelected.value = []
    await fetchDates()
  } finally {
    submitting.value = false
  }
}

async function submitRemove() {
  submitting.value = true
  try {
    const delParams = { ...operatorParams }
    if (removePeriod.value) delParams.period = removePeriod.value
    await deleteUnavailableDate(removeDate.value, { params: delParams })
    ElMessage.success('已移除')
    removeDialogVisible.value = false
    await fetchDates()
  } finally {
    submitting.value = false
  }
}

onMounted(fetchDates)
</script>

<style scoped>
.calendar-config {
  max-width: 900px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--toolbar-bg);
  border-radius: 6px;
}

/* Calendar cell */
.date-cell {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
  padding: 4px;
}

.date-cell:hover {
  background: rgba(212, 148, 28, 0.08);
}

.date-cell.unavailable-cell {
  background: rgba(220, 53, 69, 0.12);
}

.date-cell.unavailable-cell:hover {
  background: rgba(220, 53, 69, 0.22);
}

.date-cell.today-cell {
  border: 2px solid var(--color-primary);
  border-radius: 6px;
}

.date-cell.batch-selected {
  background: rgba(212, 148, 28, 0.15);
  outline: 2px solid var(--color-primary);
  outline-offset: -2px;
}

.date-num {
  font-weight: 600;
  font-size: 14px;
  line-height: 1.4;
}

.unavailable-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-danger);
  margin-top: 2px;
}

.batch-check {
  position: absolute;
  top: 2px;
  right: 2px;
  color: var(--color-primary);
}

/* Upcoming section */
.upcoming-section {
  margin-top: 20px;
}

.upcoming-section h4 {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.upcoming-list {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.upcoming-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
}

.upcoming-item:last-child {
  border-bottom: none;
}

.upcoming-item:hover {
  background: var(--toolbar-bg);
}

.upcoming-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.upcoming-date {
  font-weight: 500;
  color: var(--text-primary);
  font-size: 14px;
}

.upcoming-weekday {
  color: var(--text-muted);
  font-size: 13px;
}

.upcoming-reason {
  color: var(--text-secondary);
  font-size: 13px;
  padding-left: 8px;
  border-left: 2px solid var(--border-color);
}

.batch-dates {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* Override el-calendar inner styles */
:deep(.el-calendar-table td.is-selected) {
  background: transparent;
}

:deep(.el-calendar-table .el-calendar-day) {
  height: 60px;
  padding: 2px;
}
</style>
