// Upload IDs only correlate placeholders within this page; they are never saved.
let uploadSequence = 0

export function createImageUploadId() {
  return `image-upload-${++uploadSequence}`
}

export function knowledgeImageUploadError(error) {
  if (['ECONNABORTED', 'ETIMEDOUT'].includes(error?.code)) {
    return '图片上传超时，服务器可能仍在处理；请稍后重新选择图片'
  }
  if (error?.response?.status === 413) return '图片超过上传大小限制，请缩小图片后重新选择'
  const detail = error?.response?.data?.detail
  const message = typeof detail === 'string' ? detail : detail?.message || error?.response?.data?.message
  if (typeof message === 'string' && message) return message
  if (error?.code === 'ERR_NETWORK') return '网络连接中断，服务器可能仍在处理；请检查网络后重新选择图片'
  return error?.message || '上传失败，请移除后重试'
}

export function pendingImageCount(content) {
  let count = 0
  function walk(node) {
    if (node?.type === 'knowledgeImage' && !Number.isInteger(node.attrs?.assetId)) count += 1
    for (const child of node?.content || []) walk(child)
  }
  walk(content)
  return count
}

export function contentForKnowledgeSave(content) {
  function clean(node) {
    if (!node || typeof node !== 'object') return node
    const result = { ...node }
    if (node.type === 'knowledgeImage') {
      result.attrs = {
        assetId: node.attrs.assetId,
        alt: node.attrs.alt || '',
        caption: node.attrs.caption || '',
      }
    } else if (node.attrs) {
      result.attrs = { ...node.attrs }
    }
    if (node.content) result.content = node.content.map(clean)
    if (node.marks) result.marks = node.marks.map(mark => ({
      ...mark,
      attrs: mark.attrs ? { ...mark.attrs } : mark.attrs,
    }))
    return result
  }
  return clean(content)
}
