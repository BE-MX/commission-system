<template>
  <div class="task-tree lg-card is-static">
    <el-table
      :data="sortedNodes"
      row-key="id"
      default-expand-all
      border
      class="list-table task-tree-table"
      :tree-props="{ children: 'children' }"
      :row-class-name="rowClass"
      @row-click="row => emit('open', row.id)"
      @sort-change="changeSort" v-sticky-scrollbar>
      <el-table-column sortable="custom" prop="title" label="任务" min-width="380">
        <template #default="{ row }">
          <span class="tt-cell">
            <span class="task-code">T-{{ row.id }}</span>
            <span class="tt-title">{{ row.title }}</span>
            <button
              v-permission="'task:write'"
              type="button"
              class="tt-add"
              data-quick-task-trigger
              @click.stop="emit('add-child', row, $event)"
            >+ 子任务</button>
          </span>
        </template>
      </el-table-column>
      <el-table-column sortable="custom" prop="priority" label="重要性" min-width="100" max-width="120">
        <template #default="{ row }">
          <span class="task-prio" :class="`is-${row.priority}`">{{ row.priority }} {{ PRIORITY_META[row.priority].label }}</span>
        </template>
      </el-table-column>
      <el-table-column sortable="custom" prop="module_key" label="关联模块" min-width="170" max-width="240" show-overflow-tooltip>
        <template #default="{ row }">{{ moduleLabel(row.module_key) }}</template>
      </el-table-column>
      <el-table-column sortable="custom" prop="status" label="状态 / 进度" min-width="160" max-width="200">
        <template #default="{ row }">
          <span class="tt-status">
            <span class="task-status" :class="`is-${STATUS_META[row.status].tone}`">{{ STATUS_META[row.status].label }}</span>
            <span v-if="row.progress" class="tt-progress">
              <el-progress :percentage="percent(row)" :show-text="false" :stroke-width="5" />
              {{ row.progress.done }}/{{ row.progress.total }}
            </span>
          </span>
        </template>
      </el-table-column>
      <el-table-column sortable="custom" prop="due_date" label="截止" min-width="80" max-width="100">
        <template #default="{ row }">
          <span class="task-due" :class="{ 'is-overdue': isOverdue(row, today) }">{{ row.due_date ? row.due_date.slice(5).replace('-', '/') : '—' }}</span>
        </template>
      </el-table-column>
      <template #empty>
        <p class="tt-empty">没有符合条件的任务，换个筛选或直接新建</p>
      </template>
    </el-table>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { getSortValue, sortTableTree } from '../../../utils/tableSort.js'
import { CLOSED, PRIORITY_META, STATUS_META, isOverdue } from '../taskLabels.js'

const props = defineProps({
  nodes: { type: Array, required: true },
  modulesByKey: { type: Object, required: true },
  today: { type: String, required: true },
})
const emit = defineEmits(['open', 'add-child'])
const sort = ref({ prop: '', order: null })
const sortedNodes = computed(() => sortTableTree(props.nodes, sort.value.prop, sort.value.order, row => {
  if (sort.value.prop === 'module_key') return moduleLabel(row.module_key)
  if (sort.value.prop === 'status') return STATUS_META[row.status]?.label || row.status
  return getSortValue(row, sort.value.prop)
}))
function changeSort({ prop, order }) { sort.value = { prop, order } }

function moduleLabel(key) {
  const m = props.modulesByKey[key]
  return m ? `${m.group_title} · ${m.title}` : (key ? '已停用模块' : '—')
}

function percent(row) {
  return row.progress.total ? Math.round((row.progress.done / row.progress.total) * 100) : 0
}

function rowClass({ row }) {
  return [
    row.status === 'pending_confirm' ? 'is-pending' : '',
    CLOSED.has(row.status) ? 'is-closed' : '',
  ].join(' ')
}
</script>

<style scoped>
/* 表格融入玻璃：用 Element 的 CSS 变量在容器上继承，不做 Element 内部类的深度覆盖（UI 门禁） */
.task-tree {
  overflow: hidden;
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: color-mix(in srgb, var(--card-bg) 50%, transparent);
  --el-table-row-hover-bg-color: color-mix(in srgb, var(--card-bg) 70%, transparent);
}
.tt-cell { display: inline-flex; align-items: center; gap: 8px; max-width: calc(100% - 24px); vertical-align: middle; }
.tt-title { overflow: hidden; font-size: 13.5px; text-overflow: ellipsis; white-space: nowrap; }
.tt-add {
  flex-shrink: 0; height: 24px; padding: 0 8px; border: 0; border-radius: 6px;
  background: var(--button-primary-soft); color: var(--button-primary); font-size: 12px; cursor: pointer;
  opacity: 0; transition: opacity 120ms ease;
}
.el-table__row:hover .tt-add, .tt-add:focus-visible { opacity: 1; }
@media (hover: none) { .tt-add { opacity: 1; } }
.tt-status { display: grid; gap: 4px; }
.tt-progress { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 6px; font-size: 11.5px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.tt-empty { margin: 24px 0; font-size: 13px; color: var(--text-muted); }
</style>
