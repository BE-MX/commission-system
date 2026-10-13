// Upload IDs only correlate placeholders within this page; they are never saved.
let uploadSequence = 0

export function createImageUploadId() {
  return `image-upload-${++uploadSequence}`
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
