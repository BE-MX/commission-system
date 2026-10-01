<template>
  <div class="task-center">
    <div class="task-center-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="tc-head">
      <div>
        <h2 class="tc-title">任务中心</h2>
        <p class="tc-sub">方舟开发需求与个人事项 · 仅本人可见 · 导航栏悬停 + 可随手记</p>
      </div>
      <div class="tc-stats">
        <div v-for="s in statCards" :key="s.key" class="tc-stat" :class="s.tone">
          <b>{{ stats[s.key] }}</b><span>{{ s.label }}</span>
        </div>
      </div>
    </header>

    <TaskBriefCard class="tc-block" :brief="brief" :loading="briefLoading" @open="openTask" />

    <section class="tc-toolbar tc-block lg-card is-static">
      <el-segmented v-model="view" :options="VIEW_OPTIONS" />
      <el-input v-model="filters.q" clearable placeholder="搜索标题 / T-编号" class="tc-search" />
      <el-select v-model="filters.moduleKey" clearable filterable placeholder="全部模块" class="tc-module">
        <el-option-group v-for="g in heat" :key="g.group_key" :label="g.group_title">
          <el-option v-for="m in g.items" :key="m.key" :value="m.key" :label="m.title" />
        </el-option-group>
      </el-select>
      <div class="tc-prios" role="group" aria-label="按重要性筛选">
        <el-check-tag v-for="p in PRIORITIES" :key="p" :checked="filters.priorities.includes(p)" @change="togglePriority(p)">{{ p }}</el-check-tag>
      </div>
      <el-checkbox v-model="filters.hideClosed">隐藏已结束</el-checkbox>
      <span class="tc-spacer" />
      <el-popover trigger="click" :width="380" placement="bottom-end" @show="loadTrash">
        <template #reference><GlassButton>回收站</GlassButton></template>
        <p v-if="!trash.length" class="tc-trash-empty">回收站是空的</p>
        <ul v-else class="tc-trash">
          <li v-for="item in trash" :key="item.id">
            <span class="task-code">T-{{ item.id }}</span><span class="tc-trash-title">{{ item.title }}</span>
            <el-button v-permission="'task:write'" link type="primary" @click="restore(item)">恢复</el-button>
          </li>
        </ul>
      </el-popover>
      <GlassButton v-permission="'task:write'" variant="primary" left-icon="Plus" data-quick-task-trigger @click="newTask">新建任务</GlassButton>
    </section>

    <section v-loading="loading && !tree.length" class="tc-block">
      <TaskTreeView
        v-if="view === 'tree'"
        :nodes="filteredTree"
        :modules-by-key="modulesByKey"
        :today="today"
        @open="openTask"
        @add-child="addChild"
      />
      <TaskBoardView
        v-else-if="view === 'board'"
        :columns="columns"
        :modules-by-key="modulesByKey"
        :parent-titles="parentTitleMap"
        :today="today"
        :can-write="canWrite"
        @open="openTask"
        @move="setStatus"
      />
      <TaskModuleMap v-else :groups="heat" @pick="pickModule" @add-custom="addCustom" @remove-custom="removeCustom" />
    </section>

    <TaskDetailDrawer
      v-model="drawerOpen"
      :task-id="selectedId"
      :refresh-key="version"
      :modules="modules"
      :tree="tree"
      @status="setStatus"
      @changed="refresh"
      @open="openTask"
      @add-child="addChild"
    />
    <TaskPromptDialog />
  </div>
</template>

<script setup>
import './task-tags.css'
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { useQuickTask } from '@/composables/useQuickTask'
import { useAuthStore } from '@/stores/auth'
import TaskBoardView from './components/TaskBoardView.vue'
import TaskBriefCard from './components/TaskBriefCard.vue'
import TaskDetailDrawer from './components/TaskDetailDrawer.vue'
import TaskModuleMap from './components/TaskModuleMap.vue'
import TaskPromptDialog from './components/TaskPromptDialog.vue'
import TaskTreeView from './components/TaskTreeView.vue'
import { useTaskCenter } from './composables/useTaskCenter'
import { PRIORITIES } from './taskLabels.js'

defineOptions({ name: 'TaskCenter' })

const VIEW_OPTIONS = [
  { label: '树形', value: 'tree' },
  { label: '看板', value: 'board' },
  { label: '模块地图', value: 'map' },
]
const statCards = [
  { key: 'in_progress', label: '进行中', tone: '' },
  { key: 'pending_confirm', label: '待确认完成', tone: 'is-gold' },
  { key: 'p0_open', label: 'P0 未结束', tone: 'is-red' },
  { key: 'overdue', label: '已逾期', tone: 'is-red' },
]

const {
  tree, modules, stats, brief, trash, loading, briefLoading, version, today, view, filters,
  modulesByKey, filteredTree, columns, heat, parentTitleMap,
  refresh, loadAll, setStatus, loadTrash, restore, togglePriority, addCustom, removeCustom,
} = useTaskCenter()
const { openQuickTask, lastCreatedId } = useQuickTask()
const authStore = useAuthStore()
const canWrite = computed(() => authStore.hasPermission('task:write'))

const drawerOpen = ref(false)
const selectedId = ref(null)

function openTask(id) {
  selectedId.value = id
  drawerOpen.value = true
}

function newTask(event) {
  openQuickTask({ anchorEl: event?.currentTarget, moduleKey: filters.moduleKey || null, source: 'manual' })
}

function addChild(task, event) {
  openQuickTask({ anchorEl: event?.currentTarget, moduleKey: task.module_key, parentId: task.id, source: 'manual' })
}

function pickModule(key) {
  filters.moduleKey = key
  view.value = 'tree'
}

watch(lastCreatedId, refresh)
onMounted(loadAll)
// 页面被多标签缓存（keep-alive）时，切回来刷新一次，吃到在别的页面用悬浮 + 建的任务；
// 首次挂载时 onActivated 也会触发，跳过它避免与 loadAll 重复请求
let activatedOnce = false
onActivated(() => {
  if (activatedOnce) refresh()
  activatedOnce = true
})
</script>

<style scoped>
.task-center { position: relative; }
.task-center-aurora { inset: -24px -28px; }
.tc-head, .tc-block { position: relative; z-index: 1; }
.tc-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.tc-title { margin: 0; font: 800 26px var(--font-display); color: var(--text-primary); }
.tc-sub { margin: 4px 0 0; font-size: 13px; color: var(--text-secondary); }
.tc-stats { display: flex; flex-wrap: wrap; gap: 10px; }
.tc-stat {
  min-width: 100px; padding: 10px 14px; border: 1px solid var(--dash-glass-border); border-radius: 14px;
  background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow);
}
.tc-stat b { display: block; font: 800 22px var(--font-display); font-variant-numeric: tabular-nums; }
.tc-stat span { font-size: 11.5px; color: var(--text-secondary); }
.tc-stat.is-gold b { color: var(--color-primary); }
.tc-stat.is-red b { color: var(--color-danger); }
.tc-block { margin-bottom: 14px; }
.tc-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 10px 12px; }
.tc-search { width: 200px; }
.tc-module { width: 200px; }
.tc-prios { display: flex; gap: 4px; }
.tc-spacer { flex: 1; }
.tc-trash { display: grid; gap: 6px; max-height: 320px; margin: 0; padding: 0; overflow-y: auto; list-style: none; }
.tc-trash li { display: flex; align-items: center; gap: 8px; }
.tc-trash-title { flex: 1; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.tc-trash-empty { margin: 0; font-size: 13px; color: var(--text-muted); }
@media (max-width: 640px) {
  .tc-search, .tc-module { width: 100%; }
  .tc-spacer { display: none; }
}
</style>
