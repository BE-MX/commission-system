<template>
  <div class="concept-registry">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>数据治理 · 概念注册表</h2>
      <div class="header-actions">
        <el-button type="primary" :icon="Plus" @click="handleCreate"
          v-if="authStore.hasAnyPermission(['governance:write', 'governance:admin'])">
          新建概念
        </el-button>
        <el-button :icon="Download" @click="handleExport">导出</el-button>
        <el-button :icon="UploadFilled" @click="handleSeed"
          v-if="authStore.hasAnyPermission(['governance:admin'])">
          初始化种子数据
        </el-button>
      </div>
    </div>

    <!-- 进度看板 -->
    <div class="stats-cards" v-loading="statsLoading">
      <div class="stat-card stat-card--active">
        <div class="stat-value">{{ stats.active || 0 }}</div>
        <div class="stat-label">已完成概念</div>
        <div class="stat-pct">{{ activePct }}%</div>
      </div>
      <div class="stat-card stat-card--pending">
        <div class="stat-value">{{ stats.by_priority?.P1 || 0 }}</div>
        <div class="stat-label">待补充 P1</div>
        <div class="stat-sub">最高优先级</div>
      </div>
      <div class="stat-card stat-card--progress">
        <div class="stat-value">{{ stats.by_priority?.P2 || 0 }}</div>
        <div class="stat-label">待补充 P2</div>
      </div>
      <div class="stat-card stat-card--review">
        <div class="stat-value">{{ stats.by_priority?.P3 || 0 }}</div>
        <div class="stat-label">待补充 P3</div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="filters.layer" placeholder="层级" clearable style="width: 140px">
        <el-option label="财务" value="financial" />
        <el-option label="客户" value="customer" />
        <el-option label="产品" value="product" />
        <el-option label="生产" value="production" />
        <el-option label="销售过程" value="sales_process" />
        <el-option label="物流" value="logistics" />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" clearable style="width: 140px">
        <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-select v-model="filters.confidence" placeholder="置信度" clearable style="width: 120px">
        <el-option label="高" value="high" />
        <el-option label="中" value="medium" />
        <el-option label="低" value="low" />
      </el-select>
      <el-input v-model="filters.keyword" placeholder="搜索概念ID/名称" clearable :prefix-icon="Search"
        style="width: 220px" @keyup.enter="loadConcepts" />
      <el-button type="primary" :icon="Search" @click="loadConcepts">搜索</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <!-- 概念表格 -->
    <el-table :data="concepts" v-loading="loading" stripe @sort-change="handleSortChange"
      style="width: 100%">
      <el-table-column prop="id" label="概念 ID" min-width="160" sortable="custom" show-overflow-tooltip>
        <template #default="{ row }">
          <router-link :to="`/governance/concepts/${row.id}`" class="concept-link">
            {{ row.id }}
          </router-link>
        </template>
      </el-table-column>
      <el-table-column prop="name_zh" label="中文名" min-width="120" sortable="custom" />
      <el-table-column prop="name_en" label="英文名" min-width="160" show-overflow-tooltip />
      <el-table-column prop="layer" label="层级" width="110">
        <template #default="{ row }">{{ layerLabels[row.layer] || row.layer }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="120" sortable="custom">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small" effect="plain">
            {{ statusLabels[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="confidence" label="置信度" width="90">
        <template #default="{ row }">
          <span v-if="row.confidence">{{ confidenceLabels[row.confidence] }}</span>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="owner" label="负责人" width="100" />
      <el-table-column prop="updated_at" label="更新时间" width="170" sortable="custom">
        <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <router-link :to="`/governance/concepts/${row.id}`">
            <el-button type="primary" link size="small">查看</el-button>
          </router-link>
          <el-button v-if="row.status === 'pending' && authStore.hasAnyPermission(['governance:write'])"
            type="success" link size="small" @click="handleClaim(row)">
            认领
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize"
        :total="total" :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next" @change="loadConcepts" />
    </div>

    <!-- 新建概念对话框 -->
    <el-dialog v-model="createDialogVisible" title="新建概念" width="500px">
      <el-form :model="createForm" label-width="90px">
        <el-form-item label="概念 ID" required>
          <el-input v-model="createForm.id" placeholder="snake_case，如 sales_revenue" />
        </el-form-item>
        <el-form-item label="中文名" required>
          <el-input v-model="createForm.name_zh" />
        </el-form-item>
        <el-form-item label="英文名" required>
          <el-input v-model="createForm.name_en" />
        </el-form-item>
        <el-form-item label="所属层级" required>
          <el-select v-model="createForm.layer" style="width: 100%">
            <el-option label="财务" value="financial" />
            <el-option label="客户" value="customer" />
            <el-option label="产品" value="product" />
            <el-option label="生产" value="production" />
            <el-option label="销售过程" value="sales_process" />
            <el-option label="物流" value="logistics" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate" :loading="createLoading">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Download, UploadFilled, Search } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  listConcepts, createConcept, transitionStatus,
  getGovernanceStats, exportConcepts, seedGovernanceData,
} from '@/api/governance'

const router = useRouter()
const authStore = useAuthStore()

// ── 常量映射 ─────────────────────────────────────────────
const layerLabels = {
  financial: '财务', customer: '客户', product: '产品',
  production: '生产', sales_process: '销售过程', logistics: '物流',
}
const statusLabels = {
  draft: '草稿', pending: '待补充', in_progress: '填写中',
  review: '待审批', active: '已完成', deprecated: '已废弃',
}
const statusOptions = Object.entries(statusLabels).map(([v, l]) => ({ value: v, label: l }))
const confidenceLabels = { high: '高', medium: '中', low: '低' }

const statusTagType = (s) => ({
  draft: 'info', pending: 'warning', in_progress: '',
  review: 'warning', active: 'success', deprecated: 'danger',
}[s] || 'info')

// ── 状态 ─────────────────────────────────────────────────
const loading = ref(false)
const statsLoading = ref(false)
const concepts = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const sortField = ref('updated_at')
const sortOrder = ref('desc')
const stats = ref({})

const filters = reactive({
  layer: '', status: '', confidence: '', keyword: '',
})

const createDialogVisible = ref(false)
const createLoading = ref(false)
const createForm = reactive({
  id: '', name_zh: '', name_en: '', layer: 'financial',
})

// ── 计算属性 ─────────────────────────────────────────────
const activePct = computed(() => {
  if (!stats.value.total) return 0
  return ((stats.value.active / stats.value.total) * 100).toFixed(1)
})

// ── 加载数据 ─────────────────────────────────────────────
async function loadConcepts() {
  loading.value = true
  try {
    const { data: res } = await listConcepts({
      ...filters,
      page: page.value,
      page_size: pageSize.value,
      sort_field: sortField.value,
      sort_order: sortOrder.value,
    })
    const payload = res.data ?? res
    concepts.value = payload.items || []
    total.value = payload.total || 0
  } catch (e) {
    ElMessage.error('加载概念列表失败')
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  statsLoading.value = true
  try {
    const { data: res } = await getGovernanceStats()
    stats.value = res.data ?? res
  } catch (e) {
    console.error('加载统计失败', e)
  } finally {
    statsLoading.value = false
  }
}

// ── 事件处理 ─────────────────────────────────────────────
function handleSortChange({ prop, order }) {
  sortField.value = prop || 'updated_at'
  sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  loadConcepts()
}

function resetFilters() {
  filters.layer = ''
  filters.status = ''
  filters.confidence = ''
  filters.keyword = ''
  page.value = 1
  loadConcepts()
}

function handleCreate() {
  createForm.id = ''
  createForm.name_zh = ''
  createForm.name_en = ''
  createForm.layer = 'financial'
  createDialogVisible.value = true
}

async function submitCreate() {
  if (!createForm.id || !createForm.name_zh || !createForm.name_en || !createForm.layer) {
    ElMessage.warning('请填写必填字段')
    return
  }
  createLoading.value = true
  try {
    await createConcept({ ...createForm })
    ElMessage.success('概念创建成功')
    createDialogVisible.value = false
    loadConcepts()
    loadStats()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    createLoading.value = false
  }
}

async function handleClaim(row) {
  try {
    await transitionStatus(row.id, { action: 'claim' })
    ElMessage.success(`已认领「${row.name_zh}」`)
    loadConcepts()
    loadStats()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '认领失败')
  }
}

async function handleExport() {
  try {
    const { data: res } = await exportConcepts('json')
    const payload = res.data ?? res
    const blob = new Blob([payload.content], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `concepts_export_${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败')
  }
}

async function handleSeed() {
  try {
    await ElMessageBox.confirm('将导入 15 个已完成概念 + 9 个待补充概念 + 14 条关联关系（幂等操作）', '初始化种子数据')
    const { data: res } = await seedGovernanceData()
    const payload = res.data ?? res
    ElMessage.success(`导入完成：${payload.concepts_imported} 概念，${payload.relationships_imported} 关联`)
    loadConcepts()
    loadStats()
  } catch {
    // 取消
  }
}

function formatDate(dt) {
  if (!dt) return '-'
  return new Date(dt).toLocaleString('zh-CN', { hour12: false })
}

// ── 初始化 ───────────────────────────────────────────────
onMounted(() => {
  loadConcepts()
  loadStats()
})
</script>

<style scoped>
.concept-registry {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

.stat-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  border-left: 3px solid var(--el-color-primary);
}

.stat-card--active { border-left-color: var(--el-color-success); }
.stat-card--pending { border-left-color: var(--el-color-warning); }
.stat-card--progress { border-left-color: var(--el-color-primary); }
.stat-card--review { border-left-color: var(--el-color-info); }

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.stat-pct {
  font-size: 12px;
  color: var(--el-color-success);
  margin-top: 2px;
}

.stat-sub {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  margin-top: 2px;
}

.filter-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.concept-link {
  color: var(--el-color-primary);
  text-decoration: none;
}

.concept-link:hover {
  text-decoration: underline;
}

.text-muted {
  color: var(--el-text-color-placeholder);
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
