// Returns true only when the browser confirms that text was copied.
// This module also ships unchanged to the standalone /m/ asset page.
export async function copyText(text) {
  if (typeof text !== 'string' || !text) return false
  if (globalThis.navigator?.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return true }
    catch { /* Try selection-based copy after a browser permission rejection. */ }
  }
  if (!globalThis.document?.body) return false
  const active = document.activeElement
  const selection = document.getSelection()
  const ranges = []
  for (let i = 0; i < (selection?.rangeCount || 0); i++) ranges.push(selection.getRangeAt(i).cloneRange())
  const inputSelection = active && typeof active.selectionStart === 'number'
    ? [active.selectionStart, active.selectionEnd, active.selectionDirection] : null
  const field = document.createElement('textarea')
  field.value = text
  field.setAttribute('readonly', '')
  field.setAttribute('tabindex', '-1')
  Object.assign(field.style, { position: 'fixed', top: '0', left: '0', opacity: '0', pointerEvents: 'none' })
  try {
    document.body.appendChild(field)
    field.focus({ preventScroll: true }); field.select(); field.setSelectionRange(0, text.length)
    return document.execCommand('copy') === true
  } catch { return false }
  finally {
    field.remove()
    active?.focus?.({ preventScroll: true })
    if (inputSelection) active.setSelectionRange(...inputSelection)
    else if (selection && ranges.length) {
      selection.removeAllRanges()
      for (const range of ranges) selection.addRange(range)
    }
  }
}
