<template>
  <div class="asset-upload-page">
    <div class="page-header-row">
      <el-page-header content="素材上传" @back="$router.back()" />
      <el-button type="primary" plain @click="openFolderUpload">
        <el-icon><FolderOpened /></el-icon>文件夹批量上传
      </el-button>
    </div>

    <div class="upload-layout">
      <!-- 左侧：文件上传区 -->
      <div class="left-panel">
        <div class="upload-section">
          <el-upload
            ref="uploadRef"
            class="asset-uploader"
            drag
            :auto-upload="false"
            :show-file-list="false"
            accept="image/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
            :before-upload="handleBeforeUpload"
            :on-change="handleFileChange"
          >
            <template v-if="previewUrl">
              <div class="preview-wrapper">
                <img v-if="fileType === 'image'" :src="previewUrl" class="preview-image" />
                <video v-else-if="fileType === 'video'" :src="previewUrl" class="preview-video" controls />
                <div v-else class="preview-doc">
                  <el-icon :size="48"><Document /></el-icon>
                  <p>{{ selectedFile?.name }}</p>
                </div>
                <div class="preview-actions">
                  <el-button size="small" type="danger" plain @click.stop="clearFile">
                    移除文件
                  </el-button>
                </div>
              </div>
            </template>
            <template v-else>
              <el-icon class="el-icon--upload" :size="48"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                拖拽文件到此处，或<em>点击上传</em>
              </div>
              <div class="el-upload__tip">
                支持图片 / 视频 / 文档，单文件最大 500MB
              </div>
            </template>
          </el-upload>
        </div>

        <!-- 文件信息 -->
        <div v-if="selectedFile" class="file-info-section">
          <div class="info-row">
            <span class="info-label">文件名</span>
            <span class="info-value" :title="selectedFile.name">{{ selectedFile.name }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">大小</span>
            <span class="info-value">{{ formatSize(selectedFile.size) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">类型</span>
            <span class="info-value">{{ fileTypeLabel(fileType) }}</span>
          </div>
        </div>
      </div>

      <!-- 右侧：表单区 -->
      <div class="right-panel">
        <div class="panel-title">素材信息</div>

        <!-- AI 建议标签 -->
        <div v-if="aiSuggestions.length > 0" class="form-section ai-section">
          <div class="section-title">
            <el-icon><MagicStick /></el-icon>
            AI 建议标签
            <el-tag v-if="aiConfidence > 0" size="small" type="info">
              置信度 {{ Math.round(aiConfidence * 100) }}%
            </el-tag>
            <el-button link type="primary" size="small" @click="acceptAllAiTags">
              一键接受
            </el-button>
          </div>
          <div class="ai-suggestion-list">
            <div v-for="s in aiSuggestions" :key="s.dimension_id" class="ai-suggestion-item">
              <div class="ai-dim-label">{{ s.dimension_label }}</div>
              <div class="ai-tag-list">
                <el-tag
                  v-for="v in s.values"
                  :key="v.tag_value_id"
                  size="small"
                  effect="plain"
                  class="ai-tag"
                  :class="{ accepted: isAiTagAccepted(s.dimension_id, v.tag_value_id) }"
                  @click="toggleAiTag(s.dimension_id, v.tag_value_id)"
                >
                  {{ v.value }}
                  <el-icon v-if="isAiTagAccepted(s.dimension_id, v.tag_value_id)" class="check-icon"><Check /></el-icon>
                </el-tag>
              </div>
            </div>
          </div>
        </div>

        <!-- AI 分析中 -->
        <div v-else-if="aiAnalyzing" class="form-section">
          <div class="section-title">
            <el-icon><MagicStick /></el-icon>
            AI 分析中...
          </div>
          <el-skeleton :rows="2" animated />
        </div>

        <!-- 标签选择 -->
        <div class="form-section">
          <div class="section-title">
            <el-icon><CollectionTag /></el-icon>
            标签
            <el-text type="info" size="small">（便于检索和分类）</el-text>
          </div>
          <div v-if="dimensionsLoading" class="dim-loading">
            <el-skeleton :rows="3" animated />
          </div>
          <div v-else-if="dimensions.length === 0" class="dim-empty">
            <el-text type="info">暂无标签维度</el-text>
          </div>
          <div v-else class="dimension-list">
            <div
              v-for="dim in dimensions"
              :key="dim.id"
              class="dimension-item"
            >
              <div class="dimension-label">
                {{ dim.label }}
                <el-text v-if="dim.is_required" type="danger" size="small">*</el-text>
                <el-text v-if="dim.is_single_select" type="info" size="small">（单选）</el-text>
              </div>
              <el-checkbox-group
                v-if="!dim.is_single_select"
                v-model="selectedTags[dim.id]"
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
                v-model="selectedTags[dim.id]"
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
        </div>

        <!-- 权限设置 -->
        <div class="form-section">
          <div class="section-title">
            <el-icon><Lock /></el-icon>
            权限设置
          </div>
          <div class="permission-form">
            <el-form-item label="可见范围">
              <el-radio-group v-model="permission.permission_group">
                <el-radio-button label="all">全员可见</el-radio-button>
                <el-radio-button label="design_dept">设计部</el-radio-button>
                <el-radio-button label="sales">销售部</el-radio-button>
                <el-radio-button label="specific">指定人员</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="允许预览">
              <el-switch v-model="permission.allow_preview" :active-value="1" :inactive-value="0" />
            </el-form-item>
            <el-form-item label="允许下载">
              <el-switch v-model="permission.allow_download" :active-value="1" :inactive-value="0" />
            </el-form-item>
          </div>
        </div>

        <!-- 备注 -->
        <div class="form-section">
          <div class="section-title">
            <el-icon><Document /></el-icon>
            备注
          </div>
          <el-input
            v-model="remark"
            type="textarea"
            :rows="3"
            placeholder="补充说明，如拍摄时间、使用场景等"
            maxlength="500"
            show-word-limit
          />
        </div>

        <!-- 提交 -->
        <div class="form-actions">
          <el-button @click="$router.back()">取消</el-button>
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!canSubmit"
            @click="handleSubmit"
          >
            确认上传
          </el-button>
        </div>
      </div>
    </div>

    <!-- 文件夹批量上传 -->
    <el-dialog
      v-model="folderUploadVisible"
      :title="folderUploadStep === 'report' ? '文件夹上传完成' : '文件夹批量上传'"
      width="640px"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="closeFolderUpload"
    >
      <!-- 步骤1：输入路径 -->
      <div v-if="folderUploadStep === 'input'">
        <el-form label-position="top">
          <el-form-item label="文件夹路径">
            <el-input
              v-model="folderPath"
              placeholder="例如：D:\\upload_staging\\贴发\\产品图"
              clearable
              @keyup.enter="startFolderValidate"
            />
          </el-form-item>
          <el-form-item>
            <el-alert
              title="系统会自动遍历文件夹内的所有图片文件，并根据文件夹层级提取标签"
              type="info"
              :closable="false"
              show-icon
            />
          </el-form-item>
        </el-form>
        <div class="dialog-footer">
          <el-button @click="folderUploadVisible = false">取消</el-button>
          <el-button type="primary" @click="startFolderValidate">开始校验</el-button>
        </div>
      </div>

      <!-- 步骤2：校验中 -->
      <div v-else-if="folderUploadStep === 'validating'" class="folder-loading">
        <el-icon size="48" class="loading-icon"><Loading /></el-icon>
        <p>正在扫描文件夹结构并匹配标签库...</p>
      </div>

      <!-- 步骤3：校验失败 -->
      <div v-else-if="folderUploadStep === 'fail'">
        <div v-if="folderValidationResult?.message" class="fail-message">
          <el-icon size="24" color="#f56c6c"><CircleClose /></el-icon>
          <span>{{ folderValidationResult.message }}</span>
        </div>
        <div v-else>
          <div class="fail-header">
            <el-icon size="24" color="#e6a23c"><Warning /></el-icon>
            <span>以下文件夹名无法自动匹配到标签库，请处理后再上传</span>
          </div>

          <div v-if="folderValidationResult?.missing?.length" class="fail-section">
            <div class="fail-section-title">缺失标签（未找到匹配）</div>
            <el-table :data="folderValidationResult.missing.map(t => ({ tag_name: t }))" size="small">
              <el-table-column label="文件夹名" prop="tag_name" sortable />
              <el-table-column label="操作" width="120">
                <template #default="{ row }">
                  <el-button type="primary" link size="small" @click="goToTagManage">去创建</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div v-if="folderValidationResult?.ambiguous?.length" class="fail-section">
            <div class="fail-section-title">歧义标签（多维度匹配）</div>
            <div
              v-for="item in folderValidationResult.ambiguous"
              :key="item.tag_name"
              class="ambiguous-item"
            >
              <span class="ambiguous-tag">{{ item.tag_name }}</span>
              <span class="ambiguous-label">属于：</span>
              <el-select
                v-if="!folderTagMapping[item.tag_name]"
                placeholder="请选择维度"
                size="small"
                style="width: 160px"
                @change="(dimId) => onAmbiguousChange(item.tag_name, dimId, item.dimensions)"
              >
                <el-option
                  v-for="dim in item.dimensions"
                  :key="dim.dimension_id"
                  :label="dim.dimension_label || dim.dimension_name"
                  :value="dim.dimension_id"
                />
              </el-select>
              <el-tag v-else type="success" size="small">已选择 {{ folderTagMapping[item.tag_name].dimension_name }}</el-tag>
            </div>
          </div>
        </div>
        <div class="dialog-footer">
          <el-button @click="folderUploadStep = 'input'">返回修改</el-button>
          <el-button @click="folderUploadVisible = false">关闭</el-button>
        </div>
      </div>

      <!-- 步骤4：预览确认 -->
      <div v-else-if="folderUploadStep === 'preview'">
        <div class="preview-summary">
          <span>共 <strong>{{ folderPreviewData?.total_files || 0 }}</strong> 个文件</span>
          <span v-if="folderPreviewData?.files?.length > 100" class="async-hint">
            （超过 100 个，将后台异步处理）
          </span>
          <span v-if="folderPreviewData?.tag_summary?.length">
            ，使用标签：
            <el-tag
              v-for="(tag, i) in folderPreviewData.tag_summary"
              :key="i"
              size="small"
              effect="plain"
              class="mr-4"
            >
              {{ tag.dimension_name }}:{{ tag.tag_value }}
            </el-tag>
          </span>
        </div>
        <el-table
          :data="(folderPreviewData?.files || []).slice(0, 50)"
          size="small"
          max-height="400"
        >
          <el-table-column label="文件名" prop="file_name" show-overflow-tooltip sortable />
          <el-table-column label="标签" min-width="200">
            <template #default="{ row }">
              <el-tag
                v-for="(tag, i) in row.tags"
                :key="i"
                size="small"
                effect="plain"
                class="mr-4"
              >
                {{ tag.dimension_name }}:{{ tag.tag_value }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="(folderPreviewData?.files || []).length > 50" class="preview-more">
          还有 {{ folderPreviewData.files.length - 50 }} 个文件...
        </p>
        <div class="duplicate-policy">
          <span class="duplicate-policy-label">同名文件（标签与文件名均相同）：</span>
          <el-radio-group v-model="folderUpdateDuplicates" size="small">
            <el-radio :label="true">更新为新版本</el-radio>
            <el-radio :label="false">直接跳过</el-radio>
          </el-radio-group>
        </div>
        <div class="dialog-footer">
          <el-button @click="folderUploadStep = 'input'">返回</el-button>
          <el-button type="primary" @click="confirmFolderUpload">确认上传</el-button>
        </div>
      </div>

      <!-- 步骤5：执行中 / 后台执行中 -->
      <div v-else-if="folderUploadStep === 'executing'" class="folder-loading">
        <el-icon size="48" class="loading-icon"><Loading /></el-icon>
        <p>{{ folderJobId ? '已提交后台处理，请稍候...' : '正在逐文件入库，请稍候...' }}</p>
        <p v-if="folderJobId" class="job-hint">任务 ID: {{ folderJobId }}</p>
      </div>

      <!-- 步骤6：执行报告 -->
      <div v-else-if="folderUploadStep === 'report'">
        <div class="report-stats">
          <div class="report-stat">
            <div class="report-stat-value">{{ folderUploadReport?.total || 0 }}</div>
            <div class="report-stat-label">总文件数</div>
          </div>
          <div class="report-stat success">
            <div class="report-stat-value">{{ folderUploadReport?.success || 0 }}</div>
            <div class="report-stat-label">成功入库</div>
          </div>
          <div class="report-stat warning">
            <div class="report-stat-value">{{ folderUploadReport?.new_version_count || 0 }}</div>
            <div class="report-stat-label">作为新版本</div>
          </div>
          <div class="report-stat info">
            <div class="report-stat-value">{{ folderUploadReport?.skipped || 0 }}</div>
            <div class="report-stat-label">已跳过</div>
          </div>
          <div class="report-stat danger">
            <div class="report-stat-value">{{ folderUploadReport?.failed?.length || 0 }}</div>
            <div class="report-stat-label">失败</div>
          </div>
        </div>
        <el-table
          v-if="folderUploadReport?.failed?.length"
          :data="folderUploadReport.failed"
          size="small"
          class="report-fail-table"
        >
          <el-table-column label="文件" prop="file_name" sortable />
          <el-table-column label="原因" prop="reason" sortable />
        </el-table>
        <div class="dialog-footer">
          <el-button @click="folderUploadVisible = false">关闭</el-button>
          <el-button type="primary" @click="handleViewUploaded">查看素材库</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  UploadFilled, Document, CollectionTag, Lock, MagicStick, Check,
  FolderOpened, Loading, CircleClose, Warning,
} from '@element-plus/icons-vue'
import {
  getTagDimensions, uploadAsset, analyzePreview,
  validateFolderUpload, previewFolderUpload, executeFolderUpload,
  getFolderUploadStatus,
} from '@/api/asset'

const router = useRouter()
const uploadRef = ref(null)

// ── 文件相关 ────────────────────────────────────────────
const selectedFile = ref(null)
const previewUrl = ref('')
const fileType = ref('')

function detectFileType(filename) {
  const ext = filename.split('.').pop().toLowerCase()
  const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg']
  const videoExts = ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm']
  if (imageExts.includes(ext)) return 'image'
  if (videoExts.includes(ext)) return 'video'
  return 'document'
}

function handleBeforeUpload(file) {
  const maxSize = 500 * 1024 * 1024
  if (file.size > maxSize) {
    ElMessage.error('文件大小超过 500MB 限制')
    return false
  }
  return true
}

function handleFileChange(file) {
  if (!file || !file.raw) return
  selectedFile.value = file.raw
  fileType.value = detectFileType(file.raw.name)

  if (fileType.value === 'image' || fileType.value === 'video') {
    previewUrl.value = URL.createObjectURL(file.raw)
  } else {
    previewUrl.value = 'doc'
  }

  // 自动触发 AI 分析
  triggerAiAnalysis(file.raw.name)
}

function clearFile() {
  if (previewUrl.value && previewUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(previewUrl.value)
  }
  selectedFile.value = null
  previewUrl.value = ''
  fileType.value = ''
  uploadRef.value?.clearFiles()
  aiSuggestions.value = []
  acceptedAiTags.value = {}
  aiConfidence.value = 0
}

// ── AI 分析 ─────────────────────────────────────────────
const aiAnalyzing = ref(false)
const aiSuggestions = ref([])
const aiConfidence = ref(0)
const acceptedAiTags = ref({}) // { dimensionId: [tagValueId, ...] }

async function triggerAiAnalysis(fileName) {
  aiAnalyzing.value = true
  aiSuggestions.value = []
  acceptedAiTags.value = {}
  aiConfidence.value = 0
  try {
    const res = await analyzePreview(fileName)
    const data = res.data || {}
    aiConfidence.value = data.confidence || 0
    aiSuggestions.value = data.suggestions || []

    // 高置信度建议自动接受
    if (aiConfidence.value >= 0.7) {
      acceptAllAiTags()
    }
  } catch (e) {
    console.warn('AI 分析失败:', e)
  } finally {
    aiAnalyzing.value = false
  }
}

function isAiTagAccepted(dimId, tagValueId) {
  return (acceptedAiTags.value[dimId] || []).includes(tagValueId)
}

function toggleAiTag(dimId, tagValueId) {
  const current = acceptedAiTags.value[dimId] || []
  const idx = current.indexOf(tagValueId)
  if (idx >= 0) {
    current.splice(idx, 1)
  } else {
    current.push(tagValueId)
  }
  acceptedAiTags.value[dimId] = [...current]

  // 同步到 selectedTags
  const dim = dimensions.value.find(d => d.id === dimId)
  if (dim) {
    if (dim.is_single_select) {
      selectedTags[dimId] = current.length > 0 ? current[0] : null
    } else {
      selectedTags[dimId] = [...current]
    }
  }
}

function acceptAllAiTags() {
  aiSuggestions.value.forEach(s => {
    const ids = s.values.map(v => v.tag_value_id)
    acceptedAiTags.value[s.dimension_id] = ids

    const dim = dimensions.value.find(d => d.id === s.dimension_id)
    if (dim) {
      if (dim.is_single_select) {
        selectedTags[s.dimension_id] = ids[0] || null
      } else {
        selectedTags[s.dimension_id] = [...ids]
      }
    }
  })
}

// ── 标签维度 ────────────────────────────────────────────
const dimensions = ref([])
const dimensionsLoading = ref(false)
const selectedTags = reactive({})

async function loadDimensions() {
  dimensionsLoading.value = true
  try {
    const res = await getTagDimensions()
    dimensions.value = res.data || []
    dimensions.value.forEach(d => {
      if (!(d.name in selectedTags)) {
        selectedTags[d.id] = d.is_single_select ? null : []
      }
    })
  } catch (e) {
    console.warn('加载标签维度失败:', e)
  } finally {
    dimensionsLoading.value = false
  }
}

// ── 权限与备注 ──────────────────────────────────────────
const permission = reactive({
  permission_group: 'all',
  allow_preview: 1,
  allow_download: 1,
})
const remark = ref('')

// ── 提交 ────────────────────────────────────────────────
const submitting = ref(false)

const canSubmit = computed(() => {
  if (!selectedFile.value) return false
  for (const dim of dimensions.value) {
    if (dim.is_required) {
      const val = selectedTags[dim.id]
      if (!val || (Array.isArray(val) && val.length === 0)) {
        return false
      }
    }
  }
  return true
})

async function handleSubmit() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择文件')
    return
  }

  const tags = []
  for (const dim of dimensions.value) {
    const val = selectedTags[dim.id]
    if (!val) continue
    const tagValueIds = Array.isArray(val) ? val : [val]
    if (tagValueIds.length > 0) {
      tags.push({ dimension_id: dim.id, tag_value_ids: tagValueIds })
    }
  }

  const formData = new FormData()
  formData.append('file', selectedFile.value)
  formData.append('file_type', fileType.value)
  formData.append('tags_json', JSON.stringify(tags))
  formData.append('permission_group', permission.permission_group)
  formData.append('allow_preview', String(permission.allow_preview))
  formData.append('allow_download', String(permission.allow_download))
  if (remark.value) {
    formData.append('remark', remark.value)
  }

  submitting.value = true
  try {
    await uploadAsset(formData)
    ElMessage.success('上传成功')
    router.push('/asset/library')
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '上传失败')
  } finally {
    submitting.value = false
  }
}

// ── 工具函数 ────────────────────────────────────────────
function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return `${bytes.toFixed(1)} ${units[i]}`
}

function fileTypeLabel(type) {
  return { image: '图片', video: '视频', document: '文档' }[type] || type
}

onMounted(() => {
  loadDimensions()
})

// ── 文件夹批量上传 ──────────────────────────────────────
const folderUploadVisible = ref(false)
const folderUploadStep = ref('input')
const folderPath = ref('')
const folderValidationResult = ref(null)
const folderPreviewData = ref(null)
const folderUploadReport = ref(null)
const folderTagMapping = ref({})
const folderExtraPermission = ref({ permission_group: 'all', allow_preview: 1, allow_download: 1 })
const folderJobId = ref(null)
const folderUpdateDuplicates = ref(true)
let pollTimer = null

function openFolderUpload() {
  folderUploadVisible.value = true
  folderUploadStep.value = 'input'
  folderPath.value = ''
  folderValidationResult.value = null
  folderPreviewData.value = null
  folderUploadReport.value = null
  folderTagMapping.value = {}
  folderExtraPermission.value = { permission_group: 'all', allow_preview: 1, allow_download: 1 }
  folderJobId.value = null
  folderUpdateDuplicates.value = true
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function startFolderValidate() {
  if (!folderPath.value.trim()) {
    ElMessage.warning('请输入文件夹路径')
    return
  }
  folderUploadStep.value = 'validating'
  try {
    const res = await validateFolderUpload(folderPath.value.trim())
    const data = res.data || {}
    folderValidationResult.value = data

    if (data.message === '所选文件夹中未找到图片文件') {
      folderUploadStep.value = 'fail'
      return
    }

    if (data.is_valid) {
      const mapping = {}
      for (const m of data.matched || []) {
        mapping[m.tag_name] = {
          dimension_id: m.dimension_id,
          tag_value_id: m.tag_value_id,
          dimension_name: m.dimension_name,
          original_value: m.original_value,
        }
      }
      folderTagMapping.value = mapping

      const previewRes = await previewFolderUpload(folderPath.value.trim(), mapping)
      folderPreviewData.value = previewRes.data || {}
      folderUploadStep.value = 'preview'
    } else {
      folderUploadStep.value = 'fail'
    }
  } catch (e) {
    ElMessage.error('校验失败: ' + (e.response?.data?.message || e.message))
    folderUploadStep.value = 'input'
  }
}

function onAmbiguousChange(tagName, dimId, dimensions) {
  const dim = dimensions.find(d => d.dimension_id === dimId)
  if (dim) {
    resolveAmbiguousTag(tagName, dim.dimension_id, dim.tag_value_id, dim.dimension_name, dim.original_value)
  }
}

async function resolveAmbiguousTag(tagName, dimensionId, tagValueId, dimensionName, originalValue) {
  folderTagMapping.value[tagName] = {
    dimension_id: dimensionId,
    tag_value_id: tagValueId,
    dimension_name: dimensionName,
    original_value: originalValue,
  }
  const result = folderValidationResult.value
  const stillMissing = (result.missing || []).filter(m => !folderTagMapping.value[m])
  const stillAmbiguous = (result.ambiguous || []).filter(a => !folderTagMapping.value[a.tag_name])

  if (stillMissing.length === 0 && stillAmbiguous.length === 0) {
    const mapping = { ...folderTagMapping.value }
    for (const m of result.matched || []) {
      if (!mapping[m.tag_name]) {
        mapping[m.tag_name] = {
          dimension_id: m.dimension_id,
          tag_value_id: m.tag_value_id,
          dimension_name: m.dimension_name,
          original_value: m.original_value,
        }
      }
    }
    folderTagMapping.value = mapping
    folderUploadStep.value = 'validating'
    try {
      const previewRes = await previewFolderUpload(folderPath.value.trim(), mapping)
      folderPreviewData.value = previewRes.data || {}
      folderUploadStep.value = 'preview'
    } catch (e) {
      ElMessage.error('预览生成失败')
      folderUploadStep.value = 'fail'
    }
  }
}

async function confirmFolderUpload() {
  folderUploadStep.value = 'executing'
  try {
    const extraTags = []
    const res = await executeFolderUpload(
      folderPath.value.trim(),
      folderTagMapping.value,
      folderExtraPermission.value,
      extraTags,
      folderUpdateDuplicates.value,
    )
    const data = res.data || {}

    if (data.async) {
      // 后台异步执行，开始轮询
      folderJobId.value = data.job_id
      startPolling(data.job_id)
    } else {
      // 同步完成
      folderUploadReport.value = data.report || {}
      folderUploadStep.value = 'report'
    }
  } catch (e) {
    ElMessage.error('上传失败: ' + (e.response?.data?.message || e.message))
    folderUploadStep.value = 'preview'
  }
}

function startPolling(jobId) {
  pollTimer = setInterval(async () => {
    try {
      const res = await getFolderUploadStatus(jobId)
      const job = res.data || {}

      if (job.status === 'completed') {
        clearInterval(pollTimer)
        pollTimer = null
        folderUploadReport.value = job.report || {}
        folderUploadStep.value = 'report'
      } else if (job.status === 'failed') {
        clearInterval(pollTimer)
        pollTimer = null
        ElMessage.error('后台处理失败: ' + (job.error || '未知错误'))
        folderUploadStep.value = 'input'
      }
      // pending / running 继续轮询
    } catch (e) {
      // 轮询失败不中断，继续尝试
      console.warn('轮询任务状态失败:', e)
    }
  }, 2000)
}

function closeFolderUpload() {
  folderUploadVisible.value = false
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (folderUploadStep.value === 'report') {
    folderUploadStep.value = 'input'
  }
}

function goToTagManage() {
  folderUploadVisible.value = false
  setTimeout(() => {
    window.open('/system/tag-dimension', '_blank')
  }, 300)
}

function handleViewUploaded() {
  folderUploadVisible.value = false
  router.push('/asset/library')
}
</script>

<style scoped>
.asset-upload-page {
  padding: 20px 28px;
}

.upload-layout {
  display: flex;
  gap: 24px;
  margin-top: 20px;
  align-items: flex-start;
}

.left-panel {
  width: 420px;
  flex-shrink: 0;
}

.right-panel {
  flex: 1;
  background: #fff;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

/* 上传区 */
.upload-section {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.asset-uploader :deep(.el-upload-dragger) {
  width: 100%;
  height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.preview-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-image {
  max-width: 100%;
  max-height: 240px;
  object-fit: contain;
  border-radius: 8px;
}

.preview-video {
  max-width: 100%;
  max-height: 240px;
  border-radius: 8px;
}

.preview-doc {
  text-align: center;
  color: #999;
}

.preview-actions {
  position: absolute;
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
}

/* 文件信息 */
.file-info-section {
  background: #fff;
  border-radius: 12px;
  padding: 16px 20px;
  margin-top: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  color: #999;
  font-size: 13px;
}

.info-value {
  color: #1a1a2e;
  font-size: 13px;
  font-weight: 500;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 右侧面板 */
.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f0f0;
}

.form-section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1a1a2e;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* AI 建议标签 */
.ai-section {
  background: rgba(212, 148, 28, 0.04);
  border: 1px solid rgba(212, 148, 28, 0.15);
  border-radius: 10px;
  padding: 16px;
}

.ai-suggestion-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ai-suggestion-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.ai-dim-label {
  font-size: 12px;
  font-weight: 500;
  color: #666;
  min-width: 70px;
  padding-top: 4px;
}

.ai-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex: 1;
}

.ai-tag {
  cursor: pointer;
  transition: all 0.15s;
  border-color: #d4941c;
  color: #d4941c;
}

.ai-tag:hover {
  background: rgba(212, 148, 28, 0.08);
}

.ai-tag.accepted {
  background: #d4941c;
  color: #fff;
  border-color: #d4941c;
}

.check-icon {
  margin-left: 4px;
  font-size: 10px;
}

/* 维度标签 */
.dimension-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dimension-item {
  padding: 12px;
  background: #fafbfe;
  border-radius: 8px;
}

.dimension-label {
  font-size: 13px;
  font-weight: 500;
  color: #4a5568;
  margin-bottom: 8px;
}

.dimension-item :deep(.el-checkbox-group),
.dimension-item :deep(.el-radio-group) {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.dim-loading {
  padding: 12px;
}

.dim-empty {
  padding: 20px;
  text-align: center;
}

/* 权限表单 */
.permission-form {
  padding: 12px;
  background: #fafbfe;
  border-radius: 8px;
}

.permission-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.permission-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

/* 提交区 */
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid #f0f0f0;
}

/* 页面头部 */
.page-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* ── 文件夹上传 dialog ────────────────────────────────── */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #e4e7ed;
}

.folder-loading {
  text-align: center;
  padding: 40px 0;
}

.folder-loading .loading-icon {
  color: #d4941c;
  animation: rotate 1.5s linear infinite;
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.fail-message {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px;
  background: #fef0f0;
  border-radius: 8px;
  color: #f56c6c;
  font-size: 14px;
}

.fail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 0;
  font-size: 14px;
  color: #e6a23c;
  font-weight: 500;
}

.fail-section {
  margin-top: 16px;
}

.fail-section-title {
  font-size: 13px;
  font-weight: 500;
  color: #666;
  margin-bottom: 8px;
}

.ambiguous-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.ambiguous-tag {
  font-weight: 500;
  color: #1e1e2d;
  min-width: 80px;
}

.ambiguous-label {
  font-size: 12px;
  color: #999;
}

.preview-summary {
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 13px;
}

.preview-summary .async-hint {
  color: #e6a23c;
  margin-left: 8px;
}

.preview-more {
  text-align: center;
  color: #999;
  font-size: 12px;
  padding: 8px 0;
}

.job-hint {
  font-size: 12px;
  color: #999;
  margin-top: 8px;
}

.report-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}

.report-stat {
  flex: 1;
  text-align: center;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 8px;
}

.report-stat.success { background: #f0f9eb; }
.report-stat.warning { background: #fdf6ec; }
.report-stat.info { background: #f4f4f5; }
.report-stat.danger { background: #fef0f0; }

.report-stat-value {
  font-size: 24px;
  font-weight: 600;
  color: #1e1e2d;
}

.report-stat.success .report-stat-value { color: #67c23a; }
.report-stat.warning .report-stat-value { color: #e6a23c; }
.report-stat.info .report-stat-value { color: #909399; }
.report-stat.danger .report-stat-value { color: #f56c6c; }
.duplicate-policy {
  margin: 12px 0 4px;
  padding: 10px 12px;
  background: #faf8f3;
  border-radius: 6px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.duplicate-policy-label { color: #606266; white-space: nowrap; }

.report-stat-label {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.report-fail-table {
  margin-bottom: 16px;
}
</style>