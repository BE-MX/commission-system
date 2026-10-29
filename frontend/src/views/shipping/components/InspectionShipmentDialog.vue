<template>
  <el-dialog
    v-model="visible"
    title="上传物流单"
    width="760px"
    class="inspection-shipment-dialog"
    :close-on-click-modal="false"
    :before-close="beforeClose"
    destroy-on-close
    @closed="handleClosed"
  >
    <div v-loading="loading" class="shipment-dialog-body">
      <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
      <template v-else-if="prefill">
        <dl class="shipment-context">
          <div><dt>验货单号</dt><dd>{{ prefill.outbound_no }}</dd></div>
          <div><dt>订单 ID</dt><dd>{{ prefill.order_id || '—' }}</dd></div>
          <div><dt>客户</dt><dd>{{ prefill.customer_name || '—' }}</dd></div>
          <div>
            <dt>当前物流单</dt>
            <dd>{{ prefill.shipment ? `${prefill.shipment.carrier} · ${prefill.shipment.waybill_no}` : '未关联' }}</dd>
          </div>
        </dl>
        <p class="shipment-hint">
          收件人和国家已按订单客户信息预填，与运单面单不一致时以面单为准修改。
          保存后运单进入物流跟踪，并自动关联本验货单{{ prefill.shipment ? '（替换当前物流单）' : '' }}。
        </p>
        <WaybillUploadForm
          :state="upload"
          linkable
          :linking="linking"
          :link-blocked="linkBlocked"
          submit-text="保存并关联"
          @link-existing="linkExisting"
        />
      </template>
    </div>
  </el-dialog>

  <WaybillSuccessDialog
    v-model="upload.successVisible.value"
    :result-data="upload.resultData"
    :allow-continue="false"
  />
</template>

<script setup>
/**
 * 验货单「上传物流单」弹框：复用物流跟踪的运单上传表单（OCR / 手录 / 去重），
 * 按订单客户预填收件人与国家；保存＝录入物流跟踪＋关联本验货单，运单已存在时可直接关联。
 */
import { computed, ref, watch } from 'vue'
import {
  bindInspectionShipment, createInspectionShipment, getInspectionShipmentCandidate, getInspectionShipmentPrefill,
} from '@/api/shipping'
import { confirmAction, msgError, msgSuccessText } from '@/utils/feedback'
import { useWaybillUpload } from '@/views/tracking/composables/useWaybillUpload'
import WaybillUploadForm from '@/views/tracking/components/WaybillUploadForm.vue'
import WaybillSuccessDialog from '@/views/tracking/components/WaybillSuccessDialog.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  inspectionId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue', 'linked'])
const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })

const prefill = ref(null), loading = ref(false), loadError = ref(''), linking = ref(false)
let generation = 0, submittingFor = null

const versions = () => ({ edit_version: prefill.value.edit_version, shipment_version: prefill.value.shipment_version })
const upload = useWaybillUpload({
  defaults: () => ({
    recipient_name: prefill.value?.recipient_name || '',
    recipient_country: prefill.value?.recipient_country || '',
    ship_date: prefill.value?.ship_date || '',
  }),
  submit: async payload => {
    submittingFor = prefill.value.id
    try {
      return await createInspectionShipment(submittingFor, { ...payload, ...versions() })
    } catch (error) {
      // 运单已入库但没关联上（多半是别人刚改了这张验货单）：刷新版本号，用户直接点「关联这张已有运单」即可，不用关弹框重来
      if (String(error.response?.data?.detail || '').includes('已录入物流跟踪')) refreshVersions(submittingFor)
      throw error
    }
  },
  onSuccess: data => {
    visible.value = false
    emit('linked', submittingFor, data.shipment)
  },
  enabled: () => visible.value && Boolean(prefill.value),
})

watch(() => [props.modelValue, props.inspectionId], ([open, id]) => { if (open && id) load(id) }, { immediate: true })

// 运单号撞重复时先核对这张已有运单：不在查看范围内就直接说明原因，不给一个点了必失败的按钮
const candidate = ref(null)
let candidateKey = ''
watch(() => upload.duplicateInfo.value, info => {
  candidate.value = null
  candidateKey = info && prefill.value ? `${prefill.value.id}|${info.waybill_no}|${info.carrier}` : ''
  if (candidateKey) loadCandidate(candidateKey, info)
})
async function loadCandidate(key, info) {
  try {
    const res = await getInspectionShipmentCandidate(prefill.value.id, { waybill_no: info.waybill_no, carrier: info.carrier })
    if (key === candidateKey) candidate.value = res.data
  } catch (error) {
    console.warn('已有运单核对失败:', error.message)
  }
}
const linkBlocked = computed(() => (candidate.value && !candidate.value.visible
  ? `这张运单由 ${upload.duplicateInfo.value?.created_by || '其他同事'} 录入，不在你的物流跟踪查看范围内，无法从这里关联。请联系录入人在验货单上关联，或找管理员开通「查看全部物流」权限。`
  : ''))

async function load(id) {
  const current = ++generation
  prefill.value = null
  loadError.value = ''
  loading.value = true
  try {
    const res = await getInspectionShipmentPrefill(id)
    if (current !== generation) return
    prefill.value = res.data
    upload.resetAll()
  } catch (error) {
    if (current === generation) loadError.value = error.response?.data?.detail || '验货单信息加载失败，请关闭后重试'
  } finally {
    if (current === generation) loading.value = false
  }
}

const sameText = (a, b) => !a || !b || a.trim().toLowerCase() === b.trim().toLowerCase()

async function linkExisting(info) {
  if (linking.value || !prefill.value) return
  const { id, outbound_no: outboundNo, customer_name: customer, recipient_name: expectName, recipient_country: expectCountry } = prefill.value
  const found = candidate.value
  if (found && !found.visible) return
  // 关联后客户门户会展示这张运单的轨迹：把运单收件信息和本单客户摆在一起，手误串单一眼可见
  const mismatch = found && !(sameText(found.recipient_name, expectName) && sameText(found.recipient_country, expectCountry))
  const lines = [
    `运单 ${info.waybill_no}（${info.carrier}）收件人：${found?.recipient_name || '—'}，${found?.recipient_country || '—'}`,
    `验货单 ${outboundNo} 客户：${customer || '—'}，预填收件人 ${expectName || '—'}，${expectCountry || '—'}`,
    found?.linked_inspections ? `这张运单已关联另外 ${found.linked_inspections} 张验货单。` : '',
    mismatch ? '收件信息与本单客户不一致，关联后该客户能在客户门户看到这张运单的物流轨迹，请确认是同一票货。' : '',
  ].filter(Boolean)
  try {
    await confirmAction(lines.join('\n'), mismatch ? '收件信息不一致，确认关联？' : '关联已有运单', {
      type: mismatch ? 'warning' : 'info', confirmButtonText: '确认关联', cancelButtonText: '取消',
      customClass: 'shipment-link-confirm',
    })
  } catch { return }
  linking.value = true
  try {
    const res = await bindInspectionShipment(id, { waybill_no: info.waybill_no, carrier: info.carrier, ...versions() })
    msgSuccessText('已关联物流单')
    visible.value = false
    emit('linked', id, res.data)
  } catch (error) {
    msgError(error.response?.data?.detail || '关联失败，请稍后重试', error)
  } finally {
    linking.value = false
  }
}

// 入库/关联请求进行中不允许关弹框：结果未回来就关掉，用户不知道到底存没存
function beforeClose(done) {
  if (upload.submitting.value || linking.value) return
  done()
}

// 只更新版本号与当前关联，不重置用户已填的表单
async function refreshVersions(id) {
  const current = generation
  try {
    const res = await getInspectionShipmentPrefill(id)
    if (current !== generation || prefill.value?.id !== id) return
    const { edit_version: editVersion, shipment_version: shipmentVersion, shipment } = res.data
    Object.assign(prefill.value, { edit_version: editVersion, shipment_version: shipmentVersion, shipment })
  } catch (error) {
    console.warn('验货单版本刷新失败:', error.message)
  }
}

function handleClosed() {
  generation++
  candidateKey = ''
  candidate.value = null
  loading.value = false
  upload.resetAll()
}
</script>

<style scoped>
.shipment-dialog-body { min-height: 200px; }

.shipment-context {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 0 0 12px;
}
.shipment-context dt { font-size: 12px; color: var(--text-secondary); }
.shipment-context dd { margin: 4px 0 0; font-weight: 600; color: var(--text-primary); overflow-wrap: anywhere; }

.shipment-hint {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--text-secondary);
}

@media (max-width: 767px) {
  .shipment-context { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>

<style>
/* el-dialog 渲染到 body，非 scoped；手机端铺满可用宽度 */
@media (max-width: 767px) {
  .inspection-shipment-dialog.el-dialog { width: calc(100vw - 24px) !important; }
}
/* 关联确认框多行核对信息按行显示 */
.shipment-link-confirm .el-message-box__message p { white-space: pre-line; }
</style>
