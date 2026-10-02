<template>
  <div class="product-manage">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="product-manage-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 表格卡片：筛选区 + 操作行 + 表格 + 分页（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="search" @reset="resetFilters">
        <el-input v-model="keyword" placeholder="产品名称/编号" clearable class="filter-w-md" />
        <el-select v-model="filterModel" placeholder="型号" clearable class="filter-w-sm">
          <el-option v-for="m in filterOptions.models" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select v-model="filterRouteBound" placeholder="路线绑定" clearable class="filter-w-sm">
          <el-option label="已绑定" value="bound" />
          <el-option label="未绑定" value="unbound" />
        </el-select>
        <el-checkbox v-model="showDisabled">显示已禁用</el-checkbox>
      </FilterBar>
      <ListPageStatus :paged="false" :error="filterOptionsResource.errorMessage.value" :loading="filterOptionsResource.loading.value" :has-data="filterOptionsResource.hasLoaded.value" @retry="loadFilterOptions" />

      <!-- 操作行：批量操作 + TableTools 四图标 -->
      <div class="action-bar">
        <template v-if="selectedProducts.length > 0">
          <StatusBadge>已选 {{ selectedProducts.length }} 项</StatusBadge>
          <GlassButton v-permission="'production:write'" variant="primary" @click="openBatchBind">批量绑定路线</GlassButton>
        </template>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading" @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="hasData && errorMessage" :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table :data="items" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" @selection-change="onSelectionChange">
        <template #empty>
          <ListPageStatus :error="errorMessage" :loading="loading" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
          </ListPageStatus>
        </template>
        <el-table-column type="selection" min-width="40" />
        <el-table-column v-if="visibleKeys.includes('product-no')" prop="product_no" label="产品编号" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="产品名称" min-width="200" max-width="300" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('model')" prop="model" label="型号" min-width="100" max-width="150" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('process-route')" label="工序路线" min-width="200" max-width="300">
          <template #default="{ row }">
            <template v-if="row.process_route">
              <span>{{ row.process_route.route_name }}</span>
              <GlassButton v-permission="'production:write'" variant="link" left-icon="Edit" @click="openBindDialog(row)">编辑</GlassButton>
            </template>
            <template v-else>
              <span style="color: #909399">—</span>
              <GlassButton v-permission="'production:write'" variant="link" left-icon="Connection" @click="openBindDialog(row)">绑定</GlassButton>
            </template>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="100" max-width="120">
          <template #default="{ row }">
            <StatusBadge :type="row.disable_flag === 0 ? 'success' : 'info'" size="small" effect="plain">
              {{ row.disable_flag === 0 ? '正常' : '禁用' }}
            </StatusBadge>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </div>

    <!-- 绑定路线弹窗 -->
    <el-dialog v-model="bindDialogVisible" title="绑定工序路线" width="640px" destroy-on-close>
      <div class="bind-product-name">产品：{{ bindTarget?.name }}（{{ bindTarget?.product_no }}）</div>
      <ListPageStatus :paged="false" :error="activeRoutesResource.errorMessage.value" :loading="activeRoutesResource.loading.value" :has-data="activeRoutesResource.hasLoaded.value" @retry="loadActiveRoutes" />
      <el-form label-position="top">
        <el-form-item label="工序路线">
          <el-select v-model="bindRouteId" placeholder="选择路线" clearable style="width: 100%">
            <el-option v-for="r in activeRoutes" :key="r.id" :label="r.name" :value="r.id" />
            <el-option label="— 无（解绑）" :value="null" />
          </el-select>
        </el-form-item>
      </el-form>
      <!-- 路线预览 -->
      <ListPageStatus v-if="bindRouteId" :paged="false" :error="previewResource.errorMessage.value" :loading="previewResource.loading.value" :has-data="previewResource.hasLoaded.value" @retry="loadPreview" />
      <div v-if="previewSteps.length > 0" class="route-preview">
        <div class="preview-label">路线预览</div>
        <div class="preview-steps">
          <span v-for="(s, i) in previewSteps" :key="i">
            {{ s.process_name }}<template v-if="i < previewSteps.length - 1"> → </template>
          </span>
        </div>
      </div>
      <div class="bind-tip">
        ⚠ 修改路线后，新创建的该产品订单将按新路线初始化工序进度，已有进度不受影响
      </div>
      <template #footer>
        <el-button @click="bindDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="binding" @click="handleBind">确认绑定</el-button>
      </template>
    </el-dialog>

    <!-- 批量绑定弹窗 -->
    <el-dialog v-model="batchBindVisible" title="批量绑定路线" width="480px" destroy-on-close>
      <p>已选 {{ selectedProducts.length }} 个产品</p>
      <ListPageStatus :paged="false" :error="activeRoutesResource.errorMessage.value" :loading="activeRoutesResource.loading.value" :has-data="activeRoutesResource.hasLoaded.value" @retry="loadActiveRoutes" />
      <el-select v-model="batchRouteId" placeholder="选择路线" style="width: 100%; margin-top: 12px">
        <el-option v-for="r in activeRoutes" :key="r.id" :label="r.name" :value="r.id" />
      </el-select>
      <template #footer>
        <el-button @click="batchBindVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchBinding" @click="handleBatchBind">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { msgSuccessText, msgError, msgWarning } from '@/utils/feedback'
import { ref, computed, toRef, onMounted, watch } from 'vue'

import * as api from '@/api/production'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'

const listState = useListPage(async (params, { signal }) => {
  const response = await api.getProducts({ ...params, keyword: params.keyword || undefined, model: params.model || undefined, route_bound: params.route_bound || 'all' }, { signal, suppressToast: true })
  return { items: response.items || [], total: response.total || 0 }
}, { searchForm: { keyword: '', model: null, route_bound: null, show_disabled: false } })
const { loading, list: items, total, page, pageSize, searchForm, appliedSearchForm, hasPendingSearch, errorMessage, hasData, dataPage, fetchList, handleSearch: search, handleReset: resetFilters, handlePageChange, handleSizeChange, refreshCreate, refreshUpdate, refreshRemove } = listState
const loadData = refreshUpdate
const keyword = toRef(searchForm, 'keyword')
const filterModel = toRef(searchForm, 'model')
const filterRouteBound = toRef(searchForm, 'route_bound')
const showDisabled = toRef(searchForm, 'show_disabled')
const filterOptionsResource = useAsyncResource(async (_, { signal }) => api.getProductFilterOptions({ signal, suppressToast: true }), { initialData: { models: [], group_names: [] } })
const filterOptions = filterOptionsResource.data
// 列显隐元数据（TableTools 列面板数据源，模板列保持静态；多选列固定显示）
const columnDefs = [
  { key: 'product-no', label: '产品编号' },
  { key: 'name', label: '产品名称' },
  { key: 'model', label: '型号' },
  { key: 'process-route', label: '工序路线' },
  { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('product-manage', columnDefs)

const hasActiveFilters = computed(() => Boolean(appliedSearchForm.value.keyword) || Boolean(appliedSearchForm.value.model) || Boolean(appliedSearchForm.value.route_bound) || appliedSearchForm.value.show_disabled)




// 选择
const selectedProducts = ref([])

// 路线绑定
const bindDialogVisible = ref(false)
const bindTarget = ref(null)
const bindRouteId = ref(null)
const binding = ref(false)
const activeRoutesResource = useAsyncResource(async (_, { signal }) => (await api.getActiveRoutes({ signal, suppressToast: true })) || [], { initialData: [] })
const activeRoutes = activeRoutesResource.data
const previewResource = useAsyncResource(async (routeId, { signal }) => {
  const response = await api.getRouteSteps(routeId, { signal, suppressToast: true })
  return response.steps || []
}, { initialData: [] })
const previewSteps = previewResource.data
let bindScopeVersion = 0

// 批量绑定
const batchBindVisible = ref(false)
const batchRouteId = ref(null)
const batchBinding = ref(false)
let batchScopeVersion = 0

watch([bindRouteId, bindDialogVisible], () => {
  previewResource.clear()
  if (bindDialogVisible.value && bindRouteId.value) loadPreview()
}, { flush: 'sync' })
watch(bindDialogVisible, visible => { if (!visible) bindScopeVersion += 1 }, { flush: 'sync' })
watch(batchBindVisible, visible => { if (!visible) batchScopeVersion += 1 }, { flush: 'sync' })
function loadPreview() {
  if (!bindDialogVisible.value || !bindRouteId.value) return Promise.resolve(false)
  return previewResource.load(bindRouteId.value)
}

function onSelectionChange(rows) {
  selectedProducts.value = rows
}


const loadFilterOptions = () => filterOptionsResource.load()

const loadActiveRoutes = () => activeRoutesResource.load()

function openBindDialog(row) {
  bindScopeVersion += 1
  previewResource.clear()
  bindDialogVisible.value = false
  bindTarget.value = row
  bindRouteId.value = row.process_route?.route_id ?? null
  bindDialogVisible.value = true
}

async function handleBind() {
  if (!bindDialogVisible.value || !bindTarget.value || binding.value) return
  const productId = bindTarget.value.product_id, routeId = bindRouteId.value
  const scopeVersion = bindScopeVersion
  binding.value = true
  try {
    await api.bindProductRoute(productId, { route_id: routeId })
    msgSuccessText('绑定成功')
    if (bindScopeVersion === scopeVersion && bindTarget.value?.product_id === productId && bindRouteId.value === routeId) bindDialogVisible.value = false
    await loadData()
  } catch (e) {
    msgError(e.response?.data?.detail || '绑定失败', e)
  } finally {
    binding.value = false
  }
}

function openBatchBind() {
  batchScopeVersion += 1
  batchRouteId.value = null
  batchBindVisible.value = true
}

async function handleBatchBind() {
  if (!batchRouteId.value) { msgWarning('请选择路线'); return }
  if (!batchBindVisible.value || batchBinding.value) return
  const ids = selectedProducts.value.map(p => p.product_id), routeId = batchRouteId.value
  const scopeVersion = batchScopeVersion
  batchBinding.value = true
  try {
    const res = await api.batchBindRoute({ product_ids: ids, route_id: routeId })
    msgSuccessText(res.message || '批量绑定成功')
    if (batchScopeVersion === scopeVersion && batchRouteId.value === routeId
      && JSON.stringify(selectedProducts.value.map(p => p.product_id)) === JSON.stringify(ids)) batchBindVisible.value = false
    await loadData()
  } catch (e) {
    msgError(e.response?.data?.detail || '批量绑定失败', e)
  } finally {
    batchBinding.value = false
  }
}

onMounted(() => {
  loadFilterOptions()
  loadActiveRoutes()
})
</script>

<style scoped>
.product-manage { padding: 20px; position: relative; }

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.product-manage-aurora { inset: -24px -28px; }

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   el-dialog 默认就地渲染（append-to-body=false），通配会覆盖
   .el-overlay 的 position: fixed，弹窗打开后看不见。
   同时覆写全局 .table-card 白底为同款渐变玻璃 */
.product-manage .table-card {
  position: relative;
  z-index: 1;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 筛选区/操作行/分页均为全局规范类（app.css .table-card > …），本页不覆写 */

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.product-manage .table-card :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 全屏态：面板自身滚动（.table-card 默认 overflow:hidden） */
.product-manage .table-card:fullscreen { overflow: auto; }
.bind-product-name { font-weight: 500; margin-bottom: 16px; }
.route-preview { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.preview-label { font-size: 12px; color: #909399; margin-bottom: 8px; }
.preview-steps { font-size: 13px; line-height: 1.6; }
.bind-tip { margin-top: 12px; font-size: 12px; color: #e6a23c; }
</style>
