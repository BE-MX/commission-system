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
        <div style="display:flex;gap:10px;align-items:center;">
          <el-button type="primary" :loading="aiLoading" @click="aiBatchGenerate" v-if="authStore.hasPermission('stock:write')">
            <el-icon style="margin-right:4px"><MagicStick /></el-icon> AI 批量生成
          </el-button>
          <el-button type="success" :loading="saveLoading" @click="saveAll" v-if="authStore.hasPermission('stock:write')">
            <el-icon style="margin-right:4px"><Check /></el-icon> 保存所有
          </el-button>
          <!-- 购物车图标 -->
          <el-badge :value="cartCount" :hidden="cartCount === 0" class="cart-badge" v-if="authStore.hasPermission('production:write')">
            <el-button circle @click="cartDrawerVisible = true">
              <el-icon :size="18"><ShoppingCart /></el-icon>
            </el-button>
          </el-badge>
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
          <el-select v-model="filters.model" multiple placeholder="型号" clearable filterable style="width:140px">
            <el-option v-for="m in filterOptions.models" :key="m" :label="m" :value="m" />
          </el-select>
          <el-select v-model="filters.product_type" multiple placeholder="类型" clearable filterable style="width:140px">
            <el-option v-for="t in filterOptions.types" :key="t" :label="t" :value="t" />
          </el-select>
          <el-select v-model="filters.size" multiple placeholder="尺寸" clearable filterable style="width:120px">
            <el-option v-for="s in filterOptions.sizes" :key="s" :label="s" :value="s" />
          </el-select>
          <el-select v-model="filters.color" multiple placeholder="颜色" clearable filterable style="width:120px">
            <el-option v-for="c in filterOptions.colors" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select v-model="filters.weight" multiple placeholder="克重" clearable filterable style="width:120px">
            <el-option v-for="w in filterOptions.weights" :key="w" :label="w" :value="w" />
          </el-select>
          <el-input v-model="filters.keyword" placeholder="搜索产品名或型号" :prefix-icon="Search" clearable style="width:180px" @input="handleSearch" />
          <el-checkbox v-model="filters.has_in_transit" label="仅看在途" size="small" border @change="applyFilters" />
          <el-checkbox v-model="filters.has_safety_stock" label="仅看已设安全库存" size="small" border @change="applyFilters" />
          <el-select v-model="filters.stock_status" placeholder="备货状态" clearable style="width:120px" @change="applyFilters">
            <el-option label="全部状态" value="" />
            <el-option label="备货中" value="stocking" />
            <el-option label="加急中" value="urgent" />
          </el-select>
          <el-button type="primary" size="small" @click="applyFilters"><el-icon><Filter /></el-icon>筛选</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
        </div>
      </div>
      <el-table :data="tableData" style="width:100%" :header-cell-style="headerStyle" v-loading="loading" @sort-change="onSortChange">
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column label="型号" prop="model" min-width="100" show-overflow-tooltip sortable="custom" />
        <el-table-column label="类型" min-width="90" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).type }}</template>
        </el-table-column>
        <el-table-column label="尺寸" min-width="90" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).size }}</template>
        </el-table-column>
        <el-table-column label="颜色" min-width="80" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).color }}</template>
        </el-table-column>
        <el-table-column label="克重" min-width="80" show-overflow-tooltip>
          <template #default="{ row }">{{ parseProductName(row.product_name).weight }}</template>
        </el-table-column>
        <el-table-column label="近30日销量" prop="sales_30d" width="95" align="center" sortable="custom">
          <template #default="{ row }">
            <span class="sales-value">{{ row.sales_30d || 0 }}</span><span class="sales-unit">件</span>
          </template>
        </el-table-column>
        <el-table-column label="当前可用库存" prop="enable_count" width="105" align="center" sortable="custom">
          <template #default="{ row }">
            <span :class="['stock-value', row.enable_count < (row.safety_stock||0) ? 'stock-low' : '']">
              {{ Math.round(row.enable_count || 0) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="生产在途" width="85" align="center">
          <template #default="{ row }">
            <span :class="['in-transit-value', row.production_in_transit > 0 ? 'in-transit-active' : '']">
              {{ row.production_in_transit || 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="备货状态" width="90" align="center">
          <template #default="{ row }">
            <span
              v-if="row.stock_status"
              :class="['stock-status-label', row.stock_status === '加急中' ? 'stock-status-urgent' : 'stock-status-normal']"
              @click="openStockStatusDialog(row)"
              style="cursor:pointer"
            >
              {{ row.stock_status }}
            </span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="安全库存阈值" prop="safety_stock" width="140" align="center" sortable="custom">
          <template #default="{ row }">
            <div class="editable-cell">
              <el-input-number v-model="row.safety_stock" :min="0" :max="10000" :step="1" controls-position="right" style="width:100px" @change="markDirty(row)" />
              <span class="source-badge" v-if="row.source">
                <el-tag size="small" :type="sourceTagType(row.source)">{{ sourceLabel(row.source) }}</el-tag>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="日均销量" width="90" align="center">
          <template #default="{ row }">
            <span class="avg-daily">{{ (row.avg_daily_sales_30d||0).toFixed(1) }}</span><span class="sales-unit">/天</span>
          </template>
        </el-table-column>
        <el-table-column label="建议备货量" width="90" align="center">
          <template #default="{ row }">
            <span :class="row.suggested_qty > 0 ? 'value-danger' : 'text-muted'">
              {{ row.suggested_qty > 0 ? row.suggested_qty : '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <el-button size="small" type="warning" plain @click="aiGenerateSingle(row)" :loading="row.aiLoading" v-if="authStore.hasPermission('stock:write')">AI</el-button>
              <el-button size="small" type="primary" plain @click="openProductionDialog(row)" v-if="authStore.hasPermission('production:write')">
                <el-icon><Plus /></el-icon> 生产下单
              </el-button>
            </div>
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

    <!-- 生产下单弹窗 -->
    <el-dialog v-model="productionDialogVisible" title="生产下单" width="520px" align-center>
      <div v-if="currentProductionRow" class="production-dialog-content">
        <div class="prod-info-row">
          <span class="prod-label">产品名称</span>
          <span class="prod-value">{{ currentProductionRow.product_name }}</span>
        </div>
        <div class="prod-info-row">
          <span class="prod-label">型号</span>
          <span class="prod-value">{{ currentProductionRow.model }}</span>
        </div>
        <div class="prod-info-row">
          <span class="prod-label">近30日销量</span>
          <span class="prod-value">{{ currentProductionRow.sales_30d || 0 }} 件</span>
        </div>
        <div class="prod-info-row">
          <span class="prod-label">生产在途</span>
          <span class="prod-value" :class="currentProductionRow.production_in_transit > 0 ? 'in-transit-active' : ''">{{ currentProductionRow.production_in_transit || 0 }} 件</span>
        </div>
        <div class="prod-info-row">
          <span class="prod-label">当前库存</span>
          <span class="prod-value">{{ Math.round(currentProductionRow.enable_count || 0) }} 件</span>
        </div>
        <div class="prod-info-row">
          <span class="prod-label">安全库存</span>
          <span class="prod-value">{{ currentProductionRow.safety_stock || 0 }} 件</span>
        </div>
        <div class="prod-info-row">
          <span class="prod-label">差值</span>
          <span class="prod-value" :class="suggestedOrderQty > 0 ? 'value-danger' : ''">{{ suggestedOrderQty }}</span>
        </div>
        <el-divider />
        <el-form :model="productionForm" label-width="100px">
          <el-form-item label="生产下单数量" required class="order-qty-form-item">
            <el-input-number v-model="productionForm.order_qty" :min="1" :max="999999" :step="1" controls-position="right" style="width:160px" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="productionForm.remark" type="textarea" :rows="2" placeholder="可选" maxlength="500" show-word-limit />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="productionDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmAddToCart">确认加入购物车</el-button>
      </template>
    </el-dialog>

    <!-- 购物车抽屉 -->
    <el-drawer v-model="cartDrawerVisible" title="生产单购物车" size="580px">
      <div class="cart-drawer">
        <el-empty v-if="cartItems.length === 0" description="购物车为空" />
        <template v-else>
          <el-table :data="cartItems" @selection-change="toggleCartSelection" style="width:100%">
            <el-table-column type="selection" width="50" align="center" />
            <el-table-column label="产品名称" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                <div class="cart-product-name">{{ row.product_name }}</div>
                <div class="cart-product-model">{{ row.model }}</div>
              </template>
            </el-table-column>
            <el-table-column label="下单数量" width="110" align="center">
              <template #default="{ row }">
                <el-input-number v-model="row.order_qty" :min="1" :max="999999" :step="1" controls-position="right" size="small" style="width:90px" @change="handleCartQtyChange(row)" />
              </template>
            </el-table-column>
            <el-table-column label="备注" min-width="100" show-overflow-tooltip>
              <template #default="{ row }">
                <el-input v-model="row.remark" size="small" placeholder="备注" @blur="handleCartRemarkChange(row)" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="60" align="center">
              <template #default="{ row }">
                <el-button type="danger" link size="small" @click="removeCartItem(row.id)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="cart-footer">
            <div class="cart-selected-info">
              已选 {{ selectedCartIds.length }} 项，共 {{ selectedTotalQty }} 件
            </div>
            <div class="cart-actions">
              <el-button size="small" @click="batchDeleteCart">批量删除</el-button>
              <el-button type="primary" size="small" @click="openGenerateOrderDialog" :disabled="selectedCartIds.length === 0">
                生成生产订单
              </el-button>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 生成生产订单弹窗 -->
    <el-dialog v-model="generateOrderDialogVisible" title="生成生产订单" width="520px" align-center>
      <el-form :model="generateOrderForm" label-width="100px" :rules="orderRules" ref="orderFormRef">
        <el-form-item label="选中产品" v-if="selectedCartItems.length > 0">
          <div class="selected-products-preview">
            <el-tag v-for="item in selectedCartItems.slice(0, 5)" :key="item.id" size="small" style="margin:2px;">
              {{ item.product_name }} × {{ item.order_qty }}
            </el-tag>
            <el-tag v-if="selectedCartItems.length > 5" size="small" type="info">+{{ selectedCartItems.length - 5 }} 项</el-tag>
          </div>
        </el-form-item>
        <el-form-item label="生产批次号" prop="batch_no" required>
          <el-input v-model="generateOrderForm.batch_no" placeholder="请输入批次号" maxlength="64" />
        </el-form-item>
        <el-form-item label="是否加急">
          <el-switch v-model="generateOrderForm.is_urgent" active-text="加急" inactive-text="正常" />
        </el-form-item>
        <el-form-item label="预计交期">
          <el-date-picker v-model="generateOrderForm.expected_delivery_date" type="date" placeholder="选择预计交期" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="generateOrderForm.remark" type="textarea" :rows="2" placeholder="可选" maxlength="500" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="generateOrderDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmGenerateOrder" :loading="generatingOrder">提交</el-button>
      </template>
    </el-dialog>

    <!-- 备货状态明细弹窗 -->
    <el-dialog v-model="stockStatusDialogVisible" title="备货明细" width="600px" align-center>
      <div v-if="currentStockStatusRow" class="stock-status-dialog">
        <div class="stock-status-header">
          <span class="stock-status-product">{{ currentStockStatusRow.product_name }}</span>
          <el-tag :type="currentStockStatusRow.stock_status === '加急中' ? 'danger' : 'success'" size="small">
            {{ currentStockStatusRow.stock_status }}
          </el-tag>
        </div>
        <el-table :data="currentStockStatusRow.stock_items || []" size="small" style="width:100%" v-if="(currentStockStatusRow.stock_items || []).length > 0">
          <el-table-column label="生产单号" prop="order_no" min-width="120" />
          <el-table-column label="批次号" prop="batch_no" min-width="100" />
          <el-table-column label="下单量" width="80" align="center" prop="order_qty" />
          <el-table-column label="已入库" width="80" align="center" prop="received_qty" />
          <el-table-column label="在途" width="70" align="center" prop="in_transit_qty" />
          <el-table-column label="加急" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_urgent" type="danger" size="small">加急</el-tag>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="预计交期" width="110" align="center">
            <template #default="{ row }">{{ row.expected_delivery_date || '—' }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无备货明细" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Setting, MagicStick, Check, Search, Filter, RefreshRight, QuestionFilled, InfoFilled,
  ShoppingCart, Plus, Delete,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  getSafetyList, saveSafetyStock, autoGenerateSafety, getFilterOptions,
} from '@/api/stock'
import { useProductionCart } from './composables/useProductionCart'
import { useTableSort } from '@/composables/useTableSort'

const authStore = useAuthStore()
const { sortParams, onSortChange, reset: resetSort } = useTableSort('product_id', 'asc')

// ── 原有安全库存逻辑 ──────────────────────────
const loading = ref(false)
const saveLoading = ref(false)
const aiLoading = ref(false)
const tableData = ref([])
const pagination = reactive({ total: 0, page: 1, page_size: 20 })

const filters = reactive({
  keyword: '',
  model: [],
  product_type: [],
  size: [],
  color: [],
  weight: [],
  has_in_transit: false,
  has_safety_stock: false,
  stock_status: '',
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
      model: filters.model.length ? filters.model.join(',') : undefined,
      product_type: filters.product_type.length ? filters.product_type.join(',') : undefined,
      size: filters.size.length ? filters.size.join(',') : undefined,
      color: filters.color.length ? filters.color.join(',') : undefined,
      weight: filters.weight.length ? filters.weight.join(',') : undefined,
      sort: sortParams.value.sort_field || 'product_id',
      order: sortParams.value.sort_order || 'asc',
      has_in_transit: filters.has_in_transit || undefined,
      has_safety_stock: filters.has_safety_stock || undefined,
      stock_status: filters.stock_status || undefined,
    })
    const d = res.data
    // 后端已返回 stock_status / stock_items / production_in_transit，无需二次请求
    tableData.value = (d.items || []).map(i => {
      const effectiveStock = (i.safety_stock || 0) * 2
      const effectiveCount = (i.enable_count || 0) + (i.production_in_transit || 0)
      return {
        ...i,
        _dirty: false,
        _aiGenerated: false,
        aiLoading: false,
        stock_status: i.stock_status || '',
        stock_items: i.stock_items || [],
        suggested_qty: Math.max(0, effectiveStock - effectiveCount),
      }
    })
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
  filters.model = []
  filters.product_type = []
  filters.size = []
  filters.color = []
  filters.weight = []
  filters.has_in_transit = false
  filters.has_safety_stock = false
  filters.stock_status = ''
  resetSort()
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
      await loadData()
    }
  } catch (err) {
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

// ── 生产下单逻辑 ──────────────────────────────
const {
  cartItems, cartCount, cartLoading, selectedCartIds,
  loadCart, addToCart, updateCartItem, removeCartItem,
  batchRemoveCartItems, generateOrder, toggleSelection,
} = useProductionCart()

const cartDrawerVisible = ref(false)

const productionDialogVisible = ref(false)
const currentProductionRow = ref(null)
const productionForm = reactive({ order_qty: 0, remark: '' })

const suggestedOrderQty = computed(() => {
  if (!currentProductionRow.value) return 0
  const safety = (currentProductionRow.value.safety_stock || 0) * 2
  const enable = currentProductionRow.value.enable_count || 0
  const inTransit = currentProductionRow.value.production_in_transit || 0
  return Math.max(0, safety - enable - inTransit)
})

function openProductionDialog(row) {
  currentProductionRow.value = row
  productionForm.order_qty = suggestedOrderQty.value > 0 ? suggestedOrderQty.value : 1
  productionForm.remark = ''
  productionDialogVisible.value = true
}

async function confirmAddToCart() {
  if (!currentProductionRow.value) return
  if (productionForm.order_qty <= 0) {
    ElMessage.warning('生产下单数量必须大于0')
    return
  }
  const parts = parseProductName(currentProductionRow.value.product_name)
  const spec = `${parts.type}/${parts.size}/${parts.color}/${parts.weight}`
  const ok = await addToCart({
    product_id: currentProductionRow.value.product_id,
    product_name: currentProductionRow.value.product_name,
    model: currentProductionRow.value.model,
    spec_info: spec,
    order_qty: productionForm.order_qty,
    remark: productionForm.remark,
  })
  if (ok) {
    productionDialogVisible.value = false
  }
}

// ── 购物车 drawer ─────────────────────────────
const selectedCartItems = computed(() =>
  cartItems.value.filter(item => selectedCartIds.value.includes(item.id))
)
const selectedTotalQty = computed(() =>
  selectedCartItems.value.reduce((sum, item) => sum + (item.order_qty || 0), 0)
)

function toggleCartSelection(selection) {
  toggleSelection(selection)
}

let cartQtyTimer = null
function handleCartQtyChange(row) {
  if (cartQtyTimer) clearTimeout(cartQtyTimer)
  cartQtyTimer = setTimeout(() => {
    updateCartItem(row.id, { order_qty: row.order_qty, remark: row.remark })
  }, 500)
}

let cartRemarkTimer = null
function handleCartRemarkChange(row) {
  if (cartRemarkTimer) clearTimeout(cartRemarkTimer)
  cartRemarkTimer = setTimeout(() => {
    updateCartItem(row.id, { order_qty: row.order_qty, remark: row.remark })
  }, 500)
}

async function batchDeleteCart() {
  if (selectedCartIds.value.length === 0) {
    ElMessage.warning('请先选择要删除的产品')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selectedCartIds.value.length} 项?`, '提示', { type: 'warning' })
    await batchRemoveCartItems(selectedCartIds.value)
  } catch {
    // cancel
  }
}

// ── 生成生产订单弹窗 ──────────────────────────
const generateOrderDialogVisible = ref(false)
const generateOrderForm = reactive({ batch_no: '', remark: '', is_urgent: false, expected_delivery_date: '' })
const generatingOrder = ref(false)
const orderFormRef = ref(null)

const orderRules = {
  batch_no: [{ required: true, message: '请输入批次号', trigger: 'blur' }],
}

function openGenerateOrderDialog() {
  if (selectedCartIds.value.length === 0) {
    ElMessage.warning('请先选择产品')
    return
  }
  generateOrderForm.batch_no = ''
  generateOrderForm.remark = ''
  generateOrderForm.is_urgent = false
  generateOrderForm.expected_delivery_date = ''
  generateOrderDialogVisible.value = true
}

async function confirmGenerateOrder() {
  if (!orderFormRef.value) return
  await orderFormRef.value.validate(async (valid) => {
    if (!valid) return
    generatingOrder.value = true
    try {
      const ok = await generateOrder({
        batch_no: generateOrderForm.batch_no,
        remark: generateOrderForm.remark,
        is_urgent: generateOrderForm.is_urgent,
        expected_delivery_date: generateOrderForm.expected_delivery_date || undefined,
      })
      if (ok) {
        generateOrderDialogVisible.value = false
      }
    } finally {
      generatingOrder.value = false
    }
  })
}

// ── 备货状态弹窗 ──────────────────────────
const stockStatusDialogVisible = ref(false)
const currentStockStatusRow = ref(null)

function openStockStatusDialog(row) {
  if (!row.stock_status) return
  currentStockStatusRow.value = row
  stockStatusDialogVisible.value = true
}

// 页面加载时同步购物车
onMounted(() => {
  loadCart()
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
.in-transit-value { font-weight: 500; font-size: 14px; color: #888; }
.in-transit-active { color: #27ae60; font-weight: 600; }

.stock-status-label { font-size: 13px; }
.stock-status-normal { color: #27ae60; }
.stock-status-urgent { color: #e74c3c; font-weight: 700; }

.stock-status-dialog { padding: 10px 0; }
.stock-status-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #eee; }
.stock-status-product { font-weight: 600; font-size: 15px; color: #1e1e2d; }
.editable-cell { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.source-badge { font-size: 11px; }
.avg-daily { font-weight: 500; color: #d4af6e; }
.pagination-bar { margin-top: 16px; display: flex; justify-content: flex-end; }

.action-btns { display: flex; gap: 4px; justify-content: center; }

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

/* 生产下单弹窗 */
.production-dialog-content { padding: 10px 0; }
.prod-info-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.prod-info-row:last-child { border-bottom: none; }
.prod-label { color: #888; font-size: 13px; white-space: nowrap; flex-shrink: 0; margin-right: 16px; }
.prod-value { font-weight: 500; color: #1e1e2d; font-size: 14px; text-align: right; }
.value-danger { color: #e74c3c; font-weight: 600; }
.order-qty-form-item :deep(.el-form-item__label) { white-space: nowrap; }

/* 购物车 */
.cart-badge :deep(.el-badge__content) { background: #e74c3c; }
.cart-drawer { display: flex; flex-direction: column; height: 100%; }
.cart-product-name { font-weight: 500; color: #1e1e2d; font-size: 13px; }
.cart-product-model { color: #999; font-size: 12px; }
.cart-footer { margin-top: 16px; padding-top: 16px; border-top: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }
.cart-selected-info { font-size: 13px; color: #666; }
.cart-actions { display: flex; gap: 10px; }
.selected-products-preview { display: flex; flex-wrap: wrap; gap: 4px; }
</style>
