<template>
  <div class="outbound-page">
    <div class="outbound-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="7">
        <el-input v-model="searchForm.keyword" placeholder="搜索出库单号 / 客户名称" clearable prefix-icon="Search" @keyup.enter="handleSearch" @clear="handleSearch" />
      </el-col>
      <el-col :span="8">
        <el-date-picker
          v-model="searchForm.dateRange" type="daterange" value-format="YYYY-MM-DD"
          start-placeholder="出库起" end-placeholder="出库止" style="width: 100%" @change="handleSearch"
        />
      </el-col>
      <el-col :span="9">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card outbound-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="outbound_no" label="出库单号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户名称" min-width="130" show-overflow-tooltip />
        <el-table-column label="出库日期" min-width="120">
          <template #default="{ row }">
            <template v-if="row.record_source === 'ark_task'">
              <span class="queue-note">待出库</span><small class="queue-note">{{ row.requested_date }} 创建</small>
            </template>
            <template v-else>{{ row.outbound_date }}</template>
          </template>
        </el-table-column>
        <el-table-column label="明细 / 数量" min-width="110">
          <template #default="{ row }">{{ row.item_count }} 行 / {{ row.total_qty }} 件</template>
        </el-table-column>
        <el-table-column label="出库单状态" min-width="170">
          <template #default="{ row }">
            <el-tag :type="OUTBOUND_STATE_TAGS[row.outbound_state] || 'info'">
              {{ OUTBOUND_STATE_LABELS[row.outbound_state] || '状态待确认' }}
            </el-tag>
            <el-popover v-if="row.stock_shortages?.length" trigger="click" placement="bottom" :width="360">
              <template #reference><GlassButton variant="link">缺货详情</GlassButton></template>
              <p v-for="item in row.stock_shortages" :key="item.sku_id" class="shortage-item">
                <strong>{{ item.product_name }}</strong><br>
                需要 {{ item.required }}，可用 {{ item.available }}，缺 {{ item.shortage }}
              </p>
              <small class="queue-note">库存检查时间：{{ row.stock_checked_at || '待确认' }}</small>
              <p class="queue-note">系统约每 15 分钟复查库存，满足后自动生成出库单。</p>
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column label="检验状态" min-width="90">
          <template #default="{ row }">
            <span v-if="row.record_source === 'ark_task'" class="queue-note">—</span>
            <el-tag v-else size="small" :type="INSPECTION_STATUS_TAGS[row.status] || 'info'">
              {{ INSPECTION_STATUS_LABELS[row.status] || row.status }}
            </el-tag>
            <el-tag v-if="row.recheck_status" size="small" type="warning">{{ row.recheck_status === 'pending_sync' ? '待同步重验' : '待补验' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="照片数" min-width="80" align="right">
          <template #default="{ row }">{{ row.record_source === 'ark_task' ? '—' : row.photo_count }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="390" fixed="right">
          <template #default="{ row }">
            <GlassButton
              v-if="row.can_print && !row.recheck_status" variant="link" left-icon="Printer"
              :loading="printingId === row.outbound_record_id"
              @click="openPrint(row)"
            >打印出库单</GlassButton>
            <GlassButton v-if="row.can_print && !row.recheck_status" variant="link" left-icon="Download"
              :loading="downloadingId === row.outbound_record_id" @click="downloadWord(row)">下载 Word</GlassButton>
            <span v-if="!row.can_print || row.recheck_status" class="queue-note">{{ row.recheck_status === 'pending_sync' ? '待同步并重验' : row.recheck_status === 'pending_inspection' ? '待补验' : outboundPendingHint(row.outbound_state) }}</span>
            <span v-if="row.record_source === 'okki' && row.outbound_invoice_id" v-permission="'invoice:sync'">
              <GlassButton v-permission="'shipping_inspection:write'" variant="link" left-icon="Refresh"
                :loading="syncingId === row.outbound_record_id" :disabled="syncingId !== null || deletingId !== null"
                @click="previewSync(row)">同步订单</GlassButton>
            </span>
            <GlassButton v-if="row.record_source === 'okki' && row.outbound_invoice_id"
              v-permission="'shipping_inspection:delete'" variant="link" link-tone="danger" left-icon="Delete"
              :loading="deletingId === row.outbound_record_id" :disabled="deletingId !== null || syncingId !== null"
              @click="deleteRecord(row)">删除</GlassButton>
            <GlassButton v-if="row.record_source === 'okki'" v-permission="'shipping_inspection:admin'" variant="link" :disabled="deletingId !== null" @click="recoverDeletion(row)">恢复删除任务</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>
    <OutboundSyncDialog v-model:visible="syncVisible" :busy="syncingId !== null" :preview="syncPreview" :row="syncRow" @apply="applySync" />
  </div>
</template>

<script setup>
/**
 * OKKI 出库单列表 + 出库单直接打印（无预览弹框）。逻辑在 composables/useOutboundRecords.js（宪法 12）。
 */
import { INSPECTION_STATUS_LABELS, INSPECTION_STATUS_TAGS } from '@/api/shipping'
import GlassButton from '@/components/GlassButton.vue'
import { useOutboundRecords } from './composables/useOutboundRecords'
import { useOutboundInvoiceSync } from './composables/useOutboundInvoiceSync'
import OutboundSyncDialog from './OutboundSyncDialog.vue'
import { OUTBOUND_STATE_LABELS, OUTBOUND_STATE_TAGS, outboundPendingHint } from './composables/outboundStates'

const {
  loading, list, total, page, pageSize, searchForm, fetchList,
  handleSearch, handlePageChange, handleSizeChange,
  printingId, openPrint, downloadingId, downloadWord, deletingId, deleteRecord, recoverDeletion,
} = useOutboundRecords()
const { syncingId, syncVisible, syncPreview, syncRow, previewSync, applySync } = useOutboundInvoiceSync(fetchList)
</script>

<style scoped>
.outbound-page { position: relative; }
.outbound-aurora { inset: -24px -28px; }
.outbound-page .toolbar,
.outbound-page .outbound-panel { position: relative; z-index: 1; }

.toolbar { margin-bottom: 16px; }

.outbound-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.outbound-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.outbound-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.outbound-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.outbound-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

.pager { margin: 12px; justify-content: flex-end; }
.queue-note { color: var(--text-secondary); }
small.queue-note { display: block; margin-top: 4px; }
.shortage-item { margin: 0 0 12px; overflow-wrap: anywhere; }
</style>
