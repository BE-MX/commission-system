<template>
  <div class="gantt-wrapper" ref="wrapperRef">
    <div class="gantt-scroll" ref="scrollRef">
      <div class="gantt-grid" :style="gridStyle">
        <!-- Corner cell (spans 2 header rows) -->
        <div class="gantt-corner">{{ mode === 'pool' ? '设计组' : '设计师' }}</div>

        <!-- Row 1: Date headers, each spanning 2 columns -->
        <div
          v-for="d in dateRange"
          :key="'dh-' + d.str"
          class="gantt-date-header"
          :class="{
            'is-weekend': d.isWeekend,
            'is-today': d.isToday,
            'is-unavailable': isDateFullUnavailable(d.str),
          }"
        >
          <span class="date-weekday">{{ d.weekday }}</span>
          <span class="date-label">{{ d.dayNum }}</span>
        </div>

        <!-- Row 2: Period sub-headers (上午 / 下午) -->
        <div class="gantt-corner gantt-period-corner"></div>
        <template v-for="d in dateRange" :key="'ph-' + d.str">
          <div
            class="gantt-period-header"
            :class="{
              'is-weekend': d.isWeekend,
              'is-today': d.isToday,
              'is-unavailable': isSlotUnavailable(d.str, 'am'),
            }"
          >
            <span>上午</span>
            <span
              v-if="getLoadDot(d.str + '-am')"
              class="load-dot"
              :class="getLoadDot(d.str + '-am')"
            ></span>
          </div>
          <div
            class="gantt-period-header period-pm"
            :class="{
              'is-weekend': d.isWeekend,
              'is-today': d.isToday,
              'is-unavailable': isSlotUnavailable(d.str, 'pm'),
            }"
          >
            <span>下午</span>
            <span
              v-if="getLoadDot(d.str + '-pm')"
              class="load-dot"
              :class="getLoadDot(d.str + '-pm')"
            ></span>
          </div>
        </template>

        <!-- Pool mode: single row -->
        <template v-if="mode === 'pool'">
          <div class="gantt-row-label">设计组</div>
          <div
            class="gantt-row"
            :style="{ gridColumn: '2 / ' + (totalSlots + 2), minHeight: rowMinHeight(getMaxStack(poolStackLevels)) + 'px' }"
          >
            <div
              v-for="(slot, idx) in slotRange"
              :key="'u-' + slot.slotKey"
              class="gantt-cell-overlay"
              :class="{
                'is-weekend': slot.isWeekend,
                'is-today': slot.isToday,
                'is-unavailable': isSlotUnavailable(slot.str, slot.period),
                'is-pm': slot.period === 'pm',
              }"
              :style="{ left: (idx / totalSlots * 100) + '%', width: (1 / totalSlots * 100) + '%' }"
            ></div>
            <el-popover
              v-for="task in allTasks"
              :key="task.id || task.task_id"
              placement="top"
              :width="280"
              trigger="hover"
            >
              <template #reference>
                <div
                  class="task-bar"
                  :class="{ 'is-draggable': draggable }"
                  :style="getTaskBarStyle(task, poolStackLevels)"
                  @click="$emit('task-click', task)"
                  @mousedown="onTaskMousedown($event, task)"
                >
                  <span class="task-bar-text">{{ taskDisplayName(task) }}</span>
                  <span v-if="task.priority === 'urgent'" class="urgent-badge">急</span>
                </div>
              </template>
              <div class="task-popover">
                <p><strong>任务编号：</strong>{{ task.task_no }}</p>
                <p><strong>客户：</strong>{{ task.customer_name }}</p>
                <p><strong>业务员：</strong>{{ task.salesperson_name }}</p>
                <p><strong>拍摄类型：</strong>{{ shootTypeLabel(task.shoot_type) }}</p>
                <p><strong>优先级：</strong>{{ task.priority === 'urgent' ? '加急' : '普通' }}</p>
                <p><strong>计划日期：</strong>{{ task.plan_start_date }} {{ periodLabel(task.plan_start_period) }} ~ {{ task.plan_end_date }} {{ periodLabel(task.plan_end_period) }}</p>
                <p><strong>状态：</strong>
                  <el-tag :type="statusTagType(task.status)" size="small">
                    {{ statusLabel(task.status) }}
                  </el-tag>
                </p>
              </div>
            </el-popover>
          </div>
        </template>

        <!-- Individual mode: one row per designer -->
        <template v-else v-for="designer in designers" :key="designer.id">
          <div class="gantt-row-label">{{ designer.name }}</div>
          <div
            class="gantt-row"
            :style="{ gridColumn: '2 / ' + (totalSlots + 2), minHeight: rowMinHeight(getMaxStack(designerStackLevels(designer))) + 'px' }"
          >
            <div
              v-for="(slot, idx) in slotRange"
              :key="'u-' + slot.slotKey"
              class="gantt-cell-overlay"
              :class="{
                'is-weekend': slot.isWeekend,
                'is-today': slot.isToday,
                'is-unavailable': isSlotUnavailable(slot.str, slot.period),
                'is-pm': slot.period === 'pm',
              }"
              :style="{ left: (idx / totalSlots * 100) + '%', width: (1 / totalSlots * 100) + '%' }"
            ></div>
            <el-popover
              v-for="task in getDesignerTasks(designer)"
              :key="task.id || task.task_id"
              placement="top"
              :width="280"
              trigger="hover"
            >
              <template #reference>
                <div
                  class="task-bar"
                  :class="{ 'is-draggable': draggable }"
                  :style="getTaskBarStyle(task, designerStackLevels(designer))"
                  @click="$emit('task-click', task)"
                  @mousedown="onTaskMousedown($event, task)"
                >
                  <span class="task-bar-text">{{ taskDisplayName(task) }}</span>
                  <span v-if="task.priority === 'urgent'" class="urgent-badge">急</span>
                </div>
              </template>
              <div class="task-popover">
                <p><strong>任务编号：</strong>{{ task.task_no }}</p>
                <p><strong>客户：</strong>{{ task.customer_name }}</p>
                <p><strong>业务员：</strong>{{ task.salesperson_name }}</p>
                <p><strong>拍摄类型：</strong>{{ shootTypeLabel(task.shoot_type) }}</p>
                <p><strong>优先级：</strong>{{ task.priority === 'urgent' ? '加急' : '普通' }}</p>
                <p><strong>计划日期：</strong>{{ task.plan_start_date }} {{ periodLabel(task.plan_start_period) }} ~ {{ task.plan_end_date }} {{ periodLabel(task.plan_end_period) }}</p>
                <p><strong>状态：</strong>
                  <el-tag :type="statusTagType(task.status)" size="small">
                    {{ statusLabel(task.status) }}
                  </el-tag>
                </p>
              </div>
            </el-popover>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onBeforeUnmount } from 'vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  designers: { type: Array, default: () => [] },
  startDate: { type: String, required: true },
  endDate: { type: String, required: true },
  unavailableDates: { type: Array, default: () => [] },
  dateLoad: { type: Object, default: () => ({}) },
  mode: { type: String, default: 'individual' },
  draggable: { type: Boolean, default: false },
})

const emit = defineEmits(['task-click', 'reschedule'])

const PERIOD_LABELS = { am: '上午', pm: '下午' }

function periodLabel(p) {
  return PERIOD_LABELS[p] || ''
}

// --- Date utilities ---
function parseDate(str) {
  const [y, m, d] = str.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function formatDate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']
const todayStr = formatDate(new Date())

const dateRange = computed(() => {
  const start = parseDate(props.startDate)
  const end = parseDate(props.endDate)
  const dates = []
  const cur = new Date(start)
  while (cur <= end) {
    const str = formatDate(cur)
    const dow = cur.getDay()
    dates.push({
      str,
      display: `${String(cur.getMonth() + 1).padStart(2, '0')}/${String(cur.getDate()).padStart(2, '0')}`,
      dayNum: String(cur.getDate()),
      weekday: WEEKDAYS[dow],
      isWeekend: dow === 0 || dow === 6,
      isToday: str === todayStr,
    })
    cur.setDate(cur.getDate() + 1)
  }
  return dates
})

const totalDays = computed(() => dateRange.value.length)

const slotRange = computed(() => {
  const slots = []
  for (const d of dateRange.value) {
    slots.push({ ...d, period: 'am', slotKey: d.str + '-am' })
    slots.push({ ...d, period: 'pm', slotKey: d.str + '-pm' })
  }
  return slots
})

const totalSlots = computed(() => slotRange.value.length)

const displayRows = computed(() => {
  if (props.mode === 'pool') return 1
  return props.designers.length
})

const gridStyle = computed(() => ({
  gridTemplateColumns: `[label-col] 120px repeat(${totalSlots.value}, minmax(24px, 1fr))`,
  gridTemplateRows: `auto auto repeat(${displayRows.value}, minmax(60px, auto))`,
}))

// --- Unavailable check ---
const unavailableMap = computed(() => {
  const map = new Map()
  for (const item of props.unavailableDates) {
    const dateStr = typeof item === 'string' ? item : item.date
    const period = typeof item === 'string' ? null : item.period
    if (!map.has(dateStr)) map.set(dateStr, new Set())
    map.get(dateStr).add(period)
  }
  return map
})

function isSlotUnavailable(dateStr, period) {
  const set = unavailableMap.value.get(dateStr)
  if (!set) return false
  return set.has(null) || set.has(period)
}

function isDateFullUnavailable(dateStr) {
  const set = unavailableMap.value.get(dateStr)
  if (!set) return false
  return set.has(null)
}

// --- Load dot ---
function getLoadDot(slotKey) {
  const info = props.dateLoad[slotKey]
  if (!info) return null
  const ratio = info.max_capacity > 0 ? info.active_count / info.max_capacity : 0
  if (ratio >= 1) return 'load-red'
  if (ratio >= 0.7) return 'load-yellow'
  return 'load-green'
}

// --- Task positioning ---
function getDesignerTasks(designer) {
  return designer.tasks || []
}

const allTasks = computed(() => {
  const tasks = []
  for (const designer of props.designers) {
    if (designer.tasks) tasks.push(...designer.tasks)
  }
  if (props.tasks?.length) tasks.push(...props.tasks)
  return tasks
})

function _slotVal(dateStr, period) {
  if (!dateStr) return -1
  const d = parseDate(dateStr)
  const gridStart = parseDate(props.startDate)
  const dayOffset = (d - gridStart) / 86400000
  return dayOffset * 2 + (period === 'pm' ? 1 : 0)
}

function tasksOverlap(a, b) {
  const aStart = _slotVal(a.plan_start_date, a.plan_start_period || 'am')
  const aEnd = _slotVal(a.plan_end_date, a.plan_end_period || 'pm')
  const bStart = _slotVal(b.plan_start_date, b.plan_start_period || 'am')
  const bEnd = _slotVal(b.plan_end_date, b.plan_end_period || 'pm')
  return aStart <= bEnd && bStart <= aEnd
}

function computeStackLevels(tasks) {
  const levels = new Map()
  const sorted = [...tasks].sort((a, b) => {
    const av = _slotVal(a.plan_start_date, a.plan_start_period || 'am')
    const bv = _slotVal(b.plan_start_date, b.plan_start_period || 'am')
    return av - bv
  })
  for (const task of sorted) {
    let assigned = false
    for (let l = 0; !assigned; l++) {
      let conflict = false
      for (const other of sorted) {
        if (other === task) continue
        if (levels.has(other) && levels.get(other) === l && tasksOverlap(task, other)) {
          conflict = true
          break
        }
      }
      if (!conflict) {
        levels.set(task, l)
        assigned = true
      }
    }
  }
  return levels
}

const poolStackLevels = computed(() => computeStackLevels(allTasks.value))

function designerStackLevels(designer) {
  return computeStackLevels(getDesignerTasks(designer))
}

function getMaxStack(levels) {
  if (!levels || levels.size === 0) return 0
  return Math.max(...levels.values())
}

function rowMinHeight(taskCount) {
  return Math.max(60, (taskCount + 1) * 30 + 4)
}

function getTaskBarStyle(task, stackLevels) {
  if (!task.plan_start_date || !task.plan_end_date) return { display: 'none' }
  const gridStart = parseDate(props.startDate)
  const taskStart = parseDate(task.plan_start_date)
  const taskEnd = parseDate(task.plan_end_date)
  const total = totalSlots.value
  if (total <= 0) return { display: 'none' }

  const startDayOffset = Math.max(0, (taskStart - gridStart) / 86400000)
  const slotStart = startDayOffset * 2 + ((task.plan_start_period || 'am') === 'pm' ? 1 : 0)

  const endDayOffset = (taskEnd - gridStart) / 86400000
  const slotEnd = endDayOffset * 2 + ((task.plan_end_period || 'pm') === 'pm' ? 2 : 1)

  const clampedStart = Math.max(0, slotStart)
  const clampedEnd = Math.min(total, slotEnd)
  const span = clampedEnd - clampedStart

  if (span <= 0) return { display: 'none' }

  const left = (clampedStart / total) * 100
  const width = (span / total) * 100
  const color = statusColor(task.status)

  const level = stackLevels.get(task) || 0
  const top = 4 + level * 30

  const maxWidth = 100 - left

  return {
    left: left + '%',
    width: Math.min(width, maxWidth) + '%',
    top: top + 'px',
    backgroundColor: color,
  }
}

// --- Status helpers ---
const STATUS_COLORS = {
  pending_design: '#E6A23C',
  scheduled: '#409EFF',
  in_progress: '#F56C6C',
  completed: '#67C23A',
  cancelled: '#909399',
}

const STATUS_LABELS = {
  pending_design: '待设计',
  scheduled: '已排期',
  in_progress: '进行中',
  completed: '已完成',
  cancelled: '已取消',
}

const STATUS_TAG_TYPES = {
  pending_design: 'warning',
  scheduled: '',
  in_progress: 'danger',
  completed: 'success',
  cancelled: 'info',
}

const SHOOT_TYPE_LABELS = {
  product_photo: '产品图',
  model_photo: '模特图',
  video: '视频',
  product_video: '产品视频',
  other: '其他',
}

function statusColor(status) { return STATUS_COLORS[status] || '#409EFF' }
function statusLabel(status) { return STATUS_LABELS[status] || status }
function statusTagType(status) { return STATUS_TAG_TYPES[status] || '' }
function shootTypeLabel(type) { return SHOOT_TYPE_LABELS[type] || type || '' }

function taskDisplayName(task) {
  const typeName = SHOOT_TYPE_LABELS[task.shoot_type] || task.shoot_type || ''
  const customer = task.customer_name || ''
  return customer && typeName ? `${customer}-${typeName}` : customer || typeName || task.task_no
}

// --- Drag-to-reschedule ---
const scrollRef = ref(null)
const dragState = ref(null)

function onTaskMousedown(event, task) {
  if (!props.draggable) return
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()

  const barEl = event.currentTarget
  const rowEl = barEl.closest('.gantt-row')
  if (!rowEl) return

  const rowRect = rowEl.getBoundingClientRect()
  const cellWidth = rowRect.width / totalSlots.value

  const startSlot = _slotVal(task.plan_start_date, task.plan_start_period || 'am')
  const endSlot = _slotVal(task.plan_end_date, task.plan_end_period || 'pm')
  const duration = endSlot - startSlot

  dragState.value = {
    task,
    startX: event.clientX,
    barEl,
    cellWidth,
    duration,
    rowWidth: rowRect.width,
    origLeft: parseFloat(barEl.style.left),
  }

  barEl.classList.add('is-dragging')
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
}

function onDragMove(event) {
  if (!dragState.value) return
  const { startX, barEl, cellWidth } = dragState.value
  const dx = event.clientX - startX
  const cellOffset = Math.round(dx / cellWidth)
  const snappedDx = cellOffset * cellWidth
  barEl.style.transform = `translateX(${snappedDx}px)`
}

function onDragEnd(event) {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)

  if (!dragState.value) return
  const { task, startX, barEl, cellWidth, duration } = dragState.value
  const dx = event.clientX - startX
  const cellOffset = Math.round(dx / cellWidth)

  barEl.style.transform = ''
  barEl.classList.remove('is-dragging')

  if (cellOffset === 0) {
    dragState.value = null
    return
  }

  const origStartSlot = _slotVal(task.plan_start_date, task.plan_start_period || 'am')
  const newStartSlot = origStartSlot + cellOffset
  const newEndSlot = newStartSlot + duration

  if (newStartSlot < 0 || newEndSlot > totalSlots.value) {
    dragState.value = null
    return
  }

  const newStartDay = Math.floor(newStartSlot / 2)
  const newStartPeriod = newStartSlot % 2 === 0 ? 'am' : 'pm'
  const newEndDay = Math.floor(newEndSlot / 2)
  const newEndPeriod = newEndSlot % 2 === 0 ? 'am' : 'pm'

  const gridStart = parseDate(props.startDate)
  const startDate = new Date(gridStart)
  startDate.setDate(startDate.getDate() + newStartDay)
  const endDate = new Date(gridStart)
  endDate.setDate(endDate.getDate() + newEndDay)

  emit('reschedule', {
    taskId: task.task_id || task.id,
    planStartDate: formatDate(startDate),
    planStartPeriod: newStartPeriod,
    planEndDate: formatDate(endDate),
    planEndPeriod: newEndPeriod,
    task,
  })

  dragState.value = null
}

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
})
</script>

<style scoped>
.gantt-wrapper {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.gantt-scroll {
  overflow-x: auto;
  overflow-y: auto;
  max-height: 600px;
}

.gantt-grid {
  display: grid;
  min-width: max-content;
}

/* Corner cell */
.gantt-corner {
  position: sticky;
  left: 0;
  z-index: 3;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
  border-right: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  padding: 8px;
  grid-row: 1;
}

.gantt-period-corner {
  grid-row: 2;
  border-bottom: 1px solid #e4e7ed;
}

/* Date headers (span 2 columns each) */
.gantt-date-header {
  grid-row: 1;
  grid-column: span 2;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 6px 2px;
  font-size: 12px;
  color: #606266;
  position: relative;
  min-width: 48px;
}

.gantt-date-header.is-weekend { background: #f5f5f5; }
.gantt-date-header.is-today { border-bottom: 2px solid var(--color-gold, #e6a23c); }
.gantt-date-header.is-unavailable {
  background: repeating-linear-gradient(-45deg, transparent, transparent 3px, rgba(144,147,153,0.12) 3px, rgba(144,147,153,0.12) 6px);
}

.date-label { font-weight: 600; line-height: 1.2; }
.date-weekday { font-size: 11px; color: #909399; line-height: 1.2; }

/* Period sub-headers */
.gantt-period-header {
  grid-row: 2;
  background: #fafafa;
  border-bottom: 1px solid #e4e7ed;
  border-right: 1px dashed #ebeef5;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  font-size: 11px;
  color: #909399;
  padding: 2px 0;
  min-width: 24px;
}

.gantt-period-header.period-pm {
  border-right: 1px solid #ebeef5;
}

.gantt-period-header.is-weekend { background: #f5f5f5; }
.gantt-period-header.is-today { background: #fdf6ec; }
.gantt-period-header.is-unavailable {
  background: repeating-linear-gradient(-45deg, transparent, transparent 3px, rgba(144,147,153,0.12) 3px, rgba(144,147,153,0.12) 6px);
}

/* Load dots */
.load-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
}
.load-dot.load-green { background: #67C23A; }
.load-dot.load-yellow { background: #E6A23C; }
.load-dot.load-red { background: #F56C6C; }

/* Row label */
.gantt-row-label {
  position: sticky;
  left: 0;
  z-index: 2;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 500;
  color: #303133;
  white-space: nowrap;
}

/* Row content */
.gantt-row {
  position: relative;
  border-bottom: 1px solid #ebeef5;
  min-height: 60px;
}

/* Cell overlays */
.gantt-cell-overlay {
  position: absolute;
  top: 0;
  bottom: 0;
  pointer-events: none;
}
.gantt-cell-overlay.is-weekend { background: rgba(250,245,232,0.4); }
.gantt-cell-overlay.is-today { border-left: 2px solid var(--color-gold, #e6a23c); }
.gantt-cell-overlay.is-unavailable {
  background: repeating-linear-gradient(-45deg, transparent, transparent 3px, rgba(144,147,153,0.12) 3px, rgba(144,147,153,0.12) 6px);
}
.gantt-cell-overlay.is-pm {
  border-left: 1px dashed #ebeef5;
}

/* Task bar */
.task-bar {
  position: absolute;
  height: 28px;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  line-height: 28px;
  padding: 0 8px;
  cursor: pointer;
  z-index: 1;
  transition: filter 0.15s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.12);
}
.task-bar:hover { filter: brightness(1.1); box-shadow: 0 2px 6px rgba(0,0,0,0.18); }
.task-bar.is-draggable { cursor: grab; }
.task-bar.is-draggable:active { cursor: grabbing; }
.task-bar.is-dragging {
  opacity: 0.85;
  z-index: 10;
  box-shadow: 0 4px 12px rgba(0,0,0,0.25);
  outline: 2px dashed #409EFF;
  outline-offset: 1px;
  cursor: grabbing;
  user-select: none;
}

.task-bar-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

/* Urgent badge */
.urgent-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #F56C6C;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 16px;
  text-align: center;
  z-index: 2;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}

/* Popover content */
.task-popover p {
  margin: 4px 0;
  font-size: 13px;
  color: #303133;
  line-height: 1.6;
}
</style>
