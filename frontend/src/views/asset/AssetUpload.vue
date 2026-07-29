<template>
  <div class="asset-upload-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="asset-upload-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header-row">
      <el-page-header content="素材上传" @back="$router.back()" />
      <GlassButton variant="primary" :left-icon="FolderOpened" @click="folderDialogRef?.open()">文件夹批量上传</GlassButton>
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
                  <GlassButton variant="danger" size="sm" @click.stop="clearFile">移除文件</GlassButton>
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
          <GlassButton variant="secondary" @click="$router.back()">取消</GlassButton>
          <GlassButton
            variant="primary"
            :loading="submitting"
            :disabled="!canSubmit"
            @click="handleSubmit"
          >确认上传</GlassButton>
        </div>
      </div>
    </div>

    <FolderUploadDialog ref="folderDialogRef" :dimensions="dimensions" @uploaded="loadDimensions" />

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  UploadFilled, Document, CollectionTag, Lock, MagicStick, Check,
  FolderOpened,
} from '@element-plus/icons-vue'
import {
  getTagDimensions, uploadAsset, analyzePreview,
} from '@/api/asset'
import FolderUploadDialog from './components/FolderUploadDialog.vue'

const router = useRouter()
const uploadRef = ref(null)
const folderDialogRef = ref(null)

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

</script>

<style scoped src="./asset-upload.css"></style>
