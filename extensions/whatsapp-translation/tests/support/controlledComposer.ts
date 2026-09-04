export type ControlledComposerMode = 'accept' | 'reject' | 'rewrite'

export type ControlledComposerHarness = {
  commandCount: () => number
  flushFrame: () => void
}

function selectionCoversComposer(document: Document, composer: HTMLElement): boolean {
  const selection = document.defaultView?.getSelection()
  if (!selection || selection.rangeCount !== 1 || document.activeElement !== composer) return false
  const range = selection.getRangeAt(0)
  return range.startContainer === composer
    && range.startOffset === 0
    && range.endContainer === composer
    && range.endOffset === composer.childNodes.length
}

export function installControlledComposer(
  document: Document,
  composer: HTMLElement,
  options: { manualFrames?: boolean; mode?: ControlledComposerMode } = {},
): ControlledComposerHarness {
  const view = document.defaultView!
  const frames: FrameRequestCallback[] = []
  let commandCalls = 0
  let selectionChangeSeen = false
  let selectionReady = false

  document.addEventListener('selectionchange', () => {
    selectionChangeSeen = true
    selectionReady = false
  })
  Object.defineProperty(view, 'requestAnimationFrame', {
    configurable: true,
    value: (callback: FrameRequestCallback) => {
      const frame = () => {
        selectionReady = selectionChangeSeen && selectionCoversComposer(document, composer)
        callback(0)
      }
      if (options.manualFrames) frames.push(frame)
      else view.setTimeout(frame, 0)
      return frames.length
    },
  })
  composer.onbeforeinput = (event) => {
    commandCalls += 1
    event.preventDefault()
    const input = event as InputEvent
    if (
      !selectionReady
      || !selectionCoversComposer(document, composer)
      || input.inputType !== 'insertText'
      || options.mode === 'reject'
    ) return
    const value = options.mode === 'rewrite' ? 'Editor-owned value' : input.data ?? ''
    selectionChangeSeen = false
    void Promise.resolve().then(() => {
      composer.replaceChildren(document.createTextNode(value))
    })
  }

  return {
    commandCount: () => commandCalls,
    flushFrame: () => frames.shift()?.(0),
  }
}
