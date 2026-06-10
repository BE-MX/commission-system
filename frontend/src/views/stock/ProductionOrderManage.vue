<template>
  <div class="production-order-page">
    <!-- 统计卡 -->
    <div class="stats-row">
      <div class="stat-card submitted">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#409eff"><Document /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">已提交</div>
          <div class="stat-value">{{ statusCount.submitted }}</div>
        </div>
      </div>
      <div class="stat-card terminated">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#909399"><CircleClose /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">已终止</div>
          <div class="stat-value">{{ statusCount.terminated }}</div>
        </div>
      </div>
      <div class="stat-card completed">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#67c23a"><CircleCheck /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">已完成</div>
          <div class="stat-value">{{ statusCount.completed }}</div>
        </div>
      </div>
    </div>

    <!-- 标签页 -->
    <el-tabs v-model="activeTab" class="order-tabs">
      <!-- 标签页一：按生产单维度 -->
      <el-tab-pane label="按生产单维度" name="order">
        <div class="tab-toolbar">
          <el-select v-model="orderFilters.status" placeholder="状态" clearable style="width:120px">
            <el-option label="已提交" :value="0" />
            <el-option label="已终止" :value="1" />
            <el-option label="已完成" :value="2" />
          </el-select>
          <el-input v-model="orderFilters.keyword" placeholder="搜索单号/批次号" clearable style="width:200px" @input="handleOrderSearch" />
          <el-button type="primary" size="small" @click="loadOrderList"><el-icon><Filter /></el-icon> 筛选</el-button>
          <el-button size="small" @click="resetOrderFilters">重置</el-button>
        </div>
        <el-table :data="orderList" style="width:100%" :header-cell-style="headerStyle" v-loading="orderLoading" stripe @sort-change="handleOrderSortChange">
          <el-table-column label="生产单号" prop="order_no" min-width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column label="生产批次号" prop="batch_no" min-width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column label="创建人" min-width="100">
            <template #default="{ row }">{{ row.created_by_name || '-' }}</template>
          </el-table-column>
          <el-table-column label="创建时间" prop="created_at" min-width="140" sortable="custom">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="明细数" width="80" align="center" prop="item_count" />
          <el-table-column label="总下单量" width="90" align="center" prop="total_order_qty" />
          <el-table-column label="总入库量" width="90" align="center" prop="total_received_qty" />
          <el-table-column label="在途量" width="80" align="center">
            <template #default="{ row }">
              <span :class="row.total_in_transit_qty > 0 ? 'in-transit-active' : ''">{{ row.total_in_transit_qty }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" prop="status" width="90" align="center" sortable="custom">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ row.status_label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="viewOrderDetail(row)">详情</el-button>
              <el-button size="small" link type="primary" @click="editOrder(row)">编辑</el-button>
              <el-dropdown trigger="click" @command="(cmd) => handlePrintCommand(cmd, row)">
                <el-button size="small" link type="success">打印</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="order">打印生产单</el-dropdown-item>
                    <el-dropdown-item command="process_card">打印工序卡片</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button size="small" link type="warning" @click="printOrderHtml(row)">打印订单</el-button>
              <el-button size="small" link type="danger" @click="deleteOrder(row)" v-if="authStore.hasPermission('production:admin')">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-bar">
          <el-pagination v-model:current-page="orderPagination.page" v-model:page-size="orderPagination.page_size" :total="orderPagination.total"
            :page-sizes="[20,50,100]" layout="total,sizes,prev,pager,next,jumper" @size-change="loadOrderList" @current-change="loadOrderList" />
        </div>
      </el-tab-pane>

      <!-- 标签页二：按明细维度 -->
      <el-tab-pane label="按生产单产品明细维度" name="item">
        <div class="tab-toolbar">
          <el-select v-model="itemFilters.status" placeholder="明细状态" clearable style="width:120px">
            <el-option label="已提交" :value="0" />
            <el-option label="已终止" :value="1" />
            <el-option label="已完成" :value="2" />
          </el-select>
          <el-input v-model="itemFilters.keyword" placeholder="搜索产品/单号/批次号" clearable style="width:200px" @input="handleItemSearch" />
          <el-button type="primary" size="small" @click="loadItemList"><el-icon><Filter /></el-icon> 筛选</el-button>
          <el-button size="small" @click="resetItemFilters">重置</el-button>
        </div>
        <el-table :data="itemList" style="width:100%" :header-cell-style="headerStyle" v-loading="itemLoading" stripe @sort-change="handleItemSortChange">
          <el-table-column label="生产单号" prop="order_no" min-width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column label="批次号" prop="batch_no" min-width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column label="产品名称" prop="product_name" min-width="140" sortable="custom" show-overflow-tooltip />
          <el-table-column label="型号" prop="model" min-width="100" sortable="custom" show-overflow-tooltip />
          <el-table-column label="下单数量" width="90" align="center" prop="order_qty" sortable="custom" />
          <el-table-column label="已入库" width="80" align="center" prop="received_qty" sortable="custom" />
          <el-table-column label="在途" width="70" align="center">
            <template #default="{ row }">
              <span :class="row.in_transit_qty > 0 ? 'in-transit-active' : ''">{{ row.in_transit_qty }}</span>
            </template>
          </el-table-column>
          <el-table-column label="明细状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ row.status_label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="订单状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.order_status)" size="small" effect="plain">{{ row.order_status_label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="加急" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_urgent" type="danger" size="small">加急</el-tag>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="预计交期" width="110" align="center">
            <template #default="{ row }">{{ row.expected_delivery_date || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="260" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="editItem(row)">编辑</el-button>
              <el-button size="small" link type="primary" @click="changeItemStatus(row)">改状态</el-button>
              <el-button size="small" link type="warning" @click="inputReceived(row)">入库</el-button>
              <el-button size="small" link type="success" @click="toggleItemProgress(row)">进度</el-button>
              <el-button size="small" link type="danger" @click="deleteItem(row)" v-if="authStore.hasPermission('production:admin')">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-bar">
          <el-pagination v-model:current-page="itemPagination.page" v-model:page-size="itemPagination.page_size" :total="itemPagination.total"
            :page-sizes="[20,50,100]" layout="total,sizes,prev,pager,next,jumper" @size-change="loadItemList" @current-change="loadItemList" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 订单详情弹窗 -->
    <el-dialog v-model="detailDialogVisible" title="生产订单详情" width="960px">
      <div v-if="currentOrder" class="order-detail">
        <div class="detail-header">
          <div class="detail-row"><span class="detail-label">生产单号</span><span class="detail-value">{{ currentOrder.order_no }}</span></div>
          <div class="detail-row"><span class="detail-label">批次号</span><span class="detail-value">{{ currentOrder.batch_no }}</span></div>
          <div class="detail-row"><span class="detail-label">状态</span><el-tag :type="statusTagType(currentOrder.status)">{{ currentOrder.status_label }}</el-tag></div>
          <div class="detail-row"><span class="detail-label">创建人</span><span class="detail-value">{{ currentOrder.created_by_name || '-' }}</span></div>
          <div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">{{ formatDate(currentOrder.created_at) }}</span></div>
          <div class="detail-row"><span class="detail-label">备注</span><span class="detail-value">{{ currentOrder.remark || '-' }}</span></div>
        </div>
        <el-divider />
        <div class="detail-subtitle">产品明细</div>
        <el-table :data="currentOrder.items || []" size="small">
          <el-table-column label="操作" width="140" align="center">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="toggleItemProgress(row)">进度</el-button>
              <el-button size="small" link type="warning" @click="printCard(row)">打印流转卡</el-button>
            </template>
          </el-table-column>
          <el-table-column label="产品名称" prop="product_name" min-width="140" show-overflow-tooltip />
          <el-table-column label="型号" prop="model" min-width="100" />
          <el-table-column label="下单量" width="80" align="center" prop="order_qty" />
          <el-table-column label="已入库" width="80" align="center" prop="received_qty" />
          <el-table-column label="在途" width="70" align="center">
            <template #default="{ row }"><span :class="row.in_transit_qty > 0 ? 'in-transit-active' : ''">{{ row.in_transit_qty }}</span></template>
          </el-table-column>
          <el-table-column label="加急" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_urgent" type="danger" size="small">加急</el-tag>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="预计交期" width="100" align="center">
            <template #default="{ row }">{{ row.expected_delivery_date || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag></template>
          </el-table-column>
        </el-table>

        <!-- 工序进度看板（按需展开） -->
        <template v-for="item in (currentOrder.items || [])" :key="'progress-' + item.id">
          <div v-if="expandedProgressId === item.id" class="progress-panel">
            <div class="progress-panel-header">
              <span class="detail-subtitle">工序进度：{{ item.product_name }}</span>
              <div>
                <el-button size="small" link @click="refreshProgress(item.id)">刷新</el-button>
                <el-button size="small" link @click="expandedProgressId = null">收起</el-button>
              </div>
            </div>
            <div v-if="progressLoading" style="text-align:center; padding: 20px;">
              <el-icon class="is-loading" :size="20"><Loading /></el-icon> 加载中...
            </div>
            <div v-else-if="progressData[item.id]" class="progress-content">
              <!-- 进度条 -->
              <div class="progress-bar-wrap">
                <el-progress
                  :percentage="progressData[item.id].completion_rate"
                  :color="progressColor(progressData[item.id].completion_rate)"
                  :stroke-width="16"
                  :text-inside="true"
                  style="margin-bottom: 12px;"
                />
                <span class="progress-summary">
                  {{ progressData[item.id].completed_steps }}/{{ progressData[item.id].total_steps }} 工序完成
                  <template v-if="progressData[item.id].all_completed"> 🎉 全部完成</template>
                </span>
              </div>
              <!-- 步骤列表 -->
              <div class="step-timeline">
                <div v-for="step in progressData[item.id].steps" :key="step.id" class="step-row" :class="{ completed: step.status === 1, current: step.status === 0 && isCurrentStep(step, progressData[item.id]) }">
                  <span class="step-icon">
                    <template v-if="step.status === 1">✅</template>
                    <template v-else-if="isCurrentStep(step, progressData[item.id])">🔵</template>
                    <template v-else>⚪</template>
                  </span>
                  <span class="step-order-num">{{ step.step_order }}</span>
                  <span class="step-process-name">{{ step.process_name }}</span>
                  <span v-if="step.status === 1" class="step-meta">
                    {{ formatShortDate(step.completed_at) }} · {{ step.completed_by_user_name || '未知' }}
                  </span>
                  <span v-else-if="isCurrentStep(step, progressData[item.id])" class="step-meta">待完成（当前工序）</span>
                  <span v-else class="step-meta">未到</span>
                </div>
              </div>
            </div>
            <div v-else class="progress-empty">
              <span style="color: #909399;">未配置工序路线，请前往产品管理绑定</span>
              <router-link to="/production/products" style="margin-left: 8px;">去绑定 →</router-link>
            </div>
          </div>
        </template>
      </div>
    </el-dialog>

    <!-- 编辑订单弹窗 -->
    <el-dialog v-model="editOrderDialogVisible" title="编辑生产订单" width="480px">
      <el-form :model="editOrderForm" label-width="100px">
        <el-form-item label="生产批次号">
          <el-input v-model="editOrderForm.batch_no" placeholder="批次号" maxlength="64" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editOrderForm.remark" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="editOrderForm.status">
            <el-radio :label="0">已提交</el-radio>
            <el-radio :label="1">已终止</el-radio>
            <el-radio :label="2">已完成</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOrderDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmEditOrder" :loading="editOrderLoading">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑明细弹窗 -->
    <el-dialog v-model="editItemDialogVisible" title="编辑明细" width="480px">
      <el-form :model="editItemForm" label-width="100px">
        <el-form-item label="产品"><span>{{ currentItem?.product_name }}</span></el-form-item>
        <el-form-item label="生产下单数量">
          <el-input-number v-model="editItemForm.order_qty" :min="1" :max="999999" :step="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="是否加急">
          <el-switch v-model="editItemForm.is_urgent" :active-value="1" :inactive-value="0" active-text="加急" inactive-text="正常" />
        </el-form-item>
        <el-form-item label="预计交期">
          <el-date-picker v-model="editItemForm.expected_delivery_date" type="date" placeholder="选择预计交期" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editItemForm.remark" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editItemDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmEditItem" :loading="editItemLoading">保存</el-button>
      </template>
    </el-dialog>

    <!-- 修改状态弹窗 -->
    <el-dialog v-model="statusDialogVisible" title="修改状态" width="400px">
      <div v-if="currentItem" class="status-dialog-content">
        <p style="margin-bottom:16px;">产品：{{ currentItem.product_name }}</p>
        <p style="margin-bottom:16px;">当前状态：<el-tag :type="statusTagType(currentItem.status)">{{ currentItem.status_label }}</el-tag></p>
        <el-radio-group v-model="newStatus">
          <el-radio :label="0">已提交</el-radio>
          <el-radio :label="1">已终止</el-radio>
          <el-radio :label="2">已完成</el-radio>
        </el-radio-group>
      </div>
      <template #footer>
        <el-button @click="statusDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmChangeStatus" :loading="statusLoading">确认</el-button>
      </template>
    </el-dialog>

    <!-- 入库录入弹窗 -->
    <el-dialog v-model="receivedDialogVisible" title="录入已入库数量" width="400px">
      <div v-if="currentItem" class="received-dialog-content">
        <p style="margin-bottom:8px;">产品：{{ currentItem.product_name }}</p>
        <p style="margin-bottom:8px;">生产下单数量：{{ currentItem.order_qty }}</p>
        <p style="margin-bottom:16px;">当前已入库：{{ currentItem.received_qty }}</p>
        <el-form :model="receivedForm" label-width="120px">
          <el-form-item label="已入库数量">
            <el-input-number v-model="receivedForm.received_qty" :min="0" :max="currentItem.order_qty" :step="1" controls-position="right" />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="receivedDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmReceived" :loading="receivedLoading">确认</el-button>
      </template>
    </el-dialog>

    <!-- 工序进度弹窗（明细维度 + 备货弹窗共用） -->
    <el-dialog v-model="progressDialogVisible" title="工序进度" width="640px" @close="expandedProgressId = null">
      <div v-if="progressLoading" style="text-align:center; padding: 20px;">
        <el-icon class="is-loading" :size="20"><Loading /></el-icon> 加载中...
      </div>
      <template v-else-if="progressDialogItem && progressData[progressDialogItem.id]">
        <div style="margin-bottom: 12px; font-weight: 600; color: #1e1e2d;">{{ progressDialogItem.product_name }}</div>
        <div class="progress-bar-wrap">
          <el-progress
            :percentage="progressData[progressDialogItem.id].completion_rate"
            :color="progressColor(progressData[progressDialogItem.id].completion_rate)"
            :stroke-width="16"
            :text-inside="true"
            style="margin-bottom: 12px;"
          />
          <span class="progress-summary">
            {{ progressData[progressDialogItem.id].completed_steps }}/{{ progressData[progressDialogItem.id].total_steps }} 工序完成
            <template v-if="progressData[progressDialogItem.id].all_completed"> 🎉 全部完成</template>
          </span>
        </div>
        <div class="step-timeline">
          <div v-for="step in progressData[progressDialogItem.id].steps" :key="step.id" class="step-row" :class="{ completed: step.status === 1, current: step.status === 0 && isCurrentStep(step, progressData[progressDialogItem.id]) }">
            <span class="step-icon">
              <template v-if="step.status === 1">✅</template>
              <template v-else-if="isCurrentStep(step, progressData[progressDialogItem.id])">🔵</template>
              <template v-else>⚪</template>
            </span>
            <span class="step-order-num">{{ step.step_order }}</span>
            <span class="step-process-name">{{ step.process_name }}</span>
            <span v-if="step.status === 1" class="step-meta">
              {{ formatShortDate(step.completed_at) }} · {{ step.completed_by_user_name || '未知' }}
            </span>
            <span v-else-if="isCurrentStep(step, progressData[progressDialogItem.id])" class="step-meta">待完成（当前工序）</span>
            <span v-else class="step-meta">未到</span>
          </div>
        </div>
      </template>
      <div v-else class="progress-empty">
        <span style="color: #909399;">未配置工序路线，请前往产品管理绑定</span>
        <router-link to="/production/products" style="margin-left: 8px;">去绑定 →</router-link>
      </div>
    </el-dialog>

    <!-- 报表打印预览弹窗 -->
    <el-dialog v-model="printDialogVisible" :title="printDialogTitle" width="90%" top="2vh" destroy-on-close>
      <StimulsoftViewer
        :report-code="currentReportCode"
        :params="{ order_no: currentPrintOrderNo }"
        height="80vh"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, CircleClose, CircleCheck, Filter, Loading } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useTableSort } from '@/composables/useTableSort'
import StimulsoftViewer from '@/components/StimulsoftViewer.vue'
import { getProgress, initProgress, getPrintCardData } from '@/api/production'
import {
  getProductionOrders, getProductionOrderDetail, updateProductionOrder,
  deleteProductionOrder, getProductionOrderItems, updateProductionOrderItem,
  updateProductionItemStatus, updateProductionItemReceived, deleteProductionOrderItem,
} from '@/api/stock'

const router = useRouter()
const authStore = useAuthStore()

const orderSort = useTableSort()
const itemSort = useTableSort()
function handleOrderSortChange(sortInfo) {
  orderSort.onSortChange(sortInfo)
  orderPagination.page = 1
  loadOrderList()
}
function handleItemSortChange(sortInfo) {
  itemSort.onSortChange(sortInfo)
  itemPagination.page = 1
  loadItemList()
}

const activeTab = ref('order')
const statusCount = reactive({ submitted: 0, terminated: 0, completed: 0 })

const statusTagType = (s) => ({ 0: 'primary', 1: 'info', 2: 'success' })[s] || 'info'
const statusLabel = (s) => ({ 0: '已提交', 1: '已终止', 2: '已完成' })[s] || '未知'
const headerStyle = () => ({ background: 'linear-gradient(135deg,#f8f6f0,#f0ece3)', fontWeight: 600, color: '#4a4a5a' })

function formatDate(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}

// ── 订单维度 ────────────────────────────
const orderLoading = ref(false)
const orderList = ref([])
const orderPagination = reactive({ total: 0, page: 1, page_size: 20 })
const orderFilters = reactive({ status: null, keyword: '' })

async function loadOrderList() {
  orderLoading.value = true
  try {
    const params = {
      page: orderPagination.page,
      page_size: orderPagination.page_size,
      status: orderFilters.status,
      keyword: orderFilters.keyword || undefined,
      ...orderSort.sortParams.value,
    }
    const res = await getProductionOrders(params)
    const d = res.data
    orderList.value = d.items || []
    orderPagination.total = d.total || 0

    // 统计
    statusCount.submitted = orderList.value.filter(i => i.status === 0).length
    statusCount.terminated = orderList.value.filter(i => i.status === 1).length
    statusCount.completed = orderList.value.filter(i => i.status === 2).length
  } catch (e) {
    console.warn('加载订单列表失败:', e)
  } finally {
    orderLoading.value = false
  }
}

let orderSearchTimer = null
function handleOrderSearch() {
  if (orderSearchTimer) clearTimeout(orderSearchTimer)
  orderSearchTimer = setTimeout(() => { orderPagination.page = 1; loadOrderList() }, 400)
}

function resetOrderFilters() {
  orderFilters.status = null
  orderFilters.keyword = ''
  orderPagination.page = 1
  orderSort.reset()
  loadOrderList()
}

// ── 明细维度 ────────────────────────────
const itemLoading = ref(false)
const itemList = ref([])
const itemPagination = reactive({ total: 0, page: 1, page_size: 20 })
const itemFilters = reactive({ status: null, keyword: '' })

async function loadItemList() {
  itemLoading.value = true
  try {
    const params = {
      page: itemPagination.page,
      page_size: itemPagination.page_size,
      status: itemFilters.status,
      keyword: itemFilters.keyword || undefined,
      ...itemSort.sortParams.value,
    }
    const res = await getProductionOrderItems(params)
    const d = res.data
    itemList.value = d.items || []
    itemPagination.total = d.total || 0
  } catch (e) {
    console.warn('加载明细列表失败:', e)
  } finally {
    itemLoading.value = false
  }
}

let itemSearchTimer = null
function handleItemSearch() {
  if (itemSearchTimer) clearTimeout(itemSearchTimer)
  itemSearchTimer = setTimeout(() => { itemPagination.page = 1; loadItemList() }, 400)
}

function resetItemFilters() {
  itemFilters.status = null
  itemFilters.keyword = ''
  itemPagination.page = 1
  itemSort.reset()
  loadItemList()
}

watch(activeTab, (tab) => {
  if (tab === 'order') loadOrderList()
  else loadItemList()
})

// ── 订单详情 ────────────────────────────
const detailDialogVisible = ref(false)
const currentOrder = ref(null)

async function viewOrderDetail(row) {
  const res = await getProductionOrderDetail(row.id)
  currentOrder.value = res.data
  detailDialogVisible.value = true
}

// ── 编辑订单 ────────────────────────────
const editOrderDialogVisible = ref(false)
const editOrderLoading = ref(false)
const editOrderForm = reactive({ id: null, batch_no: '', remark: '', status: 0 })

function editOrder(row) {
  editOrderForm.id = row.id
  editOrderForm.batch_no = row.batch_no
  editOrderForm.remark = row.remark || ''
  editOrderForm.status = row.status
  editOrderDialogVisible.value = true
}

async function confirmEditOrder() {
  editOrderLoading.value = true
  try {
    await updateProductionOrder(editOrderForm.id, {
      batch_no: editOrderForm.batch_no,
      remark: editOrderForm.remark,
      status: editOrderForm.status,
    })
    ElMessage.success('已更新')
    editOrderDialogVisible.value = false
    loadOrderList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '更新失败')
  } finally {
    editOrderLoading.value = false
  }
}

// ── 删除订单 ────────────────────────────
async function deleteOrder(row) {
  try {
    await ElMessageBox.confirm(`确定删除生产订单 ${row.order_no}?`, '删除确认', { type: 'warning' })
    await deleteProductionOrder(row.id)
    ElMessage.success('已删除')
    loadOrderList()
  } catch {
    // cancel
  }
}

// ── 编辑明细 ────────────────────────────
const editItemDialogVisible = ref(false)
const editItemLoading = ref(false)
const editItemForm = reactive({ id: null, order_qty: 0, remark: '', is_urgent: 0, expected_delivery_date: '' })
const currentItem = ref(null)

function editItem(row) {
  currentItem.value = row
  editItemForm.id = row.id
  editItemForm.order_qty = row.order_qty
  editItemForm.remark = row.remark || ''
  editItemForm.is_urgent = row.is_urgent || 0
  editItemForm.expected_delivery_date = row.expected_delivery_date || ''
  editItemDialogVisible.value = true
}

async function confirmEditItem() {
  editItemLoading.value = true
  try {
    await updateProductionOrderItem(editItemForm.id, {
      order_qty: editItemForm.order_qty,
      remark: editItemForm.remark,
      is_urgent: editItemForm.is_urgent,
      expected_delivery_date: editItemForm.expected_delivery_date || undefined,
    })
    ElMessage.success('已更新')
    editItemDialogVisible.value = false
    loadItemList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '更新失败')
  } finally {
    editItemLoading.value = false
  }
}

// ── 修改明细状态 ─────────────────────────
const statusDialogVisible = ref(false)
const statusLoading = ref(false)
const newStatus = ref(0)

function changeItemStatus(row) {
  currentItem.value = row
  newStatus.value = row.status
  statusDialogVisible.value = true
}

async function confirmChangeStatus() {
  statusLoading.value = true
  try {
    await updateProductionItemStatus(currentItem.value.id, { status: newStatus.value })
    ElMessage.success('状态已更新')
    statusDialogVisible.value = false
    loadItemList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '更新失败')
  } finally {
    statusLoading.value = false
  }
}

// ── 入库录入 ────────────────────────────
const receivedDialogVisible = ref(false)
const receivedLoading = ref(false)
const receivedForm = reactive({ received_qty: 0 })

function inputReceived(row) {
  currentItem.value = row
  receivedForm.received_qty = row.received_qty
  receivedDialogVisible.value = true
}

async function confirmReceived() {
  receivedLoading.value = true
  try {
    await updateProductionItemReceived(currentItem.value.id, { received_qty: receivedForm.received_qty })
    ElMessage.success('入库数量已更新')
    receivedDialogVisible.value = false
    loadItemList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '更新失败')
  } finally {
    receivedLoading.value = false
  }
}

// ── 删除明细 ────────────────────────────
async function deleteItem(row) {
  try {
    await ElMessageBox.confirm(`确定删除明细 ${row.product_name}?`, '删除确认', { type: 'warning' })
    await deleteProductionOrderItem(row.id)
    ElMessage.success('已删除')
    loadItemList()
  } catch {
    // cancel
  }
}

onMounted(() => {
  loadOrderList()
})

// ── 工序进度看板 ──────────────────────────
const expandedProgressId = ref(null)
const progressData = ref({})
const progressLoading = ref(false)
const progressDialogVisible = ref(false)
const progressDialogItem = ref(null)

function isCurrentStep(step, progress) {
  const firstPending = progress.steps.find(s => s.status === 0)
  return firstPending && step.id === firstPending.id
}

function progressColor(rate) {
  if (rate >= 100) return '#409eff'
  if (rate > 70) return '#67c23a'
  if (rate > 30) return '#e6a23c'
  return '#f56c6c'
}

function formatShortDate(dt) {
  if (!dt) return ''
  const d = new Date(dt)
  return `${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}

async function toggleItemProgress(item) {
  // 详情弹窗内 → 内联展开
  if (detailDialogVisible.value) {
    if (expandedProgressId.value === item.id) {
      expandedProgressId.value = null
      return
    }
    expandedProgressId.value = item.id
    await loadProgress(item.id)
    return
  }
  // 明细维度标签页 → 独立弹窗
  progressDialogItem.value = item
  progressDialogVisible.value = true
  await loadProgress(item.id)
}

async function loadProgress(itemId) {
  progressLoading.value = true
  try {
    const res = await getProgress(itemId)
    // 后端直接返回进度对象（无 {code,data} 包装），axios 拦截器已解包 response.data
    progressData.value[itemId] = res.data || res
  } catch {
    // 404 = 尚未初始化进度，尝试自动初始化后再拉取
    try {
      await initProgress(itemId)
      const res2 = await getProgress(itemId)
      progressData.value[itemId] = res2.data || res2
    } catch {
      progressData.value[itemId] = null
    }
  } finally {
    progressLoading.value = false
  }
}

async function refreshProgress(itemId) {
  await loadProgress(itemId)
}

function printCard(item) {
  const url = router.resolve({ name: 'PrintCard', params: { id: item.id } }).href
  window.open(url, '_blank')
}

// ── 报表打印 ────────────────────────────
const printDialogVisible = ref(false)
const currentPrintOrderNo = ref('')
const currentReportCode = ref('production_order_print')
const printDialogTitle = ref('生产订单打印预览')

function handlePrintCommand(cmd, row) {
  currentPrintOrderNo.value = row.order_no
  if (cmd === 'process_card') {
    currentReportCode.value = 'process_card_print'
    printDialogTitle.value = '工序卡片打印预览'
  } else {
    currentReportCode.value = 'production_order_print'
    printDialogTitle.value = '生产订单打印预览'
  }
  printDialogVisible.value = true
}

function printOrderHtml(row) {
  const url = `/api/report/print/production-order?order_no=${encodeURIComponent(row.order_no)}`
  window.open(url, '_blank')
}
</script>

<style scoped>
.production-order-page { display: flex; flex-direction: column; gap: 20px; }

/* 统计卡 */
.stats-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.stat-card { background: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); display: flex; align-items: center; gap: 16px; }
.stat-icon-bg { width: 56px; height: 56px; border-radius: 14px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.stat-card.submitted .stat-icon-bg { background: linear-gradient(135deg, #e6f2ff, #cce0ff); }
.stat-card.terminated .stat-icon-bg { background: linear-gradient(135deg, #f0f0f0, #e0e0e0); }
.stat-card.completed .stat-icon-bg { background: linear-gradient(135deg, #e6f7e6, #ccf2cc); }
.stat-info { flex: 1; }
.stat-label { font-size: 13px; color: #888; margin-bottom: 4px; }
.stat-value { font-size: 28px; font-weight: 700; color: #1e1e2d; line-height: 1.2; }

/* 标签页 */
.order-tabs :deep(.el-tabs__header) { margin-bottom: 16px; }
.tab-toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }

/* 分页 */
.pagination-bar { margin-top: 16px; display: flex; justify-content: flex-end; }

/* 详情弹窗 */
.order-detail { padding: 10px 0; }
.detail-header { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.detail-row { display: flex; gap: 10px; align-items: center; }
.detail-label { color: #888; font-size: 13px; min-width: 70px; }
.detail-value { font-weight: 500; color: #1e1e2d; }
.detail-subtitle { font-size: 15px; font-weight: 600; color: #1e1e2d; margin-bottom: 12px; }

/* 状态变更弹窗 */
.status-dialog-content { padding: 10px 0; }
.received-dialog-content { padding: 10px 0; }

/* 通用 */
.in-transit-active { color: #27ae60; font-weight: 600; }

/* 工序进度看板 */
.progress-panel { margin-top: 12px; padding: 16px; background: #fafbfc; border-radius: 8px; border: 1px solid #ebeef5; }
.progress-panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.progress-content { }
.progress-bar-wrap { margin-bottom: 12px; }
.progress-summary { font-size: 13px; color: #606266; }
.step-timeline { display: flex; flex-direction: column; gap: 4px; }
.step-row { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 4px; font-size: 13px; }
.step-row.completed { background: #f0f9eb; }
.step-row.current { background: #ecf5ff; }
.step-icon { font-size: 14px; width: 20px; text-align: center; }
.step-order-num { width: 20px; height: 20px; border-radius: 50%; background: #c0c4cc; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; }
.step-row.completed .step-order-num { background: #67c23a; }
.step-row.current .step-order-num { background: #409eff; }
.step-process-name { font-weight: 500; min-width: 80px; }
.step-meta { color: #909399; font-size: 12px; }
.progress-empty { text-align: center; padding: 16px; }

</style>
