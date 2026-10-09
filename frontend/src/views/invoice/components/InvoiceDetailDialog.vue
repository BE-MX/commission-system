<template>
  <el-dialog v-model="visible" :title="order?.invoice_no || '订单发票详情'" :width="dialogWidth" :fullscreen="fullscreen" class="invoice-detail-dialog" top="3vh" destroy-on-close :close-on-click-modal="false" @closed="close">
    <template #header>
      <div class="detail-heading"><div><small>订单发票详情</small><div class="detail-title"><h2>{{ order?.invoice_no || '订单详情' }}</h2><InvoiceAnomalyBadge :anomalies="order?.anomalies || []" interactive @navigate="navigate" /></div></div><StatusBadge v-if="order" :type="detailStatus(order.sync_status).type">{{ detailStatus(order.sync_status).label }}</StatusBadge><el-button link :aria-label="fullscreen ? '退出宽屏' : '切换宽屏'" @click="fullscreen = !fullscreen"><el-icon><FullScreen /></el-icon></el-button></div>
    </template>
    <div v-if="header.state === 'loading' && !order" class="detail-loading" role="status">正在加载订单快照与关联单据…</div>
    <div v-else-if="!order" class="detail-warning" role="alert">{{ header.message || '订单加载失败' }}<GlassButton @click="refresh">重试</GlassButton></div>
    <template v-else>
      <div class="detail-overview"><div><strong>{{ order.customer_name }}</strong><span>{{ orderTypeLabel(order.order_type) }} · {{ order.customer_grade || '未分级' }} · 业务员 {{ order.sales_user_name || '—' }}</span><StatusBadge v-if="['cancelled','cancel_pending'].includes(order.status)" :type="detailStatus(order.status).type">{{ detailStatus(order.status).label }}</StatusBadge></div><span>发票日期 {{ order.invoice_date }}</span></div>
      <div v-if="order.sync_error && ['sync_failed','sync_uncertain'].includes(order.sync_status)" class="detail-warning" role="alert">订单同步：{{ order.sync_error }}</div>
      <div class="detail-progress-grid">
        <div class="detail-amount"><span>{{ order.order_type === 'presale' ? '当前明细金额' : '订单金额' }} · {{ order.currency }}</span><strong>{{ formatMoney(order.total_amount) }}</strong><small>{{ order.items?.reduce((sum,r) => sum + Number(r.quantity), 0) }} 件 · {{ order.items?.length }} 行商品</small><small v-if="order.order_type === 'presale'">累计账面 {{ formatMoney(order.ledger_total_amount) }}</small></div>
        <button v-for="card in progressCards" :key="card.key" type="button" class="detail-progress-card" @click="activeTab = card.key">
          <div><span>{{ card.label }}</span><small>{{ card.stateLabel }}</small></div><strong>{{ card.progress ? `${card.progress.percentage}%` : '—' }}</strong>
          <el-progress :percentage="card.progress?.percentage || 0" :show-text="false" :status="card.progress?.complete ? 'success' : undefined" />
          <small>{{ card.description }} <span>查看详情 →</span></small>
        </button>
      </div>
      <el-tabs v-model="activeTab" class="invoice-detail-tabs">
        <el-tab-pane label="订单详情" name="order"><InvoiceDetailOrder :order="order" :shipped="outbounds.state === 'ready' ? outbounds.summary?.by_item : null" /></el-tab-pane>
        <el-tab-pane :label="`出库单详情${outbounds.state === 'ready' ? ` (${outbounds.items?.length || 0})` : ''}`" name="outbound">
          <div v-if="outbounds.state === 'loading'" class="detail-loading" role="status">正在核验实际出库事实…</div>
          <div v-if="outbounds.state !== 'ready' && outbounds.message" class="detail-warning" role="alert">{{ outbounds.message }}</div><InvoiceDetailOutbounds v-if="outbounds.state !== 'restricted'" :panel="outbounds" />
        </el-tab-pane>
        <el-tab-pane :label="`回款单详情${receipts.state === 'ready' ? ` (${receipts.items?.length || 0})` : ''}`" name="receipt">
          <div v-if="receipts.state === 'loading'" class="detail-loading" role="status">正在核验关联回款事实…</div>
          <p v-if="receipts.state === 'ready' && receipts.source === 'background_snapshot'" class="detail-source">回款单与进度来自截至 {{ stamp(receipts) }} 的后台核验快照；按当前保存的订单金额展示，点击“刷新核验”可实时核对。</p>
          <div v-if="receipts.state !== 'ready' && receipts.message" class="detail-warning" role="alert">{{ receipts.message }}</div><InvoiceDetailReceipts v-if="receipts.state !== 'restricted'" :panel="receipts" :currency="order.currency" :presale="order.order_type === 'presale'" />
        </el-tab-pane>
      </el-tabs>
    </template>
    <template #footer><div class="dialog-footer detail-footer"><small>订单 {{ stamp(header) }} · 回款 {{ stamp(receipts) }} · 出库 {{ stamp(outbounds) }}</small><GlassButton :disabled="loading" @click="refresh">{{ loading && order ? '正在刷新' : '刷新核验' }}</GlassButton><GlassButton v-permission="'invoice:read'" :disabled="!order" @click="$emit('print', order)">打印订单预览</GlassButton><GlassButton variant="primary" @click="visible = false">关闭详情</GlassButton></div></template>
  </el-dialog>
</template>
<script setup>
import { computed } from 'vue'
import { FullScreen } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import InvoiceAnomalyBadge from './InvoiceAnomalyBadge.vue'
import InvoiceDetailOrder from './InvoiceDetailOrder.vue'
import InvoiceDetailOutbounds from './InvoiceDetailOutbounds.vue'
import InvoiceDetailReceipts from './InvoiceDetailReceipts.vue'
import { detailStatus, orderTypeLabel } from './invoiceDetailLabels'
import { progressValue } from '../composables/invoiceDetailState'
import { useInvoiceDetail } from '../composables/useInvoiceDetail'
import { formatInvoiceDateTime } from '../composables/invoiceDateTime'
import { formatMoney } from '@/utils/money'
defineEmits(['print'])
const { visible, order, activeTab, fullscreen, header, receipts, outbounds, loading, open, close, refresh } = useInvoiceDetail()
const dialogWidth = 'min(1200px, calc(100vw - 24px))'
function navigate(domain) { activeTab.value = {order:'order',outbound:'outbound',receipt:'receipt'}[domain] }
const progressCards = computed(() => [
  {key:'receipt',label:'回款进度',panel:receipts.value,n:receipts.value.summary?.effective_amount,d:receipts.value.summary?.total_amount,description:receipts.value.source === 'background_snapshot' ? `快照 ${stamp(receipts.value)} · 生效含费 / 当前订单金额` : '财务生效含费金额 / 订单金额'},
  {key:'outbound',label:'出库进度',panel:outbounds.value,n:outbounds.value.summary?.shipped_quantity,d:outbounds.value.summary?.ordered_quantity,description:'检验提交完成数量 / 订单数量'},
].map(card => { const progress = progressValue(card.n,card.d,card.panel.state); return {...card,progress,stateLabel:card.panel.state === 'loading' ? '正在核验' : card.panel.state === 'restricted' ? '无查看权限' : progress ? card.panel.source === 'background_snapshot' ? '最近核验快照' : progress.complete ? '已完成' : '进行中' : card.panel.state === 'ready' && Number(card.d) === 0 ? '无统计基数' : '待核验'} }))
function stamp(panel) { return panel.checked_at ? formatInvoiceDateTime(panel.checked_at) : panel.state === 'restricted' ? '无权限' : panel.state === 'loading' ? '核验中' : '未核验' }
defineExpose({ open })
</script>
<style src="./invoice-detail.css"></style>
