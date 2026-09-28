import { formatBeijingDate } from '@/utils/datetime'

// URL  helpers
export function getThumbUrl(path) {
  if (!path) return ''
  return `/uploads/assets/${path}`
}

export function getFileUrl(path) {
  if (!path) return ''
  return `/uploads/assets/${path}`
}

export function getTagImageUrl(path) {
  if (!path) return ''
  return `/uploads/${path}`
}

export function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return `${bytes.toFixed(1)} ${units[i]}`
}

export function formatDate(iso) {
  return formatBeijingDate(iso, { fallback: '' })
}

export function fileTypeLabel(type) {
  return { image: '图片', video: '视频', document: '文档' }[type] || type
}

export function fileTypeTag(type) {
  return { image: 'success', video: 'warning', document: 'info' }[type] || ''
}
