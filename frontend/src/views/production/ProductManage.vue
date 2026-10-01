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
      <div class="toolbar">
        <el-input v-model="keyword" placeholder="产品名称/编号" clearable class="filter-w-md" @keyup.enter="search" @clear="search" />
        <el-select v-model="filterModel" placeholder="型号" clearable class="filter-w-sm" @change="search">
          <el-option v-for="m in filterOptions.models" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select v-model="filterRouteBound" placeholder="路线绑定" clearable class="filter-w-sm" @change="search">
          <el-option label="已绑定" value="bound" />
          <el-option label="未绑定" value="unbound" />
        </el-select>
        <el-checkbox v-model="showDisabled" @change="search">显示已禁用</el-checkbox>
        <GlassButton variant="primary" left-icon="Search" @click="search">查询</GlassButton>
        <GlassButton left-icon="RefreshLeft" @click="resetFilters">重置</GlassButton>
      </div>

      <!-- 操作行：批量操作 + TableTools 四图标 -->
      <div class="action-bar">
        <template v-if="selectedProducts.length > 0">
          <el-tag>已选 {{ selectedProducts.length }} 项</el-tag>
          <GlassButton v-permission="'production:write'" variant="primary" @click="openBatchBind">批量绑定路线</GlassButton>
        </template>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="loadData"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <el-table :data="items" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" @selection-change="onSelectionChange">
        <template #empty>
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
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
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="80" max-width="120">
          <template #default="{ row }">
            <el-tag :type="row.disable_flag === 0 ? 'success' : 'info'" size="small" effect="plain">
              {{ row.disable_flag === 0 ? '正常' : '禁用' }}
            </el-tag>
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
        @current-change="loadData"
      />
    </div>

    <!-- 绑定路线弹窗 -->
    <el-dialog v-model="bindDialogVisible" title="绑定工序路线" width="520" destroy-on-close>
      <div class="bind-product-name">产品：{{ bindTarget?.name }}（{{ bindTarget?.product_no }}）</div>
      <el-form label-width="80px">
        <el-form-item label="工序路线">
          <el-select v-model="bindRouteId" placeholder="选择路线" clearable style="width: 100%">
            <el-option v-for="r in activeRoutes" :key="r.id" :label="r.name" :value="r.id" />
            <el-option label="— 无（解绑）" :value="null" />
          </el-select>
        </el-form-item>
      </el-form>
      <!-- 路线预览 -->
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
    <el-dialog v-model="batchBindVisible" title="批量绑定路线" width="480" destroy-on-close>
      <p>已选 {{ selectedProducts.length }} 个产品</p>
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
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/production'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const filterModel = ref(null)
const filterRouteBound = ref(null)
const showDisabled = ref(false)
const filterOptions = ref({ models: [], group_names: [] })

// 列显隐元数据（TableTools 列面板数据源，模板列保持静态；多选列固定显示）
const columnDefs = [
  { key: 'product-no', label: '产品编号' },
  { key: 'name', label: '产品名称' },
  { key: 'model', label: '型号' },
  { key: 'process-route', label: '工序路线' },
  { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('product-manage', columnDefs)

const hasActiveFilters = computed(() => Boolean(keyword.value) || Boolean(filterModel.value) || Boolean(filterRouteBound.value) || showDisabled.value)

function search() {
  page.value = 1
  loadData()
}

function resetFilters() {
  keyword.value = ''
  filterModel.value = null
  filterRouteBound.value = null
  showDisabled.value = false
  search()
}

function handleSizeChange() {
  page.value = 1
  loadData()
}

// 选择
const selectedProducts = ref([])

// 路线绑定
const bindDialogVisible = ref(false)
const bindTarget = ref(null)
const bindRouteId = ref(null)
const binding = ref(false)
const activeRoutes = ref([])
const previewSteps = ref([])

// 批量绑定
const batchBindVisible = ref(false)
const batchRouteId = ref(null)
const batchBinding = ref(false)

watch(bindRouteId, async (val) => {
  if (val) {
    const res = await api.getRouteSteps(val)
    previewSteps.value = res.steps || []
  } else {
    previewSteps.value = []
  }
})

function onSelectionChange(rows) {
  selectedProducts.value = rows
}

async function loadData() {
  loading.value = true
  try {
    const res = await api.getProducts({
      page: page.value, page_size: pageSize.value,
      keyword: keyword.value || undefined,
      model: filterModel.value || undefined,
      route_bound: filterRouteBound.value || 'all',
      show_disabled: showDisabled.value,
    })
    items.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function loadFilterOptions() {
  const res = await api.getProductFilterOptions()
  filterOptions.value = res
}

async function loadActiveRoutes() {
  const res = await api.getActiveRoutes()
  activeRoutes.value = res || []
}

function openBindDialog(row) {
  bindTarget.value = row
  bindRouteId.value = row.process_route?.route_id ?? null
  bindDialogVisible.value = true
}

async function handleBind() {
  binding.value = true
  try {
    await api.bindProductRoute(bindTarget.value.product_id, { route_id: bindRouteId.value })
    ElMessage.success('绑定成功')
    bindDialogVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '绑定失败')
  } finally {
    binding.value = false
  }
}

function openBatchBind() {
  batchRouteId.value = null
  batchBindVisible.value = true
}

async function handleBatchBind() {
  if (!batchRouteId.value) { ElMessage.warning('请选择路线'); return }
  batchBinding.value = true
  try {
    const ids = selectedProducts.value.map(p => p.product_id)
    const res = await api.batchBindRoute({ product_ids: ids, route_id: batchRouteId.value })
    ElMessage.success(res.message || '批量绑定成功')
    batchBindVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '批量绑定失败')
  } finally {
    batchBinding.value = false
  }
}

onMounted(() => {
  loadData()
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
