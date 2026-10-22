<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Edit, FolderAdd, Picture, Plus } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { portalAdminApi } from '@/api/portal'
import CatalogItemDialog from './CatalogItemDialog.vue'
import ImageBindingDialog from './ImageBindingDialog.vue'
import AssignFamilyDialog from './AssignFamilyDialog.vue'
import FamilyPanel from './FamilyPanel.vue'
import SwatchPanel from './SwatchPanel.vue'
import { gradeLabels } from './familyConfiguration.mjs'
import { CATALOG_STATUS } from './portalStatus'

const auth = useAuthStore(), error = ref(''), notice = ref(''), editor = ref(null), imageItem = ref(null)
const tab = ref('items'), families = ref([]), selected = ref([]), assigning = ref(false)
const columnDefs = [
  { key: 'model', label: '标准型号' }, { key: 'color', label: '颜色' }, { key: 'family', label: '产品族 / 工艺档' },
  { key: 'source', label: '来源' }, { key: 'conversion', label: '销售换算' }, { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('portal-catalog', columnDefs)
let sequence = 0, controller, familyController, disposed = false
const { list, total, page, pageSize, loading, searchForm, appliedSearchForm, hasPendingSearch, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = useListPage(async params => {
  const request = ++sequence; controller?.abort(); controller = new AbortController(); list.value = []; total.value = 0; error.value = ''; selected.value = []
  try { const result = await portalAdminApi.catalogItems(params, controller.signal); return !disposed && request === sequence ? result : { items: [], total: 0 } }
  catch (e) { if (!disposed && request === sequence) error.value = e?.response?.data?.message || '商品目录读取失败。'; return { items: [], total: 0 } }
}, { searchForm: { keyword: '', status: '', family: '' } })
const hasAppliedFilters = computed(() => Boolean(appliedSearchForm.value.keyword || appliedSearchForm.value.status || appliedSearchForm.value.family))
async function loadFamilies() {
  familyController?.abort(); familyController = new AbortController()
  try { families.value = (await portalAdminApi.catalogFamilies(familyController.signal)).items } catch { families.value = [] }
}
const familyName = code => families.value.find(family => family.code === code)?.display_name || code
function clear() { sequence++; controller?.abort(); familyController?.abort(); list.value = []; total.value = 0; editor.value = null; imageItem.value = null; assigning.value = false; selected.value = []; error.value = ''; notice.value = '' }
watch(() => [auth.accessToken, auth.user], clear)
onMounted(loadFamilies)
onBeforeUnmount(() => { disposed = true; clear() })
function changed(text) { notice.value = text; fetchList() }
function familiesChanged() { loadFamilies(); fetchList() }
</script>

<template>
  <section class="portal-page portal-catalog">
    <div class="portal-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" /></div>
    <header class="page-header"><div><h2>门户商品目录</h2><p>标准 SKU 导入草稿后，核对单位换算，归入产品族，再发布并分配给客户。</p></div></header>
    <div ref="panelRef" class="table-card portal-panel">
      <el-tabs v-model="tab" class="panel-tabs">
        <el-tab-pane label="商品 SKU" name="items" />
        <el-tab-pane label="产品族" name="families" />
        <el-tab-pane label="色块库" name="swatches" />
      </el-tabs>
      <template v-if="tab === 'items'">
        <FilterBar label="门户商品筛选" :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset">
          <el-input v-model="searchForm.keyword" aria-label="搜索门户商品" placeholder="型号、颜色或完整产品/SKU ID" maxlength="100" clearable class="filter-w-lg" />
          <el-select v-model="searchForm.status" aria-label="商品状态" placeholder="全部状态" clearable class="filter-w-sm"><el-option v-for="(entry, value) in CATALOG_STATUS" :key="value" :label="entry.label" :value="value" /></el-select>
          <el-select v-model="searchForm.family" aria-label="产品族" placeholder="全部产品族" clearable class="filter-w-md"><el-option label="未归类" value="unassigned" /><el-option v-for="family in families" :key="family.code" :label="family.display_name" :value="family.code" /></el-select>
        </FilterBar>
        <div class="action-bar">
          <GlassButton v-permission="'portal_site:admin'" variant="primary" :left-icon="Plus" @click="editor = { id: null }">导入标准 SKU</GlassButton>
          <GlassButton v-permission="'portal_site:admin'" :left-icon="FolderAdd" :disabled="!selected.length || !families.length" @click="assigning = true">归入产品族（{{ selected.length }}）</GlassButton>
          <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columnDefs" :fullscreen="isFullscreen" :loading="loading" @refresh="fetchList" @fullscreen="toggleFullscreen" />
        </div>
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="panel-alert" />
        <el-alert v-if="notice" :title="notice" type="success" :closable="false" show-icon class="panel-alert" />
        <el-table v-loading="loading" :data="list" border class="list-table" :class="densityClass" row-key="id" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar @selection-change="rows => selected = rows">
          <template #empty><el-empty v-if="!loading && !error" :image-size="96" :description="hasAppliedFilters ? '没有符合条件的商品' : '暂无商品；请先配置站点并导入标准 SKU'"><GlassButton v-if="hasAppliedFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton></el-empty></template>
          <el-table-column type="selection" min-width="48" :sortable="false" />
          <el-table-column v-if="visibleKeys.includes('model')" prop="display_name" label="标准型号" min-width="180" max-width="300" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('color')" prop="color_name" label="颜色" min-width="120" max-width="220" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('family')" label="产品族 / 工艺档" min-width="180" max-width="280" :sort-by="row => row.family_code ? familyName(row.family_code) : ''"><template #default="{ row }"><template v-if="row.family_code">{{ familyName(row.family_code) }}<span class="cell-hint">{{ gradeLabels[row.grade] }}</span></template><span v-else class="cell-hint">未归类</span></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('source')" label="来源" min-width="160" max-width="260" :sort-by="row => `${row.product_id}/${row.sku_id}`" show-overflow-tooltip><template #default="{ row }">{{ row.product_id }} / {{ row.sku_id }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('conversion')" label="销售换算" min-width="170" max-width="260" :sort-by="row => Number(row.conversion_factor)" show-overflow-tooltip><template #default="{ row }">1 {{ row.sale_unit }} = {{ row.conversion_factor }} {{ row.inventory_unit }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('status')" prop="status" label="状态" min-width="120" max-width="170"><template #default="{ row }"><StatusBadge :value="row.status" :dictionary="CATALOG_STATUS" effect="plain" /></template></el-table-column>
          <el-table-column label="操作" min-width="200" max-width="260" fixed="right" class-name="table-action-column" :sortable="false"><template #default="{ row }"><GlassButton v-permission="'portal_site:admin'" variant="link" :left-icon="Edit" @click="editor = { id: row.id }">管理商品</GlassButton><GlassButton v-permission="'asset:admin'" variant="link" :left-icon="Picture" @click="imageItem = row.id">展示图片</GlassButton></template></el-table-column>
        </el-table>
        <el-pagination class="pager" :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
      </template>
      <FamilyPanel v-else-if="tab === 'families'" @changed="familiesChanged" />
      <SwatchPanel v-else />
    </div>
    <ImageBindingDialog v-if="imageItem" :key="imageItem" :item-id="imageItem" @close="imageItem = null" @changed="changed" />
    <CatalogItemDialog v-if="editor" :item-id="editor.id" @close="editor = null" @changed="changed" />
    <AssignFamilyDialog v-if="assigning" :items="selected" :families="families" @close="assigning = false" @changed="familiesChanged" />
  </section>
</template>

<style scoped src="./portal-page.css"></style>
<style scoped>
.panel-alert { margin: 12px 14px 0; width: auto; }
.panel-tabs { padding: 4px 14px 0; background: rgba(255, 255, 255, 0.4); }
</style>
