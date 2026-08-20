<template>
  <main class="mobile-reporting">
    <header class="reporting-header">
      <div class="brand-block">
        <span class="brand-mark">▦</span>
        <div><strong>内贸扫描报工</strong><span>{{ userName }} · 浏览器模式</span></div>
      </div>
      <div class="header-actions">
        <button type="button" aria-label="返回方舟" @click="goHome"><HomeFilled /></button>
        <button type="button" aria-label="退出登录" @click="logout"><SwitchButton /></button>
      </div>
    </header>

    <div class="reporting-content">
      <section class="status-card" :class="`is-${status.tone}`" aria-live="polite">
        <div class="status-icon"><Loading v-if="status.tone === 'loading'" class="spin" /><CircleCheckFilled v-else-if="status.tone === 'success'" /><WarningFilled v-else-if="status.tone === 'error'" /><Aim v-else /></div>
        <div><span class="status-label">CURRENT STATUS</span><h1>{{ status.title }}</h1><p>{{ status.detail }}</p></div>
      </section>

      <section v-if="pending" class="pending-card">
        <div><strong>有一笔提交结果待确认</strong><p>{{ pendingOwnerMismatch ? '这笔属于另一账号，请退出并切换回原账号。' : `数量 ${pending.qty} 件 · 系统将沿用原幂等号重试。` }}</p></div>
        <button v-if="!pendingOwnerMismatch" type="button" :disabled="busy" @click="retryPending">重试同一笔</button>
      </section>

      <section class="scanner-card">
        <div class="section-heading">
          <div><span class="eyebrow">SCAN INPUT</span><h2>扫描二维码</h2></div>
          <span class="secure-badge">HTTPS 安全摄像头</span>
        </div>

        <div class="camera-stage" :class="{ active: camera.active.value || camera.starting.value }">
          <video ref="videoRef" muted playsinline aria-label="二维码摄像头预览"></video>
          <div v-if="!camera.active.value && !camera.starting.value" class="camera-placeholder">
            <Camera /><strong>后置摄像头扫码</strong><span>将内贸二维码放入取景框</span>
          </div>
          <div v-if="camera.active.value" class="scan-frame" aria-hidden="true"><i></i></div>
          <div v-if="camera.starting.value" class="camera-loading"><Loading class="spin" /> 正在启动摄像头</div>
        </div>

        <p v-if="camera.errorMessage.value" class="camera-error">{{ camera.errorMessage.value }}</p>
        <div class="scan-actions">
          <button v-if="!camera.active.value" class="primary-button" type="button" :disabled="busy || Boolean(scanned) || Boolean(pending) || camera.starting.value" @click="startCamera">
            <Camera />{{ camera.starting.value ? '正在启动…' : '打开摄像头扫码' }}
          </button>
          <button v-else class="secondary-button" type="button" @click="camera.stop"><VideoPause />关闭摄像头</button>
          <button class="secondary-button" type="button" :disabled="busy || Boolean(scanned)" @click="showManual = !showManual"><EditPen />手动输入</button>
        </div>

        <form v-if="showManual" class="manual-form" @submit.prevent="submitManual">
          <input ref="manualInput" v-model.trim="manualCode" autocomplete="off" placeholder="ARK-D:... 或 ARK-DU:..." aria-label="二维码内容" />
          <button type="submit" :disabled="busy || !manualCode">识别</button>
        </form>

        <div class="wedge-hint"><Key /><div><strong>扫描枪已监听</strong><span>键盘模拟输出建议设置回车结束符，无需把光标放进输入框</span></div></div>
        <label class="auto-unit-setting"><input v-model="autoUnit" type="checkbox" /><span>扫描枪逐件码识别后自动报 1 件</span></label>
      </section>

      <section class="metrics-grid">
        <article><strong>{{ todayCount }}</strong><span>今日次数</span></article>
        <article><strong>{{ todayQty }}</strong><span>今日件数</span></article>
      </section>

      <section class="history-card">
        <div class="section-heading">
          <div><span class="eyebrow">TODAY</span><h2>今日报工记录</h2></div>
          <button class="refresh-button" type="button" aria-label="刷新今日报工记录" :disabled="busy" @click="loadHistory"><Refresh /></button>
        </div>
        <div v-if="todayRecords.length" class="history-list">
          <article v-for="record in todayRecords" :key="record.log_id" :class="{ revoked: isRevoked(record) }">
            <div class="record-main">
              <strong>{{ record.product_name || '-' }}</strong>
              <span class="record-process">{{ record.process_name }} × {{ record.report_qty }} 件</span>
              <span>{{ orderLabel(record) }} · {{ formatTime(record.reported_at) }}</span>
              <span v-if="record.unit_codes?.length">单件：{{ record.unit_codes.join('、') }}</span>
            </div>
            <span v-if="isRevoked(record)" class="revoked-label">已撤销</span>
            <button v-else type="button" :disabled="busy || Boolean(pending)" @click="revoke(record)">撤销</button>
          </article>
        </div>
        <div v-else class="empty-state"><Aim /><strong>今天还没有报工记录</strong><span>扫描第一张流转卡开始报工</span></div>
      </section>
    </div>

    <MobileReportConfirm
      v-if="scanned"
      :scan="scanned"
      :images="images"
      :submitting="busy"
      :blocked="Boolean(pending)"
      @cancel="cancelConfirmation"
      @confirm="confirmSubmission"
      @load-image="loadImage"
    />
  </main>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import {
  Aim, Camera, CircleCheckFilled, EditPen, HomeFilled, Key, Loading,
  Refresh, SwitchButton, VideoPause, WarningFilled,
} from '@element-plus/icons-vue'
import MobileReportConfirm from './MobileReportConfirm.vue'
import { useMobileDomesticReporting } from './composables/useMobileDomesticReporting'
import { useQrCamera } from './composables/useQrCamera'
import { useScannerWedge } from './composables/useScannerWedge'
import './mobile-reporting.css'

const videoRef = ref(null)
const manualInput = ref(null)
const manualCode = ref('')
const showManual = ref(false)
const camera = useQrCamera()
const {
  autoUnit, busy, images, pending, pendingOwnerMismatch, scanned, status,
  todayCount, todayQty, todayRecords, userName,
  cancelConfirmation, confirmSubmission, handleCode, loadHistory, loadImage, logout, retryPending, revoke,
} = useMobileDomesticReporting()

useScannerWedge(raw => {
  camera.stop()
  handleCode(raw, 'keyboard')
})

async function startCamera() {
  await nextTick()
  await camera.start(videoRef.value, raw => handleCode(raw, 'camera'))
}

function submitManual() {
  if (!manualCode.value) return
  camera.stop()
  const value = manualCode.value
  manualCode.value = ''
  showManual.value = false
  handleCode(value, 'manual')
}

function goHome() {
  window.location.href = '/'
}

function isRevoked(record) {
  return record.revoked === true || Number(record.revoked) === 1
}

function orderLabel(record) {
  return [record.domestic_no, record.order_no].filter(Boolean).join(' · ') || '-'
}

function formatTime(value) {
  return String(value || '').replace('T', ' ').slice(0, 19)
}
</script>
