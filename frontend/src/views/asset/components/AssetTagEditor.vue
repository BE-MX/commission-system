<template>
  <el-dialog
    :model-value="visible"
    :title="isBatch ? `批量加标签（已选 ${assets.length} 项）` : '编辑标签'"
    width="640px"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-if="!isBatch && assets[0]" class="editor-asset-name" :title="assets[0].file_name">
      {{ assets[0].file_name }}
    </div>
    <div v-if="isBatch" class="editor-hint">
      多选维度在原有标签基础上追加；单选维度替换为所选值。未选择的维度保持不变。
    </div>
    <div v-if="editableDimensions.length === 0" class="editor-empty">
      <el-text type="info">暂无标签维度</el-text>
    </div>
    <div v-else class="editor-dim-list">
      <div v-for="dim in editableDimensions" :key="dim.id" class="editor-dim">
        <div class="editor-dim-label">
          {{ dim.label }}
          <el-text v-if="dim.is_single_select" type="info" size="small">（单选）</el-text>
          <el-button
            v-if="dim.is_single_select && selection[dim.id]"
            link
            type="primary"
            size="small"
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
            :disabled="!val.is_active"
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
            :disabled="!val.is_active"
          >
            {{ val.value }}
          </el-radio-button>
        </el-radio-group>
      </div>
    </div>
    <template #footer>
      <GlassButton variant="ghost" @click="emit('update:visible', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" @click="handleSave">保存</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { batchAddTags, updateAssetTags } from '@/api/asset'

const props = defineProps({
  visible: { type: Boolean, default: false },
  // edit 模式为单个素材；batch 模式为多选素材数组
  assets: { type: Array, default: () => [] },
  mode: { type: String, default: 'edit' }, // 'edit' | 'batch'
  dimensions: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'saved'])

const saving = ref(false)
const selection = reactive({})

const isBatch = computed(() => props.mode === 'batch')
// 托管维度（色系等）由系统派生写入，不允许人工编辑
const editableDimensions = computed(() => props.dimensions.filter(d => !d.is_managed))

// 弹窗打开时初始化选择：编辑模式回填素材当前标签，批量模式从空白开始
watch(() => props.visible, (open) => {
  if (!open) return
  const currentByDim = {}
  if (!isBatch.value && props.assets[0]?.tags) {
    for (const tag of props.assets[0].tags) {
      if (!currentByDim[tag.dimension_id]) currentByDim[tag.dimension_id] = []
      currentByDim[tag.dimension_id].push(tag.id)
    }
  }
  for (const dim of editableDimensions.value) {
    const ids = currentByDim[dim.id] || []
    selection[dim.id] = dim.is_single_select ? (ids[0] ?? null) : [...ids]
  }
})

function normalizeSelection(dim) {
  const val = selection[dim.id]
  if (dim.is_single_select) {
    return val ? [val] : []
  }
  return Array.isArray(val) ? [...val] : []
}

async function handleSave() {
  if (!props.assets.length) return
  saving.value = true
  try {
    if (isBatch.value) {
      // 批量追加：只提交有选择的维度，后端做并集/替换
      const tags = editableDimensions.value
        .map(dim => ({ dimension_id: dim.id, tag_value_ids: normalizeSelection(dim) }))
        .filter(item => item.tag_value_ids.length > 0)
      if (!tags.length) {
        ElMessage.warning('请至少选择一个标签')
        return
      }
      await batchAddTags(props.assets.map(a => a.id), tags)
      ElMessage.success('标签已批量添加')
    } else {
      // 单个编辑：提交全部可见非托管维度（空数组=清空该维度），未列出的维度后端保持原样
      const tags = editableDimensions.value.map(dim => ({
        dimension_id: dim.id,
        tag_value_ids: normalizeSelection(dim),
      }))
      await updateAssetTags(props.assets[0].id, { tags })
      ElMessage.success('标签已更新')
    }
    emit('saved')
    emit('update:visible', false)
  } catch (e) {
    // 拦截器已弹出后端错误提示，这里只兜底防 unhandled rejection
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.editor-asset-name {
  margin-bottom: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.editor-hint {
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.editor-empty {
  padding: 24px 0;
  text-align: center;
}
.editor-dim-list {
  max-height: 50vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.editor-dim-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
}
.editor-dim :deep(.el-checkbox-button),
.editor-dim :deep(.el-radio-button) {
  margin: 0 8px 8px 0;
}
</style>
