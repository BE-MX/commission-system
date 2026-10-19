<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useListPage } from '@/composables/useListPage'
import { portalAdminApi } from '@/api/portal'
import CatalogItemDialog from './CatalogItemDialog.vue'
import ImageBindingDialog from './ImageBindingDialog.vue'
import AssignFamilyDialog from './AssignFamilyDialog.vue'
import FamilyPanel from './FamilyPanel.vue'
import SwatchPanel from './SwatchPanel.vue'
import { catalogStates } from './catalogConfiguration.mjs'
import { gradeLabels } from './familyConfiguration.mjs'
const auth = useAuthStore(), error = ref(''), notice = ref(''), editor = ref(null), imageItem = ref(null)
const tab = ref('items'), families = ref([]), selected = ref([]), assigning = ref(false)
let sequence = 0, controller, familyController, disposed = false
const { list, total, page, pageSize, loading, searchForm, fetchList, handleSearch, handlePageChange, handleSizeChange } = useListPage(async params => {
  const request = ++sequence; controller?.abort(); controller = new AbortController(); list.value = []; total.value = 0; error.value = ''; selected.value = []
  try { const result = await portalAdminApi.catalogItems(params, controller.signal); return !disposed && request === sequence ? result : { items: [], total: 0 } }
  catch (e) { if (!disposed && request === sequence) error.value = e?.response?.data?.message || '商品目录读取失败。'; return { items: [], total: 0 } }
}, { searchForm: { keyword: '', status: '', family: '' } })
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
  <section>
    <header><div><h1>门户商品目录</h1><p>标准 SKU 导入草稿后，核对单位换算，归入产品族，再发布并分配给客户。</p></div><GlassButton v-if="tab === 'items'" v-permission="'portal_site:admin'" variant="primary" @click="editor = { id: null }">导入标准 SKU</GlassButton></header>
    <el-tabs v-model="tab">
      <el-tab-pane label="商品 SKU" name="items">
        <div class="toolbar">
          <el-input v-model="searchForm.keyword" aria-label="搜索门户商品" placeholder="型号、颜色或完整产品/SKU ID" maxlength="100" @keyup.enter="handleSearch" />
          <el-select v-model="searchForm.status" aria-label="商品状态" placeholder="全部状态" clearable @change="handleSearch"><el-option v-for="(label, value) in catalogStates" :key="value" :label="label" :value="value" /></el-select>
          <el-select v-model="searchForm.family" aria-label="产品族" placeholder="全部产品族" clearable @change="handleSearch"><el-option label="未归类" value="unassigned" /><el-option v-for="family in families" :key="family.code" :label="family.display_name" :value="family.code" /></el-select>
          <GlassButton @click="handleSearch">搜索</GlassButton><GlassButton :disabled="loading" @click="fetchList">刷新</GlassButton>
          <GlassButton v-permission="'portal_site:admin'" :disabled="!selected.length || !families.length" @click="assigning = true">归入产品族（{{ selected.length }}）</GlassButton>
        </div>
        <el-alert v-if="error" :title="error" type="error" :closable="false" /><el-alert v-if="notice" :title="notice" type="info" :closable="false" />
        <el-table v-loading="loading" :data="list" border class="list-table" row-key="id" v-sticky-scrollbar @selection-change="rows => selected = rows"><template #empty><el-empty :image-size="72" description="暂无商品；请先配置站点并导入标准 SKU" /></template>
          <el-table-column type="selection" min-width="44" />
          <el-table-column prop="display_name" label="标准型号" min-width="180" /><el-table-column prop="color_name" label="颜色" min-width="120" />
          <el-table-column label="产品族 / 工艺档" min-width="210"><template #default="{ row }"><template v-if="row.family_code">{{ familyName(row.family_code) }}<div class="hint">{{ gradeLabels[row.grade] }}</div></template><span v-else class="hint">未归类</span></template></el-table-column>
          <el-table-column label="来源" min-width="160"><template #default="{ row }">{{ row.product_id }} / {{ row.sku_id }}</template></el-table-column>
          <el-table-column label="销售换算" min-width="200"><template #default="{ row }">1 {{ row.sale_unit }} = {{ row.conversion_factor }} {{ row.inventory_unit }}</template></el-table-column>
          <el-table-column label="状态" min-width="90"><template #default="{ row }">{{ catalogStates[row.status] || '待核实' }}</template></el-table-column>
          <el-table-column label="操作" min-width="100" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton v-permission="'portal_site:admin'" variant="link" @click="editor = { id: row.id }">管理商品</GlassButton><GlassButton v-permission="'asset:admin'" variant="link" @click="imageItem = row.id">展示图片</GlassButton></template></el-table-column>
        </el-table>
        <el-pagination :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
      </el-tab-pane>
      <el-tab-pane label="产品族" name="families" lazy><FamilyPanel @changed="familiesChanged" /></el-tab-pane>
      <el-tab-pane label="色块库" name="swatches" lazy><SwatchPanel /></el-tab-pane>
    </el-tabs>
    <ImageBindingDialog v-if="imageItem" :key="imageItem" :item-id="imageItem" @close="imageItem = null" @changed="changed" />
    <CatalogItemDialog v-if="editor" :item-id="editor.id" @close="editor = null" @changed="changed" />
    <AssignFamilyDialog v-if="assigning" :items="selected" :families="families" @close="assigning = false" @changed="familiesChanged" />
  </section>
</template>

<style scoped>
header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
h1 { font-size: 24px; margin: 0; } p { color: var(--text-secondary); } .hint { color: var(--text-secondary); font-size: 12px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; } .toolbar .el-input { flex: 1; min-width: 180px; } .el-select { width: 160px; }
.el-alert { margin-bottom: 16px; } .el-pagination { overflow-x: auto; padding: 20px 0; }
@media (max-width: 600px) { header { align-items: flex-start; } h1 { font-size: 20px; } }
</style>
