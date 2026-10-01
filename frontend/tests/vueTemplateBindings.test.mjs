import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

function* vueFiles(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) yield* vueFiles(path)
    else if (path.endsWith('.vue')) yield path
  }
}

test('script setup views expose every template binding', () => {
  const missing = []
  for (const filename of vueFiles(fileURLToPath(new URL('../src/views', import.meta.url)))) {
    const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename })
    if (!descriptor.scriptSetup || !descriptor.template) continue
    const script = compileScript(descriptor, { id: 'binding-audit' })
    const template = compileTemplate({
      source: descriptor.template.content, filename, id: 'binding-audit',
      compilerOptions: { bindingMetadata: script.bindings },
    })
    const unresolved = [...new Set([...template.code.matchAll(/_ctx\.([A-Za-z_$][\w$]*)/g)].map(match => match[1]))]
      .filter(name => !name.startsWith('$'))
    // Tiptap provides these props through nodeViewProps at runtime; the SFC compiler cannot expand that object.
    const tiptapProps = filename.endsWith('KnowledgeImageView.vue')
      ? new Set(['selected', 'node', 'editor', 'deleteNode', 'updateAttributes']) : new Set()
    const actual = unresolved.filter(name => !tiptapProps.has(name))
    if (actual.length || template.errors.length) {
      missing.push({ filename, names: actual, errors: template.errors.map(String) })
    }
  }
  assert.deepEqual(missing, [])
})
