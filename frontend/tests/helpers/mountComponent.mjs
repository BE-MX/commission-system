import { readFileSync } from 'node:fs'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as Vue from 'vue'

export const slotShell = { inheritAttrs: false, setup: (_, { slots, attrs }) => () => Vue.h('section', attrs, slots.default?.()) }
export function loadComponent(path, modules = {}) {
  const { descriptor } = parse(readFileSync(new URL(path, import.meta.url), 'utf8'))
  const code = compileScript(descriptor, { id: path, inlineTemplate: true }).content
    .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => {
      const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
      return `const ${declaration} = modules[${JSON.stringify(key)}];`
    }).replace('export default', 'return')
  return new Function('modules', code)({ vue: Vue, ...modules })
}
export function mountComponent(t, component, props = {}, slots, registrations = {}) {
  const renderer = Vue.createRenderer({
    createElement: type => ({ type, children: [], props: {}, style: {}, clientWidth: 720 }),
    createText: text => ({ text }), createComment: () => ({}),
    insert(child, parent, anchor) {
      if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child); child.parent = parent
    },
    remove(node) { node.parent.children.splice(node.parent.children.indexOf(node), 1) },
    patchProp(node, key, _, value) { node.props[key] = value },
    setText(node, text) { node.text = text }, setElementText(node, text) { node.text = text; node.children = [] },
    parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
  })
  const root = { children: [] }, app = renderer.createApp({ setup: () => () => Vue.h(component, props, slots) })
  app.config.warnHandler = message => { throw new Error(message) }
  for (const [name, entry] of Object.entries(registrations)) app.component(name, entry)
  app.mount(root); t.after(() => app.unmount())
  const text = node => [node.text || '', ...(node.children || []).map(text)].join('')
  return { app, text: () => text(root), find(predicate) {
    const scan = node => [...(predicate(node) ? [node] : []), ...(node.children || []).flatMap(scan)]
    return scan(root)
  } }
}
