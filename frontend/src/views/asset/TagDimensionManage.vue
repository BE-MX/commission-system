<template>
  <div class="tag-dimension-page">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <h2 class="page-title">
        <el-icon><CollectionTag /></el-icon>
        标签维度管理
      </h2>
      <el-button type="primary" @click="showCreateDim = true">
        <el-icon><Plus /></el-icon>
        新建维度
      </el-button>
    </div>

    <!-- 维度列表 -->
    <div v-if="loading" class="loading-wrap">
      <el-skeleton :rows="5" animated />
    </div>
    <div v-else-if="dimensions.length === 0" class="empty-wrap">
      <el-empty description="暂无标签维度" />
    </div>
    <div v-else class="dimension-list">
      <div
        v-for="dim in sortedDimensions"
        :key="dim.id"
        class="dimension-card"
        :class="{ 'is-system': dim.is_system }"
      >
        <div class="dim-header">
          <div class="dim-info">
            <span class="dim-name">{{ dim.label }}</span>
            <span class="dim-meta">{{ dim.name }}</span>
            <el-tag v-if="dim.is_system" size="small" type="info">系统内置</el-tag>
            <el-tag v-if="dim.is_single_select" size="small" type="warning">单选</el-tag>
            <el-tag v-else size="small" type="success">多选</el-tag>
            <el-tag v-if="dim.is_required" size="small" type="danger">必填</el-tag>
            <el-tag v-if="!dim.is_visible" size="small" type="info" effect="plain">未启用</el-tag>
            <el-tag v-if="dim.is_managed" size="small" type="warning" effect="plain">系统托管</el-tag>
          </div>
          <div class="dim-actions">
            <el-button link type="primary" size="small" @click="toggleDimVisible(dim)">
              {{ dim.is_visible ? '停用' : '启用' }}
            </el-button>
            <el-button link type="primary" size="small" @click="openEditDim(dim)">
              <el-icon><Edit /></el-icon>编辑
            </el-button>
            <el-button v-if="!dim.is_managed" link type="primary" size="small" @click="openCreateValue(dim)">
              <el-icon><Plus /></el-icon>添加值
            </el-button>
            <el-button
              v-if="!dim.is_system"
              link
              type="danger"
              size="small"
              @click="handleDeleteDim(dim)"
            >
              <el-icon><Delete /></el-icon>删除
            </el-button>
          </div>
        </div>

        <!-- 标签值搜索 -->
        <div class="value-search-wrap">
          <el-input
            v-model="valueSearchQuery[dim.id]"
            placeholder="搜索标签值..."
            size="small"
            clearable
            :prefix-icon="Search"
            class="value-search-input"
          />
          <span class="value-count-hint">
            共 {{ dim.values.length }} 个，显示 {{ filteredValues(dim).length }} 个
          </span>
        </div>

        <!-- 标签值列表 -->
        <div class="value-list">
          <div
            v-for="val in filteredValues(dim)"
            :key="val.id"
            class="value-item"
          >
            <div class="value-tag-wrap">
            <img
              v-if="val.image_path"
              :src="getTagImageUrl(val.image_path)"
              class="value-tag-thumb"
            />
            <el-tag
              size="small"
              :color="val.color_hex || undefined"
              :style="val.color_hex ? 'color: #fff; border: none;' : ''"
            >
              {{ val.value }}
            </el-tag>
          </div>
            <span v-if="val.name_en" class="value-name-en">{{ val.name_en }}</span>
            <span v-if="!val.is_active" class="value-inactive">(已禁用)</span>
            <div v-if="!dim.is_managed" class="value-actions">
              <el-button link type="primary" size="small" @click="openEditValue(dim, val)">
                编辑
              </el-button>
              <el-button link type="danger" size="small" @click="handleDeleteValue(val)">
                删除
              </el-button>
            </div>
          </div>
          <el-text v-if="dim.values.length === 0" type="info" size="small">
            暂无标签值
          </el-text>
          <el-text v-else-if="filteredValues(dim).length === 0" type="info" size="small">
            无匹配标签值
          </el-text>
        </div>
      </div>
    </div>

    <!-- 新建/编辑维度弹窗 -->
    <el-dialog
      v-model="showDimDialog"
      :title="isEditDim ? '编辑维度' : '新建维度'"
      width="480px"
    >
      <el-form :model="dimForm" label-width="100px">
        <el-form-item label="标识名" required>
          <el-input v-model="dimForm.name" placeholder="英文标识，如 color" :disabled="isEditDim" />
        </el-form-item>
        <el-form-item label="显示名" required>
          <el-input v-model="dimForm.label" placeholder="中文显示名，如 颜色" />
        </el-form-item>
        <el-form-item label="选择类型">
          <el-radio-group v-model="dimForm.is_single_select">
            <el-radio-button :label="1">单选</el-radio-button>
            <el-radio-button :label="0">多选</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="是否必填">
          <el-switch v-model="dimForm.is_required" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="dimForm.sort_order" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDimDialog = false">取消</el-button>
        <el-button type="primary" :loading="dimSubmitting" @click="submitDim">
          确认
        </el-button>
      </template>
    </el-dialog>

    <!-- 新建/编辑标签值弹窗 -->
    <el-dialog
      v-model="showValueDialog"
      :title="isEditValue ? '编辑标签值' : '新建标签值'"
      width="420px"
    >
      <el-form :model="valueForm" label-width="80px">
        <el-form-item label="所属维度">
          <el-input :model-value="currentDim?.label" disabled />
        </el-form-item>
        <el-form-item label="标签值" required>
          <el-input v-model="valueForm.value" placeholder="如 #1B、20\"" />
        </el-form-item>
        <el-form-item label="英文名">
          <el-input v-model="valueForm.name_en" placeholder="agent 检索用，如 Genius Weft" />
        </el-form-item>
        <el-form-item label="别名">
          <el-input v-model="valueForm.aliasesText" placeholder="逗号分隔，如 天才,Halo" />
        </el-form-item>
        <el-form-item v-if="parentOptions.length" label="挂靠父级">
          <el-select v-model="valueForm.parent_value_id" clearable placeholder="不挂靠" style="width: 100%">
            <el-option v-for="opt in parentOptions" :key="opt.id" :label="opt.value" :value="opt.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="valueForm.color_hex" show-alpha />
        </el-form-item>
        <el-form-item label="图片">
          <div class="tag-image-uploader">
            <el-upload
              class="tag-image-upload"
              :http-request="handleTagImageUpload"
              :show-file-list="false"
              accept="image/*"
            >
              <div v-if="valueForm.image_path" class="tag-image-preview">
                <img :src="getTagImageUrl(valueForm.image_path)" />
                <el-icon class="tag-image-delete" @click.stop="valueForm.image_path = null"><CircleClose /></el-icon>
              </div>
              <el-icon v-else class="tag-image-plus"><Plus /></el-icon>
            </el-upload>
          </div>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="valueForm.sort_order" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showValueDialog = false">取消</el-button>
        <el-button type="primary" :loading="valueSubmitting" @click="submitValue">
          确认
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CollectionTag, Plus, Edit, Delete, CircleClose, Search,
} from '@element-plus/icons-vue'
import {
  getTagDimensions, createDimension, updateDimension, deleteDimension,
  createTagValue, updateTagValue, deleteTagValue, uploadTagImage,
} from '@/api/asset'

const loading = ref(false)
const dimensions = ref([])
const valueSearchQuery = ref({})

function filteredValues(dim) {
  const q = (valueSearchQuery.value[dim.id] || '').trim().toLowerCase()
  if (!q) return dim.values || []
  return (dim.values || []).filter(v =>
    (v.value || '').toLowerCase().includes(q)
  )
}

const sortedDimensions = computed(() => {
  return [...dimensions.value].sort((a, b) => a.sort_order - b.sort_order)
})

// 挂靠父级候选：内容子类 → 内容大类的值；其他维度 → 本维度未挂靠的值（产品族）
const parentOptions = computed(() => {
  const dim = currentDim.value
  if (!dim) return []
  if (dim.name === 'content_type') {
    const cat = dimensions.value.find(d => d.name === 'content_category')
    return cat?.values || []
  }
  return (dim.values || []).filter(v => !v.parent_value_id && v.id !== currentValue.value?.id)
})

async function loadData() {
  loading.value = true
  try {
    // 管理页需要看到未启用（并存期隐藏）的维度
    const res = await getTagDimensions(true)
    dimensions.value = res.data || []
  } catch (e) {
    ElMessage.error('加载标签维度失败')
  } finally {
    loading.value = false
  }
}

async function toggleDimVisible(dim) {
  const next = dim.is_visible ? 0 : 1
  try {
    if (next === 0) {
      await ElMessageBox.confirm(
        `停用后「${dim.label}」将不在筛选、上传和文件夹匹配中出现（已打的标签保留）。确定停用？`,
        '确认停用',
        { type: 'warning' },
      )
    }
    await updateDimension(dim.id, { is_visible: next })
    ElMessage.success(next ? '已启用' : '已停用')
    await loadData()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.message || '操作失败')
    }
  }
}

// ── 维度 ────────────────────────────────────────────────
const showDimDialog = ref(false)
const showCreateDim = ref(false)
const isEditDim = ref(false)
const dimSubmitting = ref(false)
const dimForm = ref({
  name: '',
  label: '',
  is_single_select: 0,
  is_required: 0,
  sort_order: 0,
})

function openEditDim(dim) {
  isEditDim.value = true
  dimForm.value = {
    name: dim.name,
    label: dim.label,
    is_single_select: dim.is_single_select,
    is_required: dim.is_required,
    sort_order: dim.sort_order,
  }
  showDimDialog.value = true
}

watch(showCreateDim, (v) => {
  if (v) {
    isEditDim.value = false
    dimForm.value = {
      name: '',
      label: '',
      is_single_select: 0,
      is_required: 0,
      sort_order: dimensions.value.length,
    }
    showDimDialog.value = true
    showCreateDim.value = false
  }
})

async function submitDim() {
  const data = { ...dimForm.value }
  if (!data.name.trim() || !data.label.trim()) {
    ElMessage.warning('请填写完整信息')
    return
  }
  dimSubmitting.value = true
  try {
    if (isEditDim.value) {
      const dim = dimensions.value.find(d => d.name === data.name)
      await updateDimension(dim.id, data)
      ElMessage.success('更新成功')
    } else {
      await createDimension(data)
      ElMessage.success('创建成功')
    }
    showDimDialog.value = false
    await loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '操作失败')
  } finally {
    dimSubmitting.value = false
  }
}

async function handleDeleteDim(dim) {
  try {
    await ElMessageBox.confirm(
      `确定删除维度「${dim.label}」？其下所有标签值也将被删除。`,
      '确认删除',
      { type: 'warning' },
    )
    await deleteDimension(dim.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.message || '删除失败')
    }
  }
}

// ── 标签值 ──────────────────────────────────────────────
const showValueDialog = ref(false)
const isEditValue = ref(false)
const valueSubmitting = ref(false)
const currentDim = ref(null)
const currentValue = ref(null)
const valueForm = ref({
  value: '',
  name_en: '',
  aliasesText: '',
  parent_value_id: null,
  color_hex: null,
  image_path: null,
  sort_order: 0,
})

function openCreateValue(dim) {
  currentDim.value = dim
  currentValue.value = null
  isEditValue.value = false
  valueForm.value = {
    value: '',
    name_en: '',
    aliasesText: '',
    parent_value_id: null,
    color_hex: null,
    image_path: null,
    sort_order: dim.values?.length || 0,
  }
  showValueDialog.value = true
}

function openEditValue(dim, val) {
  currentDim.value = dim
  currentValue.value = val
  isEditValue.value = true
  valueForm.value = {
    value: val.value,
    name_en: val.name_en || '',
    aliasesText: (val.aliases || []).join(','),
    parent_value_id: val.parent_value_id || null,
    color_hex: val.color_hex,
    image_path: val.image_path,
    sort_order: val.sort_order,
  }
  showValueDialog.value = true
}

async function submitValue() {
  if (!valueForm.value.value.trim()) {
    ElMessage.warning('请填写标签值')
    return
  }
  valueSubmitting.value = true
  try {
    const payload = {
      value: valueForm.value.value,
      name_en: valueForm.value.name_en?.trim() || null,
      aliases: valueForm.value.aliasesText
        ? valueForm.value.aliasesText.split(/[,，]/).map(s => s.trim()).filter(Boolean)
        : [],
      parent_value_id: valueForm.value.parent_value_id || null,
      color_hex: valueForm.value.color_hex,
      image_path: valueForm.value.image_path,
      sort_order: valueForm.value.sort_order,
    }
    if (isEditValue.value && currentValue.value) {
      await updateTagValue(currentValue.value.id, payload)
      ElMessage.success('更新成功')
    } else {
      await createTagValue(currentDim.value.id, payload)
      ElMessage.success('创建成功')
    }
    showValueDialog.value = false
    await loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '操作失败')
  } finally {
    valueSubmitting.value = false
  }
}

async function handleTagImageUpload(options) {
  try {
    const res = await uploadTagImage(options.file)
    valueForm.value.image_path = res.data?.image_path || null
  } catch (e) {
    ElMessage.error('图片上传失败')
  }
}

function getTagImageUrl(path) {
  if (!path) return ''
  return `/uploads/${path}`
}

async function handleDeleteValue(val) {
  try {
    await ElMessageBox.confirm(
      `确定删除标签值「${val.value}」？`,
      '确认删除',
      { type: 'warning' },
    )
    await deleteTagValue(val.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.message || '删除失败')
    }
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.tag-dimension-page {
  padding: 20px 28px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  font-size: 17px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.loading-wrap,
.empty-wrap {
  padding: 40px;
  text-align: center;
}

.dimension-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dimension-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.dimension-card.is-system {
  border-left: 4px solid #d4941c;
}

.dim-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f0f0;
}

.dim-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dim-name {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a2e;
}

.dim-meta {
  font-size: 12px;
  color: #999;
}

.dim-actions {
  display: flex;
  gap: 4px;
}

.value-search-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.value-search-input {
  width: 220px;
}

.value-count-hint {
  font-size: 12px;
  color: #999;
}

.value-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.value-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #fafbfe;
  border-radius: 8px;
}

.value-tag-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}

.value-tag-thumb {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid #e4e7ed;
}

.tag-image-uploader {
  display: flex;
}

.tag-image-upload :deep(.el-upload) {
  width: 80px;
  height: 80px;
  border: 1px dashed #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}

.tag-image-upload :deep(.el-upload:hover) {
  border-color: #d4941c;
}

.tag-image-preview {
  width: 100%;
  height: 100%;
  position: relative;
}

.tag-image-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.tag-image-delete {
  position: absolute;
  top: 2px;
  right: 2px;
  color: #fff;
  background: rgba(0,0,0,0.5);
  border-radius: 50%;
  padding: 2px;
  cursor: pointer;
}

.tag-image-plus {
  font-size: 24px;
  color: #8c939d;
}

.value-inactive {
  font-size: 12px;
  color: #999;
}

.value-name-en {
  font-size: 12px;
  color: var(--text-muted);
}

.value-actions {
  display: flex;
  gap: 4px;
  margin-left: 4px;
}
</style>
