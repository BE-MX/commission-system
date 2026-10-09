import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'

export async function captureKeyboardEvidence(page, path) {
 // An authentication control can fail after a real OTP was entered. Every
 // new screenshot masks editable fields, even on failure, without removing
 // focus/geometry diagnostics or hiding the control that failed.
 return page.screenshot({ path, mask: [page.locator('input, textarea, [contenteditable]')] })
}

// Test interaction only. No DOM focus(), locator.focus(), click(), fill() or
// check() is used in keyboard mode. Actual Tab order must reach each control.
export function createBrowserInteraction(mode, output) {
 assert.ok(['pointer', 'keyboard'].includes(mode))
 const steps = []
 async function tick(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
 }
 async function record(value) {
  steps.push(value)
  await writeFile(output + '/keyboard-progress.json', JSON.stringify({ mode, steps }, null, 2))
 }
 async function reach(locator, step) {
  await locator.waitFor({ state: 'visible' })
  assert.equal(await locator.isDisabled(), false, 'Keyboard target must be enabled: ' + step)
  const page = locator.page()
  // The focus may already be on the target because of the application's own
  // autofocus. That is valid; otherwise only real Tab presses move it.
  let tabs = 0
  while (!(await locator.evaluate(element => element === document.activeElement || element.contains(document.activeElement)))) {
   if (tabs === 180) await record({ step, kind: 'unreachable', width: page.viewportSize().width, tabs })
   assert.ok(tabs < 180, 'Target is unreachable in actual Tab order: ' + step)
   await page.keyboard.press('Tab'); tabs++; await tick(page)
  }
  const focus = await locator.evaluate(element => {
   const active = document.activeElement, bounds = active.getBoundingClientRect(), style = getComputedStyle(active)
   return { tag: active.tagName.toLowerCase(), type: active.getAttribute('type') || '', role: active.getAttribute('role') || '',
    focusedWithin: element === active || element.contains(active), keyboardVisible: active.matches(':focus-visible'),
    inViewport: bounds.left >= -1 && bounds.right <= innerWidth + 1 && bounds.top >= -1 && bounds.bottom <= innerHeight + 1,
    bounds: { left: Math.round(bounds.left), right: Math.round(bounds.right), top: Math.round(bounds.top), bottom: Math.round(bounds.bottom) },
    outline: { width: parseFloat(style.outlineWidth) || 0, style: style.outlineStyle, color: style.outlineColor } }
  })
  if (!(focus.focusedWithin && focus.keyboardVisible && focus.inViewport)) {
   await record({ step, kind: 'focus-failed', width: page.viewportSize().width, tabs, ...focus })
   await captureKeyboardEvidence(page, output + '/keyboard-failed-' + step + '.png')
  }
  assert.ok(focus.focusedWithin && focus.keyboardVisible && focus.inViewport, 'Keyboard focus must be visible and within viewport: ' + step)
  await record({ step, kind: 'reach', width: page.viewportSize().width, tabs, ...focus })
  if (step === 'trade-step-447') assert.ok(focus.outline.width >= 2 && focus.outline.style === 'solid', 'Drawer close control needs a visible keyboard focus indicator')
  if (['trade-step-234', 'trade-step-286', 'trade-step-320', 'trade-step-447'].includes(step)) {
   await captureKeyboardEvidence(page, output + '/keyboard-focus-' + step + '.png')
  }
  return page
 }
 async function click(locator, step) {
  if (mode === 'pointer') return locator.click()
  if (await locator.locator('input[type="radio"]').count()) {
   const page = await reach(locator.locator('..'), step + '-group')
   let arrows = 0
   while (!(await locator.evaluate(element => element.contains(document.activeElement)))) {
    assert.ok(arrows < 12, 'Radio choice is unreachable using ArrowRight: ' + step)
    await page.keyboard.press('ArrowRight'); arrows++; await tick(page)
   }
   await reach(locator, step)
   if (!(await locator.locator('input[type="radio"]').isChecked())) await page.keyboard.press('Space')
   await tick(page)
   assert.equal(await locator.locator('input[type="radio"]').isChecked(), true, 'Actual radio choice was not selected: ' + step)
   await record({ step, kind: 'activate', key: 'radio-arrows', width: page.viewportSize().width, arrows })
   return
  }
  const isOption = await locator.getAttribute('role') === 'option'
  if (isOption) {
   await locator.waitFor({ state: 'visible' })
   const page = locator.page()
   let arrows = 0
   while (!(await locator.evaluate(option => {
    const active = document.activeElement
    const combo = active?.closest('[role="combobox"]') || active
    return Boolean(option.id && combo?.getAttribute('aria-activedescendant') === option.id)
   }))) {
    assert.ok(arrows < 50, 'Option is unreachable using combobox ArrowDown: ' + step)
    await page.keyboard.press('ArrowDown'); arrows++; await tick(page)
   }
   await record({ step, kind: 'option', width: page.viewportSize().width, arrows })
   await page.keyboard.press('Enter'); await tick(page)
   return
  }
  const page = await reach(locator, step)
  const kind = await locator.evaluate(() => {
   const active = document.activeElement
   return active?.type === 'checkbox' || active?.type === 'radio' ? 'Space' :
    (active?.closest('[role="combobox"]') || active)?.getAttribute('role') === 'combobox' ? 'ArrowDown' : 'Enter'
  })
  await record({ step, kind: 'activate', key: kind, width: page.viewportSize().width })
  await page.keyboard.press(kind); await tick(page)
 }
 async function fill(locator, value, step) {
  if (mode === 'pointer') return locator.fill(value)
  const page = await reach(locator, step)
  await page.keyboard.press('Control+A')
  // Passwords, OTPs and customer values are never recorded in progress JSON.
  await page.keyboard.type(value)
  await tick(page)
  assert.equal(await locator.inputValue(), value, 'Keyboard input did not reach the actual field: ' + step)
  await record({ step, kind: 'input', width: page.viewportSize().width })
 }
 async function check(locator, step) {
  if (mode === 'pointer') return locator.check()
  const page = await reach(locator, step)
  if (!(await locator.isChecked())) await page.keyboard.press('Space')
  await tick(page)
  assert.equal(await locator.isChecked(), true, 'Keyboard confirmation must be explicitly checked: ' + step)
  await record({ step, kind: 'check', width: page.viewportSize().width })
 }
 return { click, fill, check, summary: () => ({ mode, steps: steps.length,
  reached: steps.filter(step => step.kind === 'reach').length,
  activated: steps.filter(step => step.kind === 'activate').length,
  inputs: steps.filter(step => step.kind === 'input').length,
  checked: steps.filter(step => step.kind === 'check').length,
  options: steps.filter(step => step.kind === 'option').length,
  widths: [...new Set(steps.map(step => step.width))].sort((a, b) => a - b),
  driverProgrammaticFocus: false, driverPointerFallback: mode !== 'keyboard',
  strategyEvidence: 'Reviewed source branch; these booleans are not event-monitor counters' }) }
}
