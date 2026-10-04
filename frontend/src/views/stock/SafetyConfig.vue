<template>
  <div class="safety-config-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="safety-config-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 全局参数 -->
    <div class="global-params-card lg-card">
      <div class="params-header">
        <div style="display:flex;align-items:center;gap:12px;">
          <el-icon :size="20" color="#d4af6e"><Setting /></el-icon>
          <span style="font-size:17px;font-weight:600;color:#1e1e2d;">全局参数配置</span>
          <StatusBadge size="small" type="info" effect="plain">应用于所有 SKU</StatusBadge>
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
        <span>AI 生成结果预览（{{ aiPreviewCount }} 条），来源：<StatusBadge size="small" type="warning">{{ aiSourceLabel }}</StatusBadge></span>
        <span class="banner-hint">点击下方「保存所有」确认写入</span>
      </div>
      <el-button @click="clearAiPreview">清除预览</el-button>
    </div>

    <!-- 数据表：筛选区 + 操作行 + 表格 + 分页（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card safety-panel">
      <ListPageStatus v-if="optionsResource.error.value" :error="optionsResource.errorMessage.value" :loading="optionsResource.loading.value" :has-data="!!optionsResource.data.value" @retry="loadFilterOptions" />
      <FilterBar :pending="listState.hasPendingSearch.value" @search="applyFilters" @reset="resetFilters">
        <span class="toolbar-title">SKU 安全库存配置</span>
        <StatusBadge size="small" type="info">共 {{ pagination.total }} 条</StatusBadge>
        <el-select v-model="filters.model" multiple placeholder="型号" clearable filterable class="filter-w-sm">
          <el-option v-for="m in filterOptions.models" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select v-model="filters.product_type" multiple placeholder="类型" clearable filterable class="filter-w-sm">
          <el-option v-for="t in filterOptions.types" :key="t" :label="t" :value="t" />
        </el-select>
        <el-input v-model="filters.keyword" placeholder="搜索产品名或型号" :prefix-icon="Search" clearable class="filter-w-md" />
        <el-select v-model="filters.stock_status" placeholder="备货状态" clearable class="filter-w-sm">
          <el-option label="全部状态" value="" />
          <el-option label="备货中" value="stocking" />
          <el-option label="加急中" value="urgent" />
        </el-select>
        <template #advanced>
        <el-select v-model="filters.size" multiple placeholder="尺寸" clearable filterable class="filter-w-sm">
          <el-option v-for="s in filterOptions.sizes" :key="s" :label="s" :value="s" />
        </el-select>
        <el-select v-model="filters.color" multiple placeholder="颜色" clearable filterable class="filter-w-sm">
          <el-option v-for="c in filterOptions.colors" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="filters.weight" multiple placeholder="克重" clearable filterable class="filter-w-sm">
          <el-option v-for="w in filterOptions.weights" :key="w" :label="w" :value="w" />
        </el-select>
        <el-checkbox v-model="filters.has_in_transit" label="仅看在途" border />
        <el-checkbox v-model="filters.has_safety_stock" label="仅看已设安全库存" border />
        </template>
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-if="authStore.hasPermission('stock:write')" variant="primary" :left-icon="MagicStick" :loading="aiLoading" @click="aiBatchGenerate">AI 批量生成</GlassButton>
        <GlassButton v-if="authStore.hasPermission('stock:write')" variant="secondary" :left-icon="Check" :loading="saveLoading" @click="saveAll">保存所有</GlassButton>
        <el-badge v-if="authStore.hasPermission('production:write')" :value="cartCount" :hidden="cartCount === 0" class="cart-badge">
          <GlassButton variant="secondary" :left-icon="ShoppingCart" @click="cartDrawerVisible = true">购物车</GlassButton>
        </el-badge>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="loadData"
          @fullscreen="toggleFullscreen"
        />
      </div>
      <ListPageStatus v-if="listState.hasData.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="loadData" />
      <el-table :data="tableData" style="width:100%" :header-cell-style="headerStyle" v-loading="loading" @sort-change="handleSortChange" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty>
          <ListPageStatus :error="listState.errorMessage.value" :loading="loading" @retry="loadData" />
          <el-empty v-if="listState.isEmpty.value" :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshRight" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column type="index" label="#" min-width="50" />
        <el-table-column v-if="visibleKeys.includes('model')" label="型号" prop="model" min-width="100" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('type')" label="类型" min-width="90" show-overflow-tooltip prop="type" sortable="custom">
          <template #default="{ row }">{{ parseProductName(row.product_name).type }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('size')" label="尺寸" min-width="90" show-overflow-tooltip prop="size" sortable="custom">
          <template #default="{ row }">{{ parseProductName(row.product_name).size }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('color')" label="颜色" prop="color" min-width="80" show-overflow-tooltip sortable="custom">
          <template #default="{ row }">{{ parseProductName(row.product_name).color }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('weight')" label="克重" min-width="80" show-overflow-tooltip prop="weight" sortable="custom">
          <template #default="{ row }">{{ parseProductName(row.product_name).weight }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('sales-30d')" label="近30日销量" prop="sales_30d" min-width="95" sortable="custom">
          <template #default="{ row }">
            <span class="sales-value">{{ row.sales_30d || 0 }}</span><span class="sales-unit">件</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('enable-count')" label="当前可用库存" prop="enable_count" min-width="105" sortable="custom">
          <template #default="{ row }">
            <span :class="['stock-value', row.enable_count < (row.safety_stock||0) ? 'stock-low' : '']">
              {{ Math.round(row.enable_count || 0) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('production-in-transit')" label="生产在途" min-width="85" prop="production_in_transit" sortable="custom">
          <template #default="{ row }">
            <span :class="['in-transit-value', row.production_in_transit > 0 ? 'in-transit-active' : '']">
              {{ row.production_in_transit || 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('stock-status')" label="备货状态" min-width="90" prop="stock_status" sortable="custom">
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
        <el-table-column v-if="visibleKeys.includes('safety-stock')" label="安全库存阈值" prop="safety_stock" min-width="140" sortable="custom">
          <template #default="{ row }">
            <div class="editable-cell">
              <el-input-number v-model="row.safety_stock" :min="0" :max="10000" :step="1" controls-position="right" style="width:100px" @change="markDirty(row)" />
              <span class="source-badge" v-if="row.source">
                <StatusBadge size="small" :type="sourceTagType(row.source)">{{ sourceLabel(row.source) }}</StatusBadge>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('avg-daily-sales')" label="日均销量" min-width="90" prop="avg_daily_sales_30d" sortable="custom">
          <template #default="{ row }">
            <span class="avg-daily">{{ (row.avg_daily_sales_30d||0).toFixed(1) }}</span><span class="sales-unit">/天</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('suggested-qty')" label="建议备货量" min-width="90" prop="suggested_qty" sortable="custom">
          <template #default="{ row }">
            <span :class="row.suggested_qty > 0 ? 'value-danger' : 'text-muted'">
              {{ row.suggested_qty > 0 ? row.suggested_qty : '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="160" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button link type="warning" @click="aiGenerateSingle(row)" :loading="row.aiLoading" v-if="authStore.hasPermission('stock:write')"><el-icon><MagicStick /></el-icon>AI</el-button>
              <el-button link type="primary" @click="openProductionDialog(row)" v-if="authStore.hasPermission('production:write')">
                <el-icon><Plus /></el-icon> 生产下单
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :total="pagination.total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager"
        @size-change="handleSizeChange" @current-change="loadData" />
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
          <StatusBadge :type="aiSuggestion.source === 'tft' ? 'success' : 'warning'" size="small">
            {{ aiSuggestion.source === 'tft' ? 'TFT 模型预测' : '公式估算' }}
          </StatusBadge>
          <span v-if="aiSuggestion.source === 'formula'" class="tft-fallback">TFT 未部署，已降级为公式计算</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="aiDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="applyAiSuggestion">应用建议</el-button>
      </template>
    </el-dialog>

    <ProductionOrderDialog
      v-model="productionDialogVisible"
      :row="currentProductionRow"
      :add-to-cart="addToCart"
    />

    <!-- 购物车抽屉 -->
    <DetailDrawer v-model="cartDrawerVisible" title="生产单购物车" width="640px">
      <div class="cart-drawer">
        <ListPageStatus :error="cartErrorMessage" :loading="cartLoading" :has-data="cartItems.length > 0" @retry="loadCart" />
        <el-empty v-if="cartItems.length === 0" description="购物车为空" />
        <template v-else>
          <el-table :data="cartItems" @selection-change="toggleCartSelection" style="width:100%" border class="list-table" v-sticky-scrollbar>
            <el-table-column type="selection" min-width="50" />
            <el-table-column :sort-by="row => row.product_name || row.model" label="产品名称" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                <div class="cart-product-name">{{ row.product_name }}</div>
                <div class="cart-product-model">{{ row.model }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="order_qty" label="下单数量" min-width="110">
              <template #default="{ row }">
                <el-input-number v-model="row.order_qty" :min="1" :max="999999" :step="1" controls-position="right" size="small" style="width:90px" @change="handleCartQtyChange(row)" />
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="备注" min-width="100" show-overflow-tooltip>
              <template #default="{ row }">
                <el-input v-model="row.remark" size="small" placeholder="备注" @blur="handleCartRemarkChange(row)" />
              </template>
            </el-table-column>
            <el-table-column class-name="table-action-column" label="操作" min-width="60">
              <template #default="{ row }">
                <el-button type="danger" link @click="removeCartItem(row.id)">
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
              <el-button @click="batchDeleteCart">批量删除</el-button>
              <el-button type="primary" @click="openGenerateOrderDialog" :disabled="selectedCartIds.length === 0">
                生成生产订单
              </el-button>
            </div>
          </div>
        </template>
      </div>
    </DetailDrawer>

    <!-- 生成生产订单弹窗 -->
    <el-dialog v-model="generateOrderDialogVisible" title="生成生产订单" width="640px" align-center>
      <el-form label-position="top" :model="generateOrderForm" :rules="orderRules" ref="orderFormRef">
        <el-form-item label="选中产品" v-if="selectedCartItems.length > 0">
          <div class="selected-products-preview">
            <StatusBadge v-for="item in selectedCartItems.slice(0, 5)" :key="item.id" size="small" style="margin:2px;">
              {{ item.product_name }} × {{ item.order_qty }}
            </StatusBadge>
            <StatusBadge v-if="selectedCartItems.length > 5" size="small" type="info">+{{ selectedCartItems.length - 5 }} 项</StatusBadge>
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
    <el-dialog v-model="stockStatusDialogVisible" title="备货明细" width="760px" align-center>
      <div v-if="currentStockStatusRow" class="stock-status-dialog">
        <div class="stock-status-header">
          <span class="stock-status-product">{{ currentStockStatusRow.product_name }}</span>
          <StatusBadge :type="currentStockStatusRow.stock_status === '加急中' ? 'danger' : 'success'" size="small">
            {{ currentStockStatusRow.stock_status }}
          </StatusBadge>
        </div>
        <el-table v-if="(currentStockStatusRow.stock_items || []).length > 0" :data="currentStockStatusRow.stock_items || []" size="small" style="width:100%" border class="list-table" v-sticky-scrollbar>
          <el-table-column class-name="table-action-column" label="操作" min-width="70">
            <template #default="{ row }">
              <el-button link type="primary" @click="openProgressDialog(row)"><el-icon><TrendCharts /></el-icon>进度</el-button>
            </template>
          </el-table-column>
          <el-table-column label="生产单号" prop="order_no" min-width="120" />
          <el-table-column label="批次号" prop="batch_no" min-width="100" />
          <el-table-column label="下单量" min-width="80" prop="order_qty" />
          <el-table-column label="已入库" min-width="80" prop="received_qty" />
          <el-table-column label="在途" min-width="70" prop="in_transit_qty" />
          <el-table-column prop="is_urgent" label="加急" min-width="100">
            <template #default="{ row }">
              <StatusBadge v-if="row.is_urgent" type="danger" size="small">加急</StatusBadge>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="expected_delivery_date" label="预计交期" min-width="110">
            <template #default="{ row }">{{ row.expected_delivery_date || '—' }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无备货明细" />
      </div>
    </el-dialog>

    <!-- 工序进度弹窗 -->
    <el-dialog v-model="progressDialogVisible" title="工序进度" width="640px">
      <ListPageStatus :error="progressResource.errorMessage.value" :loading="progressLoading" :has-data="!!progressData" @retry="progressResource.load()" />
      <div v-if="progressLoading" style="text-align:center; padding: 20px;">
        <el-icon class="is-loading" :size="20" style="animation: rotate 1s linear infinite;">⟳</el-icon> 加载中...
      </div>
      <template v-else-if="progressDialogRow && progressData">
        <div style="margin-bottom: 12px; font-weight: 600; color: #1e1e2d;">{{ progressData.order_product_id ? `${progressDialogRow.product_name || progressDialogRow.order_no}` : '' }}</div>
        <div style="margin-bottom: 12px;">
          <el-progress :percentage="progressData.completion_rate || 0" :stroke-width="16" :text-inside="true" style="margin-bottom: 12px;" />
          <span style="font-size: 13px; color: #606266;">
            {{ progressData.completed_steps || 0 }}/{{ progressData.total_steps || 0 }} 工序完成
            <template v-if="progressData.all_completed"> 🎉 全部完成</template>
          </span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <div v-for="step in (progressData.steps || [])" :key="step.id" style="display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 4px; font-size: 13px;" :style="{ background: step.status === 1 ? '#f0f9eb' : (step.status === 0 && isCurrentStep(step) ? '#ecf5ff' : 'transparent') }">
            <span style="width: 20px; text-align: center;">{{ step.status === 1 ? '✅' : (isCurrentStep(step) ? '🔵' : '⚪') }}</span>
            <span style="width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #fff;" :style="{ background: step.status === 1 ? '#67c23a' : (isCurrentStep(step) ? '#409eff' : '#c0c4cc') }">{{ step.step_order }}</span>
            <span style="font-weight: 500; min-width: 80px;">{{ step.process_name }}</span>
            <span v-if="step.status === 1" style="color: #909399; font-size: 12px;">{{ step.completed_at }} · {{ step.completed_by_user_name || '未知' }}</span>
            <span v-else-if="isCurrentStep(step)" style="color: #909399; font-size: 12px;">待完成（当前工序）</span>
            <span v-else style="color: #909399; font-size: 12px;">未到</span>
          </div>
        </div>
      </template>
      <div v-else-if="!progressResource.error.value" style="text-align: center; padding: 16px;">
        <span style="color: #909399;">未配置工序路线，请前往产品管理绑定</span>
        <router-link to="/production/products" style="margin-left: 8px;">去绑定 →</router-link>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>import { msgWarning, msgSuccessText, msgInfo, msgError, confirmAction } from '@/utils/feedback'
import { ref, reactive, onMounted, computed } from 'vue'

import {
  Setting, MagicStick, Check, Search, Filter, RefreshRight, QuestionFilled, InfoFilled,
  ShoppingCart, Plus, Delete,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  getSafetyList, saveSafetyStock, autoGenerateSafety,
} from '@/api/stock'
import { useProductionCart } from './composables/useProductionCart'
import { useSafetyConfigTable } from './composables/useSafetyConfigTable'
import { parseProductName, sourceLabel, sourceTagType, headerStyle, isCurrentProgressStep } from './safetyConfigPresentation'
import ProductionOrderDialog from './components/ProductionOrderDialog.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { loadStockFilterOptions, loadStockProgress } from './composables/stockResources'


const authStore = useAuthStore()
// 表格视图状态（列显隐/密度/全屏），columnDefs 仅供 TableTools 列显隐面板
const { columnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useSafetyConfigTable()
const { sortParams, onSortChange, reset: resetSort } = useTableSort('product_id', 'asc')
function handleSortChange(sortInfo) {
  onSortChange(sortInfo)
  return listState.handleSortChange({ sort: sortParams.value.sort_field, order: sortParams.value.sort_order })
}

// ── 原有安全库存逻辑 ──────────────────────────
const saveLoading = ref(false)
const aiLoading = ref(false)

const initialFilters = {
  keyword: '',
  model: [],
  product_type: [],
  size: [],
  color: [],
  weight: [],
  has_in_transit: false,
  has_safety_stock: false,
  stock_status: '',
}
const listState = useListPage(fetchStockList, { searchForm: initialFilters, sortParams: { sort: 'product_id', order: 'asc' } })
const filters = listState.searchForm
const loading = listState.loading; const tableData = listState.list
const pagination = reactive({ total: listState.total, page: listState.page, page_size: listState.pageSize })

const hasActiveFilters = computed(() => Boolean(
  filters.keyword || filters.model.length || filters.product_type.length ||
  filters.size.length || filters.color.length || filters.weight.length ||
  filters.has_in_transit || filters.has_safety_stock || filters.stock_status
))

const optionsResource = useAsyncResource(loadStockFilterOptions)
const allFilterOptions = computed(() => optionsResource.data.value || { models: [], types: [], sizes: [], colors: [], weights: [] })
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

function markDirty(row) {
  row._dirty = true
  row._aiGenerated = false
  row.source = 'manual'
}

async function fetchStockList(params, { signal, isCurrent }) {
    const res = await getSafetyList({ ...params,
      has_in_transit: params.has_in_transit || undefined,
      has_safety_stock: params.has_safety_stock || undefined,
      stock_status: params.stock_status || undefined,
      keyword: params.keyword || undefined,
      ...Object.fromEntries(['model', 'product_type', 'size', 'color', 'weight'].map(key => [key, params[key].length ? params[key].join(',') : undefined])),
    }, { signal, suppressToast: true })
    const d = res.data
    const items = (d.items || []).map(i => {
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
    return { items, total: d.total || 0 }
}

const loadData = listState.fetchList
const applyFilters = listState.handleSearch
const handleSizeChange = listState.handleSizeChange
function resetFilters() { resetSort(); return listState.handleReset({ sortParams: { sort: 'product_id', order: 'asc' } }) }

async function aiGenerateSingle(row) {
  row.aiLoading = true
  try {
    const res = await autoGenerateSafety({
      product_ids: [row.product_id],
      lead_time_days: globalParams.lead_time_days,
      safety_factor: globalParams.safety_factor,
      history_days: 30,
    })
    if (!tableData.value.includes(row)) return
    const item = res.data?.items?.[0]
    if (!item) {
      msgWarning('AI 建议生成失败')
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
    msgWarning('建议值为空，未应用')
  }
  aiDialogVisible.value = false
}

async function aiBatchGenerate() {
  aiLoading.value = true
  try {
    const sourceRows = tableData.value
    const visibleIds = sourceRows.map(r => r.product_id)
    const res = await autoGenerateSafety({
      product_ids: visibleIds,
      lead_time_days: globalParams.lead_time_days,
      safety_factor: globalParams.safety_factor,
      history_days: 30,
    })
    if (tableData.value !== sourceRows) return
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
    msgSuccessText(`已批量生成 ${items.length} 条安全库存建议`)
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
    msgInfo('没有需要保存的更改')
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
      msgWarning(`保存 ${saved} 条，${failed.length} 条失败`)
      console.warn('保存失败项:', failed)
    } else {
      msgSuccessText(`成功保存 ${saved} 条安全库存配置`)
      await listState.refreshUpdate()
    }
  } catch (err) {
    msgError(err.message || '保存失败', err)
  } finally {
    saveLoading.value = false
  }
}

const loadFilterOptions = () => optionsResource.load()
onMounted(loadFilterOptions)

// ── 生产下单逻辑 ──────────────────────────────
const {
  cartItems, cartCount, cartLoading, cartErrorMessage, selectedCartIds,
  loadCart, addToCart, updateCartItem, removeCartItem,
  batchRemoveCartItems, generateOrder, toggleSelection,
} = useProductionCart()

const cartDrawerVisible = ref(false)

const productionDialogVisible = ref(false)
const currentProductionRow = ref(null)

function openProductionDialog(row) {
  currentProductionRow.value = row
  productionDialogVisible.value = true
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
    msgWarning('请先选择要删除的产品')
    return
  }
  try {
    await confirmAction(`确定删除选中的 ${selectedCartIds.value.length} 项?`, '提示', { type: 'warning' })
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
    msgWarning('请先选择产品')
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
        listState.refreshUpdate()
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

// ── 工序进度弹窗 ──────────────────────────
const progressDialogVisible = ref(false)
const progressDialogRow = ref(null)
const progressResource = useAsyncResource(loadStockProgress)
const progressData = progressResource.data
const progressLoading = progressResource.loading

function isCurrentStep(step) {
  return isCurrentProgressStep(progressData.value, step)
}

async function openProgressDialog(row) {
  if (!row.item_id) return
  progressDialogRow.value = row
  progressDialogVisible.value = true
  return progressResource.load(row.item_id, { clear: true })
}

// 页面加载时同步购物车
onMounted(() => {
  loadCart()
})
</script>

<style scoped src="./safety-config.css"></style>
