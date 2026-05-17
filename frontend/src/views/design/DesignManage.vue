<template>
  <div>
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- Tab 1: 待确认任务 -->
      <el-tab-pane label="待确认任务" name="pending">
        <div class="tab-toolbar">
          <GlassButton variant="secondary" left-icon="Bell" @click="handleScanShootReminders">
            预约任务扫描
          </GlassButton>
        </div>
        <div class="filter-bar">
          <el-input v-model="pendingFilters.salesperson_name" placeholder="业务员" clearable style="width: 120px" @clear="fetchPending" @keyup.enter="fetchPending" />
          <el-select v-model="pendingFilters.shoot_type" placeholder="拍摄类型" clearable style="width: 130px" @change="fetchPending">
            <el-option v-for="(label, code) in shootTypeMap" :key="code" :label="label" :value="code" />
          </el-select>
          <el-date-picker v-model="pendingFilters.expectDateRange" type="daterange" start-placeholder="期望开始" end-placeholder="期望结束" value-format="YYYY-MM-DD" style="width: 260px" @change="fetchPending" />
        </div>
        <div class="table-card">
        <el-table
          ref="pendingTableRef"
          :data="pendingData"
          v-loading="pendingLoading"
          class="list-table"
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="request_no" label="预约编号" min-width="160" max-width="240" show-overflow-tooltip />
          <el-table-column prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
          <el-table-column prop="customer_level" label="客户等级" min-width="90" max-width="130">
            <template #default="{ row }">{{ customerLevelLabel(row.customer_level) }}</template>
          </el-table-column>
          <el-table-column prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
          <el-table-column label="拍摄类型" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="clickable-shoot-type" @click="openShootTypeDialog(row, 'request')">
                {{ buildDictLabel(row.shoot_type, shootTypeMap) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="期望日期" min-width="280" max-width="420">
            <template #default="{ row }">
              <span class="clickable-date" @click="openEditDateDialog(row)">
                {{ row.expect_start_date }} {{ periodLabel(row.expect_start_period) }} ~ {{ row.expect_end_date }} {{ periodLabel(row.expect_end_period) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="优先级" min-width="80" max-width="120">
            <template #default="{ row }">
              <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="备注" min-width="160" max-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="clickable-remark" @click="openRemarkDialog(row)">
                {{ row.remark || '-' }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column label="操作" min-width="180" max-width="260" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="View" @click="openDetail(row.id)">详情</GlassButton>
              <GlassButton variant="link" left-icon="Calendar" @click="openConfirmDialog(row)">确认排期</GlassButton>
            </template>
          </el-table-column>
        </el-table>
        </div>

        <el-pagination
          class="pagination"
          v-model:current-page="pendingPage"
          v-model:page-size="pendingPageSize"
          :total="pendingTotal"
          layout="total, prev, pager, next"
          @current-change="fetchPending"
        />
      </el-tab-pane>

      <!-- Tab 2: 排期任务 -->
      <el-tab-pane label="排期任务" name="scheduled">
        <div class="filter-bar">
          <el-input v-model="scheduledFilters.salesperson_name" placeholder="业务员" clearable style="width: 120px" @clear="fetchScheduled" @keyup.enter="fetchScheduled" />
          <el-select v-model="scheduledFilters.shoot_type" placeholder="拍摄类型" clearable style="width: 130px" @change="fetchScheduled">
            <el-option v-for="(label, code) in shootTypeMap" :key="code" :label="label" :value="code" />
          </el-select>
          <el-select v-model="scheduledFilters.designer_id" placeholder="设计师" clearable style="width: 120px" @change="fetchScheduled">
            <el-option v-for="d in designerData" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-date-picker v-model="scheduledFilters.planDateRange" type="daterange" start-placeholder="排期开始" end-placeholder="排期结束" value-format="YYYY-MM-DD" style="width: 260px" @change="fetchScheduled" />
        </div>
        <div class="table-card">
        <el-table
          ref="scheduledTableRef"
          :data="scheduledData"
          v-loading="scheduledLoading"
          class="list-table"
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="task_no" label="任务编号" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
          <el-table-column prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
          <el-table-column label="拍摄类型" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="clickable-shoot-type" @click="openShootTypeDialog(row, 'task')">
                {{ buildDictLabel(row.shoot_type, shootTypeMap) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="设计师" min-width="120" max-width="170">
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
          <el-table-column label="排期日期" min-width="280" max-width="420">
            <template #default="{ row }">
              <span class="clickable-date" @click="openEditTaskDateDialog(row)">
                {{ row.plan_start_date || '-' }} {{ periodLabel(row.plan_start_period) }} ~ {{ row.plan_end_date || '-' }} {{ periodLabel(row.plan_end_period) }}
                <el-icon class="edit-icon"><Edit /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="优先级" min-width="80" max-width="120">
            <template #default="{ row }">
              <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="备注" min-width="180" max-width="300" show-overflow-tooltip>
            <template #default="{ row }">
              <div v-if="row.remark || row.request_remark" class="remark-mixed">
                <div v-if="row.remark" class="remark-line">
                  <span class="remark-tag task">排期</span>{{ row.remark }}
                </div>
                <div v-if="row.request_remark" class="remark-line">
                  <span class="remark-tag request">预约</span>{{ row.request_remark }}
                </div>
              </div>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="100" max-width="150">
            <template #default="{ row }">
              <el-tag :type="TASK_STATUS_TAG[row.status]" effect="plain">
                {{ TASK_STATUS_MAP[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="260" max-width="380" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="View" @click="openDetail(row.request_id)">详情</GlassButton>
              <GlassButton
                v-if="row.status === 'scheduled'"
                variant="link" left-icon="VideoPlay"
                @click="handleTaskAction(row, 'start')"
              >开始执行</GlassButton>
              <GlassButton
                v-if="row.status === 'in_progress'"
                variant="link" link-tone="success" left-icon="CircleCheck"
                @click="handleTaskAction(row, 'complete')"
              >标记完成</GlassButton>
              <GlassButton
                v-if="['scheduled', 'in_progress'].includes(row.status)"
                variant="link" link-tone="danger" left-icon="CircleClose"
                @click="handleTaskAction(row, 'cancel')"
              >取消</GlassButton>
            </template>
          </el-table-column>
        </el-table>
        </div>

        <el-pagination
          class="pagination"
          v-model:current-page="scheduledPage"
          v-model:page-size="scheduledPageSize"
          :total="scheduledTotal"
          layout="total, prev, pager, next"
          @current-change="fetchScheduled"
        />
      </el-tab-pane>

      <!-- Tab 3: 已完成任务 -->
      <el-tab-pane label="已完成任务" name="completed">
        <div class="filter-bar">
          <el-input v-model="completedFilters.salesperson_name" placeholder="业务员" clearable style="width: 120px" @clear="fetchCompleted" @keyup.enter="fetchCompleted" />
          <el-select v-model="completedFilters.shoot_type" placeholder="拍摄类型" clearable style="width: 130px" @change="fetchCompleted">
            <el-option v-for="(label, code) in shootTypeMap" :key="code" :label="label" :value="code" />
          </el-select>
          <el-select v-model="completedFilters.designer_id" placeholder="设计师" clearable style="width: 120px" @change="fetchCompleted">
            <el-option v-for="d in designerData" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-date-picker v-model="completedFilters.planDateRange" type="daterange" start-placeholder="排期开始" end-placeholder="排期结束" value-format="YYYY-MM-DD" style="width: 260px" @change="fetchCompleted" />
        </div>
        <div class="table-card">
        <el-table
          ref="completedTableRef"
          :data="completedData"
          v-loading="completedLoading"
          class="list-table"
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="task_no" label="任务编号" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
          <el-table-column prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
          <el-table-column label="拍摄类型" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ buildDictLabel(row.shoot_type, shootTypeMap) }}</template>
          </el-table-column>
          <el-table-column label="设计师" min-width="100" max-width="150">
            <template #default="{ row }">{{ getDesignerName(row.designer_id) }}</template>
          </el-table-column>
          <el-table-column label="排期日期" min-width="240" max-width="360">
            <template #default="{ row }">
              {{ row.plan_start_date || '-' }} {{ periodLabel(row.plan_start_period) }} ~ {{ row.plan_end_date || '-' }} {{ periodLabel(row.plan_end_period) }}
            </template>
          </el-table-column>
          <el-table-column label="优先级" min-width="80" max-width="120">
            <template #default="{ row }">
              <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
                {{ row.priority === 'urgent' ? '加急' : '普通' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="80" max-width="120">
            <template #default="{ row }">
              <el-tag type="success" effect="plain">已完成</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="100" max-width="150" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="View" @click="openDetail(row.request_id)">详情</GlassButton>
            </template>
          </el-table-column>
        </el-table>
        </div>

        <el-pagination
          class="pagination"
          v-model:current-page="completedPage"
          v-model:page-size="completedPageSize"
          :total="completedTotal"
          layout="total, prev, pager, next"
          @current-change="fetchCompleted"
        />
      </el-tab-pane>

      <!-- Tab 4: 设计师管理 -->
      <el-tab-pane label="设计师管理" name="designers">
        <el-row style="margin-bottom: 12px" justify="end">
          <GlassButton variant="primary" left-icon="Plus" @click="openDesignerDialog(null)">新建设计师</GlassButton>
        </el-row>
        <div class="table-card">
        <el-table
          :data="designerData"
          v-loading="designerLoading"
          class="list-table"
          border
          :max-height="tabMaxHeight"
        >
          <el-table-column prop="id" label="ID" min-width="80" max-width="120" show-overflow-tooltip />
          <el-table-column prop="name" label="姓名" min-width="120" max-width="180" show-overflow-tooltip />
          <el-table-column prop="email" label="邮箱" min-width="180" max-width="270" show-overflow-tooltip />
          <el-table-column prop="dingtalk_id" label="钉钉ID" min-width="140" max-width="210" show-overflow-tooltip />
          <el-table-column label="状态" min-width="100" max-width="150">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" effect="plain">
                {{ row.is_active ? '在职' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
          <el-table-column label="操作" min-width="150" max-width="230" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="Edit" @click="openDesignerDialog(row)">编辑</GlassButton>
              <GlassButton
                variant="link"
                :link-tone="row.is_active ? 'danger' : 'success'"
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
        <DesignCalendarConfig />
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
        <el-dialog v-model="importResultVisible" title="导入结果" width="560px">
          <div v-if="importResult">
            <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
              <el-descriptions-item label="总行数">{{ importResult.total }}</el-descriptions-item>
              <el-descriptions-item label="成功">
                <el-tag type="success" size="small">{{ importResult.success }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="失败">
                <el-tag type="danger" size="small">{{ importResult.failed }}</el-tag>
              </el-descriptions-item>
            </el-descriptions>
            <el-table v-if="importResult.errors?.length" :data="importResult.errors" border size="small" max-height="300">
              <el-table-column prop="row" label="行号" width="80" />
              <el-table-column prop="reason" label="失败原因" />
            </el-table>
          </div>
        </el-dialog>
      </el-tab-pane>
    </el-tabs>

    <!-- Confirm scheduling dialog -->
    <el-dialog
      v-model="confirmVisible"
      title="确认排期"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form :model="confirmForm" label-width="90px" class="confirm-form">
        <el-form-item label="客户">
          <span>{{ confirmRow?.customer_name }}</span>
        </el-form-item>
        <el-form-item label="设计师" required>
          <el-select v-model="confirmForm.designer_id" placeholder="请选择设计师" style="width: 100%">
            <el-option
              v-for="d in designerData"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="排期日期" required class="date-period-item">
          <DatePeriodPicker
            v-model:start-date="confirmForm.startDate"
            v-model:start-period="confirmForm.startPeriod"
            v-model:end-date="confirmForm.endDate"
            v-model:end-period="confirmForm.endPeriod"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="confirmForm.comment" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="confirmForm.sync_unavailable">
            将当前排期日期同步设置为不可用
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="confirmVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitConfirm" :loading="confirming">确认</GlassButton>
      </template>
    </el-dialog>

    <!-- Designer create/edit dialog -->
    <el-dialog
      v-model="designerDialogVisible"
      :title="designerForm.id ? '编辑设计师' : '新建设计师'"
      width="460px"
      :close-on-click-modal="false"
    >
      <el-form :model="designerForm" label-width="80px">
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

    <!-- 修改期望日期 -->
    <el-dialog v-model="editDateVisible" title="修改期望日期" width="500px" :close-on-click-modal="false">
      <el-form label-width="100px">
        <el-form-item label="期望日期">
          <DatePeriodPicker
            v-model:start-date="editDateForm.startDate"
            v-model:start-period="editDateForm.startPeriod"
            v-model:end-date="editDateForm.endDate"
            v-model:end-period="editDateForm.endPeriod"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="editDateVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitEditDate" :loading="editDateSaving">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 修改备注 -->
    <el-dialog v-model="remarkVisible" title="修改备注" width="500px" :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="备注">
          <el-input v-model="remarkForm.remark" type="textarea" :rows="4" placeholder="请输入备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="remarkVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitRemark" :loading="remarkSaving">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 修改排期日期 -->
    <el-dialog v-model="editTaskDateVisible" title="修改排期日期" width="500px" :close-on-click-modal="false">
      <el-form label-width="100px">
        <el-form-item label="排期日期">
          <DatePeriodPicker
            v-model:start-date="editTaskDateForm.startDate"
            v-model:start-period="editTaskDateForm.startPeriod"
            v-model:end-date="editTaskDateForm.endDate"
            v-model:end-period="editTaskDateForm.endPeriod"
          />
        </el-form-item>
        <el-form-item label="改期备注">
          <el-input v-model="editTaskDateForm.comment" type="textarea" :rows="2" placeholder="选填，将包含在钉钉通知中" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="editTaskDateVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitEditTaskDate" :loading="editTaskDateSaving">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 修改拍摄类型 -->
    <el-dialog v-model="shootTypeVisible" title="修改拍摄类型" width="460px" :close-on-click-modal="false">
      <el-form label-width="90px">
        <el-form-item label="拍摄类型">
          <el-select v-model="shootTypeForm.shoot_type" multiple placeholder="请选择拍摄类型" style="width: 100%">
            <el-option
              v-for="(label, code) in shootTypeMap"
              :key="code"
              :label="label"
              :value="code"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="shootTypeVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitShootType" :loading="shootTypeSaving">保存</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import {
  Upload, Plus, Calendar, VideoPlay, CircleCheck, CircleClose, Edit, SwitchButton, Bell
} from '@element-plus/icons-vue'
import { buildDictLabel } from '@/utils/dict'
import DesignCalendarConfig from '@/components/design/DesignCalendarConfig.vue'
import DesignCapacityConfig from '@/components/design/DesignCapacityConfig.vue'
import DatePeriodPicker from '@/components/design/DatePeriodPicker.vue'
import RequestDetailDrawer from '@/components/design/RequestDetailDrawer.vue'

import { useDesignManage } from './composables/useDesignManage'

const {
  // 字典 / 工具
  shootTypeMap, customerLevelMap, customerLevelLabel, getDesignerName,
  periodLabel, TASK_STATUS_MAP, TASK_STATUS_TAG,
  // Tab + Detail
  activeTab, tabMaxHeight, detailVisible, detailRequestId, openDetail, onTabChange,
  // Edit dialogs
  editDateVisible, editDateSaving, editDateForm, openEditDateDialog, submitEditDate,
  remarkVisible, remarkSaving, remarkForm, openRemarkDialog, submitRemark,
  shootTypeVisible, shootTypeSaving, shootTypeTarget, shootTypeForm,
  openShootTypeDialog, submitShootType,
  editingDesignerId, editingDesignerValue,
  startEditDesigner, cancelEditDesigner, saveDesigner,
  editTaskDateVisible, editTaskDateSaving, editTaskDateForm,
  openEditTaskDateDialog, submitEditTaskDate,
  // Pending
  pendingTableRef, pendingData, pendingLoading,
  pendingPage, pendingPageSize, pendingTotal, pendingFilters,
  fetchPending, handleScanShootReminders,
  // Scheduled
  scheduledTableRef, scheduledData, scheduledLoading,
  scheduledPage, scheduledPageSize, scheduledTotal, scheduledFilters,
  fetchScheduled,
  // Completed
  completedTableRef, completedData, completedLoading,
  completedPage, completedPageSize, completedTotal, completedFilters,
  fetchCompleted,
  // Designers
  designerData, designerLoading,
  designerDialogVisible, designerSaving, designerForm,
  openDesignerDialog, submitDesigner, toggleDesignerActive,
  // Confirm
  confirmVisible, confirming, confirmForm,
  openConfirmDialog, submitConfirm,
  // Task action / Gantt
  handleTaskAction, handleReschedule,
  // Import
  uploadRef, importFile, importing,
  importResultVisible, importResult,
  onFileChange, submitImport,
} = useDesignManage()
</script>

<style scoped>
.tab-toolbar { margin-bottom: 12px; display: flex; justify-content: flex-end; }
.filter-bar { margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.pagination { margin-top: 16px; justify-content: flex-end; }
.text-muted { color: var(--text-secondary); font-size: 12px; }
.import-section { max-width: 600px; }

:deep(.el-tabs__header) {
  margin-bottom: 16px;
}

/* Prevent date picker popper from being clipped inside the dialog */
.confirm-form .date-period-item :deep(.el-date-editor),
.confirm-form .date-period-item :deep(.el-date-picker) {
  position: relative;
}

:deep(.el-dialog__body) {
  overflow: visible;
}

.clickable-date {
  cursor: pointer;
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.clickable-date:hover {
  text-decoration: underline;
}
.clickable-date .edit-icon {
  font-size: 14px;
  opacity: 0.5;
}
.clickable-date:hover .edit-icon {
  opacity: 1;
}

.clickable-remark {
  cursor: pointer;
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.clickable-remark:hover {
  text-decoration: underline;
}
.clickable-remark .edit-icon {
  font-size: 14px;
  opacity: 0.5;
}
.clickable-remark:hover .edit-icon {
  opacity: 1;
}

.clickable-shoot-type {
  cursor: pointer;
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.clickable-shoot-type:hover {
  text-decoration: underline;
}
.clickable-shoot-type .edit-icon {
  font-size: 14px;
  opacity: 0.5;
}
.clickable-shoot-type:hover .edit-icon {
  opacity: 1;
}

.clickable-cell {
  cursor: pointer;
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.clickable-cell:hover {
  text-decoration: underline;
}
.clickable-cell .edit-icon {
  font-size: 14px;
  opacity: 0.5;
}
.clickable-cell:hover .edit-icon {
  opacity: 1;
}

.inline-edit {
  display: inline-block;
}

.remark-mixed {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.remark-line {
  display: flex;
  align-items: baseline;
  gap: 4px;
  font-size: 13px;
  line-height: 1.5;
}
.remark-tag {
  display: inline-block;
  padding: 0 4px;
  border-radius: 3px;
  font-size: 11px;
  line-height: 1.4;
  white-space: nowrap;
  flex-shrink: 0;
}
.remark-tag.task {
  background: rgba(64, 158, 255, 0.15);
  color: #409eff;
}
.remark-tag.request {
  background: rgba(103, 194, 58, 0.15);
  color: #67c23a;
}
</style>
