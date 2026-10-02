import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import * as Icons from '@element-plus/icons-vue'
import * as status from '../src/utils/status.js'
import * as responsive from '../src/utils/responsiveDescriptions.js'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'

test('domain status dictionaries retain labels, legacy tones and readable unknown codes', async t => {
  const dictionary = status.statusDictionary([['done', '已完成', 'success'], ['waiting', '待确认', 'warning']])
  assert.deepEqual(status.resolveStatus('future', dictionary), { label: '未知状态（future）', type: 'info' })
  assert.deepEqual(status.resolveStatus(null, dictionary), { label: '未提供', type: 'info' })
  assert.deepEqual(status.resolveStatus('toString', dictionary), { label: '未知状态（toString）', type: 'info' })
  assert.equal(status.resolveStatus('done', { done: { label: '已完成', tone: 'success' } }).type, 'success')
  let closes = 0
  const props = Vue.reactive({ value: 'done', dictionary, closable: true, onClose: () => closes++ })
  const ui = mountComponent(t, loadComponent('../../src/components/StatusBadge.vue', { '../utils/status': status }), props, undefined, { 'el-tag': slotShell })
  assert.equal(ui.text(), '已完成')
  assert.equal(ui.find(n => n.props?.type === 'success').length, 1)
  ui.find(n => n.props?.onClose)[0].props.onClose(); assert.equal(closes, 1)
  props.value = 'future'; await Vue.nextTick()
  assert.equal(ui.text(), '未知状态（future）')
  assert.equal(ui.find(n => n.props?.type === 'info').length, 1)
  props.value = 'done'; props.label = '服务端确认完成'; await Vue.nextTick()
  assert.equal(ui.text(), '服务端确认完成')
  assert.equal(ui.find(n => n.props?.type === 'success').length, 1)
})

test('descriptions adapt to their container and release resize subscriptions on unmount', async t => {
  assert.deepEqual([239, 479, 480, 719, 720, 1000].map(w => responsive.descriptionColumns(w, 3)), [1, 1, 2, 2, 3, 3])
  let resize, disconnected = false
  const previous = globalThis.ResizeObserver
  globalThis.ResizeObserver = class { constructor(fn) { resize = fn } observe() {} disconnect() { disconnected = true } }
  t.after(() => { globalThis.ResizeObserver = previous })
  const ui = mountComponent(t, loadComponent('../../src/components/ResponsiveDescriptions.vue', { '../utils/responsiveDescriptions': responsive }),
    { column: 3, title: '订单详情' }, { default: () => Vue.h('span', '很长的客户名称和链接仍可阅读') }, { 'el-descriptions': slotShell })
  await Vue.nextTick()
  assert.equal(ui.find(n => n.props?.title === '订单详情')[0].props.column, 3)
  resize([{ contentRect: { width: 318 } }]); await Vue.nextTick()
  assert.equal(ui.find(n => n.props?.title === '订单详情')[0].props.column, 1)
  assert.match(ui.text(), /很长的客户名称/)
  ui.app.unmount(); assert.equal(disconnected, true)
})

function contrast(a, b) {
  const luminance = color => color.slice(1).match(/../g).map(v => parseInt(v, 16) / 255)
    .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0)
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (values[0] + .05) / (values[1] + .05)
}
test('normal text and semantic badges meet 4.5 contrast on workspace surfaces', () => {
  const text = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8')
  const color = name => new RegExp(`${name}:\\s*(#[a-f0-9]{6})`, 'i').exec(text)?.[1]
  for (const foreground of ['--text-primary', '--text-secondary', '--text-muted', '--text-placeholder', '--text-tertiary', '--color-primary-text', '--color-success-text', '--color-warning-text', '--color-danger-text', '--color-info-text']) {
    for (const surface of ['#ffffff', color('--page-bg')]) assert.ok(contrast(color(foreground), surface) >= 4.5, `${foreground} on ${surface}`)
  }
  for (const name of ['--color-success', '--button-danger', '--button-danger-hover', '--button-danger-active', '--button-success', '--button-success-hover', '--button-success-active', '--button-warning', '--button-warning-hover', '--button-warning-active']) assert.ok(contrast(color(name), '#ffffff') >= 4.5, name)
  assert.ok(contrast(color('--ink-dark'), color('--color-primary')) >= 4.5)
  for (const name of ['--button-primary', '--button-primary-hover', '--button-primary-active']) assert.ok(contrast(color('--button-primary-ink'), color(name)) >= 4.5, name)
  for (const tone of ['primary', 'success', 'danger', 'warning']) {
    for (const state of ['', '-hover', '-active']) {
      for (const surface of ['#ffffff', color('--page-bg'), color(`--button-${tone}-soft`), '#faf8f5']) {
        assert.ok(contrast(color(`--button-${tone}-text${state}`), surface) >= 4.5, `${tone}${state} on ${surface}`)
      }
    }
  }
  const app = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')
  assert.match(app, /body\s*\{[^}]*--el-color-primary:\s*var\(--color-primary-text\)/)
})

test('main and PM retain identical button token contracts', () => {
  const tokens = url => Object.fromEntries([...readFileSync(new URL(url, import.meta.url), 'utf8')
    .matchAll(/(--button-[\w-]+):\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]))
  assert.deepEqual(tokens('../../frontend-pm/src/styles/tokens.css'), tokens('../src/styles/tokens.css'))
})

test('GlassButton links retain icons and block disabled/loading submissions', async t => {
  let clicks = 0
  const props = Vue.reactive({ variant: 'link', linkTone: 'warning', leftIcon: 'Promotion', onClick: () => clicks++ })
  const ui = mountComponent(t, loadComponent('../../src/components/GlassButton.vue', { '@element-plus/icons-vue': Icons }), props,
    { default: () => '发送确认' }, { 'el-icon': slotShell, Promotion: Icons.Promotion })
  const button = () => ui.find(n => n.type === 'button')[0]
  assert.match(button().props.class, /gb-link-tone--warning/)
  assert.doesNotMatch(button().props.class, /gb-shadow/)
  button().props.onClick({}); assert.equal(clicks, 1)
  props.loading = true; await Vue.nextTick()
  assert.equal(button().props.disabled, true)
  assert.equal(button().props['aria-busy'], true)
  assert.equal(ui.text(), '发送确认')
  button().props.onClick({}); assert.equal(clicks, 1)
  props.loading = false; props.disabled = true; await Vue.nextTick()
  button().props.onClick({}); assert.equal(clicks, 1)
})
