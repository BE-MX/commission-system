<template>
  <div class="receipt-page">
    <div class="receipt-heading"><div><h2>回款单</h2><p>每笔回款关联订单，凭证与同步结果集中查看。</p></div><GlassButton v-permission="'receipt:write'" variant="primary" left-icon="Plus" @click="openCreate()">新建回款单</GlassButton></div>
    <el-alert title="库存单完整同步后自动生成回款；失败和待核对单仍占用订单登记额度，请在原单上处理。" type="info" :closable="false" />
    <el-alert v-if="deliveryEnabled === false" class="delivery-notice" title="小满回款同步暂未启用。已创建的回款保留在方舟，启用后自动处理。" type="warning" :closable="false" />
    <div class="receipt-filters">
      <el-input v-model="searchForm.keyword" clearable placeholder="回款单号 / 发票号 / 客户" @keyup.enter="handleSearch" />
      <el-select v-model="searchForm.sync_status" clearable placeholder="同步状态"><el-option v-for="s in states" :key="s" :value="s" :label="statusLabel(s)" /></el-select>
      <el-select v-model="searchForm.source" clearable placeholder="来源"><el-option label="库存单自动" value="auto" /><el-option label="手工登记" value="manual" /></el-select>
      <el-select v-model="searchForm.status" clearable placeholder="单据状态"><el-option label="有效" value="active" /><el-option label="已作废" value="voided" /></el-select>
      <el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="回款开始日期" end-placeholder="结束日期" />
      <GlassButton left-icon="Search" @click="handleSearch">查询</GlassButton><GlassButton @click="reset">重置</GlassButton>
    </div>
    <div class="table-card"><el-table v-loading="loading" :data="list" class="list-table" border max-height="640" empty-text="暂无符合条件的回款单">
      <el-table-column label="回款单号" min-width="240" max-width="340" show-overflow-tooltip><template #default="{row}"><el-button link type="primary" @click="showDetail(row)"><el-icon><Document /></el-icon>{{ row.receipt_no }}</el-button></template></el-table-column>
      <el-table-column label="本次回款金额" min-width="150" max-width="210"><template #default="{row}">{{ row.currency }} {{ money(row.amount) }}</template></el-table-column>
      <el-table-column label="同步状态" min-width="120" max-width="170"><template #default="{row}"><el-tag size="small" effect="plain" :type="statusTone(row.sync_status)">{{ row.status === 'voided' ? '已作废' : statusLabel(row.sync_status) }}</el-tag></template></el-table-column>
      <el-table-column prop="invoice_no" label="订单发票" min-width="150" max-width="210" show-overflow-tooltip />
      <el-table-column prop="customer_name" label="客户" min-width="170" max-width="240" show-overflow-tooltip />
      <el-table-column prop="collection_date" label="回款日期" min-width="130" max-width="180" />
      <el-table-column label="来源" min-width="120" max-width="170"><template #default="{row}">{{ row.source === 'auto' ? '库存单自动' : '手工登记' }}</template></el-table-column>
      <el-table-column label="财务状态" min-width="110" max-width="160"><template #default="{row}">{{ financeLabel(row.collect_status) }}</template></el-table-column>
      <el-table-column label="凭证" min-width="85" max-width="120"><template #default="{row}">{{ row.attachment_count }} 张</template></el-table-column>
      <el-table-column label="操作" min-width="145" max-width="300" class-name="table-action-column" fixed="right"><template #default="{row}"><div class="table-actions"><el-button link type="primary" @click="showDetail(row)"><el-icon><View /></el-icon>查看</el-button><el-button v-if="row.sync_status === 'failed' && row.status === 'active'" v-permission="'receipt:write'" link type="primary" :loading="saving" @click="retry(row)"><el-icon><Refresh /></el-icon>重试</el-button></div></template></el-table-column>
    </el-table></div>
    <el-pagination class="receipt-pagination" :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="total,sizes,prev,pager,next" @current-change="handlePageChange" @size-change="handleSizeChange" />

    <el-drawer v-model="editorVisible" :title="editing ? '修正回款资料' : '新建回款单'" size="640px" append-to-body destroy-on-close class="receipt-editor" :before-close="closeEditor">
      <el-form :model="form" label-position="top">
        <el-form-item v-if="!editing" label="对应订单发票" required><el-select v-model="form.invoice_id" filterable remote :remote-method="searchOrders" :loading="ordersLoading" :disabled="saving || uploading" placeholder="搜索发票号或客户" @change="selectOrder"><el-option v-for="o in orders" :key="o.id" :value="o.id" :disabled="o.sync_status !== 'synced'" :label="`${o.invoice_no} · ${o.customer_name}${o.sync_status !== 'synced' ? '（请先同步订单）' : ''}`" /></el-select></el-form-item>
        <div v-if="!editing" v-loading="balanceLoading" class="balance-card"><div>订单金额<b>{{ balance?.currency }} {{ money(balance?.total_amount) }}</b></div><div>已登记回款<b>{{ money(balance?.registered_amount) }}</b></div><div>可登记余额<b>{{ money(balance?.remaining_amount) }}</b></div></div>
        <p v-if="!editing && balance">已生效 {{ money(balance.effective_amount) }} · 登记中 {{ money(balance.pending_amount) }}；本次登记后剩余 {{ money(remainingAfter) }}</p>
        <el-button v-if="!editing && form.invoice_id" link type="primary" @click="refreshBalance"><el-icon><Refresh /></el-icon>刷新余额（保留凭证）</el-button>
        <ReceiptFields :form="form" :readonly="saving" :currency="editing ? detail.currency : balance?.currency" show-charge @uploading="v => uploading = v" />
        <p v-if="error" class="receipt-error" role="alert">{{ error }}</p>
      </el-form>
      <template #footer><div class="drawer-actions"><GlassButton :disabled="saving || uploading" @click="closeEditor()">取消</GlassButton><GlassButton v-permission="'receipt:write'" variant="primary" :loading="saving" :disabled="uploading || (!editing && !balance)" @click="submit">{{ editing ? '保存修正' : '创建回款单' }}</GlassButton></div></template>
    </el-drawer>

    <DetailDrawer v-model="detailVisible" :title="detail?.receipt_no || '回款单详情'" :loading="!detail">
      <template v-if="detail"><div class="detail-status"><el-tag effect="plain" :type="statusTone(detail.sync_status)">{{ detail.status === 'voided' ? '已作废' : statusLabel(detail.sync_status) }}</el-tag><el-tag effect="plain">财务：{{ financeLabel(detail.collect_status) }}</el-tag></div>
        <h1>{{ detail.currency }} {{ money(detail.amount) }}</h1>
        <el-alert v-if="detail.last_error" :title="detail.last_error" type="warning" :closable="false" />
        <el-descriptions :column="1" border class="receipt-descriptions"><el-descriptions-item label="订单发票">{{ detail.invoice_no }}</el-descriptions-item><el-descriptions-item label="客户">{{ detail.customer_name }}</el-descriptions-item><el-descriptions-item label="回款日期">{{ detail.collection_date }}</el-descriptions-item><el-descriptions-item label="回款方式">{{ detail.payment_type }}</el-descriptions-item><el-descriptions-item label="银行手续费">{{ money(detail.bank_charge) }}</el-descriptions-item><el-descriptions-item label="小满回款编号">{{ detail.xiaoman_receipt_no || '尚未取得' }}</el-descriptions-item><el-descriptions-item label="截图传输">仅方舟留存</el-descriptions-item><el-descriptions-item label="备注">{{ detail.remark || '—' }}</el-descriptions-item></el-descriptions>
        <h3>回款凭证</h3><ReceiptProofs :key="detail.id" :model-value="detail.attachments?.map(a => a.id) || []" readonly />
        <h3>同步记录</h3><el-timeline><el-timeline-item v-for="(log,i) in detail.logs" :key="i" :timestamp="formatBeijingDateTime(log.created_at)">{{ log.message }}</el-timeline-item></el-timeline>
        <el-alert v-if="candidates.length" title="以下仅为候选，管理员需核对真实凭证后绑定。" type="warning" :closable="false" /><p v-for="c in candidates" :key="c.xiaoman_receipt_id">小满 ID {{ c.xiaoman_receipt_id }} · {{ c.xiaoman_receipt_no }} · {{ money(c.amount) }}</p>
      </template>
      <template #footer><template v-if="detail"><GlassButton v-if="editable" v-permission="'receipt:write'" @click="editCurrent">修正资料</GlassButton><GlassButton v-if="editable" v-permission="'receipt:write'" @click="voidCurrent">作废</GlassButton><GlassButton v-if="detail.sync_status === 'failed' && detail.status === 'active'" v-permission="'receipt:write'" variant="primary" :loading="saving" @click="retry(detail)">重试同步</GlassButton><GlassButton v-if="['synced','uncertain'].includes(detail.sync_status)" v-any-permission="['receipt:write','receipt:admin']" :loading="saving" @click="reconcile">刷新小满结果</GlassButton><template v-if="detail.sync_status === 'uncertain' && !detail.xiaoman_receipt_id"><GlassButton v-permission="'receipt:admin'" @click="resolve('bind_receipt')">绑定已生成回款</GlassButton><GlassButton v-permission="'receipt:admin'" @click="resolve('confirm_not_created')">确认未创建</GlassButton></template></template></template>
    </DetailDrawer>
  </div>
</template>
<script setup>
import { Document, Refresh, View } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import ReceiptFields from './ReceiptFields.vue'
import ReceiptProofs from './ReceiptProofs.vue'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useReceipts, statusLabel, statusTone, financeLabel, money } from './useReceipts'
const states = ['pending','syncing','synced','failed','uncertain']
const { loading,list,total,page,pageSize,searchForm,dates,handleSearch,handlePageChange,handleSizeChange,reset,
  editorVisible,detailVisible,detail,saving,uploading,orders,ordersLoading,balance,balanceLoading,error,candidates,
  form,editing,selectedOrder,remainingAfter,editable,searchOrders,selectOrder,openCreate,showDetail,editCurrent,
  closeEditor,submit,retry,voidCurrent,reconcile,resolve,refreshBalance,deliveryEnabled } = useReceipts()
</script>
<style scoped>
.receipt-page{background:linear-gradient(150deg,var(--dash-wash-from),var(--page-bg));padding:20px;border-radius:16px}.receipt-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:20px}.receipt-heading h2{margin:0}.receipt-heading p,.receipt-page p{color:var(--text-secondary);font-size:12px;line-height:1.8}.receipt-filters{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}.receipt-filters>.el-input{width:240px}.receipt-filters>.el-select{width:145px}.receipt-filters :deep(.el-date-editor){max-width:100%;width:280px;flex-grow:0}.receipt-pagination{margin-top:20px;max-width:100%;overflow:auto}.balance-card{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;background:var(--color-gold-soft);padding:16px;border-radius:12px;margin:12px 0 20px;font-size:12px}.balance-card b{display:block;margin-top:8px;font-size:16px;font-variant-numeric:tabular-nums}.drawer-actions,.detail-status{display:flex;gap:10px;flex-wrap:wrap}.drawer-actions{justify-content:flex-end}.receipt-error{color:var(--color-danger-text)!important}.receipt-descriptions{margin:20px 0}.receipt-page h1{font-variant-numeric:tabular-nums;font-size:28px}@media(max-width:768px){.receipt-page{padding:12px}.receipt-heading{align-items:flex-start;flex-wrap:wrap}.receipt-filters>.el-input{width:100%}.receipt-filters>.el-select{width:calc(50% - 6px)}}
</style>
<style>.el-drawer.receipt-editor{max-width:100vw}.receipt-page .delivery-notice{margin-top:12px}</style>
