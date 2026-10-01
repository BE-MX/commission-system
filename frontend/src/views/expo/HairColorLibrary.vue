<template>
  <div class="color-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="color-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div ref="panelRef" class="table-card color-panel">
      <FilterBar :pending="keyword.trim() !== appliedKeyword" @search="applySearch" @reset="resetFilters">
        <el-input v-model="keyword" placeholder="搜索色号 / 名称" clearable prefix-icon="Search" class="filter-w-lg" />
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton variant="primary" left-icon="Plus" @click="openCreate">新建发色</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchColors"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus :error="listResource.errorMessage.value" :loading="loading" :has-data="colors.length > 0" @retry="fetchColors" />
      <el-table :data="filteredColors" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" style="width: 100%">
        <template #empty>
          <el-empty v-if="!loading && !listResource.error.value" :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column v-if="visibleKeys.includes('swatch')" label="色板图" min-width="70">
          <template #default="{ row }">
            <el-image v-if="row.swatch_url" :src="row.thumb_url || row.swatch_url" :preview-src-list="[row.swatch_url]" preview-teleported fit="cover" class="swatch-thumb" />
            <span v-else class="swatch-empty">无</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('code')" prop="code" label="色号" min-width="90" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="名称" min-width="120" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('hex')" label="色块" min-width="80">
          <template #default="{ row }">
            <span v-if="row.hex" class="hex-dot" :style="{ background: row.hex }" />
            <span v-else class="swatch-empty">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('description')" prop="color_description" label="颜色描述" min-width="240" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('priority')" prop="priority" label="优先级" min-width="80" sortable />
        <el-table-column v-if="visibleKeys.includes('is-active')" label="启用" min-width="80">
          <template #default="{ row }">
            <el-switch :model-value="!!row.is_active" @change="(v) => toggleActive(row, v)" />
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="140" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'expo:admin'" variant="link" left-icon="Edit" @click="openEdit(row)">编辑</GlassButton>
            <GlassButton v-permission="'expo:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <DetailDrawer v-model="drawerVisible" :title="isEdit ? '编辑发色' : '新建发色'" :width="520" destroy-on-close>
      <el-form label-position="top" ref="formRef" :model="form" :rules="rules">
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
    </DetailDrawer>
  </div>
</template>

<script setup>import { msgSuccessText, confirmDanger, msgSuccess } from '@/utils/feedback'
import { ref, computed, onMounted } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'


import { getHairColors, createHairColor, updateHairColor, deleteHairColor, uploadHairColorSwatch, getHairColorUsage } from '@/api/expo'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'

// columnDefs 只供 TableTools 列显隐面板，模板列保持静态（推广期不配置化渲染）
const columnDefs = [
  { key: 'swatch', label: '色板图' },
  { key: 'code', label: '色号' },
  { key: 'name', label: '名称' },
  { key: 'hex', label: '色块' },
  { key: 'description', label: '颜色描述' },
  { key: 'priority', label: '优先级' },
  { key: 'is-active', label: '启用' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('hair-color-library', columnDefs)

const listResource = useAsyncResource(async (_, { signal }) => (await getHairColors({ only_active: 0 }, { signal, suppressToast: true })).data || [])
const colors = computed(() => listResource.data.value || [])
const loading = listResource.loading
const keyword = ref('')
const appliedKeyword = ref('')
function applySearch() { appliedKeyword.value = keyword.value.trim(); return fetchColors() }
const filteredColors = computed(() => {
  const kw = appliedKeyword.value.toLowerCase()
  if (!kw) return colors.value
  return colors.value.filter((c) => (c.code || '').toLowerCase().includes(kw) || (c.name || '').toLowerCase().includes(kw))
})
const hasActiveFilters = computed(() => Boolean(appliedKeyword.value))
function resetFilters() {
  keyword.value = ''
  return applySearch()
}

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

const fetchColors = () => listResource.load()

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
  msgSuccessText(res.data.hex ? `色板上传成功，主色 ${res.data.hex}` : '色板上传成功')
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const body = { ...toUpsert(form.value), is_active: form.value.is_active ? 1 : 0 }
    if (isEdit.value) {
      await updateHairColor(editId.value, body)
      msgSuccessText('更新成功')
    } else {
      await createHairColor(body)
      msgSuccessText('创建成功')
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
    msgSuccessText(value ? '已启用' : '已停用')
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
/* 极光层（.lg-aurora，与工作台同源）定位上下文 */
.color-page { position: relative; }

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.color-aurora { inset: -24px -28px; }

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   会覆盖就地渲染的 el-drawer/el-dialog 的 .el-overlay position: fixed */
.color-page .color-panel { position: relative; z-index: 1; }

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.color-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.color-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：sticky 单元格 + background: inherit，行透明时会透底重影，
   改成磨砂不透明的暖白，表头/hover 态同步（同 invoice-manage.css） */
.color-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.color-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.color-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

/* 筛选区/操作行：结构类是全局 .table-card > .toolbar/.action-bar（app.css），此处只做玻璃皮肤覆写（同 invoice-manage.css） */
.toolbar { background: rgba(255, 255, 255, 0.4); }
.action-bar { background: rgba(255, 255, 255, 0.28); }

/* 全屏态：面板自身滚动 */
.color-panel:fullscreen { overflow: auto; }

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
.upload-slot:hover { border-color: var(--color-primary); color: var(--color-primary-text); }
.upload-preview { width: 88px; height: 88px; border-radius: 8px; display: block; }
.form-hint { color: var(--text-muted); font-size: 12px; line-height: 1.6; }
</style>
