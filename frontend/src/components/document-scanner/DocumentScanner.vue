<template>
  <section class="document-scan">
    <input ref="nativeInput" type="file" accept="image/*" capture="environment" hidden @change="pickPhoto" />
    <input ref="fileInput" type="file" accept="image/*" hidden @change="pickPhoto" />

    <div v-if="error" class="scan-error" role="alert">{{ error }}</div>

    <div v-if="step === 'ready'" class="lg-card is-static scan-entry" :aria-busy="busy">
      <span class="entry-icon" aria-hidden="true"><el-icon :size="34"><Document /></el-icon></span>
      <p>拍下纸张，自动找边并校正成平整的图片。</p>
      <div class="scan-actions">
        <GlassButton variant="primary" :icon="Camera" :loading="busy" @click="openCamera">拍摄文档</GlassButton>
        <GlassButton :icon="Picture" :disabled="busy" @click="fileInput.click()">选择照片</GlassButton>
      </div>
      <GlassButton
        v-if="cameraFailed"
        variant="link"
        :disabled="busy"
        @click="nativeInput.click()"
      >使用系统相机</GlassButton>
      <small v-if="finish === 'download'">图片在当前浏览器内处理</small>
      <GlassButton v-else variant="link" :disabled="busy" @click="$emit('cancel')">返回草稿</GlassButton>
    </div>

    <div v-else-if="step === 'camera'" class="lg-card is-static scan-workspace">
      <p class="scan-hint" role="status">{{ cameraHint }}</p>
      <div class="viewfinder" :style="viewfinderStyle">
        <video ref="video" autoplay muted playsinline @resize="updateVideoSize"></video>
        <svg v-if="liveCorners" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
          <polygon :points="liveCorners.map(point => point.join(',')).join(' ')" vector-effect="non-scaling-stroke" />
        </svg>
        <div v-else class="frame-guide" aria-hidden="true"></div>
      </div>
      <div class="scan-actions">
        <GlassButton @click="closeCamera">取消</GlassButton>
        <GlassButton variant="primary" :icon="Camera" :disabled="!cameraReady" @click="takePhoto">拍照</GlassButton>
      </div>
    </div>

    <div v-else-if="step === 'crop'" class="lg-card is-static scan-workspace" :aria-busy="busy">
      <div class="scan-toolbar">
        <h2>校正边缘</h2>
        <GlassButton variant="link" :disabled="busy" @click="corners = fullFrame()">使用整张</GlassButton>
      </div>
      <p class="scan-hint">{{ foundEdges ? '拖动四角，确认文档边缘。' : '未识别到完整边缘，可以拖动四角手动裁剪。' }}</p>
      <div class="crop-area" :inert="busy || undefined">
        <ScanCorners v-model="corners" :src="photoUrl" :ratio="photoRatio" />
      </div>
      <div class="scan-actions">
        <GlassButton :disabled="busy" @click="reset">换一张</GlassButton>
        <GlassButton variant="primary" :loading="busy" @click="previewCrop">应用校正</GlassButton>
      </div>
    </div>

    <div v-else class="lg-card is-static scan-workspace" :aria-busy="busy">
      <h2>扫描预览</h2>
      <div class="scan-result">
        <img :src="resultUrl" alt="校正后的文档" />
      </div>
      <div class="effect-options" role="group" aria-label="文档效果">
        <GlassButton
          v-for="option in effects"
          :key="option.value"
          :variant="effect === option.value ? 'primary' : 'secondary'"
          :aria-pressed="effect === option.value"
          :disabled="busy"
          @click="changeEffect(option.value)"
        >{{ option.label }}</GlassButton>
      </div>
      <div class="scan-actions">
        <GlassButton :disabled="busy" @click="step = 'crop'">调整边缘</GlassButton>
        <GlassButton v-if="finish === 'download'" variant="primary" :icon="Download" :disabled="busy" @click="downloadScan">保存 JPG</GlassButton>
        <GlassButton v-else variant="primary" :loading="busy" @click="useCapture">{{ finishLabel }}</GlassButton>
      </div>
      <GlassButton v-if="finish === 'download'" variant="link" :disabled="busy" @click="reset">扫描下一张</GlassButton>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { Camera, Document, Download, Picture } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import ScanCorners from './ScanCorners.vue'
import { encodeCapture } from './documentCapture.js'
import {
  canvasFrom, readDetectionPixels, readScanPhoto, rectifyDocument, renderScan, scanBlob,
} from './documentImage'
import { detectDocument } from './documentEdges'
import { distance, fullFrame, padDetectedQuad } from './documentQuad'

const props = defineProps({
  finish: { type: String, default: 'download' },
  finishLabel: { type: String, default: '使用这张' },
  defaultEffect: { type: String, default: 'original' },
  maxUploadBytes: { type: Number, default: 6 * 1024 * 1024 },
})
const emit = defineEmits(['captured', 'cancel'])

const PREVIEW_INTERVAL = 135
const PREVIEW_EDGE = 320
const PHOTO_DETECTION_EDGE = 448

const step = ref('ready')
const busy = ref(false)
const error = ref('')
const fileInput = ref(null)
const nativeInput = ref(null)
const video = ref(null)
const cameraReady = ref(false)
const cameraFailed = ref(false)
const videoRatio = ref(3 / 4)
const liveCorners = ref(null)
const corners = ref(fullFrame())
const foundEdges = ref(false)
const photoUrl = ref('')
const photoRatio = ref(1)
const resultUrl = ref('')
const effect = ref(props.defaultEffect)
const effects = [
  { value: 'original', label: '原图' },
  { value: 'enhanced', label: '增强' },
  { value: 'mono', label: '黑白' },
]

const cameraHint = computed(() => {
  if (!cameraReady.value) return '正在打开相机…'
  if (liveCorners.value) return '已找到文档边缘，可以拍照'
  return '将纸张的四个角都放进取景画面'
})
const viewfinderStyle = computed(() => ({
  aspectRatio: videoRatio.value,
  width: 'min(100%, ' + (videoRatio.value * 57) + 'svh, 720px)',
}))

let stream = null
let previewTimer = null
let previewCanvas = null
let edgeWorker = null
let pendingFrame = false
let missedFrames = 0
let cameraRequest = 0
let imageRequest = 0
let source = null
let rectified = null

function stopCamera() {
  cameraRequest++
  clearInterval(previewTimer)
  previewTimer = null
  edgeWorker?.terminate()
  edgeWorker = null
  pendingFrame = false
  missedFrames = 0
  releaseCanvas(previewCanvas)
  previewCanvas = null
  stream?.getTracks().forEach(track => track.stop())
  stream = null
  if (video.value) video.value.srcObject = null
  cameraReady.value = false
  liveCorners.value = null
}

function closeCamera() {
  stopCamera()
  step.value = 'ready'
}

function onCameraEnded(event) {
  if (step.value !== 'camera' || !stream?.getVideoTracks().includes(event.target)) return
  closeCamera()
  cameraFailed.value = true
  error.value = '相机已断开，可以重试或使用系统相机。'
}

function updateVideoSize() {
  if (video.value?.videoWidth && video.value?.videoHeight) {
    videoRatio.value = video.value.videoWidth / video.value.videoHeight
  }
}

function presentCorners(next) {
  if (!next) {
    if (++missedFrames >= 2) liveCorners.value = null
    return
  }
  missedFrames = 0
  const prior = liveCorners.value
  liveCorners.value = prior && next.every((point, i) => distance(point, prior[i]) < 0.035)
    ? next.map(([x, y], i) => [0.7 * x + 0.3 * prior[i][0], 0.7 * y + 0.3 * prior[i][1]])
    : next
}

function startEdgeWorker() {
  if (typeof Worker === 'undefined') return
  try {
    const worker = new Worker(new URL('./documentEdgeWorker.js', import.meta.url), { type: 'module' })
    worker.onmessage = ({ data }) => {
      if (worker !== edgeWorker) return
      pendingFrame = false
      presentCorners(data)
    }
    worker.onerror = () => {
      if (worker !== edgeWorker) return
      worker.terminate()
      edgeWorker = null
      pendingFrame = false
    }
    edgeWorker = worker
  } catch {
    edgeWorker = null
  }
}

function inspectFrame() {
  const frame = video.value
  if (pendingFrame || !frame?.videoWidth || frame.readyState < 2) return
  const pixels = readDetectionPixels(previewCanvas, frame, frame.videoWidth, frame.videoHeight, PREVIEW_EDGE)
  if (!edgeWorker) {
    presentCorners(detectDocument(pixels))
    return
  }
  pendingFrame = true
  const { width, height, data } = pixels
  edgeWorker.postMessage({ width, height, data }, [data.buffer])
}

async function openCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    nativeInput.value.click()
    return
  }
  error.value = ''
  cameraFailed.value = false
  videoRatio.value = 3 / 4
  step.value = 'camera'
  const request = ++cameraRequest
  try {
    const incoming = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 2560 }, height: { ideal: 1440 } },
      audio: false,
    })
    if (request !== cameraRequest) {
      incoming.getTracks().forEach(track => track.stop())
      return
    }
    stream = incoming
    stream.getVideoTracks().forEach(track => track.addEventListener('ended', onCameraEnded, { once: true }))
    await nextTick()
    if (request !== cameraRequest) return
    video.value.srcObject = stream
    await video.value.play()
    if (request !== cameraRequest) return
    updateVideoSize()
    cameraReady.value = true
    previewCanvas = document.createElement('canvas')
    startEdgeWorker()
    inspectFrame()
    previewTimer = setInterval(inspectFrame, PREVIEW_INTERVAL)
  } catch {
    if (request !== cameraRequest) return
    closeCamera()
    cameraFailed.value = true
    error.value = '网页相机无法打开，请允许访问相机，或使用系统相机。'
  }
}

function onVisibilityChange() {
  if (document.hidden && step.value === 'camera') closeCamera()
}

function replaceUrl(target, blob = null) {
  if (target.value) URL.revokeObjectURL(target.value)
  target.value = blob ? URL.createObjectURL(blob) : ''
}

function releaseCanvas(canvas) {
  if (canvas) canvas.width = canvas.height = 0
}

function reset() {
  imageRequest++
  stopCamera()
  replaceUrl(photoUrl)
  replaceUrl(resultUrl)
  releaseCanvas(source)
  source = null
  rectified = null
  busy.value = false
  error.value = ''
  cameraFailed.value = false
  effect.value = props.defaultEffect
  step.value = 'ready'
}

async function processPhoto(getPhoto) {
  const request = ++imageRequest
  busy.value = true
  error.value = ''
  let canvas
  try {
    canvas = await getPhoto()
    if (request !== imageRequest) return
    const detectionCanvas = document.createElement('canvas')
    const findEdges = edge => detectDocument(
      readDetectionPixels(detectionCanvas, canvas, canvas.width, canvas.height, edge, 'high'),
    )
    const detected = findEdges(PHOTO_DETECTION_EDGE) || findEdges(PREVIEW_EDGE)
    releaseCanvas(detectionCanvas)
    const preview = await scanBlob(canvas)
    if (request !== imageRequest) return
    source = canvas
    replaceUrl(photoUrl, preview)
    photoRatio.value = canvas.width / canvas.height
    foundEdges.value = !!detected
    corners.value = detected ? padDetectedQuad(detected) : fullFrame()
    step.value = 'crop'
  } catch {
    if (request === imageRequest) error.value = '无法读取这张照片，请重拍或选择 JPG、PNG 图片。'
  } finally {
    if (canvas !== source) releaseCanvas(canvas)
    if (request === imageRequest) busy.value = false
  }
}

function pickPhoto(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (file && !busy.value) processPhoto(() => readScanPhoto(file))
}

function takePhoto() {
  const frame = video.value
  if (!cameraReady.value || !frame?.videoWidth || frame.readyState < 2) return
  let photo
  try {
    photo = canvasFrom(frame, frame.videoWidth, frame.videoHeight)
  } catch {
    error.value = '拍摄失败，请重新取景后拍照。'
    return
  }
  closeCamera()
  processPhoto(() => photo)
}

async function updatePreview(nextEffect, applyCrop = false) {
  const request = ++imageRequest
  busy.value = true
  error.value = ''
  let canvas
  try {
    // Let the busy state paint before resampling a full-size photo.
    await new Promise(resolve => setTimeout(resolve, 16))
    if (request !== imageRequest) return
    if (applyCrop) {
      const pixels = source.getContext('2d').getImageData(0, 0, source.width, source.height)
      rectified = rectifyDocument(pixels, corners.value)
    }
    canvas = renderScan(rectified, nextEffect)
    const blob = await scanBlob(canvas)
    if (request !== imageRequest) return
    replaceUrl(resultUrl, blob)
    effect.value = nextEffect
    step.value = 'result'
  } catch {
    if (request === imageRequest) error.value = '处理图片失败，请重试或调整裁剪范围。'
  } finally {
    releaseCanvas(canvas)
    if (request === imageRequest) busy.value = false
  }
}

function previewCrop() {
  updatePreview(effect.value, true)
}

function changeEffect(nextEffect) {
  if (nextEffect !== effect.value) updatePreview(nextEffect)
}

async function useCapture() {
  const request = ++imageRequest
  busy.value = true
  error.value = ''
  const isCurrent = () => request === imageRequest
  try {
    const capture = await encodeCapture(source, rectified, effect.value, props.maxUploadBytes, isCurrent)
    if (capture && isCurrent()) emit('captured', { ...capture, corners: corners.value, effect: effect.value })
  } catch (failure) {
    if (isCurrent()) error.value = failure instanceof RangeError
      ? '校正图超过单据上传限制，请调整裁剪范围或换一张照片。'
      : '无法生成上传图片，请再试一次。'
  } finally {
    if (isCurrent()) busy.value = false
  }
}

function downloadScan() {
  const link = document.createElement('a')
  link.href = resultUrl.value
  link.download = '方舟扫描-' + Date.now() + '.jpg'
  document.body.append(link)
  link.click()
  link.remove()
}

onMounted(() => document.addEventListener('visibilitychange', onVisibilityChange))
onDeactivated(reset)
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  reset()
})
</script>

<style scoped>
.document-scan { max-width: 900px; margin: 0 auto; }
h2, p { margin: 0; }
h2 { font-size: 16px; }
.scan-entry, .scan-workspace {
  display: grid;
  justify-items: center;
  gap: 16px;
  padding: 20px;
}
.scan-entry { padding-block: clamp(28px, 8vh, 72px); text-align: center; }
.scan-entry p, .scan-hint, small { color: var(--text-secondary); }
.entry-icon {
  display: grid;
  place-items: center;
  width: 66px;
  height: 66px;
  border-radius: var(--dash-card-radius);
  background: var(--tag-gold-bg);
  color: var(--tag-gold-text);
}
.scan-actions, .effect-options {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  width: 100%;
}
.scan-workspace > h2, .scan-hint { justify-self: start; }
.scan-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.viewfinder {
  background: var(--text-primary);
  border-radius: var(--el-border-radius-base);
  overflow: hidden;
  position: relative;
}
.viewfinder video { display: block; width: 100%; height: 100%; }
.viewfinder svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  fill: var(--button-primary);
  fill-opacity: 0.07;
  stroke: var(--button-primary);
  stroke-width: 2px;
}
.frame-guide {
  position: absolute;
  inset: 9%;
  border: 1px dashed var(--button-primary);
  border-radius: var(--el-border-radius-base);
  pointer-events: none;
}
.crop-area { width: 100%; padding: 20px 22px; box-sizing: border-box; }
.scan-result {
  display: grid;
  place-items: center;
  width: 100%;
  min-height: 120px;
  background: var(--tag-neutral-bg);
  padding: 8px;
  box-sizing: border-box;
  border-radius: var(--el-border-radius-base);
}
.scan-result img {
  display: block;
  max-width: 100%;
  max-height: 50svh;
  background: var(--el-color-white);
  box-shadow: var(--el-box-shadow-light);
}
.scan-error {
  padding: 10px 14px;
  margin-bottom: 12px;
  border-radius: var(--el-border-radius-base);
  color: var(--tag-danger-text);
  background: var(--tag-danger-bg);
}
@media (max-width: 600px) {
  .scan-entry, .scan-workspace { padding-inline: 12px; gap: 12px; }
  .scan-actions > * { flex: 1 1 auto; }
}
@media (pointer: coarse) {
  .document-scan :deep(.glass-button) { min-height: 44px; }
}
</style>
