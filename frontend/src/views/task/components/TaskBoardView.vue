<template>
  <div class="task-board">
    <section
      v-for="col in BOARD_COLUMNS"
      :key="col"
      class="tb-col"
      :class="{ 'is-over': overCol === col }"
      :aria-label="STATUS_META[col].label"
      @dragover.prevent="overCol = col"
      @dragleave="onLeave($event)"
      @drop.prevent="onDrop(col)"
    >
      <header class="tb-head">{{ STATUS_META[col].label }}<span>{{ columns[col].length }}</span></header>
      <article
        v-for="task in columns[col]"
        :key="task.id"
        class="tb-card"
        :class="{ 'is-drag': dragId === task.id, 'is-readonly': !canWrite }"
        :draggable="canWrite"
        tabindex="0"
        @dragstart="dragId = task.id"
        @dragend="dragId = null; overCol = null"
        @click="emit('open', task.id)"
        @keydown.enter="emit('open', task.id)"
      >
        <div class="tb-top">
          <span class="task-code">T-{{ task.id }}</span>
          <span class="task-prio" :class="`is-${task.priority}`">{{ task.priority }}</span>
        </div>
        <div class="tb-title">{{ task.title }}</div>
        <div v-if="parentTitles.get(task.id)" class="tb-parent">↳ {{ parentTitles.get(task.id) }}</div>
        <div class="tb-foot">
          <span class="tb-module">{{ moduleLabel(task.module_key) }}</span>
          <span class="task-due" :class="{ 'is-overdue': isOverdue(task, today) }">{{ task.due_date ? task.due_date.slice(5).replace('-', '/') : '' }}</span>
        </div>
      </article>
      <p v-if="!columns[col].length" class="tb-empty">{{ col === 'pending_confirm' ? 'AI 提议完成后出现在这里' : '拖到这里' }}</p>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { BOARD_COLUMNS, STATUS_META, isOverdue, userStatusOptions } from '../taskLabels.js'

const props = defineProps({
  columns: { type: Object, required: true },
  modulesByKey: { type: Object, required: true },
  parentTitles: { type: Map, required: true },
  today: { type: String, required: true },
  canWrite: { type: Boolean, default: false },
})
const emit = defineEmits(['open', 'move'])

const dragId = ref(null)
const overCol = ref(null)

function moduleLabel(key) {
  return props.modulesByKey[key]?.title ?? ''
}

function onLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) overCol.value = null
}

// 完成确认、受阻原因都由 useTaskCenter.setStatus 统一处理；「待确认」列只接受 AI 提议，拖入忽略（列内有说明）
function onDrop(col) {
  const task = Object.values(props.columns).flat().find(t => t.id === dragId.value)
  dragId.value = null
  overCol.value = null
  if (!props.canWrite || !task || task.status === col || !userStatusOptions(task.status).includes(col)) return
  emit('move', task, col)
}
</script>

<style scoped>
.task-board { display: grid; grid-template-columns: repeat(5, minmax(200px, 1fr)); gap: 12px; align-items: start; overflow-x: auto; }
.tb-col {
  min-height: 320px; padding: 10px; border: 1px solid var(--dash-glass-border); border-radius: 16px;
  background: color-mix(in srgb, var(--card-bg) 40%, transparent); transition: background-color 150ms ease, box-shadow 150ms ease;
}
.tb-col.is-over { background: color-mix(in srgb, var(--card-bg) 75%, transparent); box-shadow: inset 0 0 0 2px var(--color-primary-glow); }
.tb-head { display: flex; justify-content: space-between; padding: 4px 6px 10px; font: 700 13px var(--font-display); }
.tb-head span { color: var(--text-muted); font-variant-numeric: tabular-nums; }
.tb-card {
  margin-bottom: 8px; padding: 11px 12px; border: 1px solid var(--dash-glass-border); border-radius: 12px;
  background: color-mix(in srgb, var(--card-bg) 88%, transparent); box-shadow: var(--card-shadow); cursor: grab;
  transition: transform 200ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 200ms ease;
}
@media (hover: hover) and (pointer: fine) {
  .tb-card:hover { transform: translateY(-2px); box-shadow: var(--card-shadow-hover); }
}
.tb-card.is-drag { opacity: 0.45; }
.tb-card.is-readonly { cursor: pointer; }
@media (prefers-reduced-motion: reduce) { .tb-card { transition: none; } .tb-card:hover { transform: none; } }
.tb-card:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tb-top, .tb-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.tb-title { margin-top: 6px; font-size: 13px; font-weight: 600; line-height: 1.45; }
.tb-parent { margin-top: 4px; font-size: 11.5px; color: var(--text-muted); }
.tb-foot { margin-top: 8px; font-size: 11.5px; color: var(--text-secondary); }
.tb-module { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tb-empty { margin: 24px 0; font-size: 12px; color: var(--text-muted); text-align: center; }
</style>
