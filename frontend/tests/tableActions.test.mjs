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

test('every action column opts into the shared wrapping layout', t => {
  let columns = 0
  for (const file of files(src)) {
    const visit = node => {
      if (node.tag === 'el-table-column') {
        const attr = name => node.props.find(prop => prop.name === name)?.value?.content
        if (['操作', '处理', '匹配结果 / 处理'].includes(attr('label'))) {
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
