<template>
  <el-dialog
    v-model="visible"
    :title="step === 'report' ? '文件夹上传完成' : '文件夹批量上传'"
    width="min(860px, 94vw)"
    class="folder-upload-dialog"
    :close-on-click-modal="false"
    :close-on-press-escape="step !== 'executing'"
    :show-close="step !== 'executing'"
    destroy-on-close
    @closed="reset"
  >
    <div v-if="step === 'input'" class="upload-input">
      <input
        ref="folderInput"
        class="visually-hidden"
        type="file"
        webkitdirectory
        directory
        multiple
        @change="onFolderInput"
      />
      <div
        class="folder-dropzone"
        :class="{ 'is-dragging': isDragging, 'has-files': selectedEntries.length }"
        role="button"
        tabindex="0"
        @click="folderInput?.click()"
        @keydown.enter.prevent="folderInput?.click()"
        @keydown.space.prevent="folderInput?.click()"
        @dragenter.prevent="isDragging = true"
        @dragover.prevent="isDragging = true"
        @dragleave.prevent="isDragging = false"
        @drop.prevent="onDrop"
      >
        <el-icon :size="42"><FolderOpened /></el-icon>
        <template v-if="selectedEntries.length">
          <strong>{{ rootNames.join('、') }}</strong>
          <span>已读取 {{ selectedEntries.length }} 个文件 · {{ formatSize(selectedSize) }}</span>
          <small>点击可重新选择，或拖入其他文件夹替换</small>
        </template>
        <template v-else>
          <strong>选择文件夹，或将文件夹拖到这里</strong>
          <span>自动读取子文件夹中的图片和视频</span>
          <small>单文件最大 500MB</small>
        </template>
      </div>

      <el-checkbox v-model="includeFilenameTags" class="filename-tag-option">
        将文件名识别为标签
      </el-checkbox>
      <p class="option-hint">默认关闭；开启后会去掉扩展名，再与标签库匹配。</p>

      <el-collapse class="server-path-collapse">
        <el-collapse-item title="从服务器暂存目录导入">
          <el-input
            v-model="serverPath"
            placeholder="例如：D:\upload_staging\贴发\产品图"
            clearable
            @focus="sourceMode = 'server'"
            @keyup.enter="startValidation"
          />
          <p class="option-hint">仅用于已放到服务器上的素材；选择文件夹会自动切回电脑直传。</p>
        </el-collapse-item>
      </el-collapse>

      <div class="dialog-footer">
        <GlassButton variant="ghost" @click="close">取消</GlassButton>
        <GlassButton variant="primary" @click="startValidation">匹配标签</GlassButton>
      </div>
    </div>

    <div v-else-if="step === 'validating'" class="folder-loading" aria-live="polite">
      <el-icon :size="46" class="loading-icon"><Loading /></el-icon>
      <p>正在扫描文件夹并匹配标签库...</p>
    </div>

    <div v-else-if="step === 'resolution'">
      <div v-if="fatalMessage" class="fatal-message">
        <el-icon><CircleClose /></el-icon>
        <span>{{ fatalMessage }}</span>
      </div>
      <template v-else>
        <div class="resolution-header">
          <div>
            <strong>确认标签匹配</strong>
            <p>精确命中的标签已自动采用；请处理下面的推荐或新标签。</p>
          </div>
          <el-tag effect="plain">{{ resolutionRows.length }} 项待确认</el-tag>
        </div>

        <div class="resolution-list">
          <div v-for="row in resolutionRows" :key="row.tagName" class="resolution-row">
            <div class="resolution-source">
              <span class="source-badge">{{ sourceLabel(row.tagName) }}</span>
              <strong :title="row.tagName">{{ row.tagName }}</strong>
              <span v-if="row.kind === 'suggested'" class="similarity">
                相似度 {{ Math.round(row.score * 100) }}%
              </span>
              <span v-else-if="row.kind === 'ambiguous'" class="similarity">同名标签有多个维度</span>
              <span v-else class="similarity">未找到相似标签</span>
            </div>

            <el-radio-group v-model="resolutions[row.tagName].mode" class="resolution-mode">
              <el-radio v-if="row.options.length" value="existing">使用标签库</el-radio>
              <el-radio v-if="canAutoCreate" value="create">自动创建</el-radio>
            </el-radio-group>

            <el-select
              v-if="resolutions[row.tagName].mode === 'existing'"
              v-model="resolutions[row.tagName].selectedId"
              placeholder="请选择匹配标签"
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
            <div v-else-if="resolutions[row.tagName].mode === 'create'" class="create-tag-inline">
              <el-select
                v-model="resolutions[row.tagName].dimensionId"
                placeholder="选择标签维度"
                filterable
                class="resolution-select"
              >
                <el-option
                  v-for="dim in creatableDimensions"
                  :key="dim.id"
                  :label="dim.label"
                  :value="dim.id"
                />
              </el-select>
              <span>创建“{{ row.tagName }}”</span>
            </div>
            <div v-else class="permission-hint">
              未找到可用标签，请联系素材管理员创建后再上传
            </div>
          </div>
        </div>
      </template>

      <div class="dialog-footer">
        <GlassButton variant="ghost" @click="step = 'input'">返回选择</GlassButton>
        <GlassButton v-if="!fatalMessage" variant="primary" @click="confirmResolutions">生成上传预览</GlassButton>
      </div>
    </div>

    <div v-else-if="step === 'preview'">
      <div class="preview-summary">
        <span>共 <strong>{{ previewData?.total_files || 0 }}</strong> 个文件</span>
        <span v-if="(previewData?.files || []).length > 20" class="async-hint">，上传后转后台处理</span>
        <span v-if="Object.keys(resolutions).length">，已确认 {{ Object.keys(resolutions).length }} 个标签处理项</span>
      </div>
      <el-table :data="(previewData?.files || []).slice(0, 50)" max-height="390" border class="list-table">
        <el-table-column label="相对路径" prop="file_path" min-width="220" show-overflow-tooltip />
        <el-table-column label="匹配标签" min-width="280">
          <template #default="{ row }">
            <el-tag
              v-for="tag in row.tags"
              :key="`${tag.dimension_id}-${tag.tag_value}`"
              size="small"
              effect="plain"
              class="tag-chip"
            >
              {{ tag.dimension_name }}：{{ tag.tag_value }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="(previewData?.files || []).length > 50" class="preview-more">
        还有 {{ previewData.files.length - 50 }} 个文件未展开
      </p>
      <div class="extra-tags-section">
        <div class="extra-tags-header">
          <span class="extra-tags-title">批量赋标签</span>
          <GlassButton variant="outline" size="sm" @click="openExtraTagPicker">选择标签</GlassButton>
        </div>
        <p class="option-hint">可选；所选标签将应用到本次上传的全部文件。</p>
        <div v-if="extraTagChips.length" class="extra-tag-chips">
          <el-tag
            v-for="chip in extraTagChips"
            :key="`${chip.dimensionId}-${chip.valueId}`"
            size="small"
            effect="plain"
            closable
            class="tag-chip"
            @close="removeExtraTag(chip)"
          >
            {{ chip.dimensionLabel }}：{{ chip.valueLabel }}
          </el-tag>
        </div>
      </div>
      <div class="duplicate-policy">
        <span>同名且标签一致的文件：</span>
        <el-radio-group v-model="updateDuplicates">
          <el-radio :value="true">更新为新版本</el-radio>
          <el-radio :value="false">直接跳过</el-radio>
        </el-radio-group>
      </div>
      <div class="dialog-footer">
        <GlassButton variant="ghost" @click="step = resolutionRows.length ? 'resolution' : 'input'">返回</GlassButton>
        <GlassButton variant="primary" @click="confirmUpload">确认并上传</GlassButton>
      </div>
    </div>

    <div v-else-if="step === 'executing'" class="folder-loading" aria-live="polite">
      <el-icon :size="46" class="loading-icon"><Loading /></el-icon>
      <p>{{ jobId ? '文件已接收，正在后台入库...' : '正在上传并入库，请勿关闭弹窗...' }}</p>
      <el-progress
        v-if="uploadProgress && !jobId"
        :percentage="uploadPercentage"
        :stroke-width="8"
        class="upload-progress"
      />
      <small v-if="uploadProgress && !jobId">
        {{ uploadProgress.fileName }} · {{ uploadProgress.fileIndex }}/{{ uploadProgress.totalFiles }}
      </small>
      <small v-if="jobId">任务 ID：{{ jobId }}</small>
    </div>

    <div v-else-if="step === 'poll_error'" class="poll-error" aria-live="assertive">
      <el-icon :size="42"><WarningFilled /></el-icon>
      <strong>暂时无法获取后台进度</strong>
      <p>{{ pollError }}</p>
      <small>任务 ID：{{ jobId }}</small>
      <div class="dialog-footer">
        <GlassButton variant="ghost" @click="close">先关闭</GlassButton>
        <GlassButton variant="primary" @click="retryPolling">重新连接</GlassButton>
      </div>
    </div>

    <div v-else-if="step === 'report'">
      <div class="report-stats">
        <div class="report-stat"><strong>{{ uploadReport?.total || 0 }}</strong><span>总文件</span></div>
        <div class="report-stat is-success"><strong>{{ uploadReport?.success || 0 }}</strong><span>成功</span></div>
        <div class="report-stat is-warning"><strong>{{ uploadReport?.new_version_count || 0 }}</strong><span>新版本</span></div>
        <div class="report-stat"><strong>{{ uploadReport?.skipped || 0 }}</strong><span>跳过</span></div>
        <div class="report-stat is-danger"><strong>{{ uploadReport?.failed?.length || 0 }}</strong><span>失败</span></div>
      </div>
      <el-alert
        v-if="uploadReport?.created_tags?.length"
        :title="`已自动创建 ${uploadReport.created_tags.length} 个标签`"
        type="success"
        :closable="false"
        show-icon
        class="created-alert"
      />
      <el-table
        v-if="uploadReport?.failed?.length"
        :data="uploadReport.failed"
        border
        class="list-table"
      >
        <el-table-column label="文件" prop="file_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="原因" prop="reason" min-width="280" show-overflow-tooltip />
      </el-table>
      <div class="dialog-footer">
        <GlassButton variant="ghost" @click="close">关闭</GlassButton>
        <GlassButton variant="primary" @click="viewLibrary">查看素材库</GlassButton>
      </div>
    </div>
  </el-dialog>

  <el-dialog
    v-model="extraTagPickerVisible"
    title="批量赋标签"
    width="min(640px, 90vw)"
    append-to-body
    class="extra-tag-picker-dialog"
  >
    <p class="option-hint picker-hint">从标签库选择标签，确认后应用到本次上传的全部文件。</p>
    <div class="extra-tag-picker">
      <div v-for="dim in assignableDimensions" :key="dim.id" class="dimension-item">
        <div class="dimension-label">
          {{ dim.label }}
          <el-text v-if="dim.is_single_select" type="info" size="small">（单选）</el-text>
        </div>
        <el-checkbox-group
          v-if="!dim.is_single_select"
          v-model="extraTagSelection[dim.id]"
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
          v-model="extraTagSelection[dim.id]"
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
      <GlassButton variant="ghost" @click="clearExtraTags">清空</GlassButton>
      <GlassButton variant="primary" @click="extraTagPickerVisible = false">确定</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, toRef } from 'vue'
import { useRouter } from 'vue-router'
import { CircleClose, FolderOpened, Loading, WarningFilled } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAuthStore } from '@/stores/auth'
import { useFolderUpload } from '../composables/useFolderUpload'

const props = defineProps({
  dimensions: { type: Array, default: () => [] },
})
const emit = defineEmits(['uploaded'])
const router = useRouter()
const authStore = useAuthStore()
const folderInput = ref(null)
const dimensionsRef = toRef(props, 'dimensions')
const canAutoCreate = computed(() => authStore.hasPermission('asset:admin'))
const {
  visible, step, selectedEntries, serverPath, sourceMode, includeFilenameTags,
  isDragging, validationResult, previewData, uploadReport, resolutions,
  updateDuplicates, jobId, fatalMessage, selectedSize, rootNames,
  uploadProgress, pollError, resolutionRows, creatableDimensions,
  extraTagSelection,
  open, close, reset, onFolderInput,
  onDrop, startValidation, confirmResolutions, confirmUpload,
  retryPolling,
} = useFolderUpload({
  dimensions: dimensionsRef,
  canAutoCreate,
  onUploaded: () => emit('uploaded'),
})
const uploadPercentage = computed(() => {
  if (!uploadProgress.value?.totalBytes) return 100
  return Math.min(100, Math.round(
    uploadProgress.value.uploadedBytes / uploadProgress.value.totalBytes * 100,
  ))
})

// ── 批量赋标签 ──────────────────────────────────────────
const extraTagPickerVisible = ref(false)
const assignableDimensions = computed(() => (
  (props.dimensions || []).filter(dim => dim.is_visible !== 0 && (dim.values || []).length)
))
const extraTagChips = computed(() => {
  const chips = []
  for (const dim of assignableDimensions.value) {
    const selected = extraTagSelection[dim.id]
    const ids = (Array.isArray(selected) ? selected : [selected]).filter(Boolean)
    for (const id of ids) {
      const val = dim.values.find(v => v.id === id)
      chips.push({
        dimensionId: dim.id,
        valueId: id,
        dimensionLabel: dim.label,
        valueLabel: val?.value || id,
      })
    }
  }
  return chips
})

function openExtraTagPicker() {
  for (const dim of assignableDimensions.value) {
    if (extraTagSelection[dim.id] === undefined) {
      extraTagSelection[dim.id] = dim.is_single_select ? null : []
    }
  }
  extraTagPickerVisible.value = true
}

function removeExtraTag(chip) {
  const selected = extraTagSelection[chip.dimensionId]
  if (Array.isArray(selected)) {
    extraTagSelection[chip.dimensionId] = selected.filter(id => id !== chip.valueId)
  } else {
    extraTagSelection[chip.dimensionId] = null
  }
}

function clearExtraTags() {
  for (const dim of assignableDimensions.value) {
    extraTagSelection[dim.id] = dim.is_single_select ? null : []
  }
}

function formatSize(bytes) {
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes || 0
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`
}

function sourceLabel(tagName) {
  const sources = validationResult.value?.candidate_sources?.[tagName] || []
  if (sources.length > 1) return '目录 / 文件名'
  return sources[0] === 'filename' ? '文件名' : '文件夹'
}

function optionLabel(option) {
  const dimension = option.dimension_label || option.dimension_name
  const score = option.score ? ` · ${Math.round(option.score * 100)}%` : ''
  return `${option.original_value} · ${dimension}${score}`
}

function viewLibrary() {
  close()
  router.push('/asset/library')
}

defineExpose({ open })
</script>

<style scoped src="./folder-upload-dialog.css"></style>
