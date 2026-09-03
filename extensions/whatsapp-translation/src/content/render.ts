import type { IncomingRenderState } from '@/content/incomingTranslator'

const TRANSLATION_STYLES = `
  :host { all: initial; }
  .ark-translation {
    background: var(--ark-surface, #ffffff);
    border-radius: 8px;
    color: var(--ark-text, #1f2937);
    display: block;
    font-family: var(--ark-font, system-ui, sans-serif);
    font-size: 13px;
    line-height: 1.4;
    margin-top: 4px;
    padding: 6px 8px;
  }
  .ark-translation__retry {
    background: transparent;
    border: none;
    color: var(--ark-primary, #2563eb);
    cursor: pointer;
    font: inherit;
    padding: 0;
    text-decoration: underline;
  }
`

const shadowRoots = new WeakMap<HTMLElement, ShadowRoot>()

export function mountTranslation(
  target: Element,
  state: IncomingRenderState,
  onRetry?: () => void,
): ShadowRoot {
  let host = target.querySelector<HTMLElement>(':scope > [data-ark-translation-host="1"]')
  if (!host) {
    host = document.createElement('div')
    host.dataset.arkTranslationHost = '1'
    target.append(host)
  }

  const existingShadow = shadowRoots.get(host)
  const shadow = existingShadow ?? host.attachShadow({ mode: 'closed' })
  shadowRoots.set(host, shadow)
  shadow.replaceChildren()

  const style = document.createElement('style')
  style.textContent = TRANSLATION_STYLES
  shadow.append(style)

  const body = document.createElement('div')
  body.className = 'ark-translation'

  if (state.kind === 'loading') {
    body.textContent = 'Translating…'
  } else if (state.kind === 'success') {
    body.textContent = state.translation ?? ''
  } else if (state.kind === 'blocked') {
    body.textContent = 'Translation is unavailable.'
  } else {
    body.textContent = state.retryAfterMs
      ? `Translation paused. Retry available in ${Math.ceil(state.retryAfterMs / 1_000)}s.`
      : 'Translation failed.'
    if (onRetry && !state.retryAfterMs) {
      const button = document.createElement('button')
      button.className = 'ark-translation__retry'
      button.type = 'button'
      button.textContent = 'Retry'
      button.addEventListener('click', onRetry)
      body.append(button)
    }
  }

  shadow.append(body)
  return shadow
}
