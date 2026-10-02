<template>
  <div class="production-order-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="prod-order-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 统计卡 -->
    <div class="stats-row">
      <div class="stat-card lg-card submitted">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#409eff"><Document /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">已提交</div>
          <div class="stat-value">{{ statusCount.submitted }}</div>
        </div>
      </div>
      <div class="stat-card lg-card terminated">
        <div class="stat-icon-bg">
          <el-icon :size="28" color="#909399"><CircleClose /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-label">已终止</div>
          <div class="stat-value">{{ statusCount.terminated }}</div>
        </div>
      </div>
      <div class="stat-card lg-card completed">
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
        <div ref="orderPanelRef" class="table-card">
          <FilterBar :pending="orderState.hasPendingSearch.value" @search="handleOrderSearch" @reset="resetOrderFilters">
            <el-select v-model="orderFilters.status" placeholder="状态" clearable class="filter-w-sm">
              <el-option label="已提交" :value="0" />
              <el-option label="已终止" :value="1" />
              <el-option label="已完成" :value="2" />
            </el-select>
            <el-input v-model="orderFilters.keyword" placeholder="搜索单号/批次号" clearable class="filter-w-md" />
          </FilterBar>
          <!-- 操作行：本页无页面级主操作，右侧 TableTools 四图标（Action Bar Spec） -->
          <div class="action-bar">
            <TableTools
              v-model:visible-keys="orderVisibleKeys"
              v-model:density="orderDensity"
              :columns="orderColumnDefs"
              :fullscreen="orderIsFullscreen"
              @refresh="loadOrderList"
              @fullscreen="orderToggleFullscreen"
            />
          </div>
          <ListPageStatus v-if="orderState.hasData.value" :error="orderState.errorMessage.value" :loading="orderLoading" :has-data="true" :data-page="orderState.dataPage.value" @retry="loadOrderList" />
          <el-table :data="orderList" style="width:100%" :header-cell-style="headerStyle" v-loading="orderLoading" border class="list-table" :class="orderDensityClass" :max-height="orderIsFullscreen ? undefined : 640" @sort-change="handleOrderSortChange">
            <template #empty>
              <ListPageStatus :error="orderState.errorMessage.value" :loading="orderLoading" @retry="loadOrderList" />
              <el-empty v-if="orderState.isEmpty.value" :image-size="96" :description="hasActiveOrderFilters ? '没有符合条件的记录' : '暂无数据'">
                <GlassButton v-if="hasActiveOrderFilters" :left-icon="RefreshRight" @click="resetOrderFilters">重置筛选</GlassButton>
              </el-empty>
            </template>
            <el-table-column v-if="orderVisibleKeys.includes('order-no')" label="生产单号" prop="order_no" min-width="130" max-width="195" sortable="custom" show-overflow-tooltip />
            <el-table-column v-if="orderVisibleKeys.includes('batch-no')" label="生产批次号" prop="batch_no" min-width="130" max-width="195" sortable="custom" show-overflow-tooltip />
            <el-table-column v-if="orderVisibleKeys.includes('created-by')" label="创建人" min-width="100" max-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ row.created_by_name || '-' }}</template>
            </el-table-column>
            <el-table-column v-if="orderVisibleKeys.includes('created-at')" label="创建时间" prop="created_at" min-width="140" max-width="210" sortable="custom" show-overflow-tooltip>
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column v-if="orderVisibleKeys.includes('item-count')" label="明细数" min-width="80" max-width="120" prop="item_count" show-overflow-tooltip />
            <el-table-column v-if="orderVisibleKeys.includes('total-order-qty')" label="总下单量" min-width="90" max-width="135" prop="total_order_qty" show-overflow-tooltip />
            <el-table-column v-if="orderVisibleKeys.includes('total-received-qty')" label="总入库量" min-width="90" max-width="135" prop="total_received_qty" show-overflow-tooltip />
            <el-table-column v-if="orderVisibleKeys.includes('in-transit-qty')" label="在途量" min-width="80" max-width="120">
              <template #default="{ row }">
                <span :class="row.total_in_transit_qty > 0 ? 'in-transit-active' : ''">{{ row.total_in_transit_qty }}</span>
              </template>
            </el-table-column>
            <el-table-column v-if="orderVisibleKeys.includes('status')" label="状态" prop="status" min-width="120" max-width="135" sortable="custom">
              <template #default="{ row }">
                <StatusBadge :type="statusTagType(row.status)" size="small" effect="plain">{{ row.status_label }}</StatusBadge>
              </template>
            </el-table-column>
            <el-table-column class-name="table-action-column" label="操作" min-width="260" max-width="390" fixed="right">
              <template #default="{ row }">
                <div class="table-actions">
                  <GlassButton variant="link" left-icon="View" @click="viewOrderDetail(row)">详情</GlassButton>
                  <GlassButton variant="link" left-icon="Edit" @click="editOrder(row)">编辑</GlassButton>
                  <el-dropdown trigger="click" @command="(cmd) => handlePrintCommand(cmd, row)">
                    <GlassButton variant="link" left-icon="Printer">打印</GlassButton>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="order">打印生产单</el-dropdown-item>
                        <el-dropdown-item command="process_card">打印工序卡片</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                  <GlassButton variant="link" left-icon="Download" @click="exportOrder(row)">导出</GlassButton>
                  <GlassButton variant="link" left-icon="Refresh" @click="handleResetProcess(row)">重置工艺</GlassButton>
                  <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="deleteOrder(row)" v-if="authStore.hasPermission('production:admin')">删除</GlassButton>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination v-model:current-page="orderPagination.page" v-model:page-size="orderPagination.page_size" :total="orderPagination.total"
            :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager"
            @size-change="handleOrderSizeChange" @current-change="loadOrderList" />
        </div>
      </el-tab-pane>

      <!-- 标签页二：按明细维度 -->
      <el-tab-pane label="按生产单产品明细维度" name="item">
        <div ref="itemPanelRef" class="table-card">
          <FilterBar :pending="itemState.hasPendingSearch.value" @search="handleItemSearch" @reset="resetItemFilters">
            <el-select v-model="itemFilters.status" placeholder="明细状态" clearable class="filter-w-sm">
              <el-option label="已提交" :value="0" />
              <el-option label="已终止" :value="1" />
              <el-option label="已完成" :value="2" />
            </el-select>
            <el-input v-model="itemFilters.keyword" placeholder="搜索产品/单号/批次号" clearable class="filter-w-md" />
          </FilterBar>
          <!-- 操作行：本页无页面级主操作，右侧 TableTools 四图标（Action Bar Spec） -->
          <div class="action-bar">
            <TableTools
              v-model:visible-keys="itemVisibleKeys"
              v-model:density="itemDensity"
              :columns="itemColumnDefs"
              :fullscreen="itemIsFullscreen"
              @refresh="loadItemList"
              @fullscreen="itemToggleFullscreen"
            />
          </div>
          <ListPageStatus v-if="itemState.hasData.value" :error="itemState.errorMessage.value" :loading="itemLoading" :has-data="true" :data-page="itemState.dataPage.value" @retry="loadItemList" />
          <el-table :data="itemList" style="width:100%" :header-cell-style="headerStyle" v-loading="itemLoading" border class="list-table" :class="itemDensityClass" :max-height="itemIsFullscreen ? undefined : 640" @sort-change="handleItemSortChange">
            <template #empty>
              <ListPageStatus :error="itemState.errorMessage.value" :loading="itemLoading" @retry="loadItemList" />
              <el-empty v-if="itemState.isEmpty.value" :image-size="96" :description="hasActiveItemFilters ? '没有符合条件的记录' : '暂无数据'">
                <GlassButton v-if="hasActiveItemFilters" :left-icon="RefreshRight" @click="resetItemFilters">重置筛选</GlassButton>
              </el-empty>
            </template>
            <el-table-column v-if="itemVisibleKeys.includes('order-no')" label="生产单号" prop="order_no" min-width="130" max-width="195" sortable="custom" show-overflow-tooltip />
            <el-table-column v-if="itemVisibleKeys.includes('batch-no')" label="批次号" prop="batch_no" min-width="120" max-width="180" sortable="custom" show-overflow-tooltip />
            <el-table-column v-if="itemVisibleKeys.includes('product-name')" label="产品名称" prop="product_name" min-width="140" max-width="210" sortable="custom" show-overflow-tooltip />
            <el-table-column v-if="itemVisibleKeys.includes('model')" label="型号" prop="model" min-width="100" max-width="150" sortable="custom" show-overflow-tooltip />
            <el-table-column v-if="itemVisibleKeys.includes('order-qty')" label="下单数量" min-width="90" max-width="135" prop="order_qty" sortable="custom" show-overflow-tooltip />
            <el-table-column v-if="itemVisibleKeys.includes('received-qty')" label="已入库" min-width="80" max-width="120" prop="received_qty" sortable="custom" show-overflow-tooltip />
            <el-table-column v-if="itemVisibleKeys.includes('in-transit')" label="在途" min-width="70" max-width="105">
              <template #default="{ row }">
                <span :class="row.in_transit_qty > 0 ? 'in-transit-active' : ''">{{ row.in_transit_qty }}</span>
              </template>
            </el-table-column>
            <el-table-column v-if="itemVisibleKeys.includes('item-status')" label="明细状态" min-width="120" max-width="135">
              <template #default="{ row }">
                <StatusBadge :type="statusTagType(row.status)" size="small" effect="plain">{{ row.status_label }}</StatusBadge>
              </template>
            </el-table-column>
            <el-table-column v-if="itemVisibleKeys.includes('order-status')" label="订单状态" min-width="120" max-width="135">
              <template #default="{ row }">
                <StatusBadge :type="statusTagType(row.order_status)" size="small" effect="plain">{{ row.order_status_label }}</StatusBadge>
              </template>
            </el-table-column>
            <el-table-column v-if="itemVisibleKeys.includes('urgent')" label="加急" min-width="100" max-width="105">
              <template #default="{ row }">
                <StatusBadge v-if="row.is_urgent" type="danger" size="small" effect="plain">加急</StatusBadge>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column v-if="itemVisibleKeys.includes('expected-delivery')" label="预计交期" min-width="110" max-width="165">
              <template #default="{ row }">{{ row.expected_delivery_date || '—' }}</template>
            </el-table-column>
            <el-table-column class-name="table-action-column" label="操作" min-width="260" max-width="390" fixed="right">
              <template #default="{ row }">
                <GlassButton variant="link" left-icon="Edit" @click="editItem(row)">编辑</GlassButton>
                <GlassButton variant="link" left-icon="VideoPause" @click="changeItemStatus(row)">改状态</GlassButton>
                <GlassButton variant="link" left-icon="Box" @click="inputReceived(row)">入库</GlassButton>
                <GlassButton link-tone="primary" variant="link" left-icon="List" @click="toggleItemProgress(row)">进度</GlassButton>
                <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="deleteItem(row)" v-if="authStore.hasPermission('production:admin')">删除</GlassButton>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination v-model:current-page="itemPagination.page" v-model:page-size="itemPagination.page_size" :total="itemPagination.total"
            :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager"
            @size-change="handleItemSizeChange" @current-change="loadItemList" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 订单详情弹窗 -->
    <DetailDrawer v-model="detailDialogVisible" title="生产订单详情" width="760px">
      <ListPageStatus :error="orderDetailResource.errorMessage.value" :loading="orderDetailResource.loading.value" :has-data="!!currentOrder" @retry="orderDetailResource.load()" />
      <div v-if="currentOrder" class="order-detail">
        <div class="detail-header">
          <div class="detail-row"><span class="detail-label">生产单号</span><span class="detail-value">{{ currentOrder.order_no }}</span></div>
          <div class="detail-row"><span class="detail-label">批次号</span><span class="detail-value">{{ currentOrder.batch_no }}</span></div>
          <div class="detail-row"><span class="detail-label">状态</span><StatusBadge :type="statusTagType(currentOrder.status)">{{ currentOrder.status_label }}</StatusBadge></div>
          <div class="detail-row"><span class="detail-label">创建人</span><span class="detail-value">{{ currentOrder.created_by_name || '-' }}</span></div>
          <div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">{{ formatDate(currentOrder.created_at) }}</span></div>
          <div class="detail-row"><span class="detail-label">备注</span><span class="detail-value">{{ currentOrder.remark || '-' }}</span></div>
        </div>
        <el-divider />
        <div class="detail-subtitle">产品明细</div>
        <el-table :data="currentOrder.items || []" border class="list-table">
          <el-table-column class-name="table-action-column" label="操作" min-width="140" max-width="210">
            <template #default="{ row }">
              <GlassButton link-tone="primary" variant="link" left-icon="List" @click="toggleItemProgress(row)">进度</GlassButton>
              <GlassButton variant="link" left-icon="Printer" @click="printCard(row)">打印流转卡</GlassButton>
            </template>
          </el-table-column>
          <el-table-column label="产品名称" prop="product_name" min-width="140" show-overflow-tooltip />
          <el-table-column label="型号" prop="model" min-width="100" show-overflow-tooltip />
          <el-table-column label="下单量" min-width="80" max-width="120" prop="order_qty" show-overflow-tooltip />
          <el-table-column label="已入库" min-width="80" max-width="120" prop="received_qty" show-overflow-tooltip />
          <el-table-column label="在途" min-width="70" max-width="105">
            <template #default="{ row }"><span :class="row.in_transit_qty > 0 ? 'in-transit-active' : ''">{{ row.in_transit_qty }}</span></template>
          </el-table-column>
          <el-table-column label="加急" min-width="100" max-width="105">
            <template #default="{ row }">
              <StatusBadge v-if="row.is_urgent" type="danger" size="small" effect="plain">加急</StatusBadge>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="预计交期" min-width="100" max-width="150">
            <template #default="{ row }">{{ row.expected_delivery_date || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" min-width="120" max-width="120">
            <template #default="{ row }"><StatusBadge :type="statusTagType(row.status)" size="small" effect="plain">{{ statusLabel(row.status) }}</StatusBadge></template>
          </el-table-column>
        </el-table>

        <!-- 工序进度看板（按需展开） -->
        <template v-for="item in (currentOrder.items || [])" :key="'progress-' + item.id">
          <div v-if="expandedProgressId === item.id" class="progress-panel">
            <div class="progress-panel-header">
              <span class="detail-subtitle">工序进度：{{ item.product_name }}</span>
              <div>
                <el-button link @click="refreshProgress(item.id)">刷新</el-button>
                <el-button link @click="expandedProgressId = null">收起</el-button>
              </div>
            </div>
            <ListPageStatus :error="progressResource.errorMessage.value" :loading="progressLoading" :has-data="!!progressResource.data.value?.progress" @retry="progressResource.load()" />
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
    </DetailDrawer>

    <!-- 编辑订单弹窗 -->
    <el-dialog v-model="editOrderDialogVisible" title="编辑生产订单" width="480px">
      <el-form label-position="top" :model="editOrderForm">
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
      <el-form label-position="top" :model="editItemForm">
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
    <el-dialog v-model="statusDialogVisible" title="修改状态" width="480px">
      <div v-if="currentItem" class="status-dialog-content">
        <p style="margin-bottom:16px;">产品：{{ currentItem.product_name }}</p>
        <p style="margin-bottom:16px;">当前状态：<StatusBadge :type="statusTagType(currentItem.status)">{{ currentItem.status_label }}</StatusBadge></p>
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
    <el-dialog v-model="receivedDialogVisible" title="录入已入库数量" width="480px">
      <div v-if="currentItem" class="received-dialog-content">
        <p style="margin-bottom:8px;">产品：{{ currentItem.product_name }}</p>
        <p style="margin-bottom:8px;">生产下单数量：{{ currentItem.order_qty }}</p>
        <p style="margin-bottom:16px;">当前已入库：{{ currentItem.received_qty }}</p>
        <el-form label-position="top" :model="receivedForm">
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
      <ListPageStatus :error="progressResource.errorMessage.value" :loading="progressLoading" :has-data="!!progressResource.data.value?.progress" @retry="progressResource.load()" />
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
    <el-dialog v-model="printDialogVisible" :title="printDialogTitle" width="480px" top="2vh" destroy-on-close>
      <StimulsoftViewer
        :report-code="currentReportCode"
        :params="{ order_no: currentPrintOrderNo }"
        height="80vh"
      />
    </el-dialog>
  </div>
</template>

<script setup>import { msgSuccessText, msgError, confirmAction, msgWarning } from '@/utils/feedback'
import { computed, ref, reactive, watch } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { loadStockProgress } from './composables/stockResources'
import { useRouter } from 'vue-router'

import { Document, CircleClose, CircleCheck, Filter, Loading, RefreshRight } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useTableSort } from '@/composables/useTableSort'
import { formatBeijingDateTime, formatBeijingShortDateTime } from '@/utils/datetime'
import StimulsoftViewer from '@/components/StimulsoftViewer.vue'
import TableTools from '@/components/TableTools.vue'
import { useProductionOrderTables } from './composables/useProductionOrderTables'
import {
  getProductionOrders, getProductionOrderDetail, updateProductionOrder,
  deleteProductionOrder, getProductionOrderItems, updateProductionOrderItem,
  updateProductionItemStatus, updateProductionItemReceived, deleteProductionOrderItem,
  resetOrderProcess,
} from '@/api/stock'

const router = useRouter()
const authStore = useAuthStore()

// 两个维度表格各自的视图状态（列显隐/密度/全屏），columnDefs 仅供 TableTools 列显隐面板
const {
  orderColumnDefs, orderDensity, orderDensityClass, orderVisibleKeys, orderPanelRef, orderIsFullscreen, orderToggleFullscreen,
  itemColumnDefs, itemDensity, itemDensityClass, itemVisibleKeys, itemPanelRef, itemIsFullscreen, itemToggleFullscreen,
} = useProductionOrderTables()

const orderSort = useTableSort()
const itemSort = useTableSort()
function handleOrderSortChange(sortInfo) {
  orderSort.onSortChange(sortInfo)
  return orderState.handleSortChange(orderSort.sortParams.value)
}
function handleItemSortChange(sortInfo) {
  itemSort.onSortChange(sortInfo)
  return itemState.handleSortChange(itemSort.sortParams.value)
}

const activeTab = ref('order')
const statusCount = reactive({ submitted: 0, terminated: 0, completed: 0 })

const statusTagType = (s) => ({ 0: 'primary', 1: 'info', 2: 'success' })[s] || 'info'
const statusLabel = (s) => ({ 0: '已提交', 1: '已终止', 2: '已完成' })[s] || '未知'
const headerStyle = () => ({ fontWeight: 600 })

function formatDate(iso) {
  return formatBeijingDateTime(iso, { seconds: false })
}

// ── 订单维度 ────────────────────────────
const orderState = useListPage(async (params, { signal, isCurrent }) => {
  const response = await getProductionOrders({ ...params, keyword: params.keyword || undefined }, { signal, suppressToast: true })
  const data = response.data
  if (isCurrent()) {
    statusCount.submitted = (data.items || []).filter(item => item.status === 0).length
    statusCount.terminated = (data.items || []).filter(item => item.status === 1).length
    statusCount.completed = (data.items || []).filter(item => item.status === 2).length
  }
  return { items: data.items || [], total: data.total || 0 }
}, { searchForm: { status: null, keyword: '' }, sortParams: orderSort.sortParams.value })
const orderLoading = orderState.loading; const orderList = orderState.list
const orderPagination = reactive({ total: orderState.total, page: orderState.page, page_size: orderState.pageSize })
const orderFilters = orderState.searchForm
const hasActiveOrderFilters = computed(() => Boolean(orderFilters.keyword) || (orderFilters.status !== null && orderFilters.status !== undefined))
const loadOrderList = orderState.fetchList
const handleOrderSearch = orderState.handleSearch
function resetOrderFilters() { orderSort.reset(); return orderState.handleReset({ sortParams: orderSort.sortParams.value }) }
const handleOrderSizeChange = orderState.handleSizeChange

// ── 明细维度 ────────────────────────────
const itemState = useListPage(async (params, { signal, isCurrent }) => {
  const response = await getProductionOrderItems({ ...params, keyword: params.keyword || undefined }, { signal, suppressToast: true })
  const data = response.data
  return { items: data.items || [], total: data.total || 0 }
}, { immediate: false, searchForm: { status: null, keyword: '' }, sortParams: itemSort.sortParams.value })
const itemLoading = itemState.loading; const itemList = itemState.list
const itemPagination = reactive({ total: itemState.total, page: itemState.page, page_size: itemState.pageSize })
const itemFilters = itemState.searchForm
const hasActiveItemFilters = computed(() => Boolean(itemFilters.keyword) || (itemFilters.status !== null && itemFilters.status !== undefined))
const loadItemList = itemState.fetchList
const handleItemSearch = itemState.handleSearch
function resetItemFilters() { itemSort.reset(); return itemState.handleReset({ sortParams: itemSort.sortParams.value }) }
const handleItemSizeChange = itemState.handleSizeChange

watch(activeTab, (tab) => {
  if (tab === 'order') loadOrderList()
  else loadItemList()
})

// ── 订单详情 ────────────────────────────
const detailDialogVisible = ref(false)
const orderDetailResource = useAsyncResource(async (id, { signal }) => {
  const response = await getProductionOrderDetail(id, { signal, suppressToast: true })
  return response.data
})
const currentOrder = orderDetailResource.data

async function viewOrderDetail(row) {
  detailDialogVisible.value = true
  expandedProgressId.value = null
  return orderDetailResource.load(row.id, { clear: true })
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
    msgSuccessText('已更新')
    editOrderDialogVisible.value = false
    orderState.refreshUpdate()
  } catch (e) {
    msgError(e?.response?.data?.message || '更新失败', e)
  } finally {
    editOrderLoading.value = false
  }
}

// ── 删除订单 ────────────────────────────
async function deleteOrder(row) {
  try {
    await confirmAction(`确定删除生产订单 ${row.order_no}?`, '删除确认', { type: 'warning' })
    await deleteProductionOrder(row.id)
    msgSuccessText('已删除')
    orderState.refreshRemove()
  } catch {
    // cancel
  }
}

async function handleResetProcess(row) {
  try {
    await confirmAction(
      `将删除订单 ${row.order_no} 下所有产品的工序进度，按最新工艺路线重新生成。确定继续？`,
      '重置工艺确认', { type: 'warning' }
    )
    const res = await resetOrderProcess(row.id)
    const data = res.data || res
    if (data.errors && data.errors.length > 0) {
      msgWarning(`重置完成：成功 ${data.success}/${data.total}，${data.errors.length} 个产品未绑定路线`)
    } else {
      msgSuccessText(`工艺重置完成，共 ${data.success} 个产品`)
    }
    progressData.value = {}
    if (currentOrder.value?.id === row.id) {
      orderDetailResource.load(row.id)
      if (expandedProgressId.value) loadProgress(expandedProgressId.value)
    }
    if (progressDialogVisible.value && progressDialogItem.value?.order_id === row.id) loadProgress(progressDialogItem.value.id)
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
    msgSuccessText('已更新')
    editItemDialogVisible.value = false
    itemState.refreshUpdate(); orderState.refreshUpdate()
  } catch (e) {
    msgError(e?.response?.data?.message || '更新失败', e)
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
    msgSuccessText('状态已更新')
    statusDialogVisible.value = false
    itemState.refreshUpdate(); orderState.refreshUpdate()
  } catch (e) {
    msgError(e?.response?.data?.message || '更新失败', e)
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
    msgSuccessText('入库数量已更新')
    receivedDialogVisible.value = false
    itemState.refreshUpdate(); orderState.refreshUpdate()
  } catch (e) {
    msgError(e?.response?.data?.message || '更新失败', e)
  } finally {
    receivedLoading.value = false
  }
}

// ── 删除明细 ────────────────────────────
async function deleteItem(row) {
  try {
    await confirmAction(`确定删除明细 ${row.product_name}?`, '删除确认', { type: 'warning' })
    await deleteProductionOrderItem(row.id)
    msgSuccessText('已删除')
    itemState.refreshRemove(); orderState.refreshUpdate()
  } catch {
    // cancel
  }
}



// ── 工序进度看板 ──────────────────────────
const expandedProgressId = ref(null)
const progressData = ref({})
const progressResource = useAsyncResource(async (itemId, context) => ({ itemId, progress: await loadStockProgress(itemId, context) }))
const progressLoading = progressResource.loading
watch(progressResource.data, result => { if (result) progressData.value[result.itemId] = result.progress })
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
  return formatBeijingShortDateTime(dt)
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

function loadProgress(itemId) { progressData.value[itemId] = null; return progressResource.load(itemId, { clear: true }) }

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

function exportOrder(row) {
  const reviewerName = encodeURIComponent(authStore.user?.real_name || '')
  const url = `/api/report/export/production-order?order_no=${encodeURIComponent(row.order_no)}&reviewer=${reviewerName}`
  window.open(url, '_blank')
}
</script>

<style scoped src="./production-order-manage.css"></style>
