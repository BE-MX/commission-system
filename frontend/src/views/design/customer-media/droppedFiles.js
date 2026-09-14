// 拖拽上传的目录遍历工具：FileSystemEntry 递归读取，按顶层文件夹名分组。
// dataTransfer.items 必须在 drop 事件回调内同步取出，因此 collectDroppedFiles
// 先同步 webkitGetAsEntry()，再异步逐层 readEntries（需循环读到空，Chrome 单次最多 100 条）。

function readAllEntries(reader) {
  return new Promise((resolve, reject) => {
    const collected = []
    const readBatch = () => {
      reader.readEntries(batch => {
        if (!batch.length) return resolve(collected)
        collected.push(...batch)
        readBatch()
      }, reject)
    }
    readBatch()
  })
}

async function collectEntryFiles(entry, files, directoryName = '') {
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject))
    files.push({ file, directoryName })
  } else if (entry.isDirectory) {
    // 多级嵌套只取顶层文件夹名作目录名，下层文件打平归入
    const children = await readAllEntries(entry.createReader())
    for (const child of children) await collectEntryFiles(child, files, directoryName || entry.name)
  }
}

/** @returns {Promise<{files: Array<{file: File, directoryName: string}>, hasDirectory: boolean}>} */
export async function collectDroppedFiles(dataTransfer) {
  const items = dataTransfer?.items
  if (!items) return { files: [], hasDirectory: false }
  const entries = [...items].map(it => it.webkitGetAsEntry?.()).filter(Boolean)
  const files = []
  for (const entry of entries) await collectEntryFiles(entry, files)
  return { files, hasDirectory: entries.some(en => en.isDirectory) }
}

/** 同步预检：本次 drop 是否包含文件夹（决定是否拦截 el-upload 原生处理） */
export function dropHasDirectory(dataTransfer) {
  const items = dataTransfer?.items
  if (!items) return false
  return [...items].some(it => it.webkitGetAsEntry?.()?.isDirectory)
}
