<template>
  <div class="design-manage-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="design-manage-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- Tab 1: 待确认任务 -->
      <el-tab-pane label="待确认任务" name="pending">
        <div ref="pendingPanelRef" class="table-card design-manage-panel">
        <FilterBar :pending="pendingState.hasPendingSearch.value" @search="searchPending" @reset="resetPendingFilters">
          <el-input v-model="pendingFilters.salesperson_name" placeholder="业务员" clearable class="filter-w-sm" />
          <el-select v-model="pendingFilters.shoot_type" placeholder="拍摄类型" clearable class="filter-w-sm">
            <el-option v-for="(label, code) in shootTypeMap" :key="code" :label="label" :value="code" />
          </el-select>
          <el-date-picker v-model="pendingFilters.expectDateRange" type="daterange" start-placeholder="期望开始" end-placeholder="期望结束" value-format="YYYY-MM-DD" class="filter-w-lg" />
        </FilterBar>
        <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
        <div class="action-bar">
          <GlassButton variant="secondary" left-icon="Bell" @click="handleScanShootReminders">
            预约任务扫描
          </GlassButton>
          <TableTools
            v-model:visible-keys="pendingVisibleKeys"
            v-model:density="pendingDensity"
            :columns="pendingColumnDefs"
            :fullscreen="pendingIsFullscreen"
            @refresh="fetchPending"
            @fullscreen="pendingToggleFullscreen"
          />
        </div>
        <ListPageStatus v-if="pendingState.hasData.value" :error="pendingState.errorMessage.value" :loading="pendingLoading" :has-data="true" :data-page="pendingState.dataPage.value" @retry="fetchPending" />
        <el-table
          ref="pendingTableRef"
          :data="pendingData"
          v-loading="pendingLoading"
          class="list-table"
          :class="pendingDensityClass"
          border
          :max-height="pendingIsFullscreen ? undefined : tabMaxHeight"
          @sort-change="handlePendingSortChange"
        >
          <template #empty>
            <ListPageStatus :error="pendingState.errorMessage.value" :loading="pendingLoading" @retry="fetchPending" />
            <el-empty v-if="pendingState.isEmpty.value" :image-size="96" :description="pendingHasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
              <GlassButton v-if="pendingHasActiveFilters" left-icon="RefreshLeft" @click="resetPendingFilters">重置筛选</GlassButton>
            </el-empty>
          </template>
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('request-no')" prop="request_no" label="预约编号" min-width="160" max-width="240" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('customer-level')" prop="customer_level" label="客户等级" min-width="90" max-width="130">
            <template #default="{ row }">{{ customerLevelLabel(row.customer_level) }}</template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('salesperson')" prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('shoot-type')" prop="shoot_type" label="拍摄类型" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="clickable-shoot-type" @click="openShootTypeDialog(row, 'request')">
                {{ buildDictLabel(row.shoot_type, shootTypeMap) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('expect-date')" label="期望日期" min-width="280" max-width="420" prop="expect_start_date">
            <template #default="{ row }">
              <span class="clickable-date" @click="openEditDateDialog(row)">
                {{ row.expect_start_date }} {{ periodLabel(row.expect_start_period) }} ~ {{ row.expect_end_date }} {{ periodLabel(row.expect_end_period) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('priority')" label="优先级" min-width="100" max-width="120" prop="priority">
            <template #default="{ row }">
              <StatusBadge :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </StatusBadge>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('remark')" prop="remark" label="备注" min-width="160" max-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <button v-any-permission="['design:write', 'design:manage']" type="button" class="clickable-remark" aria-label="修改预约备注" @click="openRemarkDialog(row)">
                {{ row.remark || '添加备注' }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </button>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="pendingVisibleKeys.includes('created-at')" prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column class-name="table-action-column" label="操作" min-width="180" max-width="260" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="View" @click="openDetail(row.id)">详情</GlassButton>
              <GlassButton variant="link" left-icon="Calendar" @click="openConfirmDialog(row)">确认排期</GlassButton>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="pager"
          v-model:current-page="pendingPage"
          v-model:page-size="pendingPageSize"
          :total="pendingTotal"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="fetchPending"
          @size-change="handlePendingSizeChange"
        />
        </div>
      </el-tab-pane>

      <!-- Tab 2: 排期任务 -->
      <el-tab-pane label="排期任务" name="scheduled">
        <div ref="scheduledPanelRef" class="table-card design-manage-panel">
        <FilterBar :pending="scheduledState.hasPendingSearch.value" @search="searchScheduled" @reset="resetScheduledFilters">
          <el-input v-model="scheduledFilters.salesperson_name" placeholder="业务员" clearable class="filter-w-sm" />
          <el-select v-model="scheduledFilters.shoot_type" placeholder="拍摄类型" clearable class="filter-w-sm">
            <el-option v-for="(label, code) in shootTypeMap" :key="code" :label="label" :value="code" />
          </el-select>
          <el-select v-model="scheduledFilters.designer_id" placeholder="设计师" clearable class="filter-w-sm">
            <el-option v-for="d in designerData" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-date-picker v-model="scheduledFilters.planDateRange" type="daterange" start-placeholder="排期开始" end-placeholder="排期结束" value-format="YYYY-MM-DD" class="filter-w-lg" />
        </FilterBar>
        <!-- 操作行：本 tab 无主操作按钮，右侧 TableTools 四图标（Action Bar Spec） -->
        <div class="action-bar">
          <TableTools
            v-model:visible-keys="scheduledVisibleKeys"
            v-model:density="scheduledDensity"
            :columns="scheduledColumnDefs"
            :fullscreen="scheduledIsFullscreen"
            @refresh="fetchScheduled"
            @fullscreen="scheduledToggleFullscreen"
          />
        </div>
        <ListPageStatus v-if="scheduledState.hasData.value" :error="scheduledState.errorMessage.value" :loading="scheduledLoading" :has-data="true" :data-page="scheduledState.dataPage.value" @retry="fetchScheduled" />
        <el-table
          ref="scheduledTableRef"
          :data="scheduledData"
          v-loading="scheduledLoading"
          class="list-table"
          :class="scheduledDensityClass"
          border
          :max-height="scheduledIsFullscreen ? undefined : tabMaxHeight"
          @sort-change="handleScheduledSortChange"
        >
          <template #empty>
            <ListPageStatus :error="scheduledState.errorMessage.value" :loading="scheduledLoading" @retry="fetchScheduled" />
            <el-empty v-if="scheduledState.isEmpty.value" :image-size="96" :description="scheduledHasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
              <GlassButton v-if="scheduledHasActiveFilters" left-icon="RefreshLeft" @click="resetScheduledFilters">重置筛选</GlassButton>
            </el-empty>
          </template>
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('task-no')" prop="task_no" label="任务编号" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('salesperson')" prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('shoot-type')" prop="shoot_type" label="拍摄类型" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="clickable-shoot-type" @click="openShootTypeDialog(row, 'task')">
                {{ buildDictLabel(row.shoot_type, shootTypeMap) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('designer')" prop="designer_name" label="设计师" min-width="120" max-width="170">
            <template #default="{ row }">
              <div v-if="editingDesignerId === row.id" class="inline-edit">
                <el-select v-model="editingDesignerValue" size="small" style="width: 100px" @change="saveDesigner(row)" @blur="cancelEditDesigner">
                  <el-option v-for="d in designerData" :key="d.id" :label="d.name" :value="d.id" />
                </el-select>
              </div>
              <span v-else class="clickable-cell" @click="startEditDesigner(row)">
                {{ getDesignerName(row.designer_id) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('plan-date')" label="排期日期" min-width="280" max-width="420" prop="plan_start_date">
            <template #default="{ row }">
              <span class="clickable-date" @click="openEditTaskDateDialog(row)">
                {{ row.plan_start_date || '-' }} {{ periodLabel(row.plan_start_period) }} ~ {{ row.plan_end_date || '-' }} {{ periodLabel(row.plan_end_period) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('priority')" prop="priority" label="优先级" min-width="100" max-width="120">
            <template #default="{ row }">
              <StatusBadge :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </StatusBadge>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('remark')" prop="remark" label="备注" min-width="180" max-width="300" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="remark-mixed">
                <div class="remark-line">
                  <span class="remark-tag task">排期</span>
                  <button v-any-permission="['design:write', 'design:manage']" type="button" class="clickable-remark" aria-label="修改排期备注" @click="openRemarkDialog(row, 'task')">
                    {{ row.remark || '添加备注' }}<el-icon class="edit-icon"><Edit /></el-icon>
                  </button>
                </div>
                <div class="remark-line">
                  <span class="remark-tag request">预约</span>
                  <button v-any-permission="['design:write', 'design:manage']" type="button" class="clickable-remark" aria-label="修改预约备注" @click="openRemarkDialog(row, 'request')">
                    {{ row.request_remark || '添加备注' }}<el-icon class="edit-icon"><Edit /></el-icon>
                  </button>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('status')" label="状态" min-width="110" max-width="150" prop="status">
            <template #default="{ row }">
              <StatusBadge :type="TASK_STATUS_TAG[row.status]" effect="plain">
                {{ TASK_STATUS_MAP[row.status] || row.status }}
              </StatusBadge>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="scheduledVisibleKeys.includes('created-at')" prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column class-name="table-action-column" label="操作" min-width="260" max-width="380" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="View" @click="openDetail(row.request_id)">详情</GlassButton>
              <GlassButton
                v-if="row.status === 'scheduled'"
                variant="link" left-icon="VideoPlay"
                @click="handleTaskAction(row, 'start')"
              >开始执行</GlassButton>
              <GlassButton
                v-if="row.status === 'in_progress'"
                v-any-permission="['customer_media:write', 'customer_media:admin']"
                variant="link" link-tone="success" left-icon="Upload"
                @click="$router.push(`/design/media/tasks/${row.id}`)"
              >上传素材</GlassButton>
              <GlassButton
                v-if="['scheduled', 'in_progress'].includes(row.status)"
                variant="link" link-tone="danger" left-icon="CircleClose"
                @click="handleTaskAction(row, 'cancel')"
              >取消</GlassButton>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="pager"
          v-model:current-page="scheduledPage"
          v-model:page-size="scheduledPageSize"
          :total="scheduledTotal"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="fetchScheduled"
          @size-change="handleScheduledSizeChange"
        />
        </div>
      </el-tab-pane>

      <!-- Tab 3: 已完成任务 -->
      <el-tab-pane label="已完成任务" name="completed">
        <div ref="completedPanelRef" class="table-card design-manage-panel">
        <FilterBar :pending="completedState.hasPendingSearch.value" @search="searchCompleted" @reset="resetCompletedFilters">
          <el-input v-model="completedFilters.salesperson_name" placeholder="业务员" clearable class="filter-w-sm" />
          <el-select v-model="completedFilters.shoot_type" placeholder="拍摄类型" clearable class="filter-w-sm">
            <el-option v-for="(label, code) in shootTypeMap" :key="code" :label="label" :value="code" />
          </el-select>
          <el-select v-model="completedFilters.designer_id" placeholder="设计师" clearable class="filter-w-sm">
            <el-option v-for="d in designerData" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-date-picker v-model="completedFilters.planDateRange" type="daterange" start-placeholder="排期开始" end-placeholder="排期结束" value-format="YYYY-MM-DD" class="filter-w-lg" />
        </FilterBar>
        <!-- 操作行：本 tab 无主操作按钮，右侧 TableTools 四图标（Action Bar Spec） -->
        <div class="action-bar">
          <TableTools
            v-model:visible-keys="completedVisibleKeys"
            v-model:density="completedDensity"
            :columns="completedColumnDefs"
            :fullscreen="completedIsFullscreen"
            @refresh="fetchCompleted"
            @fullscreen="completedToggleFullscreen"
          />
        </div>
        <ListPageStatus v-if="completedState.hasData.value" :error="completedState.errorMessage.value" :loading="completedLoading" :has-data="true" :data-page="completedState.dataPage.value" @retry="fetchCompleted" />
        <el-table
          ref="completedTableRef"
          :data="completedData"
          v-loading="completedLoading"
          class="list-table"
          :class="completedDensityClass"
          border
          :max-height="completedIsFullscreen ? undefined : tabMaxHeight"
          @sort-change="handleCompletedSortChange"
        >
          <template #empty>
            <ListPageStatus :error="completedState.errorMessage.value" :loading="completedLoading" @retry="fetchCompleted" />
            <el-empty v-if="completedState.isEmpty.value" :image-size="96" :description="completedHasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
              <GlassButton v-if="completedHasActiveFilters" left-icon="RefreshLeft" @click="resetCompletedFilters">重置筛选</GlassButton>
            </el-empty>
          </template>
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('task-no')" prop="task_no" label="任务编号" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('salesperson')" prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('shoot-type')" prop="shoot_type" label="拍摄类型" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ buildDictLabel(row.shoot_type, shootTypeMap) }}</template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('designer')" prop="designer_name" label="设计师" min-width="100" max-width="150">
            <template #default="{ row }">{{ getDesignerName(row.designer_id) }}</template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('plan-date')" label="排期日期" min-width="240" max-width="360" prop="plan_start_date">
            <template #default="{ row }">
              {{ row.plan_start_date || '-' }} {{ periodLabel(row.plan_start_period) }} ~ {{ row.plan_end_date || '-' }} {{ periodLabel(row.plan_end_period) }}
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('priority')" prop="priority" label="优先级" min-width="100" max-width="120">
            <template #default="{ row }">
              <StatusBadge :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </StatusBadge>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('status')" label="状态" min-width="110" max-width="120" prop="status">
            <template #default="{ row }">
              <StatusBadge type="success" effect="plain">已完成</StatusBadge>
            </template>
          </el-table-column>
          <el-table-column sortable="custom" v-if="completedVisibleKeys.includes('created-at')" prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column class-name="table-action-column" label="操作" min-width="100" max-width="150" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="View" @click="openDetail(row.request_id)">详情</GlassButton>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="pager"
          v-model:current-page="completedPage"
          v-model:page-size="completedPageSize"
          :total="completedTotal"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="fetchCompleted"
          @size-change="handleCompletedSizeChange"
        />
        </div>
      </el-tab-pane>

      <!-- Tab 4: 设计师管理 -->
      <el-tab-pane label="设计师管理" name="designers">
        <div ref="designerPanelRef" class="table-card design-manage-panel">
        <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
        <div class="action-bar">
          <GlassButton variant="primary" left-icon="Plus" @click="openDesignerDialog(null)">新建设计师</GlassButton>
          <TableTools
            v-model:visible-keys="designerVisibleKeys"
            v-model:density="designerDensity"
            :columns="designerColumnDefs"
            :fullscreen="designerIsFullscreen"
            @refresh="fetchDesigners"
            @fullscreen="designerToggleFullscreen"
          />
        </div>
        <ListPageStatus :error="designerResource.errorMessage.value" :loading="designerLoading" :has-data="designerData.length > 0" @retry="fetchDesigners" />
        <el-table
          :data="designerData"
          v-loading="designerLoading"
          class="list-table"
          :class="designerDensityClass"
          border
          :max-height="designerIsFullscreen ? undefined : tabMaxHeight"
        >
          <template #empty>
            <el-empty v-if="!designerLoading && !designerResource.error.value" :image-size="96" description="暂无数据" />
          </template>
          <el-table-column v-if="designerVisibleKeys.includes('id')" prop="id" label="ID" min-width="80" max-width="120" show-overflow-tooltip />
          <el-table-column v-if="designerVisibleKeys.includes('name')" prop="name" label="姓名" min-width="120" max-width="180" show-overflow-tooltip />
          <el-table-column v-if="designerVisibleKeys.includes('email')" prop="email" label="邮箱" min-width="180" max-width="270" show-overflow-tooltip />
          <el-table-column v-if="designerVisibleKeys.includes('dingtalk-id')" prop="dingtalk_id" label="钉钉ID" min-width="140" max-width="210" show-overflow-tooltip />
          <el-table-column prop="is_active" v-if="designerVisibleKeys.includes('status')" label="状态" min-width="100" max-width="150">
            <template #default="{ row }">
              <StatusBadge :type="row.is_active ? 'success' : 'info'" effect="plain">
                {{ row.is_active ? '在职' : '停用' }}
              </StatusBadge>
            </template>
          </el-table-column>
          <el-table-column v-if="designerVisibleKeys.includes('created-at')" prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column class-name="table-action-column" label="操作" min-width="150" max-width="230" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="Edit" @click="openDesignerDialog(row)">编辑</GlassButton>
              <GlassButton
                variant="link"
                :link-tone="row.is_active ? 'warning' : 'success'"
                left-icon="SwitchButton"
                @click="toggleDesignerActive(row)"
              >{{ row.is_active ? '停用' : '启用' }}</GlassButton>
            </template>
          </el-table-column>
        </el-table>
        </div>
      </el-tab-pane>

      <!-- Tab 5: 不可用日期 -->
      <el-tab-pane label="不可用日期" name="unavailable" lazy>
        <DesignCalendarConfig ref="calendarConfigRef" />
      </el-tab-pane>

      <!-- Tab 6: 容量配置 -->
      <el-tab-pane label="容量配置" name="capacity" lazy>
        <DesignCapacityConfig />
      </el-tab-pane>

      <!-- Tab 7: 批量导入 -->
      <el-tab-pane label="批量导入" name="import" lazy>
        <div class="import-section">
          <el-alert
            title="Excel 格式要求"
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          >
            <template #default>
              列顺序: 客户名称, 业务员姓名, 拍摄类型, 期望开始日期, 期望结束日期, 优先级, 备注<br/>
              拍摄类型: 产品图/模特图/视频/产品视频/其他 | 优先级: 普通/加急 | 日期格式: YYYY-MM-DD
            </template>
          </el-alert>
          <el-upload
            ref="uploadRef"
            action=""
            :auto-upload="false"
            :limit="1"
            accept=".xlsx,.xls"
            :on-change="onFileChange"
            :on-remove="() => importFile = null"
          >
            <template #trigger>
              <GlassButton variant="primary" :icon="Upload">选择文件</GlassButton>
            </template>
            <template #tip>
              <div class="el-upload__tip">仅支持 .xlsx / .xls 文件</div>
            </template>
          </el-upload>
          <GlassButton
            variant="success"
            style="margin-top: 12px"
            :disabled="!importFile"
            :loading="importing"
            @click="submitImport"
          >开始导入</GlassButton>
        </div>

        <!-- Import results dialog -->
        <el-dialog v-model="importResultVisible" title="导入结果" width="640px">
          <div v-if="importResult">
            <ResponsiveDescriptions :column="3" border size="small" style="margin-bottom: 16px">
              <el-descriptions-item label="总行数">{{ importResult.total }}</el-descriptions-item>
              <el-descriptions-item label="成功">
                <StatusBadge type="success" size="small">{{ importResult.success }}</StatusBadge>
              </el-descriptions-item>
              <el-descriptions-item label="失败">
                <StatusBadge type="danger" size="small">{{ importResult.failed }}</StatusBadge>
              </el-descriptions-item>
            </ResponsiveDescriptions>
            <el-table v-if="importResult.errors?.length" :data="importResult.errors" border size="small" max-height="300" class="list-table">
              <el-table-column prop="row" label="行号" min-width="80" />
              <el-table-column prop="reason" label="失败原因" />
            </el-table>
          </div>
        </el-dialog>
      </el-tab-pane>
    </el-tabs>

    <ConfirmSchedulingDialog
      v-model:visible="confirmVisible"
      :row="confirmRow" :form="confirmForm" :designers="designerData" :saving="confirming"
      @submit="submitConfirm"
    />

    <!-- Designer create/edit dialog -->
    <el-dialog
      v-model="designerDialogVisible"
      :title="designerForm.id ? '编辑设计师' : '新建设计师'"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top" :model="designerForm">
        <el-form-item label="姓名" required>
          <el-input v-model="designerForm.name" placeholder="请输入设计师姓名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="designerForm.email" placeholder="选填" />
        </el-form-item>
        <el-form-item label="钉钉ID">
          <el-input v-model="designerForm.dingtalk_id" placeholder="选填" />
        </el-form-item>
        <el-form-item label="状态" v-if="designerForm.id">
          <el-switch v-model="designerForm.is_active" active-text="在职" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="designerDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitDesigner" :loading="designerSaving">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 预约详情抽屉 -->
    <RequestDetailDrawer v-model="detailVisible" :request-id="detailRequestId" />

    <DesignManageEditDialogs
      v-model:edit-date-visible="editDateVisible" :edit-date-form="editDateForm" :edit-date-saving="editDateSaving" @submit-edit-date="submitEditDate"
      v-model:remark-visible="remarkVisible" :remark-target="remarkTarget" :remark-form="remarkForm" :remark-saving="remarkSaving" @submit-remark="submitRemark"
      v-model:edit-task-date-visible="editTaskDateVisible" :edit-task-date-form="editTaskDateForm" :edit-task-date-saving="editTaskDateSaving" @submit-edit-task-date="submitEditTaskDate"
      v-model:shoot-type-visible="shootTypeVisible" :shoot-type-form="shootTypeForm" :shoot-type-saving="shootTypeSaving" :shoot-type-map="shootTypeMap" @submit-shoot-type="submitShootType"
    />
  </div>
</template>

<script setup>
import {
  Upload, Plus, Calendar, VideoPlay, CircleCheck, CircleClose, Edit, SwitchButton, Bell, Search, RefreshLeft
} from '@element-plus/icons-vue'
import { buildDictLabel } from '@/utils/dict'
import DesignCalendarConfig from '@/components/design/DesignCalendarConfig.vue'
import DesignCapacityConfig from '@/components/design/DesignCapacityConfig.vue'
import ConfirmSchedulingDialog from './components/ConfirmSchedulingDialog.vue'
import DesignManageEditDialogs from './components/DesignManageEditDialogs.vue'
import RequestDetailDrawer from '@/components/design/RequestDetailDrawer.vue'
import TableTools from '@/components/TableTools.vue'
import { useDesignManage } from './composables/useDesignManage'

const {
  // 字典 / 工具
  shootTypeMap, customerLevelMap, customerLevelLabel, getDesignerName,
  periodLabel, TASK_STATUS_MAP, TASK_STATUS_TAG,
  // Tab + Detail
  activeTab, tabMaxHeight, detailVisible, detailRequestId, openDetail, onTabChange,
  calendarConfigRef,
  // Edit dialogs
  editDateVisible, editDateSaving, editDateForm, openEditDateDialog, submitEditDate,
  remarkVisible, remarkSaving, remarkTarget, remarkForm, openRemarkDialog, submitRemark,
  shootTypeVisible, shootTypeSaving, shootTypeTarget, shootTypeForm,
  openShootTypeDialog, submitShootType,
  editingDesignerId, editingDesignerValue,
  startEditDesigner, cancelEditDesigner, saveDesigner,
  editTaskDateVisible, editTaskDateSaving, editTaskDateForm,
  openEditTaskDateDialog, submitEditTaskDate,
  // Pending
  pendingTableRef, pendingData, pendingLoading,
  pendingPage, pendingPageSize, pendingTotal, pendingFilters,
  pendingState, fetchPending, handleScanShootReminders, pendingSort, handlePendingSortChange,
  pendingHasActiveFilters, searchPending, resetPendingFilters, handlePendingSizeChange,
  pendingColumnDefs, pendingDensity, pendingDensityClass, pendingVisibleKeys,
  pendingPanelRef, pendingIsFullscreen, pendingToggleFullscreen,
  // Scheduled
  scheduledTableRef, scheduledData, scheduledLoading,
  scheduledPage, scheduledPageSize, scheduledTotal, scheduledFilters,
  scheduledState, fetchScheduled, scheduledSort, handleScheduledSortChange,
  scheduledHasActiveFilters, searchScheduled, resetScheduledFilters, handleScheduledSizeChange,
  scheduledColumnDefs, scheduledDensity, scheduledDensityClass, scheduledVisibleKeys,
  scheduledPanelRef, scheduledIsFullscreen, scheduledToggleFullscreen,
  // Completed
  completedTableRef, completedData, completedLoading,
  completedPage, completedPageSize, completedTotal, completedFilters,
  completedState, fetchCompleted, completedSort, handleCompletedSortChange,
  completedHasActiveFilters, searchCompleted, resetCompletedFilters, handleCompletedSizeChange,
  completedColumnDefs, completedDensity, completedDensityClass, completedVisibleKeys,
  completedPanelRef, completedIsFullscreen, completedToggleFullscreen,
  // Designers
  designerResource, designerData, designerLoading, fetchDesigners,
  designerColumnDefs, designerDensity, designerDensityClass, designerVisibleKeys,
  designerPanelRef, designerIsFullscreen, designerToggleFullscreen,
  designerDialogVisible, designerSaving, designerForm,
  openDesignerDialog, submitDesigner, toggleDesignerActive,
  // Confirm
  confirmVisible, confirmRow, confirming, confirmForm,
  openConfirmDialog, submitConfirm,
  // Task action / Gantt
  handleTaskAction, handleReschedule,
  // Import
  uploadRef, importFile, importing,
  importResultVisible, importResult,
  onFileChange, submitImport,
} = useDesignManage()
</script>

<style scoped src="./design-manage-layout.css"></style>
<style scoped>
.remark-tag.task {
  background: rgba(64, 158, 255, 0.15);
  color: #409eff;
}
.remark-tag.request {
  background: rgba(103, 194, 58, 0.15);
  color: #67c23a;
}
</style>
