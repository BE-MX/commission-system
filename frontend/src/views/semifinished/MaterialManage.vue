<template>
  <div class="sf-page">
    <header class="sf-header">
      <div><h2>半成品列表</h2><p>按尺寸与标准化颜色跨产品共享，自动解析结果需审核后才能参与自动库存。</p></div>
    </header>

    <section ref="panelRef" class="table-card">
      <el-tabs v-model="activeTab" class="sf-tabs" @tab-change="changeTab">
        <el-tab-pane label="半成品" name="materials" />
        <el-tab-pane label="产品关联审核" name="mappings" />
      </el-tabs>
      <FilterBar :pending="listState.hasPendingSearch.value" @search="search" @reset="reset">
        <el-input v-model="filters.keyword" clearable placeholder="搜索编码、尺寸、颜色或产品" class="filter-w-lg" />
        <el-checkbox v-model="filters.review_only" label="仅看待审核" />
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-permission="'semifinished:write'" variant="primary" :left-icon="Plus" :disabled="!selectedMaterials.length" @click="openOrder">生产下单</GlassButton>
        <GlassButton v-permission="'semifinished:admin'" variant="secondary" :left-icon="Refresh" @click="applySync">应用产品同步</GlassButton>
        <GlassButton v-permission="'semifinished:admin'" variant="secondary" :left-icon="View" @click="previewSync">同步预览</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="currentColumnDefs"
          :fullscreen="isFullscreen"
          @refresh="loadCurrent"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listState.hasData.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="load" />
      <el-table v-if="activeTab === 'materials'" v-loading="loading" :data="rows" border class="list-table sf-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" @selection-change="selectedMaterials = $event">
        <template #empty>
          <ListPageStatus :error="listState.errorMessage.value" :loading="loading" @retry="load" />
          <el-empty v-if="listState.isEmpty.value" :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column type="selection" min-width="48" />
        <el-table-column v-if="visibleKeys.includes('material')" label="半成品" min-width="180">
          <template #default="{ row }"><div class="sf-material"><strong>{{ row.size }}/{{ row.color_code }}</strong><small>{{ row.material_code }}</small></div></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('color-type')" prop="color_type" label="色型" min-width="100" />
        <el-table-column v-if="visibleKeys.includes('product-count')" prop="product_count" label="关联产品" min-width="100" align="right" />
        <el-table-column v-if="visibleKeys.includes('on-hand')" label="实存(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.on_hand_grams) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('reserved')" label="占用(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.reserved_grams) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('available')" label="可用(g)" min-width="110" align="right"><template #default="{ row }"><strong>{{ grams(row.available_grams) }}</strong></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="90"><template #default="{ row }"><StatusBadge :value="row.status === 'active'" :dictionary="ENABLED_STATUS" effect="plain" /></template></el-table-column>
      </el-table>

      <el-table v-else v-loading="loading" :data="rows" border class="list-table sf-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <template #empty>
          <ListPageStatus :error="listState.errorMessage.value" :loading="loading" @retry="load" />
          <el-empty v-if="listState.isEmpty.value" :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column v-if="visibleKeys.includes('product')" prop="product_name" label="产品" min-width="300" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('model')" prop="model" label="型号" min-width="170" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('spec')" label="规格" min-width="170"><template #default="{ row }">{{ row.size }}/{{ row.color_expression }}/{{ grams(row.unit_grams) }}g</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('components')" label="半成品组成" min-width="240"><template #default="{ row }"><StatusBadge v-for="item in row.components" :key="item.material_id" size="small" effect="plain" style="margin: 2px">{{ item.size }}/{{ item.color_code }} · {{ percent(item.ratio) }}</StatusBadge></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('review')" label="审核" min-width="110"><template #default="{ row }"><StatusBadge :type="row.parse_status === 'confirmed' ? 'success' : 'warning'" effect="plain">{{ row.parse_status === 'confirmed' ? '已确认' : '待审核' }}</StatusBadge></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('parse-message')" label="说明" min-width="160" prop="parse_message" show-overflow-tooltip />
        <el-table-column class-name="table-action-column" label="操作" min-width="90" fixed="right"><template #default="{ row }"><el-button v-permission="'semifinished:write'" link type="primary" @click="editMapping(row)">配比</el-button></template></el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @size-change="handleSizeChange"
        @current-change="loadCurrent"
      />
    </section>

    <DetailDrawer v-model="previewVisible" title="产品解析预览" width="760px">
      <ListPageStatus :error="previewResource.errorMessage.value" :loading="previewResource.loading.value" :has-data="!!preview" @retry="previewResource.load()" />
      <div v-if="preview" class="sf-summary">
        <div class="sf-summary-item"><span>符合产品</span><strong>{{ preview.eligible_products }}</strong></div>
        <div class="sf-summary-item"><span>预计半成品</span><strong>{{ preview.material_count }}</strong></div>
        <div class="sf-summary-item"><span>新增关联</span><strong>{{ preview.new_mappings }}</strong></div>
        <div class="sf-summary-item"><span>待审核</span><strong>{{ preview.needs_review }}</strong></div>
      </div>
      <el-table :data="preview?.examples || []" max-height="360" border class="list-table">
        <el-table-column prop="product_name" label="产品" min-width="280" show-overflow-tooltip />
        <el-table-column label="解析结果" min-width="230"><template #default="{ row }">{{ row.components.map(c => `${row.size}/${c}`).join('、') }}</template></el-table-column>
        <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip />
      </el-table>
    </DetailDrawer>

    <el-dialog v-model="mappingVisible" title="确认半成品配比" width="640px">
      <p class="sf-muted">{{ editingMapping?.product_name }}</p>
      <ListPageStatus :error="mappingOptionsResource.errorMessage.value" :loading="mappingOptionsResource.loading.value" :has-data="mappingMaterialOptions.length > 0" @retry="mappingOptionsResource.load()" />
      <div class="sf-component-list">
        <div v-for="(item, index) in mappingComponents" :key="`${index}-${item.material_id}`" class="sf-component-row sf-mapping-row">
          <el-select v-model="item.material_id" filterable placeholder="选择半成品">
            <el-option v-for="material in mappingMaterialOptions" :key="material.id" :value="material.id" :label="`${material.size}/${material.color_code} · ${material.material_code}`" />
          </el-select>
          <el-input-number v-model="item.ratio" :min="0.000001" :max="1" :precision="6" :step="0.05" />
          <span>{{ percent(item.ratio) }}</span>
          <el-button link type="danger" @click="mappingComponents.splice(index, 1)">删除</el-button>
        </div>
      </div>
      <el-button link type="primary" @click="mappingComponents.push({ material_id: null, ratio: 0 })">+ 添加组成物料</el-button>
      <p :class="ratioValid ? 'sf-success' : 'sf-danger'">配比合计：{{ percent(ratioTotal) }}</p>
      <template #footer><el-button @click="mappingVisible = false">取消</el-button><el-button type="primary" :disabled="!ratioValid" @click="saveMapping">确认配比</el-button></template>
    </el-dialog>

    <el-dialog v-model="orderVisible" title="创建半成品订单" width="640px">
      <div class="sf-component-list">
        <div v-for="item in orderItems" :key="item.material_id" class="sf-component-row">
          <span>{{ item.label }}</span><el-input-number v-model="item.quantity_grams" :min="0.001" :precision="3" /><span>g</span>
        </div>
      </div>
      <el-input v-model="orderRemark" type="textarea" :rows="2" maxlength="500" placeholder="备注" style="margin-top: 14px" />
      <template #footer><el-button @click="orderVisible = false">取消</el-button><el-button type="primary" @click="submitOrder">提交订单</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ENABLED_STATUS } from '@/utils/status'
import { confirmAction, msgSuccessText } from '@/utils/feedback'
import { computed, reactive, ref, watch } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { watchListResourceScope } from '@/composables/useListResourceScope'
import { loadMaterialOptions } from './materialOptions'


import { Plus, Refresh, RefreshLeft, Search, View } from '@element-plus/icons-vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { applyMaterialSync, createSemifinishedOrder, getMappings, getMaterials, previewMaterialSync, updateMapping } from '@/api/semifinished'

const activeTab = ref('materials')
const selectedMaterials = ref([])
const listState = useListPage(({ resource, ...params }, { signal }) => (resource === 'materials' ? getMaterials : getMappings)({ ...params, keyword: params.keyword || undefined }, { signal, suppressToast: true }), { searchForm: { resource: 'materials', keyword: '', review_only: false } })
const loading = listState.loading; const rows = listState.list; const filters = listState.searchForm
const pagination = reactive({ page: listState.page, page_size: listState.pageSize, total: listState.total })
watchListResourceScope(listState, ['resource'], () => { selectedMaterials.value = [] })
function changeTab() { filters.resource = activeTab.value; return listState.handleSearch() }
const previewVisible = ref(false)
const previewResource = useAsyncResource((_, { signal }) => previewMaterialSync({ signal, suppressToast: true, showLoading: false }))
const preview = previewResource.data
const mappingVisible = ref(false)
const editingMapping = ref(null)
const mappingComponents = ref([])
const mappingOptionsResource = useAsyncResource((_, context) => loadMaterialOptions(context))
const mappingMaterialOptions = computed(() => mappingOptionsResource.data.value || [])
const orderVisible = ref(false)
const orderItems = ref([])
const orderRemark = ref('')

const ratioTotal = computed(() => mappingComponents.value.reduce((sum, item) => sum + Number(item.ratio || 0), 0))
const ratioValid = computed(() => {
  const ids = mappingComponents.value.map(item => item.material_id).filter(Boolean)
  return ids.length === mappingComponents.value.length
    && new Set(ids).size === ids.length
    && ids.length > 0
    && Math.abs(ratioTotal.value - 1) < 0.000001
})
const hasActiveFilters = computed(() => Boolean(filters.keyword || filters.review_only))
const grams = value => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 })
const percent = value => `${(Number(value || 0) * 100).toFixed(2)}%`

// 列显隐面板数据源（两个 tab 各一套列；渲染保持静态模板列，v-if 按 key 控制）
const materialColumnDefs = [
  { key: 'material', label: '半成品' },
  { key: 'color-type', label: '色型' },
  { key: 'product-count', label: '关联产品' },
  { key: 'on-hand', label: '实存(g)' },
  { key: 'reserved', label: '占用(g)' },
  { key: 'available', label: '可用(g)' },
  { key: 'status', label: '状态' },
]
const mappingColumnDefs = [
  { key: 'product', label: '产品' },
  { key: 'model', label: '型号' },
  { key: 'spec', label: '规格' },
  { key: 'components', label: '半成品组成' },
  { key: 'review', label: '审核' },
  { key: 'parse-message', label: '说明' },
]
const currentColumnDefs = computed(() => (activeTab.value === 'materials' ? materialColumnDefs : mappingColumnDefs))
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('semifinished-materials', [...materialColumnDefs, ...mappingColumnDefs])
watch(currentColumnDefs, columns => {
  if (!columns.some(column => visibleKeys.value.includes(column.key))) {
    visibleKeys.value = [...visibleKeys.value, columns[0].key]
  }
}, { immediate: true })

const loadCurrent = listState.fetchList
const load = loadCurrent
const search = listState.handleSearch
function reset() { filters.keyword = ''; filters.review_only = false; return search() }
const handleSizeChange = listState.handleSizeChange
async function previewSync() { previewVisible.value = true; return previewResource.load(null, { clear: true }) }
async function applySync() {
  await confirmAction('将按当前产品列表新增或更新自动解析结果，人工确认的配比不会被覆盖。', '应用产品同步')
  const result = await applyMaterialSync()
  msgSuccessText(`已同步 ${result.applied} 个产品，${result.needs_review} 个待审核`)
  listState.refreshUpdate()
}
async function editMapping(row) { editingMapping.value = row; mappingComponents.value = row.components.map(item => ({ ...item, ratio: Number(item.ratio) })); mappingVisible.value = true; return mappingOptionsResource.load(row.id, { clear: true }) }
async function saveMapping() {
  await updateMapping(editingMapping.value.id, { components: mappingComponents.value.map(item => ({ material_id: item.material_id, ratio: Number(item.ratio) })) })
  msgSuccessText('配比已确认'); mappingVisible.value = false; listState.refreshUpdate()
}
function openOrder() {
  orderItems.value = selectedMaterials.value.map(row => ({ material_id: row.id, label: `${row.size}/${row.color_code}`, quantity_grams: 100 }))
  orderRemark.value = ''; orderVisible.value = true
}
async function submitOrder() {
  await createSemifinishedOrder({ items: orderItems.value.map(item => ({ material_id: item.material_id, quantity_grams: item.quantity_grams })), remark: orderRemark.value || null })
  msgSuccessText('半成品订单已创建'); orderVisible.value = false; listState.refreshUpdate()
}

</script>

<style scoped src="./semifinished.css"></style>
