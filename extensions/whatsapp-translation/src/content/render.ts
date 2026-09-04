import type { IncomingRenderState } from '@/content/incomingTranslator'
import { messageForCode } from '@/content/messages'
import { ARK_MARKS } from '@/shared/marks'
import { languageLabel } from '@/shared/contracts'

/**
 * Inline translation under an incoming bubble. Seen dozens of times a day, so it
 * never animates. Colors follow WhatsApp's light/dark theme via data-ark-theme.
 */
const TRANSLATION_STYLES = `
  :host { all: initial; display: block; }
  .ark-translation {
    --bg: rgba(0, 0, 0, 0.04);
    --fg: #111b21;
    --muted: #667781;
    --accent: #008069;
    --danger: #b3261e;
    background: var(--bg);
    border-left: 2px solid var(--accent);
    border-radius: 0 6px 6px 0;
    color: var(--fg);
    display: block;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 13.5px;
    line-height: 1.45;
    margin: 6px 0 2px;
    padding: 5px 8px 5px 9px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  :host([data-ark-theme="dark"]) .ark-translation {
    --bg: rgba(255, 255, 255, 0.06);
    --fg: #e9edef;
    --muted: #8696a0;
    --accent: #00a884;
    --danger: #f28b82;
  }
  .ark-translation__meta {
    color: var(--muted);
    display: inline-block;
    font-size: 11px;
    margin-right: 6px;
    user-select: none;
  }
  .ark-translation--pending, .ark-translation--loading, .ark-translation--error, .ark-translation--blocked { color: var(--muted); }
  .ark-translation--error { border-left-color: var(--danger); }
  .ark-translation__retry {
    background: transparent;
    border: none;
    color: var(--accent);
    cursor: pointer;
    font: inherit;
    font-size: 12.5px;
    margin-left: 6px;
    padding: 0;
    text-decoration: underline;
  }
`

const shadowRoots = new WeakMap<HTMLElement, ShadowRoot>()

export type RenderOptions = { dark?: boolean }

export function mountTranslation(
  target: Element,
  state: IncomingRenderState,
  onRetry?: () => void,
  options: RenderOptions = {},
): ShadowRoot {
  let host = target.querySelector<HTMLElement>(`:scope > [${ARK_MARKS.translationHost}="1"]`)
  if (!host) {
    host = target.ownerDocument.createElement('div')
    host.setAttribute(ARK_MARKS.translationHost, '1')
    target.append(host)
  }
  host.setAttribute(ARK_MARKS.translationState, state.kind === 'retryable_error' ? 'error' : state.kind)
  if (options.dark !== undefined) host.setAttribute('data-ark-theme', options.dark ? 'dark' : 'light')

  const existingShadow = shadowRoots.get(host)
  const shadow = existingShadow ?? host.attachShadow({ mode: 'closed' })
  shadowRoots.set(host, shadow)
  shadow.replaceChildren()

  const style = target.ownerDocument.createElement('style')
  style.textContent = TRANSLATION_STYLES
  shadow.append(style)

  const body = target.ownerDocument.createElement('div')
  body.className = 'ark-translation'

  if (state.kind === 'pending') {
    body.classList.add('ark-translation--pending')
    const button = target.ownerDocument.createElement('button')
    button.className = 'ark-translation__retry'
    button.type = 'button'
    button.textContent = '译此消息'
    if (onRetry) button.addEventListener('click', onRetry)
    body.append(button)
  } else if (state.kind === 'loading') {
    body.classList.add('ark-translation--loading')
    body.textContent = '翻译中…'
  } else if (state.kind === 'success') {
    if (state.sourceLanguage) {
      const meta = target.ownerDocument.createElement('span')
      meta.className = 'ark-translation__meta'
      meta.textContent = `译自${languageLabel(state.sourceLanguage)}`
      body.append(meta)
    }
    body.append(target.ownerDocument.createTextNode(state.translation ?? ''))
  } else if (state.kind === 'blocked') {
    body.classList.add('ark-translation--blocked')
    body.textContent = messageForCode(state.code).text
  } else {
    body.classList.add('ark-translation--error')
    const message = messageForCode(state.code)
    body.textContent = state.retryAfterMs
      ? `请求较快，${Math.ceil(state.retryAfterMs / 1_000)} 秒后自动恢复`
      : message.text
    if (onRetry && !state.retryAfterMs && message.retryable) {
      const button = target.ownerDocument.createElement('button')
      button.className = 'ark-translation__retry'
      button.type = 'button'
      button.textContent = '重试'
      button.addEventListener('click', onRetry)
      body.append(button)
    }
  }

  shadow.append(body)
  return shadow
}
