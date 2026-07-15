<template>
  <div class="color-page">
    <el-row :gutter="16" class="toolbar">
      <el-col :span="8">
        <el-input v-model="keyword" placeholder="搜索色号 / 名称" clearable prefix-icon="Search" />
      </el-col>
      <el-col :span="16">
        <GlassButton variant="primary" left-icon="Plus" @click="openCreate">新建发色</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card">
      <el-table :data="filteredColors" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column label="色板图" min-width="70">
          <template #default="{ row }">
            <el-image v-if="row.swatch_url" :src="row.swatch_url" :preview-src-list="[row.swatch_url]" preview-teleported fit="cover" class="swatch-thumb" />
            <span v-else class="swatch-empty">无</span>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="色号" min-width="90" show-overflow-tooltip />
        <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
        <el-table-column label="色块" min-width="80">
          <template #default="{ row }">
            <span v-if="row.hex" class="hex-dot" :style="{ background: row.hex }" />
            <span v-else class="swatch-empty">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="color_description" label="颜色描述" min-width="240" show-overflow-tooltip />
        <el-table-column prop="priority" label="优先级" min-width="80" sortable />
        <el-table-column label="启用" min-width="80">
          <template #default="{ row }">
            <el-switch :model-value="!!row.is_active" @change="(v) => toggleActive(row, v)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="140" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'expo:admin'" variant="link" left-icon="Edit" @click="openEdit(row)">编辑</GlassButton>
            <GlassButton v-permission="'expo:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawerVisible" :title="isEdit ? '编辑发色' : '新建发色'" :size="520" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="色号" prop="code"><el-input v-model="form.code" placeholder="如 1B / 613" /></el-form-item>
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" placeholder="如 自然黑" /></el-form-item>
        <el-form-item label="色板图">
          <el-upload :show-file-list="false" :http-request="uploadSwatch" accept="image/*">
            <el-image v-if="swatchPreview" :src="swatchPreview" fit="cover" class="upload-preview" />
            <div v-else class="upload-slot">+ 上传色板</div>
          </el-upload>
          <div class="form-hint">上传后自动提取主色作为色块；合成时色板图随自拍一并送入模型</div>
        </el-form-item>
        <el-form-item label="色块">
          <el-color-picker v-model="form.hex_code" />
          <span class="form-hint" style="margin-left: 8px">仅用于选色界面的色点展示</span>
        </el-form-item>
        <el-form-item label="颜色描述" prop="color_description">
          <el-input v-model="form.color_description" type="textarea" :rows="3" placeholder="描述这个发色的观感，如：深栗棕带暖调，光下泛柔和红棕光泽（用于合成提示词）" />
        </el-form-item>
        <el-form-item label="优先级"><el-input-number v-model="form.priority" :min="0" :max="999" style="width: 100%" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="drawerVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submit">保存</GlassButton>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getHairColors, createHairColor, updateHairColor, deleteHairColor, uploadHairColorSwatch, getHairColorUsage } from '@/api/expo'
import { confirmDanger, msgSuccess } from '@/utils/feedback'

const colors = ref([])
const loading = ref(false)
const keyword = ref('')
const filteredColors = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return colors.value
  return colors.value.filter((c) => (c.code || '').toLowerCase().includes(kw) || (c.name || '').toLowerCase().includes(kw))
})

const drawerVisible = ref(false)
const isEdit = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref()
const swatchPreview = ref('')

function emptyForm() {
  return { code: '', name: '', hex_code: '', swatch_path: '', color_description: '', priority: 0, is_active: true }
}
const form = ref(emptyForm())
const rules = {
  code: [{ required: true, message: '请输入色号', trigger: 'blur' }],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
}

async function fetchColors() {
  loading.value = true
  try {
    const res = await getHairColors({ only_active: 0 })
    colors.value = res.data || []
  } finally {
    loading.value = false
  }
}

function toUpsert(src) {
  return {
    code: src.code, name: src.name,
    hex_code: src.hex_code ?? src.hex ?? '',
    swatch_path: src.swatch_path || '',
    color_description: src.color_description || '',
    priority: src.priority || 0,
    is_active: src.is_active ? 1 : 0,
  }
}

function openCreate() {
  isEdit.value = false
  editId.value = null
  form.value = { ...emptyForm() }
  swatchPreview.value = ''
  drawerVisible.value = true
}

function openEdit(row) {
  isEdit.value = true
  editId.value = row.id
  form.value = { ...toUpsert(row), is_active: !!row.is_active }
  swatchPreview.value = row.swatch_url || ''
  drawerVisible.value = true
}

async function uploadSwatch({ file }) {
  const res = await uploadHairColorSwatch(file)
  form.value.swatch_path = res.data.path
  swatchPreview.value = res.data.url
  if (res.data.hex && !form.value.hex_code) form.value.hex_code = res.data.hex
  ElMessage.success(res.data.hex ? `色板上传成功，主色 ${res.data.hex}` : '色板上传成功')
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const body = { ...toUpsert(form.value), is_active: form.value.is_active ? 1 : 0 }
    if (isEdit.value) {
      await updateHairColor(editId.value, body)
      ElMessage.success('更新成功')
    } else {
      await createHairColor(body)
      ElMessage.success('创建成功')
    }
    drawerVisible.value = false
    fetchColors()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function toggleActive(row, value) {
  try {
    await updateHairColor(row.id, { ...toUpsert(row), is_active: value ? 1 : 0 })
    row.is_active = value ? 1 : 0
    ElMessage.success(value ? '已启用' : '已停用')
  } catch { /* 拦截器已提示 */ }
}

async function handleDelete(row) {
  // 先查影响面：删发色会一并抹掉各发型对该色的三角度备图（合成会回退原色）
  let extra = ''
  try {
    const res = await getHairColorUsage(row.id)
    const n = (res.data ?? res)?.combo_count || 0
    if (n) extra = `⚠️ 已有 ${n} 个发型为该色备了三角度试戴图，删除会一并清除，这些发型将退回原色。`
  } catch { /* 查影响面失败不阻断删除，保守用通用文案 */ }
  try {
    await confirmDanger('删除', `发色 ${row.code}`, `将物理删除该发色及其色板图。历史效果图存的是发色快照，不受影响。${extra}`)
  } catch { return }
  try {
    await deleteHairColor(row.id)
    msgSuccess('删除')
    fetchColors()
  } catch { /* 拦截器已提示 */ }
}

onMounted(fetchColors)
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.swatch-thumb { width: 40px; height: 40px; border-radius: 6px; display: block; }
.swatch-empty { color: var(--text-muted); font-size: 12px; }
.hex-dot {
  display: inline-block; width: 22px; height: 22px; border-radius: 50%;
  border: 1px solid var(--border-color); vertical-align: middle;
}
.upload-slot {
  width: 88px; height: 88px; border: 1px dashed var(--border-color); border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-muted); font-size: 12px; cursor: pointer; background: var(--toolbar-bg);
}
.upload-slot:hover { border-color: var(--color-primary); color: var(--color-primary); }
.upload-preview { width: 88px; height: 88px; border-radius: 8px; display: block; }
.form-hint { color: var(--text-muted); font-size: 12px; line-height: 1.6; }
</style>
