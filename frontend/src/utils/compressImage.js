/**
 * 端上压图：长边限制 + JPEG 重编码，返回可直接投喂 FormData 的 File。
 *
 * 为什么必须端上压：走 leshine.work 公网上传要过「云 Nginx 5MB 上限（超限 413
 * 根本到不了后端）+ 新加坡→办公室 frp 跨境隧道（实测 15~120KB/s）」——手机原片
 * 3~15MB 必然被拒或超时（展会 2026-07-17 413 实案 / PM 站 2026-07-22 Q9 实案）。
 * kiosk 相册路径同思路已在生产验证（useCaptureScreen.downscalePickedPhoto）。
 *
 * 原图小且尺寸达标时原样返回，避免无谓二次有损；PNG 透明铺白底（与后端 JPEG 约定一致）。
 */
export async function compressImage(file, { maxEdge = 1600, quality = 0.85, keepUnderBytes = 400 * 1024 } = {}) {
  if (!/^image\/(jpeg|png|webp)$/i.test(file.type || '')) return file
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise((resolve, reject) => {
      const image = new Image()
      image.onload = () => resolve(image)
      image.onerror = reject
      image.src = url
    })
    const edge = Math.max(img.naturalWidth, img.naturalHeight)
    if (file.size <= keepUnderBytes && edge <= maxEdge) return file
    const scale = Math.min(1, maxEdge / edge)
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale))
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality))
    if (!blob) return file
    const stem = (file.name || 'photo').replace(/\.[^.]+$/, '')
    return new File([blob], `${stem}.jpg`, { type: 'image/jpeg' })
  } finally {
    URL.revokeObjectURL(url)
  }
}
