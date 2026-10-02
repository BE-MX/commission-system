import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from '@vue/compiler-dom'

const src = fileURLToPath(new URL('../src/', import.meta.url))
const files = directory => fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
  const name = path.join(directory, entry.name)
  return entry.isDirectory() ? files(name) : name.endsWith('.vue') ? [name] : []
})

test('action buttons use links, explicit icons and component semantic colors', t => {
  let buttons = 0
  const errors = []
  const hasIcon = node => node.props?.some(p => ['icon', 'left-icon', 'leftIcon'].includes(p.name) ||
    (p.name === 'bind' && ['icon', 'left-icon', 'leftIcon'].includes(p.arg?.content))) ||
    node.children?.some(n => n.tag === 'el-icon' || n.tag === 'svg' || hasIcon(n))
  for (const file of files(src)) {
    const visit = (node, inActions = false) => {
      if (node.tag === 'el-table-column') inActions = node.props.some(p => p.name === 'class-name' && p.value?.content.includes('table-action-column'))
      if (inActions && ['GlassButton', 'el-button'].includes(node.tag)) {
        buttons++
        const attr = name => node.props.find(p => p.name === name)?.value?.content
        const where = `${path.relative(src, file)}:${node.loc.start.line}`
        if (!(node.tag === 'GlassButton' ? attr('variant') === 'link' : node.props.some(p => p.name === 'link'))) errors.push(`${where}: must be link`)
        if (!hasIcon(node)) errors.push(`${where}: needs an icon`)
        if (/color\s*:/.test(attr('style') || '')) errors.push(`${where}: inline color bypasses semantic states`)
        if (attr('size')) errors.push(`${where}: link geometry is shared`)
        if (attr('link-tone') && !['primary', 'success', 'danger', 'warning'].includes(attr('link-tone'))) errors.push(`${where}: unsupported tone`)
      }
      for (const child of node.children || []) visit(child, inActions)
    }
    visit(parse(fs.readFileSync(file, 'utf8')))
  }
  // The dropdown trigger is rendered by a reusable component outside the table AST.
  const menu = fs.readFileSync(path.join(src, 'views/commission/components/CommissionExportMenu.vue'), 'utf8')
  assert.match(menu, /variant="link"/)
  assert.match(menu, /left-icon=/)
  assert.equal(errors.length, 0, errors.join('\n'))
  assert.ok(buttons >= 272, 'retain full operation button coverage')
  t.diagnostic(`Audited ${buttons} direct buttons and CommissionExportMenu`)
})

test('every action column opts into the shared wrapping layout', t => {
  let columns = 0
  for (const file of files(src)) {
    const visit = node => {
      if (node.tag === 'el-table-column') {
        const attr = name => node.props.find(prop => prop.name === name)?.value?.content
        // A data field named "操作" describes a change; it has no action buttons to wrap.
        const descriptiveAction = attr('prop') === 'action' && node.children.length === 0
        if (['操作', '处理', '匹配结果 / 处理'].includes(attr('label')) && !descriptiveAction) {
          columns++
          assert.ok(attr('class-name')?.split(/\s+/).includes('table-action-column'),
            `${path.relative(src, file)}:${node.loc.start.line} action column would inherit ellipsis`)
          assert.ok(!node.props.some(prop => prop.name === 'show-overflow-tooltip'),
            `${file}: action buttons must not be tooltip-only content`)
        }
      }
      for (const child of node.children || []) visit(child)
    }
    visit(parse(fs.readFileSync(file, 'utf8')))
  }
  assert.ok(columns > 0)
  t.diagnostic(`Audited ${columns} action columns`)
})
