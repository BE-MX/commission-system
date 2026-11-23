<template>
  <main class="mobile-waybills">
    <header v-if="!cameraLive" class="mobile-header">
      <button v-if="step !== 'list'" :disabled="busy === 'submit'" aria-label="返回列表" @click="back">‹</button>
      <router-link v-else to="/dashboard" aria-label="返回工作台">‹</router-link>
      <h1>{{ step === 'list' ? '手机录物流单' : step === 'camera' ? '拍运单' : '核对物流单' }}</h1>
      <span v-if="step === 'list'">{{ total }} 张</span>
    </header>
    <template v-if="step === 'list'">
      <div class="queue-tools">
        <div class="tabs" role="tablist" aria-label="物流单状态">
          <button :aria-selected="tab === 'pending'" role="tab" @click="tab = 'pending'">待录</button>
          <button :aria-selected="tab === 'done'" role="tab" @click="tab = 'done'">今天已录</button>
        </div>
        <label class="search"><span class="sr-only">搜索出库单号、客户名</span><input v-model="keyword" type="search" placeholder="搜索出库单号、客户名" /></label>
      </div>
      <p v-if="!allowed" class="notice">需要物流单上传权限，请联系管理员</p>
      <p v-if="loading && !rows.length" role="status" class="empty">正在加载验货单…</p>
      <p v-else-if="refreshing" role="status" class="refreshing">正在刷新…</p>
      <div v-else-if="queueError" class="alert" role="alert">{{ queueError }}<button @click="loadQueue">重试</button></div>
      <p v-else-if="!rows.length && !loading" class="empty">{{ tab === 'pending' ? '暂无待录物流单' : '今天还没有录入' }}</p>
      <section v-for="row in rows" :key="row.id" class="queue-card" :class="{ stale: refreshing }" :inert="refreshing || undefined">
        <div class="card-top"><span>{{ row.outbound_no }}</span><span v-if="row.cross_border?.is_9610" class="badge">9610</span></div>
        <h2>{{ row.customer_name || '未填写客户名' }}</h2>
        <p>{{ row.recipient_country || '国家待核对' }} · {{ row.quantity ?? '—' }} 件</p>
        <p class="secondary">{{ tab === 'done' ? '录入 ' + formatBeijingShortDateTime(row.bound_at) : '提交 ' + formatBeijingShortDateTime(row.submitted_at) }}</p>
        <div v-if="tab === 'done'" class="done-photo"><WaybillPhotoViewer v-if="row.photo" :photo="row.photo" /><strong>{{ row.shipment?.waybill_no }}</strong></div>
        <button :ref="element => setCardAction(row.id, element)" class="primary card-action" :disabled="!allowed || locked" @click="begin(row)">{{ tab === 'done' ? '更换物流单' : '拍运单' }}</button>
      </section>
      <div v-if="hasMore" ref="moreSentinel" class="more-sentinel"><button class="older" :disabled="loading" @click="loadMore">{{ loading ? '正在加载…' : '加载更多' }}</button></div>
      <button v-if="tab === 'pending' && !includeOlder && !keyword" class="older" @click="includeOlder = true">查看更早</button>
    </template>
    <template v-else>
      <section v-if="!cameraLive" class="customer-context"><strong>{{ selected.customer_name }}</strong><span>{{ selected.recipient_country || '国家待核对' }}</span><small>{{ selected.outbound_no }}</small></section>
      <DocumentScanner v-if="step !== 'list'" v-show="step === 'camera' || adjusting" ref="scanner" finish="capture" direct-capture immersive require-original default-effect="enhanced" :max-upload-bytes="16 * 1024 * 1024" @captured="onCaptured" @cancel="back" @camera="scannerCamera = $event">
        <template #overlay>
          <div class="camera-context">
            <button type="button" aria-label="返回列表" @click="back">‹</button>
            <div><strong>{{ selected.customer_name || '未填写客户名' }}</strong><small>{{ selected.outbound_no }} · {{ selected.recipient_country || '国家待核对' }}</small></div>
          </div>
        </template>
      </DocumentScanner>
      <template v-if="step === 'review' && !adjusting">
        <section class="review-card">
          <img :src="imageUrl" class="captured-photo" alt="本次运单增强裁正图" />
          <div class="photo-actions"><button :disabled="locked" @click="retakePhoto">重拍</button><button :disabled="locked" @click="adjust">调整边缘</button></div>
          <p v-if="busy === 'photo'" role="status">正在保存照片并识别…</p>
          <p v-if="notice" class="notice" role="status">{{ notice }}</p>
          <div v-if="error" class="alert" role="alert">{{ error }}<button v-if="!photoToken" :disabled="locked" @click="upload">重试上传</button></div>
          <fieldset :disabled="locked">
            <label>运单号 <span class="source-label">{{ numberSourceLabel[numberSource] }}</span><input v-model="form.waybill_no" inputmode="numeric" autocomplete="off" @input="editNumber" /></label>
            <p v-if="inferredDhl && !preview?.existing?.exists" class="secondary">按单号格式判定为 DHL</p>
            <label v-else>承运商<select v-model="form.carrier" :disabled="preview?.existing?.exists"><option value="">请选择承运商</option><option v-for="carrier in ['DHL', 'FedEx', 'UPS', 'SF', '未知']" :key="carrier">{{ carrier }}</option></select></label>
            <details :open="countryOpen" @toggle="countryOpen = $event.target.open"><summary>收件信息 <span v-if="!form.recipient_country" class="required">请填写收件国家</span></summary><label>收件人<input v-model="form.recipient_name" /></label><label>收件国家（必填）<input v-model="form.recipient_country" :aria-invalid="!form.recipient_country" required /></label><label>发件日期<input v-model="form.ship_date" type="date" /></label></details>
          </fieldset>
          <p v-if="selected.cross_border?.is_9610" class="notice">本单走 9610，请确认已在 DHL 填写跨境申报。{{ selected.cross_border.invoices?.map(invoice => invoice.alibaba_order_no).filter(Boolean).join('、') }}</p>
          <p v-if="selected.cross_border?.has_exported" class="notice">本单已导出报关，更换后会在 9610 核对里标为异常</p>
          <button class="sync-button" :disabled="locked || !photoToken" @click="sync">{{ busy === 'sync' ? '正在同步…' : preview ? '重新同步物流信息' : '同步物流信息' }}</button>
        </section>
        <section v-if="preview" class="review-card" aria-live="polite">
          <h2>物流信息与系统核对</h2>
          <p v-if="!preview.format_valid" class="alert">这不像 {{ form.carrier }} 运单号{{ form.carrier === 'DHL' ? '（应为 10 位数字）' : '' }}</p>
          <p :class="preview.sync_result === 'failed' ? 'notice' : 'secondary'">{{ syncMessage(preview.sync_result, form.carrier) }}</p>
          <strong v-if="preview.tracking?.status_text">{{ preview.tracking.status_text }}</strong>
          <p v-if="preview.tracking?.destination_country">目的国：{{ preview.tracking.destination_country }}</p>
          <div v-if="preview.tracking?.events?.length"><p>{{ eventText(preview.tracking.events[0]) }}</p><details v-if="preview.tracking.events.length > 1"><summary>最近轨迹</summary><p v-for="(event, index) in preview.tracking.events.slice(1, 5)" :key="index">{{ eventText(event) }}</p></details></div>
          <p v-if="preview.existing?.blocked" class="alert">这张运单已关联到另一位客户的验货单，很可能拍错了包裹，请核对手里的包裹。</p>
          <p v-else-if="preview.existing?.exists" class="notice">{{ preview.existing.outside_tracking_scope ? '运单已由其他同事录入' : `运单已录入，已关联本客户 ${preview.existing.linked_inspections || 0} 张验货单` }}，承运商沿用已有记录（{{ preview.existing.carrier }}）。</p>
          <div v-for="warning in preview.warnings" :key="warning.code" class="notice"><p>{{ warning.message }}</p><label v-if="warning.requires_confirmation" class="confirmation"><input v-model="confirmations" type="checkbox" :value="warning.code" :disabled="locked" />我已核对，确认没有拍错包裹</label></div>
        </section>
        <footer class="submit-bar"><p v-if="!preview">先同步物流信息</p><button class="primary" :disabled="!canSubmit" @click="submit">{{ busy === 'submit' ? '正在提交…' : submitLabel }}</button></footer>
      </template>
    </template>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import DocumentScanner from '@/components/document-scanner/DocumentScanner.vue'
import WaybillPhotoViewer from './components/WaybillPhotoViewer.vue'
import { formatBeijingShortDateTime } from '@/utils/datetime'
import { useMobileWaybills } from './composables/useMobileWaybills'
import { numberSourceLabel, syncMessage } from './composables/mobileWaybillState'
const { refreshing, nextInspectionId, total, hasMore, loadMore, allowed, tab, keyword, includeOlder, rows, loading, queueError, selected, step, busy, error, notice, imageUrl, form, numberSource, photoToken, preview, confirmations, countryOpen, locked, canSubmit, inferredDhl, submitLabel, loadQueue, begin, back, retake, captured, upload, editNumber, sync, submit } = useMobileWaybills()
const scanner = ref(null), adjusting = ref(false), scannerCamera = ref(false)
// 只有真正处在全屏取景时才隐藏页头和客户卡；扫描器退回入口/手动裁剪时仍要能返回、能看到是哪张单
const cameraLive = computed(() => step.value === 'camera' && scannerCamera.value)
const cardActions = new Map()
// 滑到列表底部附近自动续载下一页，按钮保留作兜底
const moreSentinel = ref(null)
let moreObserver = null
watch(moreSentinel, element => {
  moreObserver?.disconnect(); moreObserver = null
  if (!element || typeof IntersectionObserver === 'undefined') return
  moreObserver = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting) && hasMore.value && !loading.value && step.value === 'list') loadMore()
  }, { rootMargin: '400px 0px' })
  moreObserver.observe(element)
})
onBeforeUnmount(() => moreObserver?.disconnect())
function setCardAction(id, element) { if (element) cardActions.set(id, element); else cardActions.delete(id) }
watch(nextInspectionId, async id => {
  if (id == null) return
  await nextTick()
  if (nextInspectionId.value !== id || step.value !== 'list' || tab.value !== 'pending') return
  const action = cardActions.get(id)
  action?.closest('.queue-card')?.scrollIntoView({ block: 'center', behavior: 'instant' })
  action?.focus({ preventScroll: true })
}, { flush: 'post' })
function eventText(event) { return [formatBeijingShortDateTime(event.event_time), event.location, event.description].filter(Boolean).join(' · ') }
async function retakePhoto() { retake(); await nextTick(); scanner.value?.retake() }
function onCaptured(value) { adjusting.value = false; captured(value) }
async function adjust() { adjusting.value = true; await nextTick(); scanner.value?.adjustEdges() }
</script>

<style scoped>
.mobile-waybills { min-height: 100dvh; max-width: 560px; margin: auto; padding: 0 16px 110px; background: var(--page-bg); color: var(--text-primary); overflow-wrap: anywhere; box-sizing: border-box; }
.mobile-waybills * { box-sizing: border-box; }
.mobile-header { display: flex; align-items: center; gap: 12px; min-height: 64px; }
.mobile-header button { min-width: 44px; }
h1 { font-size: 19px; margin: 0; flex: 1; } h2 { font-size: 17px; margin: 10px 0; } p { line-height: 1.6; margin: 8px 0; } small, .secondary { color: var(--text-secondary); }
button, input, select, summary, .mobile-header a { min-height: 44px; font: inherit; } button { cursor: pointer; border: 1px solid var(--border-color); border-radius: 10px; padding: 10px 14px; background: var(--card-bg); color: var(--text-primary); } button:disabled { opacity: .5; cursor: default; } button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible { outline: 2px solid var(--button-primary); outline-offset: 2px; }
.mobile-header a { display: grid; place-items: center; font-size: 30px; width: 44px; color: var(--text-primary); text-decoration: none; }
.tabs { display: flex; gap: 8px; margin-bottom: 12px; }.tabs button { flex: 1; }.tabs [aria-selected="true"] { background: var(--tag-gold-bg); color: var(--tag-gold-text); border-color: var(--button-primary); }
input:not([type="checkbox"]), select { display: block; width: 100%; min-width: 0; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--card-bg); color: var(--text-primary); font-size: 16px; }
.queue-card, .review-card { margin: 16px 0; padding: 16px; border: 1px solid var(--border-color); border-radius: 16px; background: var(--card-bg); }.card-top { display: flex; justify-content: space-between; gap: 8px; color: var(--text-secondary); font-size: 13px; }.badge, .source-label { background: var(--tag-gold-bg); color: var(--tag-gold-text); padding: 3px 8px; border-radius: 6px; font-size: 12px; }.card-action, .older, .sync-button { width: 100%; }.primary { background: var(--button-primary); color: var(--button-primary-ink); border-color: var(--button-primary); font-weight: 600; }.done-photo { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }.empty { padding: 40px 0; text-align: center; color: var(--text-secondary); }
.customer-context { display: grid; grid-template-columns: 1fr auto; gap: 6px; padding: 14px; border-radius: 12px; background: var(--tag-gold-bg); }.customer-context strong { font-size: 18px; }.customer-context small { grid-column: 1 / -1; }.captured-photo { width: 100%; max-height: 230px; object-fit: contain; background: var(--page-bg); }.photo-actions { display: flex; gap: 8px; margin-top: 8px; }.photo-actions button { flex: 1; }
fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }label { display: block; margin: 12px 0; line-height: 1.8; }summary { cursor: pointer; padding: 10px 0; }.alert { padding: 12px; color: var(--tag-danger-text); background: var(--tag-danger-bg); border-radius: 8px; }.notice { padding: 12px; color: var(--tag-warning-text); background: var(--tag-warning-bg); border-radius: 8px; }.required { color: var(--tag-danger-text); font-size: 13px; }.confirmation { display: flex; align-items: center; gap: 8px; }.confirmation input { width: 22px; height: 22px; flex-shrink: 0; }.submit-bar { position: fixed; bottom: 0; left: 50%; transform: translateX(-50%); width: min(100%, 560px); padding: 12px 16px max(12px, env(safe-area-inset-bottom)); background: var(--card-bg); border-top: 1px solid var(--border-color); z-index: 5; }.submit-bar button { width: 100%; }.submit-bar p { margin: 0 0 6px; text-align: center; color: var(--text-secondary); font-size: 13px; }.camera-context { display: flex; align-items: center; gap: 8px; color: var(--camera-ink); }.camera-context button { flex-shrink: 0; width: 44px; padding: 0; border: 0; border-radius: 999px; background: var(--camera-scrim); color: var(--camera-ink); font-size: 26px; line-height: 1; }.camera-context div { display: grid; gap: 2px; min-width: 0; }.camera-context strong { font-size: 17px; text-shadow: 0 1px 2px var(--camera-scrim); }.camera-context small { font-size: 13px; opacity: .85; color: var(--camera-ink); }.refreshing { margin: 0; text-align: center; color: var(--text-secondary); font-size: 13px; }.queue-card.stale { opacity: .55; transition: opacity 150ms ease-out; }.more-sentinel { margin-bottom: 16px; }.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
