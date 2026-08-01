/**
 * 拍摄页（CaptureScreen.vue）逻辑：相机取景/翻转、快门拍照、相册选图降采样、
 * 扫码上传的二维码渲染与待取照片预览、拍摄示范浮层。
 *
 * 从 CaptureScreen.vue 抽出（Task 7 加了二维码面板后 SFC 超过 500 行，
 * 触发前端硬约定 12：单文件 >500 行必须拆 composable）。纯搬运，不改行为。
 */
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

export function useCaptureScreen() {
  const flow = inject('tryonFlow')
  const isScene = computed(() => flow.mode.value === 'scene')

  const videoEl = ref(null)
  const cameraOn = ref(false)
  const previewUrl = ref('')
  const submitting = ref(false)
  // 拍摄示范一客只自动弹一次（flow 级标志，resetAll 复位）：register↔capture 往返、
  // 分析失败退回重拍都不重弹——避免同一位客户重复看引导、浮层盖住头部导航
  const guideOpen = ref(!flow.guideShown.value)
  flow.guideShown.value = true
  let stream = null
  let photoBlob = null

  function openGuide() {
    guideOpen.value = true
    flow.touch()
  }

  function closeGuide() {
    guideOpen.value = false
    flow.touch()
  }

  // 默认前置自拍；「反转镜头」切后置（顾问帮客户拍/平板朝外摆位）。facingMode 传裸值
  // 是 ideal 语义：单摄设备请求后置不报错，浏览器自动回退可用摄像头——所以成功后回读
  // 实际 facing 同步状态，防止单摄平板上按钮切了状态、画面却还是前置导致镜像方向错
  const facing = ref('user')
  let flipping = false

  async function startCamera() {
    stopCamera()
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing.value, width: { ideal: 1280 }, height: { ideal: 1280 } },
      })
      videoEl.value.srcObject = stream
      cameraOn.value = true
      const actual = stream.getVideoTracks()[0]?.getSettings?.().facingMode
      if (actual) facing.value = actual // 桌面摄像头常无此字段 → 保留请求值
    } catch (e) {
      cameraOn.value = false // 无摄像头/未授权 → 文件选择兜底
    }
  }

  onMounted(startCamera)

  async function flipCamera() {
    if (flipping) return // 双击守卫：在途 getUserMedia 未归还前不重复发起（防流泄漏）
    flipping = true
    facing.value = facing.value === 'user' ? 'environment' : 'user'
    await startCamera()
    flipping = false
    flow.touch()
  }

  onBeforeUnmount(() => {
    stopCamera()
    if (flashTimer) clearTimeout(flashTimer)
    // 本实例即将销毁：清掉指向本实例 previewUrl 的回调。拍摄页会在 capture↔register/
    // analyzing 之间反复挂载/卸载，而 pollPending 的轮询活在 flow 里跨挂载持续跑；
    // 不清的话，旧实例卸载后若待取照片才到达，会把 URL 写进一个没人看得见的死引用里
    flow.setPendingHandler(null)
  })

  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach(t => t.stop())
      stream = null
    }
  }

  // ── 扫码上传：画二维码 + 接收待取照片 ──
  const qrCanvas = ref(null)
  // 扫码来源的预览是服务端图片，弱网下有真实加载耗时；现场拍照走本地 blob 是同步可用的，
  // 不需要这个状态（两条路径共用同一个 <img>，靠这个 ref 区分要不要露加载提示）
  const previewLoading = ref(false)

  // 二维码：qrcode 动态引入，失败静默降级为不显示（与 ResultScreen 同策略）
  watch([() => flow.qrUrl.value, qrCanvas], async () => {
    if (!flow.qrUrl.value) return
    await nextTick()
    if (!qrCanvas.value) return
    try {
      const QRCode = (await import('qrcode')).default
      // 墨色码点 + 暖米底：黑金语系里可扫性最稳的组合（反色码部分扫码器不认）。
      // 这两个是字面 hex 而非裸写的 CSS 颜色——qrcode 库自己解析颜色字符串，不认
      // var(--xk-*)，只能传真实色值；check_conventions 的裸 hex 红线管的是 <style>
      // 里的样式声明，不是画布 API 的参数，这里不算违反宪法 13
      await QRCode.toCanvas(qrCanvas.value, flow.qrUrl.value, {
        width: 220, margin: 1,
        color: { dark: '#0c0a08', light: '#f3ead9' },
      })
    } catch (e) { /* 依赖缺失时不显示二维码，不阻断流程 */ }
  }, { immediate: true })

  // 面板有效期提示：qrExpiresAt 是开面板那一刻定下的绝对时间戳，取一次差值即可——
  // 不需要每秒重算的倒计时，也就不用额外定时器；只是让「10 分钟后静默消失」变得可预期，
  // 不是让客户盯着表看
  const qrValidMinutes = computed(() => {
    if (!flow.qrExpiresAt.value) return 10
    return Math.max(1, Math.round((flow.qrExpiresAt.value - Date.now()) / 60000))
  })

  // 手机传到的照片直接进既有预览态：与现场拍照共用「重拍 / 就用这张」两个按钮，
  // 顾问在同一个位置做同一个决定
  function openPendingPhoto(photoUrl) {
    previewLoading.value = true
    previewUrl.value = photoUrl
  }
  function onPreviewLoaded() {
    previewLoading.value = false
  }
  function onPreviewError() {
    previewLoading.value = false
    if (previewUrl.value.startsWith('blob:')) return // 本地 blob 极少加载失败，出现也不该报「服务器已收到」
    // 后端已经从待取目录把这张照片收下了，缩略图加载失败不影响提交——不清 previewUrl/pendingName，
    // 客户仍可直接点「就用这张」，只是看不到确认用的缩略图
    flow.errorText.value = '预览图加载较慢或失败，可直接点“就用这张”提交（服务器已收到照片）'
  }
  flow.setPendingHandler(openPendingPhoto)

  function snap() {
    const video = videoEl.value
    // 即时反馈：先冻结取景画面 + 快门闪一下，再做异步 toBlob——否则平板 WebView 上
    // toBlob 有可感延迟，快门像"点了没反应"
    video.pause()
    triggerFlash()
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
      if (!blob) { video.play?.()?.catch(() => {}); return } // 极端失败恢复取景
      photoBlob = blob
      // 防串源：新拍的照片作废旧的扫码待取名。createSession 按「有 pendingName 就优先用它」
      // 判断来源，不清的话——分析失败自动退回本屏是既有路径（poll() 里直接跳 step，不经过
      // retake()）——现场重拍会静默提交回那张旧的扫码照，而不是刚拍的这张
      flow.pendingName.value = ''
      previewUrl.value = URL.createObjectURL(blob)
    }, 'image/jpeg', 0.9)
  }

  const flashing = ref(false)
  let flashTimer = null
  function triggerFlash() {
    flashing.value = true
    if (flashTimer) clearTimeout(flashTimer)
    flashTimer = setTimeout(() => { flashing.value = false }, 180)
  }

  // 相册/系统相机原片先在端上压到与拍照路径同口径（1080px JPEG）再传：
  // 原图 3~15MB 会撞云 Nginx 5m 上限（2026-07-17 展会 413 实case），且过 frp 隧道极慢。
  // 不做方形裁切——相册照人脸位置任意，居中裁可能切脸；等比缩放交给取景框 object-fit 展示
  const PICK_MAX_EDGE = 1080
  const PICK_RAW_OK_BYTES = 1024 * 1024 // 尺寸达标且 ≤1MB 的原图直接用，避免无谓二次有损

  async function downscalePickedPhoto(file) {
    const url = URL.createObjectURL(file)
    try {
      const img = new Image()
      img.src = url
      await img.decode()
      const scale = PICK_MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight)
      if (scale >= 1 && file.size <= PICK_RAW_OK_BYTES) return file
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(img.naturalWidth * Math.min(scale, 1))
      canvas.height = Math.round(img.naturalHeight * Math.min(scale, 1))
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height)
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9))
      return blob || file
    } catch (e) {
      return file // 解码失败（损坏/罕见格式）：退回原图直传，后端 downscale_inplace 兜底
    } finally {
      URL.revokeObjectURL(url)
    }
  }

  async function onFilePick(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const blob = await downscalePickedPhoto(file)
    photoBlob = blob
    flow.pendingName.value = '' // 同 snap()：本地相册/系统相机取到新照片同样要作废旧的扫码待取名
    previewUrl.value = URL.createObjectURL(blob)
  }

  function retake() {
    // 只对本地 blob 调 revoke：待取照片的 previewUrl 是服务端 URL，
    // 对非 blob URL 调 revokeObjectURL 是无声的错用
    if (previewUrl.value.startsWith('blob:')) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
    previewLoading.value = false
    photoBlob = null
    flow.pendingName.value = ''   // 不清则「重拍」后仍会提交上一张扫码传来的照片
    // 恢复取景（snap 时 pause 了）；仅相机路径，文件选择兜底下 video 无流，play() 会 reject
    if (cameraOn.value) videoEl.value?.play?.()?.catch(() => {})
  }

  async function confirm() {
    // 两种来源二选一即可提交：现场拍照有 blob，扫码上传有待取文件名
    if ((!photoBlob && !flow.pendingName.value) || submitting.value) return
    submitting.value = true
    try {
      // 不在此处 stopCamera：上传失败会留在拍摄页（errorText 提示），提前停流
      // 会让「重拍」露出黑屏死相机；成功离屏时 onBeforeUnmount(stopCamera) 兜底
      await flow.submitPhoto(photoBlob)
    } finally {
      submitting.value = false
    }
  }

  return {
    flow, isScene,
    videoEl, cameraOn, previewUrl, submitting,
    guideOpen, openGuide, closeGuide,
    facing, flipCamera,
    qrCanvas, previewLoading, qrValidMinutes,
    onPreviewLoaded, onPreviewError,
    flashing, snap, onFilePick, retake, confirm,
  }
}
