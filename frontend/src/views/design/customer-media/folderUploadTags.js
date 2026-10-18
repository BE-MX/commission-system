// Use only the dropped root folder; descendants remain display paths.
export async function queueFolderFiles(rawItems, {
  getCustomerTags, getSelectedTags, selectFolderTag, confirmCreate, createTag, addFiles,
}) {
  const originalTags = getSelectedTags().map(tag => ({ ...tag }))
  const groups = new Map()
  const looseFiles = []
  for (const item of rawItems) {
    if (!item.pathSegments?.length) { looseFiles.push(item); continue }
    const name = item.pathSegments[0].replace(/\s/g, '')
    if (!name) throw new Error('文件夹名称去除空格后为空，请重命名后重新添加')
    if (!groups.has(name)) groups.set(name, [])
    groups.get(name).push(item)
  }
  for (const [name, files] of groups) {
    let tag = getCustomerTags().find(item => item.value.replace(/\s/g, '') === name)
    if (!tag) {
      if (!await confirmCreate(name)) continue
      tag = await createTag(name)
    }
    const tags = selectFolderTag(tag)
    addFiles(files, tags)
  }
  if (looseFiles.length) addFiles(looseFiles, originalTags)
}
