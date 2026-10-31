<template>
  <div>
    <div class="page-header">
      <h2>产品与 SKU</h2>
      <p>维护本地产品目录。停用保留历史单据；SKU 编码与单位创建后保持不变。</p>
    </div>
    <div ref="panelRef" class="table-card">
      <FilterBar
        class="toolbar"
        :loading="loading"
        :pending="hasPendingSearch"
        @search="handleSearch"
        @reset="handleReset"
      >
        <el-input v-model="searchForm.keyword" clearable placeholder="搜索产品名称 / 编码" class="filter-w-lg" />
        <el-select v-model="searchForm.active" clearable placeholder="全部状态" class="filter-w-sm">
          <el-option label="启用" :value="true" />
          <el-option label="停用" :value="false" />
        </el-select>
      </FilterBar>
      <div class="action-bar">
        <GlassButton v-permission="'catalog:write'" variant="primary" left-icon="Plus" @click="editProduct()">
          新建产品
        </GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columns"
          :fullscreen="isFullscreen"
          :loading="loading"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>
      <ListPageStatus :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table
        :data="list"
        v-loading="loading"
        border
        class="list-table"
        :class="densityClass"
        :max-height="isFullscreen ? undefined : 640"
       v-sticky-scrollbar>
        <el-table-column
          v-for="column in columns.filter(c => visibleKeys.includes(c.key))"
          :key="column.key"
          :prop="column.key"
          :label="column.label"
          min-width="140"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <StatusBadge v-if="column.key === 'active'" :type="row.active ? 'success' : 'info'">
              {{ row.active ? '启用' : '停用' }}
            </StatusBadge>
            <span v-else-if="column.key === 'kind'">{{ row.kind === 'hair' ? '发制品' : '配件' }}</span>
            <span v-else>{{ row[column.key] || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="190" fixed="right" class-name="table-action-column">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="selected = row; detailOpen = true">
              SKU 明细
            </GlassButton>
            <GlassButton
              v-permission="'catalog:write'"
              variant="link"
              left-icon="Edit"
              @click="editProduct(row)"
            >
              编辑
            </GlassButton>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty v-if="!errorMessage" description="暂无产品，可调整筛选或新建产品" :image-size="96" />
        </template>
      </el-table>
      <el-pagination
        class="pager"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>
    <DetailDrawer v-model="detailOpen" :title="selected?.display_name || 'SKU 明细'" width="760px">
      <p>产品编码：{{ selected?.code }} · SKU 单位：件</p>
      <div class="action-bar">
        <GlassButton
          v-permission="'catalog:write'"
          variant="primary"
          left-icon="Plus"
          :disabled="!selected?.active"
          @click="newSku"
        >
          新增 SKU
        </GlassButton>
      </div>
      <el-table :data="selected?.skus || []" border class="list-table" v-sticky-scrollbar>
        <el-table-column prop="code" label="SKU 编码" min-width="130" />
        <el-table-column prop="color" label="颜色" min-width="100" />
        <el-table-column prop="size" label="尺寸" min-width="100" />
        <el-table-column prop="curl" label="曲度" min-width="100" />
        <el-table-column prop="weight_grams" label="克重" min-width="90" />
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">
            <StatusBadge :type="row.active ? 'success' : 'info'">{{ row.active ? '启用' : '停用' }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="175" class-name="table-action-column">
          <template #default="{ row }">
            <GlassButton v-permission="'catalog:write'" variant="link" left-icon="Edit" @click="editSku(row)">
              编辑
            </GlassButton>
            <GlassButton
              v-permission="'catalog:write'"
              variant="link"
              left-icon="SwitchButton"
              :loading="statusPending === row.id"
              :disabled="statusPending !== null"
              @click="toggleSku(row)"
            >
              {{ row.active ? '停用' : '启用' }}
            </GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </DetailDrawer>
    <el-dialog
      v-model="dialogOpen"
      :title="skuMode ? (editingSkuId ? '编辑 SKU' : '新增 SKU') : editingId ? '编辑产品' : '新建产品'"
      width="640px"
      :close-on-click-modal="!saving"
      :close-on-press-escape="!saving"
      :show-close="!saving"
    >
      <el-form ref="formRef" :model="form" label-position="top" :disabled="saving">
        <el-form-item
          v-if="skuMode || !editingId"
          label="编码"
          prop="code"
          :rules="[{ required: true, message: '请输入编码' }, { pattern: /^[A-Za-z0-9._-]+$/, message: '编码仅支持字母、数字、点、下划线和短横线' }]"
        >
          <el-input v-model="form.code" maxlength="64" :disabled="!!editingSkuId" />
        </el-form-item>
        <template v-if="!skuMode">
          <el-form-item
            label="产品名称"
            prop="name"
            :rules="[{ required: true, message: '请输入产品名称', whitespace: true }]"
          >
            <el-input v-model="form.name" maxlength="512" />
          </el-form-item>
          <el-form-item
            label="显示名称"
            prop="display_name"
            :rules="[{ required: true, message: '请输入显示名称', whitespace: true }]"
          >
            <el-input v-model="form.display_name" maxlength="256" />
          </el-form-item>
          <el-form-item v-if="!editingId" label="品类">
            <el-select v-model="form.kind">
              <el-option label="发制品" value="hair" />
              <el-option label="配件" value="accessory" />
            </el-select>
          </el-form-item>
          <el-form-item label="型号">
            <el-input v-model="form.model" maxlength="200" />
          </el-form-item>
          <el-form-item v-if="editingId" label="启用产品">
            <el-switch v-model="form.active" />
          </el-form-item>
        </template>
        <template v-else>
          <p v-if="editingSkuId">已用于库存、订单或生产等业务的 SKU 不能修改规格，请新建正确 SKU。</p>
          <el-form-item label="颜色">
            <el-input v-model="form.color" maxlength="128" />
          </el-form-item>
          <el-form-item label="尺寸">
            <el-input v-model="form.size" maxlength="128" />
          </el-form-item>
          <el-form-item label="曲度">
            <el-input v-model="form.curl" maxlength="64" />
          </el-form-item>
          <el-form-item label="克重（选填，不作为库存数量）">
            <el-input-number v-model="form.weight_grams" :min="0.001" :precision="3" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <GlassButton :disabled="saving" @click="dialogOpen = false">取消</GlassButton>
          <GlassButton variant="primary" :loading="saving" @click="save">保存</GlassButton>
        </div>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { getProducts, createProduct, updateProduct, createSku, updateSku, setSkuStatus } from '@/api/catalog'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { msgSuccess, msgError, confirmDanger, isFeedbackCancelled } from '@/utils/feedback'
const state = useListPage(async (params, { signal }) => (await getProducts({ ...params, active: params.active === '' ? undefined : params.active }, { signal, suppressToast: true })).data, { searchForm: { keyword: '', active: '' } })
const { list, loading, errorMessage, hasData, dataPage, searchForm, hasPendingSearch, page, pageSize, total, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = state
const columns = [{ key: 'code', label: '产品编码' }, { key: 'display_name', label: '显示名称' }, { key: 'name', label: '产品名称' }, { key: 'kind', label: '品类' }, { key: 'model', label: '型号' }, { key: 'active', label: '状态' }]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView('catalog-products', columns)
const selected = ref(null), detailOpen = ref(false), dialogOpen = ref(false), skuMode = ref(false), editingSkuId = ref(null), editingId = ref(null), saving = ref(false), statusPending = ref(null), formRef = ref(), form = ref({})
function editProduct(row) {
  skuMode.value = false; editingSkuId.value = null; editingId.value = row?.id || null
  form.value = row ? { name: row.name, display_name: row.display_name, model: row.model, active: row.active } : { code: '', name: '', display_name: '', kind: 'hair', model: '' }
  dialogOpen.value = true
}
function editSku(row) { editingSkuId.value = row.id; skuMode.value = true; form.value = { code: row.code, color: row.color, size: row.size, curl: row.curl, weight_grams: row.weight_grams == null ? undefined : Number(row.weight_grams) }; dialogOpen.value = true }
function newSku() { editingSkuId.value = null; skuMode.value = true; form.value = { code: '', color: '', size: '', curl: '', weight_grams: undefined }; dialogOpen.value = true }
async function refreshSelected() {
  await fetchList()
  if (selected.value) { const current = list.value.find(p => p.id === selected.value.id); if (current) selected.value = current; else detailOpen.value = false }
}
async function save() {
  if (saving.value) return
  saving.value = true
  if (!await formRef.value.validate().catch(() => false)) { saving.value = false; return }
  try {
    if (!skuMode.value && editingId.value && !form.value.active) await confirmDanger('停用产品', form.value.display_name, '历史单据保留，新的库存操作将无法选择该产品。')
    if (skuMode.value && editingSkuId.value) await updateSku(editingSkuId.value, form.value)
    else if (skuMode.value) await createSku(selected.value.id, form.value)
    else if (editingId.value) await updateProduct(editingId.value, form.value)
    else await createProduct(form.value)
    msgSuccess('保存'); dialogOpen.value = false; await refreshSelected()
  } catch (error) { if (!isFeedbackCancelled(error)) msgError('保存失败，请核对输入后重试', error) }
  finally { saving.value = false }
}
async function toggleSku(row) {
  if (statusPending.value !== null) return
  statusPending.value = row.id
  try { if (row.active) await confirmDanger('停用 SKU', row.code, '历史记录保留。'); await setSkuStatus(row.id, !row.active); msgSuccess('更新 SKU'); await refreshSelected() }
  catch (error) { if (!isFeedbackCancelled(error)) msgError('更新 SKU 失败', error) }
  finally { statusPending.value = null }
}
</script>
