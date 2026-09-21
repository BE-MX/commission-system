<template>
  <el-button v-permission="'receipt:admin'" @click="open">核实远端删改</el-button>
  <el-dialog v-model="visible" title="核实小满回款变更" width="min(600px, 94vw)" append-to-body :close-on-click-modal="false">
    <div v-loading="busy">
      <el-alert title="此操作只登记已核实的小满变更，不执行退款。按小满净额加本地分摊费用登记，保留原小满ID、凭证和变更前记录。" type="warning" :closable="false" />
      <template v-if="proof">
        <p>小满回款 ID：{{ proof.remote_id }}</p>
        <p v-if="!proof.after">已查询到原回款不存在；确认后释放该笔登记额度。</p>
        <el-table :data="rows" class="list-table" border>
          <el-table-column prop="label" label="项目" />
          <el-table-column prop="before" label="方舟原记录" />
          <el-table-column prop="after" label="核对后方舟记录" />
        </el-table>
        <el-input v-model="reason" type="textarea" placeholder="填写实际收款、退款及远端变更的核对依据（至少10字）" maxlength="500" />
        <el-checkbox v-model="confirmed">已核实真实资金情况，确认登记以上变更</el-checkbox>
      </template>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </div>
    <template #footer><el-button :disabled="busy" @click="load">重新预览</el-button><el-button type="primary" :loading="busy" :disabled="!proof || !confirmed || reason.trim().length < 10" @click="accept">确认登记</el-button></template>
  </el-dialog>
</template>
<script setup>
import { computed, ref } from 'vue'
import { previewReceiptRemoteChange, acceptReceiptRemoteChange } from '@/api/receipt'
const props = defineProps({ receiptId: { type: Number, required: true } })
const emit = defineEmits(['updated'])
const visible = ref(false), busy = ref(false), proof = ref(null), error = ref(''), reason = ref(''), confirmed = ref(false)
const labels = { amount: '回款金额', bank_charge: '手续费', collection_date: '回款日期', collect_status: '财务状态（1已生效，0未生效）' }
const rows = computed(() => Object.entries(labels).map(([key, label]) => ({ label, before: proof.value?.before[key], after: proof.value?.after?.[key] ?? '远端已删除' })))
async function load() {
  if (busy.value) return
  busy.value = true; proof.value = null; confirmed.value = false; error.value = ''
  try { proof.value = await previewReceiptRemoteChange(props.receiptId) }
  catch (e) { error.value = e.response?.data?.detail || '未取得可靠证据，请稍后重试' }
  finally { busy.value = false }
}
async function open() { visible.value = true; reason.value = ''; await load() }
async function accept() {
  if (busy.value || !proof.value || !confirmed.value || reason.value.trim().length < 10) return
  busy.value = true
  try {
    const row = await acceptReceiptRemoteChange(props.receiptId, { version: proof.value.version, evidence_hash: proof.value.evidence_hash, reason: reason.value.trim(), confirmed: true })
    visible.value = false; emit('updated', row)
  } catch (e) { error.value = e.response?.data?.detail || '结果未确认，请刷新原回款'; proof.value = null; confirmed.value = false }
  finally { busy.value = false }
}
</script>
