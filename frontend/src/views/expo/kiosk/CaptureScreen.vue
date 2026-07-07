<template>
  <div class="capture">
    <div class="viewport">
      <!-- 相机可用：实时取景；不可用：文件选择兜底 -->
      <video v-show="cameraOn && !previewUrl" ref="videoEl" autoplay playsinline muted />
      <img v-if="previewUrl" :src="previewUrl" class="preview" alt="预览" />

      <div v-if="!previewUrl" class="guide" />
      <div class="corner tl" /><div class="corner tr" />
      <div class="corner bl" /><div class="corner br" />

      <div v-if="!previewUrl" class="tip">
        {{ isScene ? '保持佩戴状态，将面部对准取景框' : '请将面部对准取景框' }}
        <small>{{ isScene ? '发型完整入镜 · 光线充足 · 拍完可重拍' : '光线充足 · 正对镜头 · 拍完可重拍' }}</small>
      </div>
      <div v-if="!cameraOn && !previewUrl" class="fallback">
        <label class="xk-btn ghost">
          从相册选择 / 调用系统相机
          <input type="file" accept="image/*" capture="user" hidden @change="onFilePick" />
        </label>
      </div>
    </div>

    <div class="actions">
      <template v-if="previewUrl">
        <button class="xk-btn ghost" @click="retake">重拍</button>
        <button class="xk-btn" :disabled="submitting" @click="confirm">
          {{ submitting ? '上传中…' : '就用这张' }}
        </button>
      </template>
      <!-- 三槽布局：快门始终居中，本地相册为右侧次级入口（不带 capture，直达相册） -->
      <template v-else-if="cameraOn">
        <span class="side" aria-hidden="true" />
        <button class="shutter" aria-label="拍照" @click="snap"><i /></button>
        <label class="xk-btn ghost side album">
          本地相册
          <input type="file" accept="image/*" hidden @change="onFilePick" />
        </label>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'

const flow = inject('tryonFlow')
const isScene = computed(() => flow.mode.value === 'scene')

const videoEl = ref(null)
const cameraOn = ref(false)
const previewUrl = ref('')
const submitting = ref(false)
let stream = null
let photoBlob = null

onMounted(async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 1280 } },
    })
    videoEl.value.srcObject = stream
    cameraOn.value = true
  } catch (e) {
    cameraOn.value = false // 无摄像头/未授权 → 文件选择兜底
  }
})

onBeforeUnmount(stopCamera)

function stopCamera() {
  if (stream) {
    stream.getTracks().forEach(t => t.stop())
    stream = null
  }
}

function snap() {
  const video = videoEl.value
  const size = Math.min(video.videoWidth, video.videoHeight)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = Math.min(size, 1080)
  const ctx = canvas.getContext('2d')
  ctx.drawImage(
    video,
    (video.videoWidth - size) / 2, (video.videoHeight - size) / 2, size, size,
    0, 0, canvas.width, canvas.height,
  )
  canvas.toBlob(blob => {
    photoBlob = blob
    previewUrl.value = URL.createObjectURL(blob)
  }, 'image/jpeg', 0.9)
}

function onFilePick(event) {
  const file = event.target.files?.[0]
  if (!file) return
  photoBlob = file
  previewUrl.value = URL.createObjectURL(file)
  event.target.value = ''
}

function retake() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  photoBlob = null
}

async function confirm() {
  if (!photoBlob || submitting.value) return
  submitting.value = true
  try {
    await flow.submitPhoto(photoBlob)
    stopCamera()
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.capture { flex: 1; display: flex; flex-direction: column; padding: 0 4vw 3vh; }
.viewport {
  position: relative; flex: 1; min-height: 0;
  border-radius: 26px; overflow: hidden;
  background: radial-gradient(60% 55% at 50% 42%, #2c251c, #15110c);
}
video, .preview {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: cover; transform: scaleX(-1); /* 镜像取景更符合直觉 */
}
.preview { transform: none; }
.guide {
  position: absolute; left: 50%; top: 46%; transform: translate(-50%, -50%);
  width: min(52vw, 300px); aspect-ratio: 0.78; border-radius: 50% / 54%;
  border: 2px dashed rgba(232, 196, 121, 0.75);
  box-shadow: 0 0 0 200vmax rgba(8, 6, 4, 0.55);
  animation: guide-pulse 2.6s ease-in-out infinite;
}
@keyframes guide-pulse {
  0%, 100% { border-color: rgba(232, 196, 121, 0.4); }
  50% { border-color: var(--xk-gold-hi); }
}
.corner { position: absolute; width: 26px; height: 26px; border: 2px solid var(--xk-gold); }
.corner.tl { top: 18px; left: 18px; border-right: 0; border-bottom: 0; border-radius: 8px 0 0 0; }
.corner.tr { top: 18px; right: 18px; border-left: 0; border-bottom: 0; border-radius: 0 8px 0 0; }
.corner.bl { bottom: 18px; left: 18px; border-right: 0; border-top: 0; border-radius: 0 0 0 8px; }
.corner.br { bottom: 18px; right: 18px; border-left: 0; border-top: 0; border-radius: 0 0 8px 0; }
.tip {
  position: absolute; left: 0; right: 0; bottom: 26px; text-align: center;
  font-size: 14px; letter-spacing: 0.2em; color: var(--xk-gold-hi);
}
.tip small { display: block; margin-top: 6px; font-size: 11px; color: var(--xk-mut); letter-spacing: 0.14em; }
.fallback { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); }
.actions {
  flex: none; display: flex; justify-content: center; gap: 16px;
  padding-top: 18px; min-height: 88px; align-items: center;
}
/* 快门两侧等宽占位，保证快门绝对居中；相册入口做次级视觉弱化 */
.side { width: 112px; flex: none; }
.album { display: flex; justify-content: center; cursor: pointer; }
.shutter {
  width: 72px; height: 72px; border-radius: 50%;
  border: 2px solid var(--xk-gold); background: transparent;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
}
.shutter i {
  width: 56px; height: 56px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, var(--xk-gold-hi), var(--xk-gold) 60%, var(--xk-gold-dim));
}
.shutter:active i { transform: scale(0.92); }
</style>
