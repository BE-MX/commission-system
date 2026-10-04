import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, relative } from 'node:path'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { parse as parseTemplate } from '@vue/compiler-dom'

const root = fileURLToPath(new URL('../src/', import.meta.url))
function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory()
    ? files(join(dir, entry.name)) : entry.name.endsWith('.vue') ? [join(dir, entry.name)] : [])
}
function attr(node, name) {
  const prop = node.props?.find(prop => prop.name === name || (prop.name === 'bind' && prop.arg?.content === name))
  return prop?.value?.content ?? prop?.exp?.content ?? (prop ? '' : undefined)
}
const tables = []
for (const file of files(root)) {
  const source = readFileSync(file, 'utf8')
  const template = parseSfc(source).descriptor.template
  if (!template) continue
  function visit(node, table) {
    if (node.tag === 'el-table') {
      table = { file: relative(root, file).replaceAll('\\', '/'), line: source.slice(0, template.loc.start.offset + node.loc.start.offset).split('\n').length,
        data: attr(node, 'data'), columns: [] }
      tables.push(table)
    }
    if (node.tag === 'el-table-column' && table) {
      const hasColumn = child => child.tag === 'el-table-column' || child.children?.some(hasColumn)
      if (!node.children?.some(hasColumn)) {
        const type = attr(node, 'type')
        const label = attr(node, 'label')
        const action = /table-action-column/.test(attr(node, 'class-name') || '') || /^(操作|处理|选择|#|序号)$/.test(label || '')
        const field = attr(node, 'prop') ?? attr(node, 'property') ?? attr(node, 'sort-by') ?? attr(node, 'sort-method')
        const sort = attr(node, 'sortable')
        const inferred = [...node.loc.source.matchAll(/(?:\brow|\b(?:scope|s)\.row)\.([\w.]+)/g)].map(match => match[1])
        table.columns.push({ label, field, sort, type, action, inferred: [...new Set(inferred)],
          offset: template.loc.start.offset + node.loc.start.offset })
      }
    }
    for (const child of node.children || []) visit(child, table)
  }
  try { visit(parseTemplate(template.content), null) }
  catch (error) { throw new Error(`${relative(root, file)}: ${error.message}`, { cause: error }) }
}
if (process.argv.includes('--json')) console.log(JSON.stringify(tables, null, 2))
else {
  const missing = tables.flatMap(table => table.columns.filter(column => !column.action && (!column.type || column.type === 'default')
    && column.field == null && column.sort == null).map(column => ({ file: table.file, table: table.data, ...column })))
  console.log(`Tables: ${tables.length}; data columns without a sorting field: ${missing.length}`)
  for (const column of missing) console.log(`${column.file} [${column.table}] ${column.label}: ${column.inferred.join(', ') || 'needs explicit display value'}`)
  if (missing.length) process.exitCode = 1
}
