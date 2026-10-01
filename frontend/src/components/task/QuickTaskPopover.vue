<template>
  <Teleport to="body">
    <Transition name="quick-pop">
      <section
        v-if="quickTask.open"
        ref="panelRef"
        class="quick-task"
        :style="panelStyle"
        role="dialog"
        aria-labelledby="quick-task-title"
        @keydown="onKeydown"
      >
        <header class="quick-task__head">
          <h2 id="quick-task-title">{{ quickTask.parentId ? '加子任务' : '记任务' }}</h2>
          <span v-if="moduleLabel" class="quick-task__pill">
            {{ moduleLabel }}
            <button type="button" aria-label="取消预填模块" @click="clearModule">×</button>
          </span>
          <span v-else class="quick-task__pill is-muted">AI 自动识别模块</span>
          <button type="button" class="quick-task__close" aria-label="关闭" @click="closeQuickTask">×</button>
        </header>

        <el-input
          ref="textRef"
          v-model="text"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 6 }"
          maxlength="1000"
          placeholder="一句话说清要做什么，例如：回款列表按业务员筛选很慢，明天前搞定"
        />

        <p v-if="drafting" class="quick-task__thinking" aria-live="polite">
          <span class="quick-task__shimmer" />AI 正在补全标题、重要性和验收标准…
        </p>

        <div v-if="draft" class="quick-task__draft">
          <el-alert v-if="draft.notice" :title="draft.notice" type="warning" :closable="false" show-icon />
          <p v-if="draft.duplicates.length" class="quick-task__dup">
            可能和
            <template v-for="(d, i) in draft.duplicates" :key="d.id">{{ i ? '、' : '' }}<b>{{ d.code }} {{ d.title }}</b></template>
            重复，确认是新任务再创建
          </p>
          <el-form label-position="top">
            <el-form-item label="标题"><el-input v-model="draft.title" maxlength="200" /></el-form-item>
            <div class="quick-task__grid">
              <el-form-item label="重要性">
                <el-select v-model="draft.priority" @visible-change="trackInner">
                  <el-option v-for="p in PRIORITIES" :key="p" :value="p" :label="`${p} ${PRIORITY_META[p].label}`" />
                </el-select>
              </el-form-item>
              <el-form-item label="截止">
                <el-date-picker v-model="draft.due_date" type="date" value-format="YYYY-MM-DD" clearable class="quick-task__date" @visible-change="trackInner" />
              </el-form-item>
              <el-form-item label="关联模块">
                <el-select v-model="draft.module_key" filterable clearable placeholder="不关联" @visible-change="trackInner">
                  <el-option-group v-for="g in moduleGroups" :key="g.title" :label="g.title">
                    <el-option v-for="m in g.items" :key="m.key" :value="m.key" :label="m.title" />
                  </el-option-group>
                </el-select>
              </el-form-item>
              <el-form-item label="父任务">
                <el-select v-model="draft.parent_id" filterable clearable placeholder="顶层任务" @visible-change="trackInner">
                  <el-option v-for="p in parentOptions" :key="p.id" :value="p.id" :label="p.label" />
                </el-select>
              </el-form-item>
            </div>
            <el-form-item label="验收标准（每行一条）">
              <el-input v-model="acceptanceText" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
            </el-form-item>
          </el-form>
        </div>

        <footer class="quick-task__actions">
          <span class="quick-task__hint"><kbd>Ctrl</kbd>+<kbd>Enter</kbd> {{ draft ? '创建' : 'AI 补全' }} · <kbd>Esc</kbd> 关闭</span>
          <template v-if="draft">
            <GlassButton size="sm" :disabled="drafting || !hasText" @click="runDraft">重新补全</GlassButton>
            <GlassButton size="sm" variant="primary" :loading="saving" :disabled="!draft.title.trim()" @click="create(false)">创建任务</GlassButton>
          </template>
          <template v-else>
            <GlassButton size="sm" :disabled="drafting || saving || !hasText" @click="create(true)">直接创建</GlassButton>
            <GlassButton size="sm" variant="primary" :loading="drafting" :disabled="!hasText" @click="runDraft">AI 补全</GlassButton>
          </template>
        </footer>
      </section>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useZIndex } from 'element-plus'
import GlassButton from '@/components/GlassButton.vue'
import { createTask, draftTask, listTaskModules, listTasks } from '@/api/task'
import { useQuickTask } from '@/composables/useQuickTask'
import { msgSuccess } from '@/utils/feedback'
import { PRIORITIES, PRIORITY_META } from '@/views/task/taskLabels.js'
import { flattenForSelect } from '@/views/task/taskTree.js'

const WIDTH = 440
const EST_HEIGHT = 540
const { quickTask, closeQuickTask, notifyCreated } = useQuickTask()
const { nextZIndex } = useZIndex()

const panelRef = ref(null)
const textRef = ref(null)
const text = ref('')
const draft = ref(null)
const acceptanceText = ref('')
const moduleKey = ref(null)
const drafting = ref(false)
const saving = ref(false)
const modules = ref([])
const tree = ref([])
const zIndex = ref(2000)
const innerOpen = ref(0)   // 打开中的内层下拉/日期面板数：>0 时 Esc 只交给面板自己收起

const hasText = computed(() => Boolean(text.value.trim()))
const moduleLabel = computed(() => {
  const m = modules.value.find(x => x.key === moduleKey.value)
  return m ? `${m.group_title} · ${m.title}` : ''
})
const moduleGroups = computed(() => {
  const groups = new Map()
  for (const m of modules.value) {
    if (!groups.has(m.group_title)) groups.set(m.group_title, { title: m.group_title, items: [] })
    groups.get(m.group_title).items.push(m)
  }
  return [...groups.values()]
})
const parentOptions = computed(() => flattenForSelect(tree.value))

// 侧栏入口在菜单项右侧展开，页头/页面入口在按钮下方右对齐；都夹在视口内。
const panelStyle = computed(() => {
  const a = quickTask.anchor
  const vw = window.innerWidth
  const vh = window.innerHeight
  let left
  let top
  let origin
  if (!a) {
    left = (vw - WIDTH) / 2; top = 96; origin = 'center top'
  } else if (a.side === 'right') {
    left = a.right + 10; top = a.top - 8; origin = 'left top'
  } else {
    left = a.right - WIDTH; top = a.bottom + 8; origin = 'right top'
  }
  left = Math.max(12, Math.min(left, vw - WIDTH - 12))
  top = Math.max(12, Math.min(top, vh - EST_HEIGHT - 12))
  return {
    left: `${left}px`, top: `${top}px`, width: `${Math.min(WIDTH, vw - 24)}px`,
    transformOrigin: origin, zIndex: zIndex.value,
  }
})

function trackInner(visible) {
  innerOpen.value = Math.max(0, innerOpen.value + (visible ? 1 : -1))
}

// 每次打开都重取：新建的私有分类、刚建的任务都能立刻出现在下拉里
async function loadOptions() {
  const [m, t] = await Promise.all([listTaskModules(), listTasks()])
  modules.value = m.data
  tree.value = t.data
  if (moduleKey.value && !modules.value.some(x => x.key === moduleKey.value)) moduleKey.value = null
}

watch(() => quickTask.seq, async () => {
  if (!quickTask.open) return
  zIndex.value = nextZIndex()
  innerOpen.value = 0
  text.value = ''
  draft.value = null
  acceptanceText.value = ''
  moduleKey.value = quickTask.moduleKey
  await nextTick()
  textRef.value?.focus()
  loadOptions().catch(() => { /* 拦截器已提示；浮层仍可「直接创建」 */ })
})

function clearModule() {
  moduleKey.value = null
  if (draft.value) draft.value.module_key = null
}

async function runDraft() {
  if (!hasText.value || drafting.value) return
  drafting.value = true
  try {
    const res = await draftTask({ text: text.value, module_key: moduleKey.value, parent_id: quickTask.parentId })
    draft.value = { ...res.data }
    acceptanceText.value = (res.data.acceptance || []).join('\n')
  } finally {
    drafting.value = false
  }
}

async function create(raw) {
  if (saving.value || (raw ? !hasText.value : !draft.value?.title.trim())) return
  const payload = raw
    ? { title: text.value.trim().slice(0, 200), module_key: moduleKey.value, parent_id: quickTask.parentId, source: quickTask.source }
    : {
        title: draft.value.title.trim(),
        priority: draft.value.priority,
        due_date: draft.value.due_date || null,
        module_key: draft.value.module_key || null,
        parent_id: draft.value.parent_id || null,
        acceptance: acceptanceText.value.split('\n').map(line => line.trim()).filter(Boolean),
        source: quickTask.source,
      }
  saving.value = true
  try {
    const res = await createTask(payload)
    msgSuccess(`创建 T-${res.data.id} `)
    notifyCreated(res.data.id)
    closeQuickTask()
  } finally {
    saving.value = false
  }
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    if (innerOpen.value) return
    event.stopPropagation()
    closeQuickTask()
  } else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    if (draft.value) create(false)
    else runDraft()
  }
}

// 点浮层外关闭；放过：另一个入口按钮（交给 openQuickTask 重新初始化）、teleport 出去的下拉/日期面板、消息框
function onPointerDown(event) {
  if (!quickTask.open || panelRef.value?.contains(event.target)) return
  if (event.target.closest?.('[data-quick-task-trigger], .el-popper, .el-message-box, .el-overlay')) return
  closeQuickTask()
}
document.addEventListener('pointerdown', onPointerDown, true)
onBeforeUnmount(() => document.removeEventListener('pointerdown', onPointerDown, true))
</script>

<style scoped>
.quick-task {
  position: fixed;
  max-height: calc(100dvh - 24px);
  overflow-y: auto;
  padding: 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: 16px;
  background: var(--card-bg);
  box-shadow: var(--dash-glass-shadow-hover);
}
.quick-task__head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.quick-task__head h2 { margin: 0; font: 700 14px var(--font-display); color: var(--text-primary); }
.quick-task__pill {
  display: inline-flex; align-items: center; gap: 6px; height: 24px; padding: 0 9px; border-radius: 6px;
  font-size: 12px; color: var(--color-warning-text); background: var(--color-gold-soft);
}
.quick-task__pill.is-muted { color: var(--text-muted); background: var(--color-info-bg); }
.quick-task__pill button, .quick-task__close { border: 0; background: none; color: inherit; cursor: pointer; }
.quick-task__close { margin-left: auto; width: 28px; height: 28px; border-radius: 8px; font-size: 18px; color: var(--text-muted); }
.quick-task__close:hover { background: var(--color-info-bg); }
.quick-task__thinking { display: flex; align-items: center; gap: 10px; margin: 12px 0 0; font-size: 12.5px; color: var(--text-secondary); }
.quick-task__shimmer {
  width: 80px; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg, var(--color-info-bg), var(--color-gold-soft), var(--color-info-bg));
  background-size: 200% 100%; animation: quick-shimmer 1s linear infinite;
}
@keyframes quick-shimmer { to { background-position: -200% 0; } }
.quick-task__draft { margin-top: 12px; padding: 12px; border-radius: 12px; border: 1px solid var(--border-color); }
.quick-task__dup { margin: 0 0 10px; padding: 8px 10px; border-radius: 8px; font-size: 12px; color: var(--color-warning-text); background: var(--color-warning-bg); }
.quick-task__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px; }
.quick-task__date { width: 100%; }
.quick-task__actions { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.quick-task__hint { margin-right: auto; font-size: 11.5px; color: var(--text-muted); }
.quick-task__hint kbd { padding: 0 4px; border: 1px solid var(--border-color); border-radius: 4px; font: 600 10.5px var(--font-mono); }

/* 起止动效：进 200ms、出 120ms，strong ease-out；从触发点方向缩放展开 */
.quick-pop-enter-active { transition: opacity 180ms cubic-bezier(0.23, 1, 0.32, 1), transform 200ms cubic-bezier(0.23, 1, 0.32, 1); }
.quick-pop-leave-active { transition: opacity 120ms ease, transform 120ms ease; }
.quick-pop-enter-from, .quick-pop-leave-to { opacity: 0; transform: scale(0.96); }
@media (prefers-reduced-motion: reduce) {
  .quick-pop-enter-from, .quick-pop-leave-to { transform: none; }
  .quick-task__shimmer { animation: none; }
}
@media (max-width: 480px) {
  .quick-task__grid { grid-template-columns: 1fr; }
}
</style>
