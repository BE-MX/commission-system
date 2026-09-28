<template>
  <main ref="stationRoot" class="shipping-station" :class="{ 'has-quick-actions': view && !invalid }">
    <header class="station-header"><div class="station-brand"><img src="/shipping-app/icon-180.png" alt="" width="32" height="32" /><span>莱莎出库检验</span></div><button v-if="view" class="station-link" type="button" :disabled="busy" @click="end"><HomeFilled :size="18" />返回主页</button><span v-else class="station-device">共用手机 · 发货质检</span></header>
    <StationInstallHint v-if="!view && !scannerOpen" />
    <section ref="identityCard" class="identity-card" :class="{ chosen: operator, expired: invalid }" aria-live="polite" aria-atomic="true">
      <div class="identity-eyebrow"><UserRound :size="16" />{{ invalid ? '操作身份已失效' : view ? '本单操作人' : prompt }}</div>
      <div :key="selectionVersion" class="identity-name" :class="{ 'identity-change': operator && !invalid }">{{ operator?.name || '请先选择姓名' }}<BadgeCheck v-if="operator && !invalid" :size="28" aria-hidden="true" /></div>
      <div class="identity-caption">{{ view ? '本次上传、删除和提交将记录为以上人员' : '每单开始前，点选本次实际操作人' }}</div>
    </section>

    <section v-if="receipt" class="station-success" role="status"><CheckCircle2 :size="24" /><div><strong>{{ receipt.operator_name }}已提交</strong><p>{{ receipt.outbound_no }} · 下一单请重新选择人员</p></div></section>
    <section v-if="error" class="station-error" role="alert"><AlertCircle :size="20" /><div>{{ error }}<a v-if="loginRequired" :href="loginUrl">重新登录</a></div></section>

    <template v-if="!view">
      <router-link v-if="!scannerOpen" v-any-permission="['shipping_inspection:read', 'shipping_inspection:write', 'shipping_inspection:admin']" class="station-secondary station-query" to="/shipping/inspections?from=station">查询验货单</router-link>
      <StationScanner v-if="scannerOpen" @decoded="decoded" @cancel="scannerOpen = false" />
      <template v-else>
        <button class="scan-button" type="button" :disabled="busy || loading || loginRequired || !operators.length" @click="scanTap"><ScanLine :size="34" /><span>{{ busy ? '正在校验出库单…' : selected ? `以 ${selected.name} 身份扫描` : '扫出库单二维码' }}</span><ArrowRight :size="21" /></button>
        <p class="scan-hint">扫描纸质出库单右上角二维码，拍照后提交检验</p>
      </template>
      <StationOperatorPicker ref="picker" :people="operators" :selected-id="selected?.id" :loading="loading" :disabled="busy || scannerOpen || loginRequired" :attention="selectionVersion" @choose="choose" />
      <button v-if="!operators.length && !loading" class="station-secondary" :disabled="loginRequired" @click="loadOperators">重新加载人员</button>
    </template>

    <template v-else>
      <section class="station-card record-card"><div class="section-heading"><h1>{{ view.record.outbound_no }}</h1><span class="record-badge">{{ submitted ? '已提交' : '待提交' }}</span></div><p>{{ view.record.customer_name }}</p><small>出库日期 {{ view.record.outbound_date || '—' }}</small><div class="record-note">发货备注：{{ view.record.remark || '无' }}</div><button class="station-link" :disabled="busy || invalid || !!pendingSubmit" @click="refreshAtCurrentPosition"><RefreshCw :size="15" />刷新状态及已上传内容</button></section>
      <p v-if="submitted" class="readonly-hint">本单已提交，照片和视频只读。撤回后可刷新继续编辑。</p>
      <p v-if="view.outbound_sync_pending" class="readonly-hint">订单已修改，出库单等待仓库确认“同步并重验”。请暂缓上传、提交和使用旧纸单。</p>
      <p v-if="view.required_recheck_ids?.length" class="readonly-hint">出库资料已更新。旧版本照片仅作留档；请为变更明细补拍照片后提交。</p>
      <p v-if="missingRecheck.length" class="readonly-hint">还需补拍：{{ missingRecheck.join('、') }}</p>
      <section v-if="!invalid" class="station-card"><div class="section-heading"><h2>整单照片与视频</h2><span>整单留档</span></div><StationMediaGroup :media="mediaFor(null)" :feedback="uploadFeedbackFor(null)" @prepare-video="prepareVideo" @cancel-video="cancelVideoPreparation" @retry="retryMedia" @discard="discardCompression" :capture-disabled="!!pendingCompression" :session-id="sessionId" :editable="!submitted" :disabled="!canWrite" @upload="upload" @remove="remove" @error="fail" /></section>
      <section v-for="(item, index) in invalid ? [] : view.items" :key="item.item_id" class="station-card item-card" :data-item-id="item.item_id" tabindex="-1"><div class="item-top"><span class="item-index">{{ String(index + 1).padStart(2, '0') }}</span><span>数量 <b>{{ item.qty }} {{ item.unit }}</b></span></div><h2 class="item-model">{{ item.model || '未维护型号' }}</h2><p class="item-attributes">{{ [item.size, item.color].filter(Boolean).join(' / ') || item.product_name }}</p><p v-if="item.spec" class="item-spec">规格：{{ item.spec }}</p><StationMediaGroup :media="mediaFor(item.item_id)" :feedback="uploadFeedbackFor(item.item_id)" @prepare-video="prepareVideo" @cancel-video="cancelVideoPreparation" @retry="retryMedia" @discard="discardCompression" :capture-disabled="!!pendingCompression" :session-id="sessionId" :item-id="item.item_id" :editable="!submitted" :disabled="!canWrite" @upload="upload" @remove="remove" @error="fail" /></section>
      <section v-if="!invalid" class="station-card"><label class="remark-label" for="station-remark">检验备注</label><textarea id="station-remark" v-model="remark" maxlength="500" rows="3" :disabled="!canWrite" placeholder="填写需要说明的情况（选填）" /><p class="station-help">已上传 {{ photos.length }} 张照片、{{ videos.length }} 段视频。至少需要一张照片，视频不进入验货打印。</p></section>
      <div v-if="busy" class="upload-progress" role="status">{{ uploadStage || '正在处理，请勿切换人员' }}<progress v-if="uploadStage" :value="progress" max="100" /><span v-if="uploadStage">{{ progress }}%</span></div>
      <button v-if="pendingUpload && !busy && !invalid" class="station-secondary" @click="retryUpload">重试本次上传（不会重复保存）</button>
      <footer class="station-actions"><button v-if="!submitted && !invalid" class="submit-button" :disabled="busy || (!pendingSubmit && (!canWrite || !photos.length || missingRecheck.length))" @click="submit"><Check :size="20" />{{ pendingSubmit ? '确认上次提交结果' : `由 ${operator.name} 提交验货` }}</button><button class="station-secondary" :disabled="busy" @click="end">{{ invalid ? '重新选择人员并扫码' : '返回主页 / 重新选择人员' }}</button></footer>
    </template>
    <StationQuickNav v-if="view && !invalid" :items="view.items || []" :active-index="activeItemIndex" :refresh-disabled="busy || !!pendingSubmit" @top="scrollToTop" @refresh="refreshAtCurrentPosition" @jump="jumpToItem" />
    <div v-if="view && quickNotice" class="station-quick-notice" role="status">{{ quickNotice }}</div>
    <div class="station-footnote">莱莎方舟 · 发货检验</div>
  </main>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { FullScreen as ScanLine, User as UserRound, CircleCheck as BadgeCheck, Right as ArrowRight, CircleCheckFilled as CheckCircle2, Warning as AlertCircle, Refresh as RefreshCw, Check, HomeFilled } from '@element-plus/icons-vue'
import { confirmDanger } from '@/utils/feedback'
import { useShippingStation } from './composables/useShippingStation'
import StationOperatorPicker from './components/StationOperatorPicker.vue'
import StationScanner from './components/StationScanner.vue'
import StationMediaGroup from './components/StationMediaGroup.vue'
import StationInstallHint from './components/StationInstallHint.vue'
import StationQuickNav from './components/StationQuickNav.vue'
import { captureStationScroll, restoredStationScroll } from './composables/stationScroll'
const station = useShippingStation()
const { operators, selected, operator, view, remark, busy, loading, scannerOpen, error, invalid, loginRequired,
  prompt, selectionVersion, receipt, progress, uploadStage, photos, videos, submitted, canWrite, missingRecheck, sessionId, dirty, pendingUpload, pendingSubmit,
  choose, startScan, decoded, refresh, upload, retryUpload, remove, submit, end, loadOperators, fail } = station
const { uploadItemId, uploadError, pendingCompression, retryCompression, awaitingVideoActivation, discardCompression, prepareVideo, cancelVideoPreparation } = station
const picker = ref(null)
const stationRoot = ref(null)
const identityCard = ref(null)
const activeItemIndex = ref(0)
const quickNotice = ref('')
let highlightTimer
let scrollFrame
let noticeTimer
function showQuickNotice(message) {
  quickNotice.value = message
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { quickNotice.value = '' }, 1800)
}
const itemCards = () => [...(stationRoot.value?.querySelectorAll('.item-card') || [])]
const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
const itemOffset = () => {
  const card = identityCard.value
  if (!card) return 24
  return parseFloat(getComputedStyle(card).top) + card.getBoundingClientRect().height + 16
}
function updateActiveItem() {
  if (!view.value?.items?.length) { activeItemIndex.value = 0; return }
  const cards = itemCards()
  const index = cards.findIndex(card => card.getBoundingClientRect().bottom > itemOffset())
  activeItemIndex.value = index < 0 ? cards.length - 1 : index
}
function onScroll() {
  if (scrollFrame) return
  scrollFrame = requestAnimationFrame(() => { scrollFrame = 0; updateActiveItem() })
}
function scrollToTop() {
  window.scrollTo({ top: 0, behavior: reduceMotion() ? 'instant' : 'smooth' })
  showQuickNotice('已返回顶部')
}
function jumpToItem(index) {
  const target = itemCards()[index]
  if (!target) return
  clearTimeout(highlightTimer)
  itemCards().forEach(card => card.classList.remove('item-landed'))
  target.focus({ preventScroll: true })
  window.scrollTo({ top: window.scrollY + target.getBoundingClientRect().top - itemOffset(), behavior: reduceMotion() ? 'instant' : 'smooth' })
  target.classList.add('item-landed')
  highlightTimer = setTimeout(() => target.classList.remove('item-landed'), 2400)
  showQuickNotice(`已定位到第 ${String(index + 1).padStart(2, '0')} 项`)
}
async function refreshAtCurrentPosition() {
  if (busy.value || invalid.value || pendingSubmit.value || !sessionId.value) return
  const originalSession = sessionId.value
  const position = captureStationScroll(itemCards(), window.scrollY, itemOffset(), window.innerHeight)
  const refreshed = await refresh()
  await nextTick()
  if (sessionId.value !== originalSession) return
  const top = restoredStationScroll(position, itemCards(), window.scrollY)
  window.scrollTo({ top, behavior: 'instant' })
  updateActiveItem()
  if (refreshed) showQuickNotice('已刷新，已保留原浏览位置')
}
const allMedia = computed(() => [...photos.value, ...videos.value])
const mediaFor = id => allMedia.value.filter(media => (media.item_id || null) === (id || null))
const uploadFeedbackFor = id => uploadItemId.value === id ? {
  stage: uploadStage.value, progress: progress.value, error: uploadError.value,
  notice: awaitingVideoActivation.value ? '视频已选好，点击下方按钮开始压缩并上传' : '',
  canDiscard: !!pendingCompression.value && canWrite.value,
  retryLabel: !busy.value && !invalid.value && !submitted.value && !pendingSubmit.value
    ? awaitingVideoActivation.value ? '开始压缩并上传' : pendingCompression.value ? '重试压缩并上传' : pendingUpload.value ? '重试上传' : '' : '',
} : null
const retryMedia = () => pendingCompression.value ? retryCompression() : retryUpload()
const loginUrl = '/login?redirect=%2Fshipping%2Fscan'
function scanTap() {
  if (startScan() === false) picker.value?.$el.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
}
onMounted(() => window.addEventListener('scroll', onScroll, { passive: true }))
onBeforeUnmount(() => { window.removeEventListener('scroll', onScroll); cancelAnimationFrame(scrollFrame); clearTimeout(highlightTimer); clearTimeout(noticeTimer) })
onBeforeRouteLeave(async () => {
  if (busy.value) return false
  if (dirty.value || pendingCompression.value) { try { await confirmDanger('离开', '', '未上传视频和未提交备注不会保存，已上传文件保留。') } catch { return false } }
  return true
})
</script>
<style src="./station.css" scoped></style>
