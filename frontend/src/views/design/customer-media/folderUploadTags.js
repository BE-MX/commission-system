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
  const matched = new Map()
  for (const tag of getCustomerTags()) {
    const name = tag.value.replace(/\s/g, '')
    if (!matched.has(name)) matched.set(name, tag)
  }
  const missing = [...groups.keys()].filter(name => !matched.has(name))
  const choices = missing.length ? await confirmCreate(missing) : null
  for (const [name, files] of groups) {
    let tag = matched.get(name)
    if (!tag) {
      const dimension = choices?.get(name)
      if (!dimension) continue
      try {
        tag = await createTag(name, dimension)
      } catch (error) {
        throw new Error(`创建标签「${name}」失败，请重新添加文件夹：${error.message || '请求失败'}`, { cause: error })
      }
    }
    const tags = selectFolderTag(tag)
    addFiles(files, tags)
  }
  if (looseFiles.length) addFiles(looseFiles, originalTags)
}
