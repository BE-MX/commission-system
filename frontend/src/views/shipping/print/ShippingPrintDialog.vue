<template>
  <el-dialog
    :model-value="visible" :title="title" width="960px"
    class="shipping-print-dialog" append-to-body top="5vh" destroy-on-close @update:model-value="close"
  >
    <div v-if="loadError" class="state-line">{{ loadError }}</div>
    <div v-else-if="loading" class="state-line">
      <el-icon class="is-loading"><Loading /></el-icon><span>加载打印内容…</span>
    </div>
    <!-- 预览用 iframe 装的是完整独立文档，打印时对它调 print()，
         所见即所印，也不会把列表页和侧边栏带进去 -->
    <iframe
      v-show="!loading && !loadError" ref="frameRef" class="preview-frame"
      :srcdoc="docHtml" title="打印预览"
    />

    <template #footer>
      <div class="footer-bar">
        <span class="tip">打印对话框里缩放选「实际大小 / 100%」，纸张 A4</span>
        <div class="footer-actions">
          <GlassButton variant="ghost" @click="close">关闭</GlassButton>
          <GlassButton variant="primary" left-icon="Printer" :disabled="loading || !!loadError" @click="doPrint">
            打印
          </GlassButton>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
/**
 * 发货检验打印弹框（出库单 / 验货单共用）。
 * 弹框停留在列表页上，用户关掉就回到原来的列表和抽屉，不用按浏览器后退。
 */
import { computed, onDeactivated, onUnmounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { Loading } from '@element-plus/icons-vue'
import { fetchImageDataUrl, getInspectionRecord, getOutboundPrintData } from '@/api/shipping'
import GlassButton from '@/components/GlassButton.vue'
import { buildInspectionDoc, buildOutboundDoc } from './printDocs'

const props = defineProps({
  visible: { type: Boolean, default: false },
  mode: { type: String, default: 'outbound' },   // outbound=出库单 / inspection=验货单
  // outbound 模式传 outbound_record_id，inspection 模式传验货单 id
  recordId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:visible'])

const loading = ref(false)
const loadError = ref('')
const payload = ref(null)
const frameRef = ref(null)
const auth = useAuthStore()
let sequence = 0, controller
function cancel() { sequence++; controller?.abort(); payload.value = null; loading.value = false }


const title = computed(() => (props.mode === 'inspection' ? '打印验货单' : '打印出库单'))

const docHtml = computed(() => {
  if (!payload.value) return ''
  return props.mode === 'inspection'
    ? buildInspectionDoc(payload.value)
    : buildOutboundDoc(payload.value)
})

// 验货照片要鉴权，转 data URL 带进 srcdoc；失败的图直接丢掉，不挡打印
async function loadInspectionPhotos(photos, signal) {
  const loaded = await Promise.all((photos || []).map(async photo => {
    try {
      return { item_id: photo.item_id ?? null, dataUrl: await fetchImageDataUrl(photo.file_path, { signal }) }
    } catch {
      return null
    }
  }))
  return loaded.filter(Boolean)
}

async function load() {
  const request = ++sequence, id = props.recordId, mode = props.mode
  controller?.abort(); controller = new AbortController()
  const signal = controller.signal
  const current = () => request === sequence && props.visible && id === props.recordId && mode === props.mode && !signal.aborted
  loading.value = true
  loadError.value = ''
  payload.value = null
  try {
    if (mode === 'inspection') {
      const res = await getInspectionRecord(id, { signal })
      if (!current()) return
      const data = res.data || {}
      if (data.status !== 'submitted' || data.outbound_sync_pending || data.required_recheck_ids?.length) {
        loadError.value = '出库资料待同步或待补验，请完成重新验货后打印'
        return
      }
      const items = data.items || []
      const nextPayload = {
        record: data,
        items,
        photosDataUrls: await loadInspectionPhotos((data.photos || []).filter(photo => !photo.stale), signal),
        photoItemMap: Object.fromEntries(items.map(item => [item.item_id, item.product_name])),
      }
      if (current()) payload.value = nextPayload
    } else {
      const res = await getOutboundPrintData(id, { signal })
      if (!current()) return
      const data = res.data || {}
      payload.value = {
        record: data.record || {},
        items: data.items || [],
        qr_code_base64: data.qr_code_base64 || '',
      }
    }
  } catch {
    if (!current()) return
    loadError.value = mode === 'inspection'
      ? '这张验货单加载失败（可能已被删除），原因见右上角报错提示'
      : '这张出库单加载失败，原因见右上角报错提示'
  } finally {
    if (current()) loading.value = false
  }
}

async function doPrint() {
  if (loading.value || loadError.value || !payload.value) return
  const request = sequence, id = props.recordId, mode = props.mode, snapshot = payload.value
  const current = () => request === sequence && props.visible && id === props.recordId && mode === props.mode && snapshot === payload.value
  loading.value = true
  try {
    if (props.mode === 'inspection') {
      const latest = (await getInspectionRecord(id)).data || {}
      if (!current()) return
      if (latest.status !== 'submitted' || latest.outbound_sync_pending || latest.required_recheck_ids?.length
          || latest.edit_version !== payload.value.record.edit_version) {
        throw new Error('inspection changed')
      }
    } else {
      const latest = (await getOutboundPrintData(id)).data || {}
      if (!current()) return
      if (JSON.stringify(latest.record) !== JSON.stringify(payload.value.record)
          || JSON.stringify(latest.items) !== JSON.stringify(payload.value.items)) {
        throw new Error('outbound changed')
      }
    }
    if (!current()) return
    const frame = frameRef.value
    if (!frame?.contentWindow) return
    // 必须先 focus：不聚焦时部分浏览器会把打印指令派给父文档，又变成打印整页
    frame.contentWindow.focus()
    frame.contentWindow.print()
  } catch {
    if (!current()) return
    loadError.value = '单据资料已变化，请关闭后重新打开打印预览'
  } finally { if (current()) loading.value = false }
}

function close() {
  cancel()
  emit('update:visible', false)
}

watch(() => [props.visible, props.recordId, props.mode], ([isOpen]) => {
  cancel()
  if (isOpen && props.recordId) load()
}, { immediate: true })
watch(() => JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions]), close)
onDeactivated(close)
onUnmounted(cancel)
</script>

<style scoped>
.state-line {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 60px 0;
  color: var(--el-text-color-secondary);
}

.preview-frame {
  width: 100%;
  height: 62vh;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.footer-bar {
  display: flex;
  align-items: center;
  gap: 16px;
}

.tip {
  flex: 1;
  text-align: left;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.footer-actions {
  display: flex;
  gap: 8px;
}
</style>

<style>
.shipping-print-dialog { max-width:calc(100vw - 24px); }
</style>
<style scoped>
@media(max-width:600px) { .footer-bar { align-items:stretch; flex-direction:column; } .footer-actions { justify-content:flex-end; } }
</style>
