import { onBeforeUnmount, ref } from 'vue'

function cameraMessage(error) {
  if (!globalThis.isSecureContext) return '摄像头只能在 HTTPS 页面中使用'
  if (!navigator.mediaDevices?.getUserMedia) return '当前浏览器不支持摄像头扫码，请使用扫描枪或手动输入'
  if (error?.name === 'NotAllowedError') return '摄像头权限被拒绝，请在浏览器设置中允许访问摄像头'
  if (error?.name === 'NotFoundError') return '没有找到可用摄像头'
  if (error?.name === 'NotReadableError') return '摄像头正被其他应用占用'
  return error?.message || '摄像头启动失败，请使用扫描枪或手动输入'
}

export function useQrCamera() {
  const active = ref(false)
  const starting = ref(false)
  const errorMessage = ref('')
  let controls = null
  let generation = 0
  let resultLocked = false

  function stop() {
    generation += 1
    controls?.stop()
    controls = null
    active.value = false
    starting.value = false
    resultLocked = false
  }

  async function start(videoElement, onResult) {
    if (starting.value || active.value) return
    errorMessage.value = ''
    if (!globalThis.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      errorMessage.value = cameraMessage()
      return
    }

    const run = ++generation
    starting.value = true
    resultLocked = false
    try {
      const { BrowserQRCodeReader } = await import('@zxing/browser')
      const reader = new BrowserQRCodeReader(undefined, {
        delayBetweenScanAttempts: 180,
        delayBetweenScanSuccess: 500,
      })
      const nextControls = await reader.decodeFromConstraints(
        {
          audio: false,
          video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 640 },
            height: { ideal: 480 },
          },
        },
        videoElement,
        result => {
          if (!result || resultLocked || run !== generation) return
          resultLocked = true
          const text = result.getText()
          stop()
          onResult(text)
        },
      )
      if (run !== generation) {
        nextControls.stop()
        return
      }
      controls = nextControls
      active.value = true
    } catch (error) {
      if (run === generation) errorMessage.value = cameraMessage(error)
      stop()
    } finally {
      if (run === generation) starting.value = false
    }
  }

  onBeforeUnmount(stop)

  return { active, starting, errorMessage, start, stop }
}
