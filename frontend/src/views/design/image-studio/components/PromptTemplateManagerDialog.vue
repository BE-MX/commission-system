<template>
  <el-dialog
    :model-value="visible"
    :title="editing ? (form.id ? '编辑模板' : '新增模板') : '管理提示词模板'"
    width="760px"
    append-to-body
    class="prompt-manager-dialog"
    @update:model-value="emit('update:visible', $event)"
    @open="onOpen"
  >
    <!-- ── 列表视图 ── -->
    <div v-if="!editing" v-loading="loading" class="mgr-list">
      <div class="mgr-toolbar">
        <el-switch v-model="showInactive" inline-prompt active-text="含停用" inactive-text="仅启用" @change="fetchItems" />
        <GlassButton variant="primary" size="sm" @click="startCreate">
          <template #left-icon><el-icon><Plus /></el-icon></template>
          新增模板
        </GlassButton>
      </div>
      <div class="mgr-rows">
        <div v-for="item in items" :key="item.id" class="mgr-row" :class="{ 'is-inactive': !item.is_active }">
          <div class="mgr-row-main">
            <div class="mgr-row-head">
              <strong>{{ item.name }}</strong>
              <span class="mgr-category">{{ categoryLabel(item.category) }}</span>
              <span class="mgr-sort">排序 {{ item.sort }}</span>
              <span class="mgr-status" :class="item.is_active ? 'is-on' : 'is-off'">{{ item.is_active ? '启用中' : '已停用' }}</span>
            </div>
            <p>{{ item.content }}</p>
          </div>
          <div class="mgr-row-actions">
            <GlassButton variant="ghost" size="sm" @click="startEdit(item)">编辑</GlassButton>
            <GlassButton v-if="item.is_active" variant="ghost" size="sm" @click="disable(item)">停用</GlassButton>
            <GlassButton v-else variant="soft" size="sm" @click="enable(item)">启用</GlassButton>
          </div>
        </div>
        <p v-if="!loading && !items.length" class="mgr-empty">还没有模板，点击右上角新增</p>
      </div>
    </div>

    <!-- ── 编辑视图 ── -->
    <div v-else class="mgr-form">
      <div class="form-grid">
        <label class="form-field">
          <span>分类</span>
          <el-select v-model="form.category" filterable allow-create default-first-option placeholder="选择或输入新分类">
            <el-option v-for="cat in categoryOptions" :key="cat.key" :label="cat.label" :value="cat.key" />
          </el-select>
        </label>
        <label class="form-field">
          <span>名称</span>
          <el-input v-model="form.name" maxlength="100" placeholder="如：白底产品图" />
        </label>
        <label class="form-field form-field--sm">
          <span>排序（小在前）</span>
          <el-input-number v-model="form.sort" :min="0" :max="9999" controls-position="right" />
        </label>
        <label class="form-field form-field--sm">
          <span>状态</span>
          <el-switch v-model="form.is_active" inline-prompt active-text="启用" inactive-text="停用" />
        </label>
      </div>

      <label class="form-field">
        <span>模板内容（用 {key} 标记参数槽，如 在{scene}拍摄）</span>
        <el-input v-model="form.content" type="textarea" :rows="4" maxlength="4000" placeholder="完整提示词，用户选择的参数值会替换 {key} 占位" />
      </label>

      <div class="options-editor">
        <div class="options-head">
          <span>参数槽</span>
          <GlassButton variant="outline" size="sm" @click="addOption">
            <template #left-icon><el-icon><Plus /></el-icon></template>
            添加参数槽
          </GlassButton>
        </div>
        <div v-for="(option, index) in form.options" :key="index" class="option-row">
          <el-input v-model="option.key" class="option-key" placeholder="key（小写）" maxlength="32" />
          <el-input v-model="option.label" class="option-label" placeholder="显示名，如 场景" maxlength="32" />
          <el-select
            v-model="option.choices"
            class="option-choices"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入取值后回车，可多个"
          />
          <button type="button" class="option-remove" :aria-label="`删除参数槽 ${index + 1}`" @click="form.options.splice(index, 1)">
            <el-icon><Close /></el-icon>
          </button>
        </div>
        <p v-if="!form.options.length" class="options-hint">无参数槽时，模板内容将原样填入输入框</p>
      </div>

      <p v-if="validationMessage" class="form-warning">{{ validationMessage }}</p>
    </div>

    <template #footer>
      <template v-if="editing">
        <GlassButton variant="ghost" @click="editing = null">返回</GlassButton>
        <GlassButton variant="primary" :disabled="!canSave" :loading="saving" @click="save">保存模板</GlassButton>
      </template>
      <GlassButton v-else variant="ghost" @click="close">关闭</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Close, Plus } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  createPromptTemplate, deletePromptTemplate, listPromptTemplates, updatePromptTemplate,
} from '@/api/designImage'
import { msgError, msgSuccess } from '@/utils/feedback'

const props = defineProps({
  visible: { type: Boolean, default: false },
})
const emit = defineEmits(['update:visible', 'changed'])

const CATEGORY_LABELS = {
  product: '产品图',
  scene: '场景图',
  poster: '海报',
  detail: '细节图',
  restyle: '换款改图',
}
const KEY_PATTERN = /^[a-z][a-z0-9_]*$/

const items = ref([])
const loading = ref(false)
const saving = ref(false)
const showInactive = ref(true)
const editing = ref(null)
const form = ref(emptyForm())

function emptyForm() {
  return { id: null, category: '', name: '', content: '', options: [], is_active: true, sort: 0 }
}

function categoryLabel(key) {
  return CATEGORY_LABELS[key] || key
}

const categoryOptions = computed(() => {
  const seen = new Map()
  for (const item of items.value) {
    if (!seen.has(item.category)) seen.set(item.category, { key: item.category, label: categoryLabel(item.category) })
  }
  return [...seen.values()]
})

const placeholders = computed(() => {
  const matches = form.value.content.matchAll(/\{([a-z][a-z0-9_]*)\}/g)
  return [...new Set([...matches].map(match => match[1]))]
})

const validationMessage = computed(() => {
  const value = form.value
  if (!value.category.trim()) return '请填写分类'
  if (!value.name.trim()) return '请填写名称'
  if (!value.content.trim()) return '请填写模板内容'
  const keys = value.options.map(option => option.key.trim())
  if (keys.some(key => !KEY_PATTERN.test(key))) return '参数槽 key 必须是小写字母开头的标识符（小写字母/数字/下划线）'
  if (new Set(keys).size !== keys.length) return '参数槽 key 不能重复'
  for (const option of value.options) {
    if (!option.label.trim()) return `参数槽「${option.key}」需要显示名`
    if (!option.choices.length) return `参数槽「${option.key}」至少需要一个取值`
  }
  const missing = placeholders.value.filter(key => !keys.includes(key))
  if (missing.length) return `模板内容里的 {${missing.join('}、{')}} 缺少对应参数槽`
  const unused = keys.filter(key => !placeholders.value.includes(key))
  if (unused.length) return `参数槽「${unused.join('、')}」在模板内容中未使用，请删除或补充 {${unused[0]}} 占位`
  return ''
})

const canSave = computed(() => !validationMessage.value && !saving.value)

async function fetchItems() {
  loading.value = true
  try {
    const response = await listPromptTemplates({ includeInactive: showInactive.value })
    items.value = response?.data?.items ?? []
  } catch {
    msgError('模板列表读取失败')
  } finally {
    loading.value = false
  }
}

function startCreate() {
  form.value = emptyForm()
  editing.value = 'create'
}

function startEdit(item) {
  form.value = {
    id: item.id,
    category: item.category,
    name: item.name,
    content: item.content,
    options: (item.options || []).map(option => ({ ...option, choices: [...option.choices] })),
    is_active: item.is_active,
    sort: item.sort,
  }
  editing.value = 'edit'
}

function addOption() {
  form.value.options = [...form.value.options, { key: '', label: '', choices: [] }]
}

function payload() {
  const value = form.value
  return {
    category: value.category.trim(),
    name: value.name.trim(),
    content: value.content.trim(),
    options: value.options.map(option => ({
      key: option.key.trim(),
      label: option.label.trim(),
      choices: option.choices,
    })),
    is_active: value.is_active,
    sort: value.sort,
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  try {
    if (form.value.id) await updatePromptTemplate(form.value.id, payload())
    else await createPromptTemplate(payload())
    msgSuccess('保存')
    editing.value = null
    await fetchItems()
    emit('changed')
  } catch (error) {
    msgError(error?.response?.data?.message || '保存失败，请检查填写内容')
  } finally {
    saving.value = false
  }
}

async function disable(item) {
  try {
    await deletePromptTemplate(item.id)
    msgSuccess('已停用')
    await fetchItems()
    emit('changed')
  } catch {
    msgError('停用失败，请稍后重试')
  }
}

async function enable(item) {
  try {
    await updatePromptTemplate(item.id, {
      category: item.category,
      name: item.name,
      content: item.content,
      options: item.options || [],
      is_active: true,
      sort: item.sort,
    })
    msgSuccess('已启用')
    await fetchItems()
    emit('changed')
  } catch {
    msgError('启用失败，请稍后重试')
  }
}

function onOpen() {
  editing.value = null
  void fetchItems()
}

function close() {
  emit('update:visible', false)
}
</script>

<style scoped>
.mgr-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.mgr-rows { display: flex; max-height: 420px; flex-direction: column; gap: 8px; overflow-y: auto; }
.mgr-row {
  display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
  border: 1px solid var(--border-color); border-radius: var(--radius-lg, 12px); background: var(--card-bg);
}
.mgr-row.is-inactive { opacity: 0.62; }
.mgr-row-main { min-width: 0; flex: 1; }
.mgr-row-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 4px; }
.mgr-row-head strong { color: var(--text-primary); font-size: 13px; }
.mgr-category { padding: 2px 8px; border-radius: 6px; background: var(--color-primary-light); color: var(--color-gold-muted); font-size: 11px; font-weight: 600; }
.mgr-sort { color: var(--text-muted); font-size: 11px; }
.mgr-status { font-size: 11px; font-weight: 600; }
.mgr-status.is-on { color: var(--color-success-text); }
.mgr-status.is-off { color: var(--text-muted); }
.mgr-row-main > p {
  display: -webkit-box; margin: 0; overflow: hidden; color: var(--text-muted); font-size: 12px;
  line-height: 1.6; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
}
.mgr-row-actions { display: flex; flex: 0 0 auto; gap: 4px; }
.mgr-empty { margin: 48px 0; color: var(--text-muted); font-size: 12px; text-align: center; }

.mgr-form { display: flex; flex-direction: column; gap: 14px; }
.form-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) minmax(0, 0.8fr) minmax(0, 0.6fr); gap: 10px; }
.form-field { display: flex; min-width: 0; flex-direction: column; gap: 6px; }
.form-field > span { color: var(--text-muted); font-size: 11px; font-weight: 600; }
.form-field :deep(.el-input-number) { width: 100%; }

.options-editor { padding: 12px; border: 1px dashed var(--border-color); border-radius: var(--radius-lg, 12px); background: var(--toolbar-bg); }
.options-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.options-head > span { color: var(--text-muted); font-size: 11px; font-weight: 600; }
.option-row { display: grid; grid-template-columns: 110px 130px minmax(0, 1fr) 26px; gap: 8px; margin-bottom: 8px; align-items: center; }
.option-remove {
  display: grid; width: 24px; height: 24px; place-items: center; border: 0; border-radius: 50%;
  background: transparent; color: var(--text-muted); cursor: pointer;
  transition: color 160ms cubic-bezier(0.23, 1, 0.32, 1), background-color 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.options-hint { margin: 0; color: var(--text-muted); font-size: 11px; }
.form-warning { margin: 0; color: var(--color-warning-text); font-size: 12px; }

@media (hover: hover) and (pointer: fine) {
  .option-remove:hover { background: var(--color-danger-bg); color: var(--color-danger-text); }
}
@media (max-width: 720px) {
  .form-grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .option-row { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 26px; }
  .option-choices { grid-column: 1 / -2; }
}
@media (prefers-reduced-motion: reduce) {
  .option-remove { transition: none; }
}
</style>
