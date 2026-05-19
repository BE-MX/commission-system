<template>
  <div class="safety-config-page">
    <!-- 全局参数 -->
    <div class="global-params-card">
      <div class="params-header">
        <div style="display:flex;align-items:center;gap:12px;">
          <el-icon :size="20" color="#d4af6e"><Setting /></el-icon>
          <span style="font-size:17px;font-weight:600;color:#1e1e2d;">全局参数配置</span>
          <el-tag size="small" type="info" effect="plain">应用于所有 SKU</el-tag>
        </div>
        <div style="display:flex;gap:10px;">
          <el-button type="primary" :loading="aiLoading" @click="aiBatchGenerate" v-if="authStore.hasPermission('stock:write')">
            <el-icon style="margin-right:4px"><MagicStick /></el-icon> AI 批量生成
          </el-button>
          <el-button type="success" :loading="saveLoading" @click="saveAll" v-if="authStore.hasPermission('stock:write')">
            <el-icon style="margin-right:4px"><Check /></el-icon> 保存所有
          </el-button>
        </div>
      </div>
      <div class="params-row">
        <div class="param-item">
          <label class="param-label">备货周期</label>
          <el-input-number v-model="globalParams.lead_time_days" :min="7" :max="180" :step="1" controls-position="right" />
          <span class="param-unit">天</span>
          <el-tooltip content="从下单到货物入库的平均周期">
            <el-icon class="info-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
        <div class="param-divider" />
        <div class="param-item">
          <label class="param-label">安全系数</label>
          <el-input-number v-model="globalParams.safety_factor" :min="1" :max="5" :step="0.1" :precision="2" controls-position="right" />
          <span class="param-unit">倍</span>
          <el-tooltip content="安全系数越高，安全库存越保守">
            <el-icon class="info-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
        <div class="param-divider" />
        <div class="param-formula">
          <el-icon :size="16" color="#d4af6e"><InfoFilled /></el-icon>
          <span class="formula-text">
            公式：<code>safety_stock = avg_daily_sales × {{ globalParams.lead_time_days }} × {{ globalParams.safety_factor }}</code>
          </span>
        </div>
      </div>
    </div>

    <!-- AI 预览横幅 -->
    <div v-if="aiPreviewCount > 0" class="ai-preview-banner">
      <div class="banner-content">
        <el-icon :size="20" color="#d4af6e"><MagicStick /></el-icon>
        <span>AI 生成结果预览（{{ aiPreviewCount }} 条），来源：<el-tag size="small" type="warning">{{ aiSourceLabel }}</el-tag></span>
        <span class="banner-hint">点击下方「保存所有」确认写入</span>
      </div>
      <el-button size="small" @click="clearAiPreview">清除预览</el-button>
    </div>

    <!-- 数据表 -->
    <div class="card card-gold-border">
      <div class="table-toolbar">
        <div class="toolbar-left">
          <span class="toolbar-title">SKU 安全库存配置</span>
          <el-tag size="small" type="info">共 {{ pagination.total }} 条</el-tag>
        </div>
        <div class="toolbar-filters">
          <el-select v-model="filters.model" placeholder="型号" clearable filterable style="width:120px">
            <el-option v-for="m in filterOptions.models" :key="m" :label="m" :value="m" />
          </el-select>
          <el-select v-model="filters.product_type" placeholder="类型" clearable filterable style="width:120px">
            <el-option v-for="t in filterOptions.types" :key="t" :label="t" :value="t" />
          </el-select>
          <el-select v-model="filters.size" placeholder="尺寸" clearable filterable style="width:100px">
            <el-option v-for="s in filterOptions.sizes" :key="s" :label="s" :value="s" />
          </el-select>
          <el-select v-model="filters.color" placeholder="颜色" clearable filterable style="width:90px">
            <el-option v-for="c in filterOptions.colors" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select v-model="filters.weight" placeholder="克重" clearable filterable style="width:100px">
            <el-option v-for="w in filterOptions.weights" :key="w" :label="w" :value="w" />
          </el-select>
          <el-input v-model="filters.keyword" placeholder="搜索产品名或型号" :prefix-icon="Search" clearable style="width:180px" @input="handleSearch" />
          <el-button type="primary" size="small" @click="applyFilters"><el-icon><Filter /></el-icon>筛选</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
        </div>
      </div>
      <el-table :data="tableData" style="width:100%" :header-cell-style="headerStyle" v-loading="loading">
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column label="型号" prop="model" min-width="120" show-overflow-tooltip />
        <el-table-column label="类型" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).type }}</template>
        </el-table-column>
        <el-table-column label="尺寸" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).size }}</template>
        </el-table-column>
        <el-table-column label="颜色" min-width="90" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).color }}</template>
        </el-table-column>
        <el-table-column label="克重" min-width="90" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).weight }}</template>
        </el-table-column>
        <el-table-column label="近30日销量" width="110" align="center">
          <template #default="{ row }">
            <span class="sales-value">{{ row.sales_30d || 0 }}</span><span class="sales-unit">件</span>
          </template>
        </el-table-column>
        <el-table-column label="当前可用库存" width="120" align="center">
          <template #default="{ row }">
            <span :class="['stock-value', row.enable_count < (row.safety_stock||0) ? 'stock-low' : '']">
              {{ Math.round(row.enable_count || 0) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="安全库存阈值" width="160" align="center">
          <template #default="{ row }">
            <div class="editable-cell">
              <el-input-number v-model="row.safety_stock" :min="0" :max="10000" :step="1" controls-position="right" style="width:110px" @change="markDirty(row)" />
              <span class="source-badge" v-if="row.source">
                <el-tag size="small" :type="sourceTagType(row.source)">{{ sourceLabel(row.source) }}</el-tag>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="日均销量" width="100" align="center">
          <template #default="{ row }">
            <span class="avg-daily">{{ (row.avg_daily_sales_30d||0).toFixed(1) }}</span><span class="sales-unit">/天</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center" fixed="right" v-if="authStore.hasPermission('stock:write')">
          <template #default="{ row }">
            <el-button size="small" type="warning" plain @click="aiGenerateSingle(row)" :loading="row.aiLoading">AI</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-bar">
        <el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :total="pagination.total"
          :page-sizes="[20,50,100]" layout="total,sizes,prev,pager,next,jumper" @size-change="loadData" @current-change="loadData" />
      </div>
    </div>

    <!-- AI 建议弹窗 -->
    <el-dialog v-model="aiDialogVisible" title="AI 安全库存建议" width="480px" align-center>
      <div v-if="aiSuggestion" class="ai-dialog-content">
        <div class="ai-product-info">
          <div class="ai-product-name">{{ aiSuggestion.product_name }}</div>
          <div class="ai-product-model">{{ aiSuggestion.model }}</div>
        </div>
        <div class="ai-stats-grid">
          <div class="ai-stat-item">
            <div class="ai-stat-label">近30天日均销量</div>
            <div class="ai-stat-value">{{ aiSuggestion.avg_daily_sales?.toFixed(2) || '—' }}</div>
          </div>
          <div class="ai-stat-item">
            <div class="ai-stat-label">预测30天销量</div>
            <div class="ai-stat-value">{{ aiSuggestion.predicted_30d_sales }}</div>
          </div>
          <div class="ai-stat-item">
            <div class="ai-stat-label">建议安全库存</div>
            <div class="ai-stat-value highlight">{{ aiSuggestion.suggested_safety_stock }}</div>
          </div>
          <div class="ai-stat-item">
            <div class="ai-stat-label">当前安全库存</div>
            <div class="ai-stat-value">{{ aiSuggestion.current_safety_stock }}</div>
          </div>
        </div>
        <div class="ai-source-row">
          <el-tag :type="aiSuggestion.source === 'tft' ? 'success' : 'warning'" size="small">
            {{ aiSuggestion.source === 'tft' ? 'TFT 模型预测' : '公式估算' }}
          </el-tag>
          <span v-if="aiSuggestion.source === 'formula'" class="tft-fallback">TFT 未部署，已降级为公式计算</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="aiDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="applyAiSuggestion">应用建议</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Setting, MagicStick, Check, Search, Filter, RefreshRight, QuestionFilled, InfoFilled,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { getSafetyList, saveSafetyStock, autoGenerateSafety, getFilterOptions } from '@/api/stock'

const authStore = useAuthStore()

const loading = ref(false)
const saveLoading = ref(false)
const aiLoading = ref(false)
const tableData = ref([])
const pagination = reactive({ total: 0, page: 1, page_size: 20 })

const filters = reactive({
  keyword: '',
  model: '',
  product_type: '',
  size: '',
  color: '',
  weight: '',
})

function parseProductName(name) {
  if (!name) return { type: '', size: '', color: '', weight: '' }
  const parts = name.split('/')
  const n = parts.length
  const type = parts[0] || ''
  const size = parts[1] || ''
  const color = (n >= 5 && parts[n - 3].startsWith('#'))
    ? `${parts[n - 3]}/${parts[n - 2]}`
    : (parts[n - 2] || '')
  const weight = parts[n - 1] || ''
  return { type, size, color, weight }
}

const allFilterOptions = ref({ models: [], types: [], sizes: [], colors: [], weights: [] })

const filterOptions = computed(() => allFilterOptions.value)

const aiDialogVisible = ref(false)
const aiSuggestion = ref(null)
const currentAiRow = ref(null)

const globalParams = reactive({ lead_time_days: 30, safety_factor: 1.5 })

const aiPreviewCount = computed(() => tableData.value.filter(r => r._aiGenerated).length)
const aiSourceLabel = computed(() => {
  const hasFormula = tableData.value.some(r => r.source === 'formula')
  return hasFormula ? '公式估算' : '—'
})

const sourceLabel = (s) => ({ '': '未设置', manual: '手动', formula: '公式估算', tft: 'TFT预测' })[s] || s
const sourceTagType = (s) => ({ '': 'info', manual: 'primary', formula: 'warning', tft: 'success' })[s] || 'info'

function markDirty(row) {
  row._dirty = true
  row._aiGenerated = false
  row.source = 'manual'
}

function headerStyle() {
  return { background: 'linear-gradient(135deg,#faf8f3,#f0ece3)', fontWeight: 600, color: '#4a4a5a' }
}

async function loadData() {
  loading.value = true
  try {
    const res = await getSafetyList({
      page: pagination.page,
      page_size: pagination.page_size,
      keyword: filters.keyword || undefined,
      model: filters.model || undefined,
      product_type: filters.product_type || undefined,
      size: filters.size || undefined,
      color: filters.color || undefined,
      weight: filters.weight || undefined,
    })
    const d = res.data
    tableData.value = (d.items || []).map(i => ({ ...i, _dirty: false, _aiGenerated: false, aiLoading: false }))
    pagination.total = d.total || 0
  } finally {
    loading.value = false
  }
}

let searchTimer = null
function handleSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { pagination.page = 1; loadData() }, 400)
}

function applyFilters() {
  pagination.page = 1
  loadData()
}

function resetFilters() {
  filters.keyword = ''
  filters.model = ''
  filters.product_type = ''
  filters.size = ''
  filters.color = ''
  filters.weight = ''
  pagination.page = 1
  loadData()
}

async function aiGenerateSingle(row) {
  row.aiLoading = true
  try {
    const res = await autoGenerateSafety({
      product_ids: [row.product_id],
      lead_time_days: globalParams.lead_time_days,
      safety_factor: globalParams.safety_factor,
      history_days: 30,
    })
    const item = res.data?.items?.[0]
    if (!item) {
      ElMessage.warning('AI 建议生成失败')
      return
    }
    aiSuggestion.value = {
      ...item,
      current_safety_stock: row.safety_stock,
      source: item.source,
    }
    currentAiRow.value = row
    aiDialogVisible.value = true
  } finally {
    row.aiLoading = false
  }
}

function applyAiSuggestion() {
  if (!currentAiRow.value || !aiSuggestion.value) return
  if (aiSuggestion.value.suggested_safety_stock != null) {
    currentAiRow.value.safety_stock = aiSuggestion.value.suggested_safety_stock
    currentAiRow.value.source = aiSuggestion.value.source
    currentAiRow.value._dirty = true
    currentAiRow.value._aiGenerated = true
  } else {
    ElMessage.warning('建议值为空，未应用')
  }
  aiDialogVisible.value = false
}

async function aiBatchGenerate() {
  aiLoading.value = true
  try {
    const visibleIds = tableData.value.map(r => r.product_id)
    const res = await autoGenerateSafety({
      product_ids: visibleIds,
      lead_time_days: globalParams.lead_time_days,
      safety_factor: globalParams.safety_factor,
      history_days: 30,
    })
    const items = res.data?.items || []
    // 仅当前页可编辑; 把建议值回填到 visible rows
    const idToSuggestion = {}
    items.forEach(it => { idToSuggestion[it.product_id] = it })
    tableData.value = tableData.value.map(row => {
      const s = idToSuggestion[row.product_id]
      if (s && s.suggested_safety_stock != null) {
        return {
          ...row,
          safety_stock: s.suggested_safety_stock,
          source: s.source,
          _dirty: true,
          _aiGenerated: true,
        }
      }
      return row
    })
    ElMessage.success(`已批量生成 ${items.length} 条安全库存建议`)
  } finally {
    aiLoading.value = false
  }
}

function clearAiPreview() {
  tableData.value = tableData.value.map(r => ({ ...r, _aiGenerated: false }))
}

async function saveAll() {
  const dirtyItems = tableData.value.filter(r => r._dirty)
  if (!dirtyItems.length) {
    ElMessage.info('没有需要保存的更改')
    return
  }
  saveLoading.value = true
  try {
    const payload = {
      lead_time_days: globalParams.lead_time_days,
      safety_factor: globalParams.safety_factor,
      items: dirtyItems.map(r => ({
        product_id: r.product_id,
        safety_stock: r.safety_stock,
        updated_at: r.updated_at,
      })),
    }
    const res = await saveSafetyStock(payload)
    const saved = res.data?.saved_count || 0
    const failed = res.data?.failed_items || []
    if (failed.length) {
      ElMessage.warning(`保存 ${saved} 条，${failed.length} 条失败`)
      console.warn('保存失败项:', failed)
    } else {
      ElMessage.success(`成功保存 ${saved} 条安全库存配置`)
      // 清掉 dirty 标记，重新加载确认状态
      await loadData()
    }
  } catch (err) {
    // 乐观锁冲突 409 实际上后端返回 200 并带 failed_items
    ElMessage.error(err.message || '保存失败')
  } finally {
    saveLoading.value = false
  }
}

async function loadFilterOptions() {
  try {
    const res = await getFilterOptions()
    if (res.data) {
      allFilterOptions.value = {
        models: res.data.models || [],
        types: res.data.types || [],
        sizes: res.data.sizes || [],
        colors: res.data.colors || [],
        weights: res.data.weights || [],
      }
    }
  } catch (e) {
    console.warn('加载筛选选项失败:', e)
  }
}

onMounted(() => {
  loadData()
  loadFilterOptions()
})
</script>

<style scoped>
.safety-config-page { display: flex; flex-direction: column; gap: 20px; }

.global-params-card { background: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); border: 1px solid rgba(212,175,110,0.15); }
.params-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.params-row { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; padding: 16px; background: linear-gradient(135deg, #faf8f3, #f5f0e6); border-radius: 12px; }
.param-item { display: flex; align-items: center; gap: 10px; }
.param-label { font-size: 13px; font-weight: 500; color: #666; }
.param-unit { font-size: 13px; color: #888; }
.info-icon { color: #d4af6e; cursor: pointer; font-size: 16px; }
.param-divider { width: 1px; height: 36px; background: #e0d8c8; }
.param-formula { display: flex; align-items: center; gap: 8px; flex: 1; }
.formula-text { font-size: 13px; color: #666; }
.formula-text code { background: rgba(212,175,110,0.1); padding: 2px 8px; border-radius: 6px; color: #d4af6e; font-weight: 500; }

.ai-preview-banner { background: linear-gradient(135deg, #fff8e7, #fff3d6); border: 1px solid rgba(212,175,110,0.3); border-radius: 12px; padding: 14px 20px; display: flex; align-items: center; justify-content: space-between; }
.banner-content { display: flex; align-items: center; gap: 10px; font-size: 14px; color: #5a4a2a; }
.banner-hint { color: #d4af6e; font-size: 13px; font-style: italic; }

.card { background: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.card-gold-border { border: 1px solid rgba(212,175,110,0.15); }
.table-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.toolbar-left { display: flex; align-items: center; gap: 10px; }
.toolbar-title { font-size: 16px; font-weight: 600; color: #1e1e2d; }
.toolbar-filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sales-value { font-weight: 600; color: #1e1e2d; }
.sales-unit { font-size: 12px; color: #999; margin-left: 2px; }
.stock-value { font-weight: 600; font-size: 15px; }
.stock-low { color: #e74c3c; }
.editable-cell { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.source-badge { font-size: 11px; }
.avg-daily { font-weight: 500; color: #d4af6e; }
.pagination-bar { margin-top: 16px; display: flex; justify-content: flex-end; }

.ai-dialog-content { padding: 10px 0; }
.ai-product-info { text-align: center; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #eee; }
.ai-product-name { font-size: 18px; font-weight: 600; color: #1e1e2d; }
.ai-product-model { font-size: 14px; color: #999; margin-top: 4px; }
.ai-stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.ai-stat-item { background: #faf8f3; border-radius: 10px; padding: 14px; text-align: center; }
.ai-stat-label { font-size: 12px; color: #888; margin-bottom: 6px; }
.ai-stat-value { font-size: 20px; font-weight: 700; color: #1e1e2d; }
.ai-stat-value.highlight { color: #d4af6e; }
.ai-source-row { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 12px; background: #f5f5f5; border-radius: 8px; }
.tft-fallback { font-size: 12px; color: #999; }
</style>
