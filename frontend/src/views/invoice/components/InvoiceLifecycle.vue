<template>
  <el-button v-permission="'invoice:admin'" link @click="open">取消 / 恢复</el-button>
  <el-drawer v-model="visible" title="订单取消与异常恢复" size="min(600px, 94vw)" append-to-body :close-on-click-modal="false">
    <div v-loading="busy" class="lifecycle-body">
      <template v-if="data">
        <h3>{{ data.invoice_no }}</h3>
        <el-alert :title="data.cancellation?.message || '取消前将冻结订单编辑、新回款发送和自动出库。已发生的货款记录保留。'" type="info" :closable="false" />
        <p v-if="data.cancellation">处理状态：{{ states[data.cancellation.status] || data.cancellation.status }}</p>
        <p v-if="data.cancellation?.reason">取消原因：{{ data.cancellation.reason }}</p>
        <p v-for="text in data.cancellation?.evidence?.blockers || []" :key="text">{{ text }}</p>
        <p v-for="doc in data.cancellation?.evidence?.outbounds || []" :key="doc.id">出库单 {{ doc.number || doc.id }}（{{ String(doc.status) === '2' ? '已出库' : '待核对' }}）</p>
        <p v-if="data.outbound">自动出库：{{ data.outbound.status }} · {{ data.outbound.reason || '等待处理' }}</p>
        <div class="lifecycle-actions">
          <el-button v-if="!data.cancellation || data.cancellation.status === 'aborted'" :disabled="busy" type="danger" @click="act('begin')">发起取消</el-button>
          <template v-if="data.cancellation && !terminal">
            <el-button :disabled="busy" @click="act('refresh')">核对关联单据</el-button>
            <el-button v-if="['pending','blocked'].includes(data.cancellation.status)" :disabled="busy" type="danger" @click="act('remove')">尝试删除小满订单</el-button>
            <el-button :disabled="busy" @click="act('retain')">保留原单并取消业务</el-button>
            <el-button v-if="['pending','blocked'].includes(data.cancellation.status)" :disabled="busy" @click="act('abort')">撤回取消申请</el-button>
          </template>
          <template v-if="!['cancel_pending','cancelled'].includes(data.status)">
            <el-button :disabled="busy" @click="act('outbound_retry')">恢复漏建 / 未发送出库</el-button>
            <el-button :disabled="busy" @click="act('ack_outbound')">确认出库资料已核对</el-button>
          </template>
          <el-button :disabled="busy" @click="load">刷新处理结果</el-button>
        </div>
        <p>已有出库单不自动整单重建；补发、退货及退款请按实际业务处理。保留原单取消不会执行退款或库存冲销。</p>
      </template>
      <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    </div>
  </el-drawer>
</template>
<script setup>
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { getInvoiceLifecycle, applyInvoiceLifecycle } from '@/api/invoice'
const props = defineProps({ invoiceId: { type: Number, required: true } })
const emit = defineEmits(['changed'])
const visible = ref(false), data = ref(null), busy = ref(false), error = ref('')
const terminal = computed(() => ['remote_deleted','retained','aborted'].includes(data.value?.cancellation?.status))
const states = { pending: '待核对', blocked: '有关联事项待处理', deleting: '删除处理中', uncertain: '删除结果待核对', remote_deleted: '远端已删除，本地归档', retained: '业务已取消，原单保留', aborted: '取消已撤回' }
const prompts = {
  begin: '将冻结订单编辑、新回款发送和自动出库。请填写取消原因。',
  remove: '将实时核对并尝试删除小满订单，方舟保留原单。请确认已处理关联货款并填写依据。',
  retain: '保留小满及方舟原单，停止后续自动出库和回款。不会执行退款或库存冲销，请填写货款及库存的处理安排。',
  abort: '恢复原订单业务状态及尚未执行的自动任务。请填写撤回原因。',
  outbound_retry: '仅恢复未发送或漏建任务。已有出库、结果不确定及删除后任务不会重建。请填写核对依据。',
  ack_outbound: '系统会重新核对数量与明细关联；请确认价格、地址、备注已经人工核对，填写依据。',
}
async function load() { data.value = await getInvoiceLifecycle(props.invoiceId) }
async function open() { visible.value = true; busy.value = true; error.value = ''; try { await load() } catch (e) { error.value = e.response?.data?.detail || '暂时无法读取订单状态，请稍后重试' } finally { busy.value = false } }
async function act(action) {
  if (busy.value) return
  busy.value = true
  let reason = '管理员请求重新核对原订单及关联单据'
  if (action !== 'refresh') {
    try { reason = (await ElMessageBox.prompt(prompts[action], '确认处理', { inputValidator: v => v?.trim().length >= 10 || '请填写至少10字依据', confirmButtonText: '确认执行' })).value.trim() }
    catch { busy.value = false; return }
  }
  busy.value = true; error.value = ''
  try {
    await applyInvoiceLifecycle(props.invoiceId, { action, reason, expected_version: data.value.version, confirmed: true })
    await load(); emit('changed')
  } catch (e) {
    error.value = e.response?.data?.detail || '结果尚未确认，请刷新原任务；不要重复发送'
    await load().catch(() => {})
  } finally { busy.value = false }
}
</script>
<style scoped>
.lifecycle-body { padding: 0 12px; }
.lifecycle-actions { display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0; }
p { color: var(--text-secondary); line-height: 1.7; }
</style>
