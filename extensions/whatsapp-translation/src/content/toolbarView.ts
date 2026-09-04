import { messageForCode } from '@/content/messages'
import type { OutgoingPreview } from '@/content/outgoingComposer'
import { TARGET_LANGUAGES, languageLabel } from '@/shared/contracts'

/**
 * Composer toolbar + preview card, rendered into a closed shadow root that the
 * adapter mounts as its own row above WhatsApp's compose line.
 *
 * Motion budget (emil-design-eng): preview card 160ms ease-out on
 * opacity/transform only; button press scale(0.97); keyboard-triggered
 * replacement renders with no animation; reduced-motion drops the translate.
 */

export type ToolbarStatus =
  | { kind: 'idle' }
  | { kind: 'busy' }
  | { kind: 'error'; code: string }
  | { kind: 'replaced' }

export type ToolbarModel = {
  canRestore: boolean
  preview?: OutgoingPreview
  status: ToolbarStatus
  targetLanguage: string
}

export type ToolbarHandlers = {
  onCancelPreview: () => void
  onLanguageChange: (language: string) => void
  onReplace: () => void
  onRestore: () => void
  onRetry: () => void
  onTranslate: () => void
}

const STYLES = `
  :host { all: initial; display: block; }
  * { box-sizing: border-box; }
  .ark {
    --bg: #ffffff;
    --surface: #f0f2f5;
    --fg: #111b21;
    --muted: #667781;
    --accent: #008069;
    --accent-fg: #ffffff;
    --danger: #b3261e;
    --border: rgba(17, 27, 33, 0.08);
    --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
    color: var(--fg);
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 13px;
    line-height: 1.4;
    padding: 6px 16px 0;
  }
  :host([data-ark-theme="dark"]) .ark {
    --bg: #202c33;
    --surface: #2a3942;
    --fg: #e9edef;
    --muted: #8696a0;
    --accent: #00a884;
    --accent-fg: #111b21;
    --danger: #f28b82;
    --border: rgba(233, 237, 239, 0.1);
  }
  .bar { align-items: center; display: flex; gap: 8px; min-height: 30px; }
  .chip, .btn, .link {
    align-items: center;
    border: 1px solid var(--border);
    border-radius: 15px;
    cursor: pointer;
    display: inline-flex;
    font: inherit;
    gap: 4px;
    height: 28px;
    padding: 0 10px;
    transition: transform 120ms var(--ease-out), background-color 120ms ease;
    user-select: none;
  }
  .chip { background: var(--surface); color: var(--fg); position: relative; }
  .chip select {
    appearance: none;
    background: transparent;
    border: none;
    color: inherit;
    cursor: pointer;
    font: inherit;
    padding-right: 12px;
  }
  .chip::after { color: var(--muted); content: "▾"; font-size: 11px; margin-left: -12px; pointer-events: none; }
  .btn { background: var(--accent); border-color: transparent; color: var(--accent-fg); font-weight: 600; }
  .btn[disabled] { cursor: progress; opacity: 0.7; }
  .link { background: transparent; border-color: transparent; color: var(--accent); padding: 0 4px; }
  .link.danger { color: var(--danger); }
  @media (hover: hover) and (pointer: fine) {
    .chip:hover { background: var(--border); }
    .btn:hover:not([disabled]) { filter: brightness(1.05); }
    .link:hover { text-decoration: underline; }
  }
  .chip:active, .btn:active:not([disabled]), .link:active { transform: scale(0.97); }
  .status { color: var(--muted); font-size: 12.5px; margin-left: auto; }
  .status.error { color: var(--danger); }
  .card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 2px 8px rgba(11, 20, 26, 0.12);
    margin: 0 0 6px;
    padding: 8px 12px;
  }
  .card[data-animate="1"] {
    animation: ark-in 160ms var(--ease-out);
  }
  @keyframes ark-in { from { opacity: 0; transform: translateY(4px); } }
  @media (prefers-reduced-motion: reduce) {
    @keyframes ark-in { from { opacity: 0; } }
    .chip, .btn, .link { transition: none; }
  }
  .row { display: grid; gap: 2px 10px; grid-template-columns: 2.5em 1fr; margin: 2px 0; }
  .label { color: var(--muted); font-size: 11.5px; padding-top: 1px; user-select: none; }
  .text { white-space: pre-wrap; word-break: break-word; }
  .text.primary { font-size: 14px; }
  .text.back { color: var(--muted); }
  .actions { align-items: center; display: flex; gap: 8px; margin-top: 6px; }
  .hint { color: var(--muted); font-size: 11.5px; margin-left: auto; }
`

export type ToolbarView = {
  render: (model: ToolbarModel, options?: { animatePreview?: boolean }) => void
}

export function createToolbarView(shadow: ShadowRoot, handlers: ToolbarHandlers): ToolbarView {
  const doc = shadow.ownerDocument ?? document
  const style = doc.createElement('style')
  style.textContent = STYLES
  const root = doc.createElement('div')
  root.className = 'ark'
  shadow.replaceChildren(style, root)

  function el<TKey extends keyof HTMLElementTagNameMap>(tag: TKey, className?: string, text?: string) {
    const node = doc.createElement(tag)
    if (className) node.className = className
    if (text !== undefined) node.textContent = text
    return node
  }

  function renderPreview(preview: OutgoingPreview, animate: boolean): HTMLElement {
    const card = el('div', 'card')
    if (animate) card.dataset.animate = '1'

    const original = el('div', 'row')
    original.append(el('span', 'label', '原文'), el('div', 'text', preview.original))
    const translated = el('div', 'row')
    translated.append(el('span', 'label', '译文'), el('div', 'text primary', preview.translated))
    card.append(original, translated)
    if (preview.backTranslation) {
      const back = el('div', 'row')
      back.append(el('span', 'label', '回译'), el('div', 'text back', preview.backTranslation))
      card.append(back)
    }

    const actions = el('div', 'actions')
    const replace = el('button', 'btn', '替换到输入框')
    replace.type = 'button'
    replace.addEventListener('click', handlers.onReplace)
    const cancel = el('button', 'link', '取消')
    cancel.type = 'button'
    cancel.addEventListener('click', handlers.onCancelPreview)
    actions.append(replace, cancel, el('span', 'hint', 'Alt + T 也可替换'))
    card.append(actions)
    return card
  }

  function renderBar(model: ToolbarModel): HTMLElement {
    const bar = el('div', 'bar')

    const chip = el('label', 'chip')
    chip.title = '当前聊天的发送语言'
    const select = el('select')
    select.setAttribute('aria-label', '发送语言')
    for (const code of TARGET_LANGUAGES) {
      const option = el('option', undefined, `→ ${languageLabel(code)}`)
      option.value = code
      select.append(option)
    }
    select.value = model.targetLanguage
    select.addEventListener('change', () => handlers.onLanguageChange(select.value))
    chip.append(select)

    const translate = el('button', 'btn', model.status.kind === 'busy' ? '翻译中…' : '翻译')
    translate.type = 'button'
    translate.title = '翻译输入框内容并预览（Alt + T）'
    translate.disabled = model.status.kind === 'busy'
    translate.addEventListener('click', handlers.onTranslate)

    bar.append(chip, translate)

    if (model.status.kind === 'error') {
      const message = messageForCode(model.status.code)
      const status = el('span', 'status error', message.text)
      if (message.retryable) {
        const retry = el('button', 'link', '重试')
        retry.type = 'button'
        retry.addEventListener('click', handlers.onRetry)
        status.append(retry)
      }
      bar.append(status)
    } else if (model.status.kind === 'replaced' && model.canRestore) {
      const status = el('span', 'status', '已替换为译文')
      const restore = el('button', 'link', '恢复中文')
      restore.type = 'button'
      restore.addEventListener('click', handlers.onRestore)
      status.append(restore)
      bar.append(status)
    }
    return bar
  }

  return {
    render(model, options = {}) {
      root.replaceChildren()
      if (model.preview) root.append(renderPreview(model.preview, options.animatePreview ?? false))
      root.append(renderBar(model))
    },
  }
}
