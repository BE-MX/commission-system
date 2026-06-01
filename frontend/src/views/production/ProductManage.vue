<template>
  <div class="product-manage">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-input v-model="keyword" placeholder="产品名称/编号" clearable style="width: 200px" @keyup.enter="loadData" @clear="loadData" />
        <el-select v-model="filterModel" placeholder="型号" clearable style="width: 120px" @change="loadData">
          <el-option v-for="m in filterOptions.models" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select v-model="filterRouteBound" placeholder="路线绑定" clearable style="width: 130px" @change="loadData">
          <el-option label="已绑定" value="bound" />
          <el-option label="未绑定" value="unbound" />
        </el-select>
        <el-button type="primary" @click="loadData">搜索</el-button>
        <el-checkbox v-model="showDisabled" @change="loadData">显示已禁用</el-checkbox>
      </div>
      <div class="toolbar-right">
        <template v-if="selectedProducts.length > 0">
          <el-tag>已选 {{ selectedProducts.length }} 项</el-tag>
          <el-button type="primary" size="small" @click="openBatchBind">批量绑定路线</el-button>
        </template>
      </div>
    </div>

    <!-- 表格 -->
    <el-table :data="items" v-loading="loading" stripe @selection-change="onSelectionChange">
      <el-table-column type="selection" width="40" />
      <el-table-column prop="product_no" label="产品编号" width="120" />
      <el-table-column prop="name" label="产品名称" min-width="200" show-overflow-tooltip />
      <el-table-column prop="model" label="型号" width="80" />
      <el-table-column label="工序路线" width="180">
        <template #default="{ row }">
          <template v-if="row.process_route">
            <span>{{ row.process_route.route_name }}</span>
            <el-button link type="primary" size="small" @click="openBindDialog(row)">✏</el-button>
          </template>
          <template v-else>
            <span style="color: #909399">—</span>
            <el-button link type="primary" size="small" @click="openBindDialog(row)">绑定</el-button>
          </template>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="70">
        <template #default="{ row }">
          <el-tag :type="row.disable_flag === 0 ? 'success' : 'info'" size="small">
            {{ row.disable_flag === 0 ? '正常' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-wrap">
      <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="loadData" />
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
.product-manage { padding: 20px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.toolbar-left { display: flex; gap: 10px; align-items: center; }
.toolbar-right { display: flex; gap: 8px; align-items: center; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
.bind-product-name { font-weight: 500; margin-bottom: 16px; }
.route-preview { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.preview-label { font-size: 12px; color: #909399; margin-bottom: 8px; }
.preview-steps { font-size: 13px; line-height: 1.6; }
.bind-tip { margin-top: 12px; font-size: 12px; color: #e6a23c; }
</style>
