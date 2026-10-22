<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Edit, Refresh } from '@element-plus/icons-vue'
import { portalAdminApi } from '@/api/portal'
import { isFeedbackCancelled, msgSuccessText, promptAction } from '@/utils/feedback'
import { statusDictionary } from '@/utils/status'
import { colorTypeLabels, colorTypeSources, swatchBody } from './familyConfiguration.mjs'
const ENABLED_STATE = statusDictionary([['enabled', '启用', 'success'], ['disabled', '停用', 'info']])
const IMAGE_STATE = statusDictionary([[true, '已绑定', 'success'], [false, '未绑定', 'warning']])
const DEFAULT_FILTERS = { keyword: '', missing_image: false }
const swatches = ref([]), unregistered = ref([]), loading = ref(false), error = ref(''), filters = ref({ ...DEFAULT_FILTERS }), applied = ref({ ...DEFAULT_FILTERS })
const pending = computed(() => filters.value.keyword !== applied.value.keyword || filters.value.missing_image !== applied.value.missing_image)
const editing = ref(null), form = ref(null), saving = ref(false)
const assets = ref([]), assetKeyword = ref(''), assetsLoading = ref(false), preview = ref(''), previewing = ref(false)
let controller, assetController, previewController
const message = e => e?.response?.data?.message || e?.message || '色块操作失败，请刷新后重试。'
const imageCount = computed(() => swatches.value.filter(row => row.image_asset_id).length)
async function load() {
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''
  try { const data = await portalAdminApi.colorSwatches(applied.value, controller.signal); swatches.value = data.items; unregistered.value = data.unregistered_colors }
  catch (e) { if (e?.name !== 'CanceledError') error.value = message(e) }
  finally { loading.value = false }
}
function search() { applied.value = { ...filters.value }; return load() }
function reset() { filters.value = { ...DEFAULT_FILTERS }; return search() }
async function sync() {
  try {
    const { value } = await promptAction('将为目录中尚无色块的颜色登记色号（不绑定图片）。请填写操作原因：', '同步目录颜色', { inputValidator: v => !!v?.trim() || '请填写原因' })
    const result = await portalAdminApi.syncColorSwatches(value.trim())
    msgSuccessText(result.created.length ? `已登记 ${result.created.length} 个色号` : '目录颜色均已登记'); await load()
  } catch (e) { if (!isFeedbackCancelled(e)) error.value = message(e) }
}
function clearPreview() { previewController?.abort(); if (preview.value) URL.revokeObjectURL(preview.value); preview.value = ''; previewing.value = false }
function edit(row) {
  clearPreview(); assets.value = []; editing.value = row
  // File names carry the color code, so the asset search starts from it.
  assetKeyword.value = row.color_code.replace(/^#/, '').split(/[/-]/)[0]
  form.value = { color_code: row.color_code, display_name: row.display_name || '', status: row.status, image: row.image_asset_id ? 'keep' : 'new', asset_id: '', asset_reference: '', reason: '' }
}
async function searchAssets() {
  assetController?.abort(); assetController = new AbortController(); assetsLoading.value = true
  try { assets.value = (await portalAdminApi.imageAssets({ keyword: assetKeyword.value.trim(), page: 1, page_size: 20 }, assetController.signal)).items }
  catch (e) { if (e?.name !== 'CanceledError') error.value = message(e) }
  finally { assetsLoading.value = false }
}
async function choose(asset) {
  clearPreview(); form.value.image = 'new'; form.value.asset_id = asset.id; form.value.asset_reference = ''; previewing.value = true
  previewController = new AbortController()
  try {
    const data = await portalAdminApi.previewImage(asset.id, previewController.signal)
    if (!(data.blob instanceof Blob) || !data.reference?.startsWith(asset.id + ':')) throw new Error('图片预览回执无效。')
    preview.value = URL.createObjectURL(data.blob); form.value.asset_reference = data.reference
  } catch (e) { if (e?.name !== 'CanceledError') error.value = message(e) }
  finally { previewing.value = false }
}
async function save() {
  if (saving.value || previewing.value) return
  let body
  try { body = swatchBody(form.value) } catch (e) { error.value = e.message; return }
  saving.value = true; error.value = ''
  try { await portalAdminApi.updateColorSwatch(editing.value.id, body, editing.value.row_version); msgSuccessText('色块已保存'); close(); await load() }
  catch (e) { error.value = message(e) }
  finally { saving.value = false }
}
function close() { if (saving.value) return; clearPreview(); assetController?.abort(); editing.value = null }
onMounted(load)
onBeforeUnmount(() => { controller?.abort(); assetController?.abort(); clearPreview() })
</script>

<template>
  <div class="tab-body">
    <FilterBar label="色块筛选" :loading="loading" :pending="pending" @search="search" @reset="reset">
      <el-input v-model="filters.keyword" aria-label="搜索色号" placeholder="色号，如 9ATP9A" maxlength="64" clearable class="filter-w-md" />
      <el-checkbox v-model="filters.missing_image">只看未绑定图片</el-checkbox>
    </FilterBar>
    <div class="action-bar">
      <GlassButton v-permission="'portal_site:admin'" variant="primary" :left-icon="Refresh" @click="sync">同步目录颜色</GlassButton>
      <span class="action-hint">共 {{ swatches.length }} 个色号，已绑定图片 {{ imageCount }} 个。色型取自方舟「色号→计价颜色类型」表，与标准价格一致。</span>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="panel-alert" />
    <el-alert v-if="unregistered.length" :title="`目录中有 ${unregistered.length} 个颜色尚未登记色块：${unregistered.slice(0, 12).join('、')}${unregistered.length > 12 ? ' …' : ''}`" type="warning" :closable="false" show-icon class="panel-alert" />
    <el-table v-loading="loading" :data="swatches" border class="list-table" v-sticky-scrollbar><template #empty><el-empty v-if="!loading" :image-size="96" :description="applied.keyword || applied.missing_image ? '没有符合条件的色块' : '暂无色块；先导入商品，再点「同步目录颜色」'"><GlassButton v-if="applied.keyword || applied.missing_image" left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton></el-empty></template>
      <el-table-column prop="color_code" label="色号" min-width="140" max-width="220" show-overflow-tooltip />
      <el-table-column prop="display_name" label="展示名" min-width="140" max-width="220" show-overflow-tooltip><template #default="{ row }">{{ row.display_name || '—' }}</template></el-table-column>
      <el-table-column label="色型" min-width="170" max-width="260" :sort-by="row => colorTypeLabels[row.color_type] || ''"><template #default="{ row }">{{ colorTypeLabels[row.color_type] || '未识别' }}<span :class="['source', row.color_type_source]">{{ colorTypeSources[row.color_type_source] }}</span></template></el-table-column>
      <el-table-column prop="item_count" label="使用商品数" min-width="110" max-width="160" />
      <el-table-column label="色块图" min-width="100" max-width="140" :sort-by="row => row.image_asset_id ? 1 : 0"><template #default="{ row }"><StatusBadge :value="Boolean(row.image_asset_id)" :dictionary="IMAGE_STATE" effect="plain" /></template></el-table-column>
      <el-table-column prop="status" label="状态" min-width="100" max-width="140"><template #default="{ row }"><StatusBadge :value="row.status" :dictionary="ENABLED_STATE" effect="plain" /></template></el-table-column>
      <el-table-column label="操作" min-width="100" max-width="140" fixed="right" class-name="table-action-column" :sortable="false"><template #default="{ row }"><GlassButton v-permission="'portal_site:admin'" variant="link" :left-icon="Edit" @click="edit(row)">编辑</GlassButton></template></el-table-column>
    </el-table>
    <el-dialog v-if="editing" :model-value="true" :title="`编辑色块 · ${editing.color_code}`" width="760px" class="portal-swatch-dialog" :close-on-click-modal="false" @update:model-value="v => { if (!v) close() }">
      <el-form label-position="top" :disabled="saving">
        <div class="grid">
          <el-form-item label="标准色号写法（只能调整格式）"><el-input v-model="form.color_code" maxlength="64" /></el-form-item>
          <el-form-item label="展示名（可选）"><el-input v-model="form.display_name" maxlength="128" placeholder="如 Cookies Cream" /></el-form-item>
        </div>
        <el-form-item label="状态"><el-radio-group v-model="form.status"><el-radio value="enabled">启用</el-radio><el-radio value="disabled">停用</el-radio></el-radio-group></el-form-item>
        <el-form-item label="色块图">
          <el-radio-group v-model="form.image"><el-radio v-if="editing.image_asset_id" value="keep">保留当前图片</el-radio><el-radio value="new">选择新图片</el-radio><el-radio v-if="editing.image_asset_id" value="remove">移除图片</el-radio></el-radio-group>
        </el-form-item>
        <template v-if="form.image === 'new'">
          <div class="search"><el-input v-model="assetKeyword" aria-label="搜索图片素材" placeholder="按素材文件名搜索" @keyup.enter="searchAssets" /><GlassButton v-permission="'asset:admin'" left-icon="Search" :loading="assetsLoading" @click="searchAssets">搜索素材</GlassButton></div>
          <el-table v-loading="assetsLoading" :data="assets" border max-height="220" class="list-table" v-sticky-scrollbar><template #empty><el-empty :image-size="48" description="搜索素材库中允许公开预览和下载的图片" /></template>
            <el-table-column prop="name" label="素材文件名" min-width="260" max-width="480" show-overflow-tooltip />
            <el-table-column label="操作" min-width="90" max-width="120" class-name="table-action-column" :sortable="false"><template #default="{ row }"><GlassButton v-permission="'asset:admin'" variant="link" :left-icon="form.asset_id === row.id ? 'Check' : 'Pointer'" :disabled="previewing" @click="choose(row)">{{ form.asset_id === row.id ? '已选' : '选择' }}</GlassButton></template></el-table-column>
          </el-table>
          <div v-loading="previewing" class="preview"><img v-if="preview" :src="preview" :alt="`${editing.color_code} 色块预览`" /><p v-else>选择素材后在此核对色块图。</p></div>
        </template>
        <el-form-item label="操作原因" required><el-input v-model="form.reason" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer><div class="dialog-footer"><GlassButton variant="ghost" :disabled="saving" @click="close">取消</GlassButton><GlassButton v-permission="'portal_site:admin'" variant="primary" :loading="saving" :disabled="previewing" @click="save">保存</GlassButton></div></template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* FilterBar sits inside .tab-body, so the global sticky .toolbar rule would float it over the table header. */
.tab-body > .toolbar { position: static; top: auto; margin-bottom: 0; padding: 14px; background: rgba(255, 255, 255, 0.4); border: none; border-bottom: 1px solid var(--border-color); border-radius: 0; box-shadow: none; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.tab-body > .toolbar .filter-w-md { width: 200px; }
.action-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px; border-bottom: 1px solid var(--border-color); background: rgba(255, 255, 255, 0.28); }
.action-hint { flex: 1; min-width: 220px; color: var(--text-secondary); font-size: 13px; }
.panel-alert { margin: 12px 14px 0; width: auto; }
.source { margin-left: 8px; font-size: 12px; color: var(--text-secondary); } .source.inferred, .source.missing { color: var(--color-warning-text); }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.search { display: flex; gap: 10px; margin-bottom: 12px; } .search .el-input { flex: 1; }
.preview { min-height: 80px; margin: 16px 0; } .preview img { display: block; max-width: 100%; max-height: 260px; object-fit: contain; } .preview p { color: var(--text-secondary); }
@media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
</style>
<style>.portal-swatch-dialog { max-width: calc(100vw - 24px); }</style>
