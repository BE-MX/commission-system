<template>
  <el-dialog :model-value="true" title="恢复原出库任务" width="640px" append-to-body
    class="shipment-recovery-dialog" :close-on-click-modal="false" :close-on-press-escape="!busy"
    :show-close="!busy" :before-close="close">
    <p class="shipment-recovery-number">{{ row.settlement_no }}</p>
    <el-alert type="warning" :closable="false" show-icon
      title="仅查询不到单据不足以恢复。请先核实小满原请求已结束，且不会再生成单据；已有单据应返回核对并绑定原单。" />
    <el-form label-position="top" @submit.prevent="submit">
      <el-form-item label="核实记录／工单号" required>
        <el-input v-model="reference" type="textarea" :rows="3" :maxlength="200" show-word-limit
          :disabled="busy" placeholder="填写小满侧处理记录或工单号" />
      </el-form-item>
      <el-checkbox v-model="requestClosed" :disabled="busy" class="shipment-recovery-check">
        <span class="shipment-recovery-attestation">我已核实原请求已结束，且未生成、不会再生成出库单</span>
      </el-checkbox>
    </el-form>
    <p class="shipment-recovery-note">恢复后继续原批次，保留原编号、明细和资金分配。</p>
    <template #footer>
      <GlassButton :disabled="busy" @click="close">返回</GlassButton>
      <GlassButton v-permission="'shipment:admin'" variant="primary" :loading="busy"
        :disabled="!body || busy" @click="submit">核实未生成并恢复</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { outboundRecoveryBody } from '../composables/shipmentOutboundRecovery.js'

const props = defineProps({ row: { type: Object, required: true }, busy: Boolean })
const emit = defineEmits(['close', 'submit'])
const reference = ref(''), requestClosed = ref(false)
const body = computed(() => outboundRecoveryBody(props.row, requestClosed.value, reference.value))
function close() { if (!props.busy) emit('close') }
function submit() { if (body.value && !props.busy) emit('submit', body.value) }
</script>

<style scoped>
.shipment-recovery-number { margin: 0 0 12px; font-weight: 600; color: var(--text-primary); }
.el-form { margin-top: 16px; }
.shipment-recovery-check { height: auto; align-items: flex-start; }
.shipment-recovery-attestation { white-space: normal; }
.shipment-recovery-note { margin: 16px 0 0; color: var(--text-secondary); font-size: 12px; }
</style>
<style>.shipment-recovery-dialog { max-width: calc(100vw - 24px); }</style>
