<template>
  <div class="page page-wide">
    <header class="page-head rise">
      <div class="head-row">
        <div>
          <p class="page-eyebrow">TASKS</p>
          <h1 class="page-title">任务看板</h1>
        </div>
        <button class="btn btn-primary" type="button" @click="openCreate">+ 新建任务</button>
      </div>
      <div class="toolbar">
        <div class="filters">
          <select v-model="filters.assignee" class="select select-inline" @change="load">
            <option value="">全部负责人</option>
            <option v-for="m in members" :key="m.username" :value="m.username">{{ m.display_name }}</option>
          </select>
          <select v-model="filters.phase" class="select select-inline" @change="load">
            <option value="">全部 Phase</option>
            <option v-for="p in [1, 2, 3, 4]" :key="p" :value="p">Phase {{ p }}</option>
          </select>
        </div>
        <div class="view-toggle" role="tablist">
          <button
            v-for="v in [['board', '看板'], ['list', '列表']]"
            :key="v[0]"
            class="toggle-btn"
            :class="{ active: view === v[0] }"
            type="button"
            role="tab"
            @click="view = v[0]"
          >{{ v[1] }}</button>
        </div>
      </div>
    </header>

    <div v-if="loading" class="board-loading"><span class="spinner"></span></div>

    <!-- 看板视图 -->
    <div v-else-if="view === 'board'" class="board rise rise-1">
      <section v-for="col in columns" :key="col.status" class="board-col">
        <header class="col-head">
          <StatusBadge :label="TASK_STATUS[col.status].label" :tone="TASK_STATUS[col.status].tone" dot />
          <span class="col-count num">{{ col.tasks.length }}</span>
        </header>
        <div class="col-body">
          <article
            v-for="(task, i) in col.tasks"
            :key="task.id"
            class="task-card"
            :style="{ animationDelay: `${Math.min(i * 40, 240)}ms` }"
            @click="openEdit(task)"
          >
            <h3 class="task-title">{{ task.title }}</h3>
            <p v-if="task.status === 'blocked' && task.blocked_reason" class="task-blocked">
              卡点：{{ task.blocked_reason }}
            </p>
            <div v-if="task.materials.length" class="task-mats">
              <router-link
                v-for="m in task.materials"
                :key="m.id"
                :to="`/materials/${m.id}`"
                class="task-mat"
                @click.stop
              >
                <span class="mat-dot" :class="`tone-bg-${MATERIAL_STATUS[m.status]?.tone}`"></span>{{ m.name }}
              </router-link>
            </div>
            <footer class="task-meta">
              <span v-if="task.assignee" class="task-assignee">{{ nameOf(task.assignee) }}</span>
              <span v-else class="task-assignee none">未指派</span>
              <time v-if="task.due_date" class="task-due" :class="{ overdue: isOverdue(task) }">
                {{ task.due_date.slice(5) }}<template v-if="isOverdue(task)"> · 逾期</template>
              </time>
              <span v-if="task.phase" class="task-phase mono">P{{ task.phase }}</span>
              <span class="task-status-slot" @click.stop>
                <UiDropdown align="right">
                  <template #trigger>
                    <span class="status-click">
                      <StatusBadge :label="TASK_STATUS[task.status].label" :tone="TASK_STATUS[task.status].tone" />
                    </span>
                  </template>
                  <template #default="{ close }">
                    <div class="status-menu">
                      <button
                        v-for="s in nextStatuses(task.status)"
                        :key="s"
                        class="status-option"
                        type="button"
                        @click="pickStatus(task, s, close)"
                      >
                        <StatusBadge :label="TASK_STATUS[s].label" :tone="TASK_STATUS[s].tone" dot />流转到此
                      </button>
                      <div v-if="blockingFor === task.id" class="blocked-form">
                        <input
                          v-model.trim="blockedReason"
                          class="input"
                          type="text"
                          placeholder="受阻原因（必填）"
                          @keydown.enter="confirmBlocked(task, close)"
                        />
                        <button class="btn btn-sm btn-accent" type="button" @click="confirmBlocked(task, close)">确认</button>
                      </div>
                    </div>
                  </template>
                </UiDropdown>
              </span>
            </footer>
          </article>
          <p v-if="!col.tasks.length" class="col-empty">—</p>
        </div>
      </section>
    </div>

    <!-- 列表视图 -->
    <div v-else class="list rise rise-1">
      <table class="list-table">
        <thead>
          <tr>
            <th>任务</th><th>状态</th><th>负责人</th><th>截止</th><th>Phase</th><th>关联资料</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id" @click="openEdit(task)">
            <td class="cell-title">{{ task.title }}</td>
            <td><StatusBadge :label="TASK_STATUS[task.status].label" :tone="TASK_STATUS[task.status].tone" /></td>
            <td>{{ task.assignee ? nameOf(task.assignee) : '—' }}</td>
            <td class="mono" :class="{ overdue: isOverdue(task) }">{{ task.due_date || '—' }}</td>
            <td class="mono">{{ task.phase ? `P${task.phase}` : '—' }}</td>
            <td class="cell-mats">{{ task.materials.map((m) => m.name).join('、') || '—' }}</td>
            <td class="cell-actions">
              <button class="btn btn-sm btn-ghost btn-danger" type="button" @click.stop="askDelete(task)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!tasks.length" title="还没有任务" hint="点右上角「新建任务」开始" />
    </div>

    <TaskDrawer
      v-model="drawerOpen"
      :task="editing"
      :members="members"
      :material-options="materialOptions"
      @save="onSave"
    />
    <UiModal
      v-model="deleteConfirm"
      title="删除任务"
      :message="`确定删除「${deleting?.title}」？删除为软删除，操作留痕。`"
      confirm-text="删除"
      danger
      @confirm="remove(deleting)"
    />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import StatusBadge from '../components/StatusBadge.vue'
import TaskDrawer from '../components/TaskDrawer.vue'
import UiDropdown from '../components/UiDropdown.vue'
import UiModal from '../components/UiModal.vue'
import { useTasks } from '../composables/useTasks.js'
import { MATERIAL_STATUS, TASK_STATUS, TASK_STATUS_ORDER } from '../utils/labels.js'

const { tasks, members, materialOptions, loading, filters, view, load, save, changeStatus, remove } = useTasks()

const drawerOpen = ref(false)
const editing = ref(null)
const deleteConfirm = ref(false)
const deleting = ref(null)
const blockingFor = ref(null)
const blockedReason = ref('')

const columns = computed(() =>
  TASK_STATUS_ORDER.map((status) => ({
    status,
    tasks: tasks.value.filter((t) => t.status === status),
  }))
)

const nameOf = (username) => members.value.find((m) => m.username === username)?.display_name || username

function isOverdue(task) {
  if (!task.due_date || task.status === 'done') return false
  const today = new Date()
  const ymd = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  return task.due_date < ymd
}

function nextStatuses(current) {
  return TASK_STATUS_ORDER.filter((s) => s !== current)
}

function pickStatus(task, status, close) {
  if (status === 'blocked') {
    blockingFor.value = task.id
    blockedReason.value = ''
    return // 留在菜单里填受阻原因
  }
  blockingFor.value = null
  changeStatus(task, status)
  close()
}

function confirmBlocked(task, close) {
  if (!blockedReason.value) return
  blockingFor.value = null
  changeStatus(task, 'blocked', blockedReason.value)
  close()
}

function openCreate() {
  editing.value = null
  drawerOpen.value = true
}
function openEdit(task) {
  editing.value = task
  drawerOpen.value = true
}
async function onSave(id, payload) {
  await save(id, payload)
}
function askDelete(task) {
  deleting.value = task
  deleteConfirm.value = true
}
</script>

<style scoped>
.page-wide { max-width: 1280px; }
.head-row { display: flex; justify-content: space-between; align-items: flex-end; }
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 22px;
  gap: 16px;
  flex-wrap: wrap;
}
.filters { display: flex; gap: 10px; }
.select-inline { width: auto; min-width: 128px; padding: 6px 10px; font-size: 13px; }
.view-toggle {
  display: inline-flex;
  border: 1px solid var(--hairline-strong);
  border-radius: var(--radius);
  padding: 2px;
  background: var(--paper-raised);
}
.toggle-btn {
  padding: 5px 14px;
  font-size: 12.5px;
  color: var(--ink-3);
  border-radius: 2px;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.toggle-btn.active { background: var(--ink); color: var(--paper); }

.board-loading { display: flex; justify-content: center; padding: 100px 0; }

.board {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  align-items: start;
}
.board-col {
  background: var(--paper-sunken);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  padding: 12px;
  min-height: 240px;
}
.col-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 4px 10px;
}
.col-count { font-size: 12px; color: var(--ink-4); }
.col-body { display: flex; flex-direction: column; gap: 10px; }
.col-empty { text-align: center; color: var(--ink-4); padding: 18px 0; }

.task-card {
  background: var(--paper-raised);
  border: 1px solid var(--hairline-strong);
  border-radius: var(--radius);
  padding: 13px 14px 11px;
  cursor: pointer;
  animation: rise-in 300ms var(--ease-out) both;
  transition: border-color var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out),
              transform var(--dur-fast) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .task-card:hover { border-color: var(--ink-3); box-shadow: var(--shadow-raised); }
}
.task-card:active { transform: scale(0.985); }
.task-title { font-size: 13.5px; font-weight: 600; line-height: 1.5; }
.task-blocked {
  margin-top: 6px;
  font-size: 12px;
  color: var(--danger);
  border-left: 2px solid var(--danger-line);
  padding-left: 8px;
}
.task-mats { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.task-mat {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-2);
  background: var(--paper-sunken);
  border: 1px solid var(--hairline);
  border-radius: 2px;
  padding: 1px 7px;
  transition: border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .task-mat:hover { border-color: var(--ink-3); color: var(--ink); }
}
.mat-dot { width: 5px; height: 5px; border-radius: 50%; }
.tone-bg-gold { background: var(--gold-strong); }
.tone-bg-danger { background: var(--danger); }
.tone-bg-amber { background: var(--amber); }
.tone-bg-sage { background: var(--sage); }
.tone-bg-slate { background: var(--slate); }
.tone-bg-muted { background: var(--ink-4); }
.task-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px dashed var(--hairline);
  font-size: 11.5px;
}
.task-assignee { color: var(--ink-2); font-weight: 500; }
.task-assignee.none { color: var(--ink-4); font-weight: 400; }
.task-due { color: var(--ink-3); }
.task-due.overdue, .overdue { color: var(--danger); }
.task-phase { color: var(--ink-4); }
.task-status-slot { margin-left: auto; }
.status-click { display: inline-block; transition: transform var(--dur-fast) var(--ease-out); }
.status-click:active { transform: scale(0.96); }

.status-menu { display: flex; flex-direction: column; min-width: 150px; }
.status-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 9px;
  font-size: 12.5px;
  color: var(--ink-3);
  border-radius: var(--radius);
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .status-option:hover { background: var(--paper-sunken); color: var(--ink); }
}
.blocked-form {
  display: flex;
  gap: 6px;
  padding: 8px;
  border-top: 1px solid var(--hairline);
  margin-top: 4px;
}
.blocked-form .input { padding: 5px 8px; font-size: 12.5px; }

.list-table { width: 100%; border-collapse: collapse; background: var(--paper-raised); border: 1px solid var(--hairline-strong); }
.list-table th {
  text-align: left;
  font-size: 11.5px;
  letter-spacing: 0.08em;
  color: var(--ink-3);
  font-weight: 500;
  padding: 10px 14px;
  border-bottom: 1px solid var(--hairline-strong);
  background: var(--paper-sunken);
}
.list-table td { padding: 11px 14px; border-bottom: 1px solid var(--hairline); font-size: 13px; }
.list-table tbody tr { cursor: pointer; transition: background var(--dur-fast) var(--ease-out); }
.list-table tbody tr:last-child td { border-bottom: none; }
@media (hover: hover) and (pointer: fine) {
  .list-table tbody tr:hover { background: var(--paper-sunken); }
}
.cell-title { font-weight: 600; }
.cell-mats { color: var(--ink-3); font-size: 12px; max-width: 220px; }
.cell-actions { text-align: right; }

@media (max-width: 1000px) {
  .board { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .board { grid-template-columns: 1fr; }
}
</style>
