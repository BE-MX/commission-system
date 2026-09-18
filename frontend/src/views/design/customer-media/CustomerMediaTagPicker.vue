<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="min(640px, 92vw)"
    destroy-on-close
    class="customer-tag-picker"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p v-if="hint" class="picker-hint">{{ hint }}</p>
    <div v-if="!editableDimensions.length" class="picker-empty">
      <el-text type="info">暂无客户标签维度，请先在「标签维度管理」创建客户标签维度</el-text>
    </div>
    <div v-else class="picker-dim-list">
      <div v-for="dim in editableDimensions" :key="dim.id" class="picker-dim">
        <div class="picker-dim-label">
          <span>{{ dim.label }}</span>
          <el-text v-if="dim.is_single_select" type="info" size="small">（单选）</el-text>
          <el-button
            v-if="dim.is_single_select && selection[dim.id] != null"
            link
            type="primary"
            @click="selection[dim.id] = null"
          >清除</el-button>
        </div>
        <el-checkbox-group
          v-if="!dim.is_single_select"
          v-model="selection[dim.id]"
          size="small"
        >
          <el-checkbox-button
            v-for="val in dim.values"
            :key="val.id"
            :label="val.id"
            :disabled="val.is_active === 0"
          >
            {{ val.value }}
          </el-checkbox-button>
        </el-checkbox-group>
        <el-radio-group
          v-else
          v-model="selection[dim.id]"
          size="small"
        >
          <el-radio-button
            v-for="val in dim.values"
            :key="val.id"
            :label="val.id"
            :disabled="val.is_active === 0"
          >
            {{ val.value }}
          </el-radio-button>
        </el-radio-group>
        <div class="picker-create">
          <template v-if="creatingDimId === dim.id">
            <el-input
              v-model="creatingValue"
              size="small"
              maxlength="128"
              :placeholder="`新建「${dim.label}」标签`"
              class="picker-create-input"
              @keyup.enter="submitCreate(dim)"
            />
            <el-button type="primary" :loading="creating" @click="submitCreate(dim)">新建</el-button>
            <el-button link @click="cancelCreate">取消</el-button>
          </template>
          <el-button v-else link type="primary" @click="startCreate(dim)">+ 新建标签</el-button>
        </div>
      </div>
    </div>
    <template #footer>
      <GlassButton variant="ghost" @click="emit('update:modelValue', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" @click="handleSave">保存</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import GlassButton from '@/components/GlassButton.vue'
import { createCustomerTagValue } from '@/api/customerMedia'
import { flattenSelection, groupTagsByDimension, selectionFromTags } from './customerMediaTags'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 客户标签维度（tag_scope='customer'），行内新建会直接追加到本地副本
  dimensions: { type: Array, default: () => [] },
  // 当前标签 [{dimension_id, tag_value_id, ...}]，打开时回填
  tags: { type: Array, default: () => [] },
  title: { type: String, default: '编辑标签' },
  hint: { type: String, default: '' },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'save', 'created'])

const localDims = ref([])
const selection = ref({})
const creatingDimId = ref(null)
const creatingValue = ref('')
const creating = ref(false)

// 托管维度由系统派生，不允许人工编辑
const editableDimensions = computed(() => localDims.value.filter(dim => !dim.is_managed))

watch(() => props.modelValue, open => {
  if (!open) return
  localDims.value = props.dimensions.map(dim => ({ ...dim, values: [...(dim.values || [])] }))
  selection.value = selectionFromTags(props.tags, editableDimensions.value)
  creatingDimId.value = null
  creatingValue.value = ''
})

function startCreate(dim) {
  creatingDimId.value = dim.id
  creatingValue.value = ''
}

function cancelCreate() {
  creatingDimId.value = null
  creatingValue.value = ''
}

async function submitCreate(dim) {
  const value = creatingValue.value.trim()
  if (!value || creating.value) return
  creating.value = true
  try {
    const res = await createCustomerTagValue(dim.id, value)
    const created = res.data
    const target = localDims.value.find(item => item.id === dim.id)
    if (target && !target.values.some(v => v.id === created.id)) {
      target.values.push(created)
    }
    // 新建后即刻选中（单选维度直接替换）
    if (dim.is_single_select) selection.value[dim.id] = created.id
    else selection.value[dim.id] = [...(selection.value[dim.id] || []), created.id]
    emit('created', { dimension_id: dim.id, value: created })
    ElMessage.success(`标签「${created.value ?? value}」已就绪`)
    cancelCreate()
  } catch {
    // 拦截器已弹出后端错误提示
  } finally {
    creating.value = false
  }
}

function handleSave() {
  const flat = flattenSelection(selection.value, editableDimensions.value)
  emit('save', { tags: groupTagsByDimension(flat), flat })
}
</script>

<style scoped>
.picker-hint { margin: 0 0 12px; color: var(--text-secondary); font-size: 12px; }
.picker-empty { padding: 24px 0; text-align: center; }
.picker-dim-list { max-height: 52vh; overflow-y: auto; display: grid; gap: 16px; }
.picker-dim-label { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 13px; font-weight: 600; }
.picker-dim :deep(.el-checkbox-button), .picker-dim :deep(.el-radio-button) { margin: 0 8px 8px 0; }
.picker-create { display: flex; align-items: center; gap: 8px; }
.picker-create-input { width: 200px; }
</style>
