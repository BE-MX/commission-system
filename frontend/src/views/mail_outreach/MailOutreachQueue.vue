<template>
  <div class="workflow mail-outreach-queue">
    <MailboxSettings @updated="mailboxes = $event" />

    <div ref="panelRef" class="table-card">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset">
        <el-select v-model="searchForm.status" placeholder="全部状态" clearable class="filter-w-sm">
          <el-option v-for="(label, value) in JOB_STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="searchForm.mailbox_binding_id" placeholder="全部发件邮箱" clearable class="filter-w-md">
          <el-option v-for="mailbox in mailboxes" :key="mailbox.id" :label="mailbox.sender_email" :value="mailbox.id" />
        </el-select>
      </FilterBar>

      <div class="action-bar">
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>
      <ListPageStatus v-if="listPageState.hasData.value" :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="fetchList" />
<el-table v-loading="loading" :data="list" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" row-key="id" @sort-change="listPageState.handleSortChange($event.order ? { sort_field: $event.prop, sort_order: $event.order === 'ascending' ? 'asc' : 'desc' } : {})">
        <el-table-column sortable="custom" prop="customer_name" v-if="visibleKeys.includes('customer')" label="客户" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.customer_name || `客户 #${row.customer_id}` }}</template>
        </el-table-column>
        <el-table-column sortable="custom" prop="to_email" v-if="visibleKeys.includes('to-email')" label="收件邮箱" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.to_email || row.to_email_snapshot || '-' }}</template>
        </el-table-column>
        <el-table-column sortable="custom" prop="sender_email" v-if="visibleKeys.includes('sender-email')" label="发件邮箱" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ senderEmailOf(row) }}</template>
        </el-table-column>
        <el-table-column sortable="custom" prop="status" v-if="visibleKeys.includes('status')" label="状态" min-width="160">
          <template #default="{ row }"><StatusBadge :type="jobStatusTagType(row.status)">{{ jobStatusLabel(row.status) }}</StatusBadge></template>
        </el-table-column>
        <el-table-column sortable="custom" prop="due_at" v-if="visibleKeys.includes('due-at')" label="计划发送时间（北京时间）" min-width="170">
          <template #default="{ row }">{{ row.due_at ? formatBeijingDateTime(row.due_at, { seconds: false }) : '-' }}</template>
        </el-table-column>
        <el-table-column sortable="custom" prop="reschedule_count" v-if="visibleKeys.includes('reschedule-count')" label="顺延次数" min-width="100">
          <template #default="{ row }">{{ row.reschedule_count ?? 0 }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="110" fixed="right">
          <template #default="{ row }">
            <GlassButton left-icon="Close" v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="link" link-tone="danger"
              :disabled="!isCancellable(row)" @click="cancel(row)">撤销</GlassButton>
          </template>
        </el-table-column>
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无发送任务；草稿批准并排程后会进入队列'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
      </el-table>

      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager"
        @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>
    <MailInboundEvents />
  </div>
</template>

<script setup>import { promptAction, msgSuccess } from '@/utils/feedback'
import { computed, ref } from 'vue'

import { cancelJob, listJobs } from '@/api/mailOutreach'
import { formatBeijingDateTime } from '@/utils/datetime'
import GlassButton from '@/components/GlassButton.vue'
import TableTools from '@/components/TableTools.vue'
import MailboxSettings from './MailboxSettings.vue'
import MailInboundEvents from './MailInboundEvents.vue'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import {
  JOB_STATUS_LABELS, jobStatusLabel, jobStatusTagType,
} from './presentation'

const listPageState = useListPage(async (params, { signal }) => {
  return (await listJobs(stripEmpty(params), { signal, suppressToast: true })).data
}, { searchForm: { status: '', mailbox_binding_id: null } })
const {
  loading, list, total, page, pageSize, searchForm,
  errorMessage, hasData, dataPage, hasPendingSearch, error, refreshUpdate,
  fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange,
} = listPageState

const hasActiveFilters = computed(() => Boolean(searchForm.status || searchForm.mailbox_binding_id))

// 列显隐元数据（TableTools 列设置面板数据源，Action Bar Spec）
const columnDefs = [
  { key: 'customer', label: '客户' },
  { key: 'to-email', label: '收件邮箱' },
  { key: 'sender-email', label: '发件邮箱' },
  { key: 'status', label: '状态' },
  { key: 'due-at', label: '计划发送时间（北京时间）' },
  { key: 'reschedule-count', label: '顺延次数' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('mail-outreach-queue', columnDefs)

function stripEmpty(params) {
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '' && value != null))
}

const mailboxes = ref([])

function senderEmailOf(row) {
  if (row.sender_email) return row.sender_email
  return mailboxes.value.find(mailbox => mailbox.id === row.mailbox_binding_id)?.sender_email || '-'
}

/** 终态与已进入外部调用的任务不提供撤销入口；sending 中途撤销由服务端判定"撤销太晚" */
function isCancellable(row) {
  return ['scheduled', 'claimed', 'blocked', 'needs_review'].includes(row.status) && !row.send_started_at_utc
}

async function cancel(row) {
  let note = ''
  try {
    const result = await promptAction(
      `确定撤销发往「${row.to_email || row.to_email_snapshot || '-'}」的发送任务？已开始发送的任务无法撤销。`,
      '撤销发送任务',
      {
        type: 'warning',
        confirmButtonText: '确定撤销',
        cancelButtonText: '取消',
        inputType: 'textarea',
        inputPlaceholder: '撤销说明（可选，会记录到任务备注）',
      },
    )
    note = result.value?.trim() || ''
  } catch { return }
  await cancelJob(row.id, { note })
  msgSuccess('任务已撤销')
  await refreshUpdate()
}
</script>

<style scoped>
.workflow { display: grid; gap: 14px; }
.mailbox-strip { display: flex; flex-wrap: wrap; gap: 12px; min-height: 60px; }
.mailbox-card { display: grid; gap: 8px; min-width: 240px; padding: 14px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--toolbar-bg); }
.mailbox-card__header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.mailbox-card__header strong { color: var(--text-primary); overflow-wrap: anywhere; }
.mailbox-card__meta { margin: 0; color: var(--text-secondary); font-size: 13px; }
.el-pagination { overflow-x: auto; }
</style>
