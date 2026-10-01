<template>
  <section v-if="operation" class="linked-result" aria-live="polite">
    <div class="linked-heading"><strong>关联单据同步结果</strong><StatusBadge :type="operation.status === 'done' ? 'success' : 'warning'">{{ labels[operation.status] || operation.status }}</StatusBadge></div>
    <p>订单金额：{{ formatMoney(operation.before.total_amount, { missing: '—' }) }} → {{ formatMoney(operation.after.total_amount, { missing: '—' }) }} {{ operation.after.currency }}；手续费：{{ formatMoney(operation.before.surcharge_amount, { missing: '—' }) }} → {{ formatMoney(operation.after.surcharge_amount, { missing: '—' }) }}</p>
    <div v-for="(step, key) in operation.steps" :key="key" class="linked-step">
      <strong>{{ names[key] }}</strong><StatusBadge size="small" :type="step.status === 'done' ? 'success' : 'info'">{{ labels[step.status] || step.status }}</StatusBadge><span>{{ step.message }}</span>
      <p v-if="step.balance">已生效 {{ formatMoney(step.balance.effective_amount, { missing: '—' }) }} · 待处理 {{ formatMoney(step.balance.pending_amount, { missing: '—' }) }} · 待收 {{ formatMoney(step.unpaid_amount, { missing: '—' }) }} · 超收待核对 {{ formatMoney(step.overpaid_amount, { missing: '—' }) }}</p>
      <p v-for="doc in step.documents || []" :key="doc.id">小满出库单 {{ doc.number || doc.id }} · {{ String(doc.status) === '2' ? '已出库' : '待核对状态 ' + doc.status }}</p>
      <p v-for="item in step.differences || []" :key="`${item.product_id}-${item.sku_id}`">SKU {{ item.sku_id }}：订单数量 {{ item.ordered }}，出库单数量 {{ item.outbound }}，差额 {{ item.difference }}</p>
    </div>
    <div class="linked-actions">
      <el-button :disabled="busy" @click="$emit('refresh')">刷新结果</el-button>
      <el-button v-if="['pending', 'failed'].includes(operation.status)" v-permission="'invoice:sync'" :loading="busy" type="primary" @click="$emit('retry')">{{ operation.status === 'pending' ? '继续同步' : '重试未完成步骤' }}</el-button>
      <el-button v-if="['done', 'manual'].includes(operation.status) && operation.steps.order.status === 'done'" v-permission="'invoice:sync'" :loading="busy" @click="$emit('recheck')">重新核对关联单据</el-button>
      <el-button v-if="operation.status === 'failed'" v-permission="'invoice:sync'" :disabled="busy" @click="$emit('close')">保留结果并结束本次同步</el-button>
      <el-button v-if="operation.status === 'uncertain'" v-permission="'invoice:admin'" :disabled="busy" @click="$emit('resolve')">人工核对后结束</el-button>
    </div>
    <p v-if="operation.status === 'uncertain'">同步结果不确定，已停止自动重发。请管理员核对小满原单及库存处理结果。</p>
  </section>
</template>
<script setup>
import { formatMoney } from '../../../utils/money.js'

defineProps({ operation: { type: Object, default: null }, busy: Boolean })
defineEmits(['refresh', 'retry', 'recheck', 'close', 'resolve'])
const names = { order: '小满订单', outbound: '出库单', receipt: '回款单', resolution: '人工核对记录' }
const labels = { pending: '待处理', running: '同步中', sending: '发送中', done: '已完成', failed: '未完成', uncertain: '待核对', manual: '需要处理' }
</script>
<style scoped>
.linked-result { margin: 16px 0; padding: 16px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--card-bg); }
.linked-heading, .linked-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.linked-step { margin-top: 12px; }
.linked-step > span, .linked-step > strong { margin-right: 8px; }
p { color: var(--text-secondary); line-height: 1.6; }
</style>
