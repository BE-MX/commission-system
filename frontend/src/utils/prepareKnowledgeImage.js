// Match the server's display size while preserving PNG/WebP transparency.
// Small files keep their original bytes; only use a re-encoding if it saves bytes.
export async function prepareKnowledgeImage(file) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size <= 400 * 1024) return file
  // Let the server enforce its configured upload/pixel limits on oversized inputs.
  if (file.size > 10 * 1024 * 1024) return file
  const url = URL.createObjectURL(file)
  try {
    const image = await new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error('图片无法解码，请选择有效的 JPEG、PNG 或 WebP 图片'))
      img.src = url
    })
    if (image.naturalWidth * image.naturalHeight > 60_000_000) return file
    const scale = Math.min(1, 2400 / Math.max(image.naturalWidth, image.naturalHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) return file
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise(resolve => canvas.toBlob(resolve, file.type, 0.9))
    // A browser without the requested encoder may return PNG instead.
    if (!blob || blob.type !== file.type || blob.size >= file.size) return file
    return new File([blob], file.name, { type: blob.type, lastModified: file.lastModified })
  } finally {
    URL.revokeObjectURL(url)
  }
}
