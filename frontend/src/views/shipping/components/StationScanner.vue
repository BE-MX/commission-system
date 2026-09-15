<template>
  <section class="scanner" aria-label="出库单扫码相机">
    <div class="scanner-top"><strong>对准出库单右上角二维码</strong><button type="button" @click="cancel">取消扫描</button></div>
    <div class="camera-frame"><video ref="video" autoplay muted playsinline /><div class="scan-frame" aria-hidden="true" /></div>
    <p role="status">{{ error || '请保持手机稳定，识别后将自动打开出库单' }}</p>
    <button v-if="error" type="button" @click="start">重新打开相机</button>
  </section>
</template>
<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
const emit = defineEmits(['decoded', 'cancel'])
const video = ref(null), error = ref('')
let stream, timer, generation = 0
function stop() { generation++; clearTimeout(timer); stream?.getTracks().forEach(track => track.stop()); stream = null; if (video.value) video.value.srcObject = null }
function cancel() { stop(); emit('cancel') }
async function start() {
  stop(); error.value = ''; const batch = generation
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('请使用 HTTPS 页面并允许浏览器访问摄像头')
    const incoming = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } }, audio: false })
    if (batch !== generation) { incoming.getTracks().forEach(track => track.stop()); return }
    stream = incoming; video.value.srcObject = stream; await video.value.play()
    const { default: jsQR } = await import('jsqr')
    if (batch !== generation) return
    const canvas = document.createElement('canvas'), context = canvas.getContext('2d', { willReadFrequently: true })
    function tick() {
      if (batch !== generation || !video.value) return
      try {
      if (video.value.readyState >= 2 && video.value.videoWidth) {
        canvas.width = Math.min(720, video.value.videoWidth)
        canvas.height = Math.round(canvas.width * video.value.videoHeight / video.value.videoWidth)
        context.drawImage(video.value, 0, 0, canvas.width, canvas.height)
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height)
        const result = jsQR(pixels.data, canvas.width, canvas.height, { inversionAttempts: 'dontInvert' })
        if (result?.data) { stop(); emit('decoded', result.data); return }
      }
      timer = setTimeout(tick, 150)
      } catch {
        stop(); error.value = '二维码识别中断，请重新打开相机后重试'
      }
    }
    tick()
  } catch (e) {
    if (batch !== generation) return
    stop()
    error.value = e.name === 'NotAllowedError' ? '摄像头权限被拒绝，请在浏览器设置中允许后重试' : e.message || '无法打开摄像头，请关闭其他占用相机的应用后重试'
  }
}
function visibility() { if (document.hidden) cancel() }
onMounted(() => { start(); document.addEventListener('visibilitychange', visibility) })
onBeforeUnmount(() => { stop(); document.removeEventListener('visibilitychange', visibility) })
</script>
<style scoped>
.scanner{padding:16px;border:1px solid var(--border-color);border-radius:20px;background:var(--card-bg)}.scanner-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.scanner button{min-height:44px;border:1px solid var(--border-color);border-radius:12px;padding:8px;color:var(--text-primary);background:var(--page-bg)}.camera-frame{position:relative;overflow:hidden;border-radius:16px;background:var(--text-primary)}video{width:100%;display:block;min-height:250px;max-height:55dvh;object-fit:cover}.scan-frame{position:absolute;inset:18%;border:3px solid var(--color-primary);border-radius:12px;pointer-events:none}.scanner p{font-size:14px;color:var(--text-secondary);line-height:1.6}
</style>
