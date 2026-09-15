<template>
  <el-dialog
    :model-value="modelValue"
    title="确认文件夹标签"
    width="min(760px, 94vw)"
    :close-on-click-modal="false"
    destroy-on-close
    class="tag-confirm-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="客户标签会展示在客户素材门户，标签命名即对外可见。"
      class="confirm-notice"
    />

    <div v-if="matchedRows.length" class="matched-block">
      <div class="block-title">已命中标签库（自动采用）</div>
      <div class="matched-list">
        <div v-for="row in matchedRows" :key="row.tag_name" class="matched-row">
          <span class="folder-name" :title="row.tag_name">{{ row.tag_name }}</span>
          <el-icon><Right /></el-icon>
          <el-tag size="small" effect="plain" type="success">{{ row.dimension_label }}：{{ row.original_value }}</el-tag>
        </div>
      </div>
    </div>

    <div v-if="resolutionRows.length" class="resolution-block">
      <div class="block-title">
        待确认 <el-tag size="small" effect="plain">{{ resolutionRows.length }} 项</el-tag>
      </div>
      <div class="resolution-list">
        <div v-for="row in resolutionRows" :key="row.tagName" class="resolution-row">
          <div class="resolution-source">
            <span class="source-badge">文件夹</span>
            <strong :title="row.tagName">{{ row.tagName }}</strong>
            <span v-if="row.kind === 'suggested'" class="similarity">
              相似标签 · {{ Math.round(row.score * 100) }}%
            </span>
            <span v-else-if="row.kind === 'ambiguous'" class="similarity">同名标签有多个维度</span>
            <span v-else class="similarity">标签库中不存在</span>
          </div>

          <template v-if="row.kind === 'missing'">
            <el-checkbox v-model="resolutions[row.tagName].create" class="create-check">
              自动新建客户标签
            </el-checkbox>
            <el-select
              v-if="resolutions[row.tagName].create"
              v-model="resolutions[row.tagName].dimensionId"
              placeholder="选择目标维度"
              class="resolution-select"
            >
              <el-option
                v-for="dim in creatableDimensions"
                :key="dim.id"
                :label="dim.label"
                :value="dim.id"
              />
            </el-select>
          </template>
          <el-select
            v-else
            v-model="resolutions[row.tagName].selectedId"
            placeholder="选择标签库中的客户标签"
            filterable
            class="resolution-select"
          >
            <el-option
              v-for="option in row.options"
              :key="option.tag_value_id"
              :label="optionLabel(option)"
              :value="option.tag_value_id"
            />
          </el-select>
        </div>
      </div>
    </div>

    <template #footer>
      <GlassButton variant="ghost" :disabled="confirming" @click="emit('update:modelValue', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="confirming" @click="handleConfirm">确认并继续</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Right } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // POST /tags/validate 的 data：{matched, suggested, missing, ambiguous}
  result: { type: Object, default: null },
  dimensions: { type: Array, default: () => [] },
  confirming: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'confirm'])

const resolutions = reactive({})

const matchedRows = computed(() => props.result?.matched || [])
const resolutionRows = computed(() => {
  const result = props.result || {}
  return [
    ...(result.suggested || []).map(item => ({
      kind: 'suggested',
      tagName: item.tag_name,
      options: item.alternatives || [],
      score: item.recommended?.score || 0,
    })),
    ...(result.ambiguous || []).map(item => ({
      kind: 'ambiguous',
      tagName: item.tag_name,
      options: item.dimensions || [],
    })),
    ...(result.missing || []).map(tagName => ({ kind: 'missing', tagName, options: [] })),
  ]
})
// 可新建标签的目标维度：可见且非系统托管
const creatableDimensions = computed(() => (
  (props.dimensions || []).filter(dim => dim.is_visible !== 0 && !dim.is_managed)
))

function defaultDimensionId() {
  const builtin = creatableDimensions.value.find(dim => dim.name === 'customer_general')
  return (builtin || creatableDimensions.value[0])?.id ?? null
}

watch(() => props.modelValue, open => {
  if (!open) return
  Object.keys(resolutions).forEach(key => delete resolutions[key])
  for (const row of resolutionRows.value) {
    if (row.kind === 'missing') {
      resolutions[row.tagName] = { create: true, dimensionId: defaultDimensionId() }
    } else {
      const recommended = (props.result?.suggested || []).find(item => item.tag_name === row.tagName)?.recommended
      resolutions[row.tagName] = { selectedId: recommended?.tag_value_id ?? null }
    }
  }
})

function optionLabel(option) {
  const dimension = option.dimension_label || option.dimension_name || ''
  const value = option.original_value ?? option.value ?? ''
  const score = option.score ? ` · ${Math.round(option.score * 100)}%` : ''
  return `${value} · ${dimension}${score}`
}

function handleConfirm() {
  const selected = {}
  const creates = {}
  for (const row of resolutionRows.value) {
    const resolution = resolutions[row.tagName]
    if (row.kind === 'missing') {
      if (!resolution?.create) continue
      if (row.tagName.length > 128) {
        ElMessage.warning(`「${row.tagName.slice(0, 20)}…」超过 128 个字符，不能创建为标签`)
        return
      }
      if (!resolution.dimensionId) {
        ElMessage.warning(`请选择「${row.tagName}」要新建到哪个维度`)
        return
      }
      creates[row.tagName] = resolution.dimensionId
      continue
    }
    const option = row.options.find(item => item.tag_value_id === resolution?.selectedId)
    if (!option) {
      ElMessage.warning(`请为「${row.tagName}」选择匹配标签`)
      return
    }
    selected[row.tagName] = {
      dimension_id: option.dimension_id,
      dimension_label: option.dimension_label || option.dimension_name || '',
      tag_value_id: option.tag_value_id,
      value: option.original_value ?? option.value ?? row.tagName,
    }
  }
  emit('confirm', { selected, creates })
}
</script>

<style scoped>
.confirm-notice { margin-bottom: 16px; }
.block-title { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-weight: 600; }
.matched-block { margin-bottom: 18px; }
.matched-list { display: grid; gap: 6px; }
.matched-row { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); }
.folder-name { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); font-weight: 600; }
.resolution-list { display: grid; gap: 10px; max-height: 46vh; overflow-y: auto; }
.resolution-row { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(200px, 260px); align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--card-bg); }
.resolution-source { display: flex; min-width: 0; align-items: center; gap: 8px; }
.resolution-source strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-badge { flex: 0 0 auto; padding: 2px 8px; border-radius: 999px; background: var(--color-primary-light); color: var(--color-primary-hover); font-size: 11px; }
.similarity { flex: 0 0 auto; color: var(--text-secondary); font-size: 12px; }
.create-check { white-space: nowrap; }
.resolution-select { width: 100%; }
@media (max-width: 700px) {
  .resolution-row { grid-template-columns: minmax(0, 1fr); }
}
</style>
