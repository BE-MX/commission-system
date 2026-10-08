<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useListPage } from '@/composables/useListPage'
import { portalAdminApi } from '@/api/portal'
import CatalogItemDialog from './CatalogItemDialog.vue'
import ImageBindingDialog from './ImageBindingDialog.vue'
import { catalogStates } from './catalogConfiguration.mjs'
const auth = useAuthStore(), error = ref(''), notice = ref(''), editor = ref(null), imageItem = ref(null)
let sequence = 0, controller, disposed = false
const { list, total, page, pageSize, loading, searchForm, fetchList, handleSearch, handlePageChange, handleSizeChange } = useListPage(async params => {
  const request = ++sequence; controller?.abort(); controller = new AbortController(); list.value = []; total.value = 0; error.value = ''
  try { const result = await portalAdminApi.catalogItems(params, controller.signal); return !disposed && request === sequence ? result : { items: [], total: 0 } }
  catch (e) { if (!disposed && request === sequence) error.value = e?.response?.data?.message || '商品目录读取失败。'; return { items: [], total: 0 } }
}, { searchForm: { keyword: '', status: '' } })
function clear() { sequence++; controller?.abort(); list.value = []; total.value = 0; editor.value = null; imageItem.value = null; error.value = ''; notice.value = '' }
watch(() => [auth.accessToken, auth.user], clear)
onBeforeUnmount(() => { disposed = true; clear() })
function changed(text) { notice.value = text; fetchList() }
</script>

<template>
  <section>
    <header><div><h1>门户商品目录</h1><p>标准 SKU 导入草稿后，核对单位换算，再发布并分配给客户。</p></div><GlassButton v-permission="'portal_site:admin'" variant="primary" @click="editor = { id: null }">导入标准 SKU</GlassButton></header>
    <div class="toolbar"><el-input v-model="searchForm.keyword" aria-label="搜索门户商品" placeholder="型号、颜色或完整产品/SKU ID" maxlength="100" @keyup.enter="handleSearch" /><el-select v-model="searchForm.status" aria-label="商品状态" placeholder="全部状态" clearable @change="handleSearch"><el-option v-for="(label, value) in catalogStates" :key="value" :label="label" :value="value" /></el-select><GlassButton @click="handleSearch">搜索</GlassButton><GlassButton :disabled="loading" @click="fetchList">刷新</GlassButton></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" /><el-alert v-if="notice" :title="notice" type="info" :closable="false" />
    <el-table v-loading="loading" :data="list" border class="list-table" v-sticky-scrollbar><template #empty><el-empty :image-size="72" description="暂无商品；请先配置站点并导入标准 SKU" /></template>
      <el-table-column prop="display_name" label="标准型号" min-width="180" /><el-table-column prop="color_name" label="颜色" min-width="140" />
      <el-table-column label="来源" min-width="180"><template #default="{ row }">{{ row.product_id }} / {{ row.sku_id }}</template></el-table-column>
      <el-table-column label="销售换算" min-width="230"><template #default="{ row }">1 {{ row.sale_unit }} = {{ row.conversion_factor }} {{ row.inventory_unit }}</template></el-table-column>
      <el-table-column label="状态" min-width="110"><template #default="{ row }">{{ catalogStates[row.status] || '待核实' }}</template></el-table-column>
      <el-table-column label="操作" min-width="100" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton v-permission="'portal_site:admin'" variant="link" @click="editor = { id: row.id }">管理商品</GlassButton><GlassButton v-permission="'asset:admin'" variant="link" @click="imageItem = row.id">展示图片</GlassButton></template></el-table-column>
    </el-table>
    <el-pagination :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    <ImageBindingDialog v-if="imageItem" :key="imageItem" :item-id="imageItem" @close="imageItem = null" @changed="changed" />
    <CatalogItemDialog v-if="editor" :item-id="editor.id" @close="editor = null" @changed="changed" />
  </section>
</template>

<style scoped>
header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
h1 { font-size: 24px; margin: 0; } p { color: var(--text-secondary); }
.toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; } .toolbar .el-input { flex: 1; min-width: 180px; } .el-select { width: 160px; }
.el-alert { margin-bottom: 16px; } .el-pagination { overflow-x: auto; padding: 20px 0; }
@media (max-width: 600px) { header { align-items: flex-start; } h1 { font-size: 20px; } }
</style>
