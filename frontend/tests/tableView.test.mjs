import assert from 'node:assert/strict'
import test from 'node:test'
import { createRenderer, markRaw } from 'vue'
import { useTableView } from '../src/composables/useTableView.js'

function mountTable(pageKey) {
  let view
  const renderer = createRenderer({
    createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    setText() {}, setElementText() {}, patchProp() {}, insert() {}, remove() {},
    parentNode: () => null, nextSibling: () => null,
  })
  const app = renderer.createApp({
    setup() {
      view = useTableView(pageKey, [{ key: 'name', label: '名称' }])
      return () => null
    },
  })
  app.mount({})
  const classes = new Set()
  const ancestorClasses = new Set()
  view.panelRef.value = markRaw({
    classList: { add: name => classes.add(name), remove: name => classes.delete(name) },
    parentElement: markRaw({
      classList: { add: name => ancestorClasses.add(name), remove: name => ancestorClasses.delete(name) },
      parentElement: globalThis.document.body,
    }),
  })
  return { app, view, classes, ancestorClasses }
}

test('table viewport mode keeps dialogs available and restores page scroll', () => {
  const originalDocument = globalThis.document
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const listeners = new Map()
  let dialogOpen = false
  globalThis.document = {
    body: { style: { overflow: 'auto' } },
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: name => listeners.delete(name),
    querySelector: () => dialogOpen ? {} : null,
  }
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true, value: { getItem: () => null, setItem() {} },
  })
  let table
  try {
    table = mountTable('table-view-test')
    table.view.toggleFullscreen()
    assert.equal(table.view.isFullscreen.value, true)
    assert.equal(table.classes.has('table-card--fullscreen'), true)
    assert.equal(table.ancestorClasses.has('table-fullscreen-ancestor'), true)
    assert.equal(document.body.style.overflow, 'hidden')

    dialogOpen = true
    listeners.get('keydown')({ key: 'Escape' })
    assert.equal(table.view.isFullscreen.value, true, 'dialog handles Escape first')
    dialogOpen = false
    listeners.get('keydown')({ key: 'Escape' })
    assert.equal(table.view.isFullscreen.value, false)
    assert.equal(table.classes.size, 0)
    assert.equal(table.ancestorClasses.size, 0)
    assert.equal(document.body.style.overflow, 'auto')

    table.view.toggleFullscreen()
    table.app.unmount()
    table = null
    assert.equal(document.body.style.overflow, 'auto')
    assert.equal(listeners.size, 0)
  } finally {
    table?.app.unmount()
    globalThis.document = originalDocument
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage)
    else delete globalThis.localStorage
  }
})
