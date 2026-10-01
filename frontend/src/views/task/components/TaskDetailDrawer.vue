<template>
  <DetailDrawer
    :model-value="modelValue"
    :title="detail ? `T-${detail.id}` : '任务详情'"
    :width="640"
    :loading="loading"
    @update:model-value="v => emit('update:modelValue', v)"
  >
    <ListPageStatus :paged="false" :error="detailResource.errorMessage.value" :loading="loading" :has-data="detailResource.hasData.value" @retry="load" />
    <template v-if="detail">
      <p v-if="detail.path.length" class="td-path">{{ detail.path.map(p => `${p.code} ${p.title}`).join(' › ') }}</p>
      <el-input v-model="form.title" maxlength="200" :input-style="TITLE_STYLE" :disabled="!canWrite" @change="save('title')" />
      <el-alert v-if="detail.status === 'blocked'" :title="`受阻：${detail.blocked_reason}`" type="error" :closable="false" class="td-alert" />

      <div class="td-fields">
        <label class="td-field">
          <span>状态</span>
          <el-select :model-value="detail.status" class="td-control" :disabled="!canWrite" @change="to => emit('status', detail, to)">
            <el-option v-for="s in userStatusOptions(detail.status)" :key="s" :value="s" :label="STATUS_META[s].label" :disabled="s === detail.status" />
          </el-select>
        </label>
        <label class="td-field">
          <span>重要性</span>
          <el-select v-model="form.priority" class="td-control" :disabled="!canWrite" @change="save('priority')">
            <el-option v-for="p in PRIORITIES" :key="p" :value="p" :label="`${p} ${PRIORITY_META[p].label}`" />
          </el-select>
        </label>
        <label class="td-field">
          <span>关联模块</span>
          <el-select v-model="form.module_key" class="td-control" filterable clearable placeholder="不关联" :disabled="!canWrite" @change="save('module_key')">
            <el-option v-if="form.module_key && !moduleKeys.has(form.module_key)" :value="form.module_key" label="已停用模块" disabled />
            <el-option-group v-for="g in moduleGroups" :key="g.title" :label="g.title">
              <el-option v-for="m in g.items" :key="m.key" :value="m.key" :label="m.title" />
            </el-option-group>
          </el-select>
        </label>
        <label class="td-field td-field--wide">
          <span>父任务</span>
          <el-select v-model="form.parent_id" class="td-control" filterable clearable placeholder="顶层任务" :disabled="!canWrite" @change="move">
            <el-option v-for="p in parentOptions" :key="p.id" :value="p.id" :label="p.label" :disabled="p.id === detail.id" />
          </el-select>
        </label>
        <label class="td-field">
          <span>截止</span>
          <el-date-picker v-model="form.due_date" class="td-control" type="date" value-format="YYYY-MM-DD" clearable :disabled="!canWrite" @change="save('due_date')" />
        </label>
      </div>

      <section class="td-sec">
        <h4>验收标准</h4>
        <el-input v-model="form.acceptanceText" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" :disabled="!canWrite"
          placeholder="每行一条。二期起 AI 提议完成时会逐条对照" @change="save('acceptance')" />
      </section>

      <section class="td-sec">
        <h4>描述</h4>
        <el-input v-model="form.description" type="textarea" :autosize="{ minRows: 2, maxRows: 10 }" :disabled="!canWrite"
          placeholder="背景、链接、想法都可以写在这里" @change="save('description')" />
      </section>

      <section class="td-sec">
        <h4>
          子任务<span v-if="detail.progress" class="td-count">{{ detail.progress.done }}/{{ detail.progress.total }}</span>
          <el-button v-permission="'task:write'" link type="primary" data-quick-task-trigger @click="emit('add-child', detail, $event)">+ 子任务</el-button>
        </h4>
        <button v-for="c in detail.children" :key="c.id" type="button" class="td-child" @click="emit('open', c.id)">
          <span class="task-code">T-{{ c.id }}</span><span class="td-child-title">{{ c.title }}</span>
          <span class="task-status" :class="`is-${STATUS_META[c.status].tone}`">{{ STATUS_META[c.status].label }}</span>
        </button>
        <p v-if="!detail.children.length" class="td-empty">没有子任务。超过一天的事，拆成子任务更好跟进</p>
      </section>

      <section class="td-sec">
        <h4>关联</h4>
        <div v-for="l in detail.links" :key="l.id" class="td-link">
          <span class="td-kind">{{ LINK_KIND_META[l.kind] }}</span>
          <a v-if="l.kind === 'url'" :href="l.ref" target="_blank" rel="noopener">{{ l.title }}</a>
          <code v-else :title="l.ref">{{ l.ref }}</code>
          <el-button v-permission="'task:write'" link @click="unlink(l)">移除</el-button>
        </div>
        <p v-if="!detail.links.length" class="td-empty">分支和 commit 自动关联在二期上线，现在可以手工挂文档或原型</p>
        <div v-permission="'task:write'" class="td-link-form">
          <el-select v-model="linkForm.kind" class="td-link-kind">
            <el-option v-for="(label, kind) in LINK_KIND_META" :key="kind" :value="kind" :label="label" />
          </el-select>
          <el-input v-model="linkForm.ref" :placeholder="linkForm.kind === 'url' ? 'https://...' : 'docs/requirements/...'" @keyup.enter="link" />
          <GlassButton size="sm" @click="link">添加</GlassButton>
        </div>
      </section>

      <section class="td-sec">
        <h4>时间线</h4>
        <ol class="td-timeline">
          <li v-for="e in detail.events" :key="e.id" :class="{ 'is-ai': e.actor === 'ai' }">
            <time>{{ formatBeijingShortDateTime(e.created_at) }}</time>{{ ACTOR_LABELS[e.actor] || e.actor }} {{ eventText(e) }}
          </li>
        </ol>
      </section>
    </template>

    <template #footer>
      <template v-if="detail">
        <GlassButton v-permission="'task:write'" variant="danger" @click="remove">删除</GlassButton>
        <GlassButton @click="copyBrief">复制代理任务书</GlassButton>
        <GlassButton v-if="detail.status === 'done' || detail.status === 'shelved'" v-permission="'task:write'" @click="emit('status', detail, 'todo')">重开</GlassButton>
        <GlassButton v-else v-permission="'task:write'" variant="primary" @click="emit('status', detail, 'done')">标记完成</GlassButton>
      </template>
    </template>
  </DetailDrawer>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { addTaskLink, deleteTask, getTask, moveTask, removeTaskLink, updateTask } from '@/api/task'
import { useAuthStore } from '@/stores/auth'
import { formatBeijingShortDateTime } from '@/utils/datetime'
import { confirmDanger, msgError, msgSuccess } from '@/utils/feedback'
import {
  ACTOR_LABELS, EVENT_LABELS, LINK_KIND_META, PRIORITIES, PRIORITY_META, STATUS_META, userStatusOptions,
} from '../taskLabels.js'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { flattenForSelect } from '../taskTree.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  taskId: { type: Number, default: null },
  refreshKey: { type: Number, default: 0 },
  modules: { type: Array, default: () => [] },
  tree: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'status', 'changed', 'open', 'add-child'])

const TITLE_STYLE = { fontFamily: 'var(--font-display)', fontSize: '17px', fontWeight: 700 }
const FIELD_LABELS = { title: '标题', description: '描述', acceptance: '验收标准', priority: '重要性', module_key: '关联模块', due_date: '截止' }

const authStore = useAuthStore()
const canWrite = computed(() => authStore.hasPermission('task:write'))
const detailResource = useAsyncResource(async (id, { signal, isCurrent }) => {
  const data = (await getTask(id, { signal, suppressToast: true })).data
  if (isCurrent()) Object.assign(form, {
    title: data.title, priority: data.priority, module_key: data.module_key, parent_id: data.parent_id,
    due_date: data.due_date, acceptanceText: (data.acceptance || []).join('\n'), description: data.description || '',
  })
  return data
})
const detail = detailResource.data, loading = detailResource.loading
const form = reactive({ title: '', priority: 'P2', module_key: null, parent_id: null, due_date: null, acceptanceText: '', description: '' })
// 可选父任务：未结束任务，自己禁选；成环与层数超限由后端校验并提示
const parentOptions = computed(() => flattenForSelect(props.tree))
const linkForm = reactive({ kind: 'doc', ref: '' })

const moduleKeys = computed(() => new Set(props.modules.map(m => m.key)))
const moduleGroups = computed(() => {
  const groups = new Map()
  for (const m of props.modules) {
    if (!groups.has(m.group_title)) groups.set(m.group_title, { title: m.group_title, items: [] })
    groups.get(m.group_title).items.push(m)
  }
  return [...groups.values()]
})

function load() {
  if (!props.modelValue || !props.taskId) return false
  return detailResource.load(props.taskId)
}
watch(() => [props.modelValue, props.taskId], () => { detailResource.clear(); if (props.modelValue) void load() })
watch(() => props.refreshKey, load)
watch(() => authStore.user?.id, () => { detailResource.clear(); emit('update:modelValue', false) })

async function save(field) {
  const value = field === 'acceptance'
    ? form.acceptanceText.split('\n').map(s => s.trim()).filter(Boolean)
    : (form[field] === '' ? null : form[field])
  try {
    await updateTask(detail.value.id, { [field]: value })
    emit('changed')
  } catch {
    await load()   // 拦截器已提示原因；回滚为服务器上的值
  }
}

async function move(parentId) {
  try {
    await moveTask(detail.value.id, parentId ?? null)
    emit('changed')
  } catch {
    await load()
  }
}

async function link() {
  if (!linkForm.ref.trim()) return
  await addTaskLink(detail.value.id, { kind: linkForm.kind, ref: linkForm.ref.trim() })
  linkForm.ref = ''
  await load()
}

async function unlink(item) {
  await removeTaskLink(item.id)
  await load()
}

async function remove() {
  try {
    await confirmDanger('删除', `T-${detail.value.id} ${detail.value.title}`, '子任务会一起进入回收站，可以在回收站恢复。')
  } catch {
    return
  }
  await deleteTask(detail.value.id)
  msgSuccess('删除')
  emit('update:modelValue', false)
  emit('changed')
}

function eventText(e) {
  const p = e.payload || {}
  if (e.type === 'status_changed') {
    const from = STATUS_META[p.from]?.label ?? p.from
    const to = STATUS_META[p.to]?.label ?? p.to
    return `${from} → ${to}${p.reason ? `：${p.reason}` : ''}`
  }
  if (e.type === 'updated') return `修改了${(p.fields || []).map(f => FIELD_LABELS[f] || f).join('、')}`
  if (e.type === 'created' && p.source === 'nav_quick') return '从导航栏悬浮 + 创建'
  if (e.type === 'created' && p.source === 'header_quick') return '从页头「记任务」创建'
  if (e.type === 'linked' || e.type === 'unlinked') return `${EVENT_LABELS[e.type]} ${p.ref}`
  return EVENT_LABELS[e.type] || e.type
}

async function copyBrief() {
  const d = detail.value
  const m = props.modules.find(x => x.key === d.module_key)
  const text = [
    `任务 ${d.code}：${d.title}`,
    `模块：${m ? `${m.group_title} / ${m.title}` : '未关联'}`,
    '验收标准：',
    ...((d.acceptance || []).length ? d.acceptance.map((a, i) => `${i + 1}. ${a}`) : ['（待补）']),
    `分支命名：<tool>/${d.code}-<slug>；commit message 带 ${d.code}。`,
    '完成后提议完成，不要自行标记完成。',
  ].join('\n')
  try {
    await navigator.clipboard.writeText(text)
    msgSuccess('复制代理任务书')
  } catch {
    msgError('浏览器不允许写剪贴板，请在抽屉里手动复制验收标准')
  }
}
</script>

<style scoped>
.td-path { margin: 0 0 6px; font-size: 12px; color: var(--text-muted); }
.td-alert { margin-top: 10px; }
.td-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.td-field { display: grid; gap: 4px; }
.td-field > span { font-size: 11.5px; color: var(--text-muted); }
.td-field--wide { grid-column: 1 / -1; }
.td-control { width: 100%; }
.td-sec { margin-top: 18px; }
.td-sec h4 {
  display: flex; align-items: center; gap: 8px; margin: 0 0 8px;
  font: 700 12px var(--font-display); letter-spacing: 0.06em; color: var(--text-muted);
}
.td-sec h4 .el-button { margin-left: auto; }
.td-count { color: var(--text-secondary); letter-spacing: 0; }
.td-child {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 10px; border: 0; border-radius: 9px;
  background: transparent; text-align: left; cursor: pointer;
}
.td-child:hover { background: var(--color-info-bg); }
.td-child-title { flex: 1; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.td-empty { margin: 0; font-size: 12.5px; color: var(--text-muted); }
.td-link { display: flex; align-items: center; gap: 10px; padding: 8px 10px; margin-bottom: 6px; border: 1px solid var(--border-color); border-radius: 10px; font-size: 12.5px; }
.td-link code, .td-link a { flex: 1; overflow: hidden; font-family: var(--font-mono); text-overflow: ellipsis; white-space: nowrap; }
.td-kind { width: 36px; flex-shrink: 0; font: 700 11px var(--font-display); color: var(--text-muted); }
.td-link-form { display: flex; gap: 8px; margin-top: 8px; }
.td-link-kind { width: 90px; flex-shrink: 0; }
.td-timeline { display: grid; gap: 8px; margin: 0; padding: 0 0 0 14px; border-left: 2px solid var(--border-color); list-style: none; }
.td-timeline li { font-size: 12.5px; color: var(--text-secondary); }
.td-timeline li.is-ai { color: var(--color-warning-text); }
.td-timeline time { margin-right: 6px; font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
@media (max-width: 480px) { .td-fields { grid-template-columns: 1fr; } }
</style>
