import { Mark } from '@tiptap/core'

const options = [
  { tone: null, label: '默认', cssColor: 'var(--text-primary)' },
  { tone: 'gold', label: '重点', cssColor: 'var(--color-primary)' },
  { tone: 'danger', label: '风险', cssColor: 'var(--color-danger-text)' },
  { tone: 'success', label: '完成', cssColor: 'var(--color-success-text)' },
  { tone: 'info', label: '说明', cssColor: 'var(--color-info-text)' },
]

export const TEXT_COLOR_OPTIONS = Object.freeze(options.map(option => Object.freeze(option)))
const TEXT_COLOR_TONES = new Set(TEXT_COLOR_OPTIONS.flatMap(option => option.tone ? [option.tone] : []))

export function normalizeTextColorTone(value) {
  return TEXT_COLOR_TONES.has(value) ? value : null
}

export function applyTextColor(editor, tone) {
  const normalized = normalizeTextColorTone(tone)
  if (tone !== null && !normalized) return false
  const chain = editor.chain().focus()
  return normalized
    ? chain.setMark('textColor', { tone: normalized }).run()
    : chain.unsetMark('textColor').run()
}

export const TextColorMark = Mark.create({
  name: 'textColor',

  addAttributes() {
    return { tone: { default: null } }
  },

  parseHTML() {
    return [{
      tag: 'span[data-text-color]',
      getAttrs: element => {
        const tone = normalizeTextColorTone(element.getAttribute('data-text-color'))
        return tone ? { tone } : false
      },
    }]
  },

  renderHTML({ HTMLAttributes }) {
    const tone = normalizeTextColorTone(HTMLAttributes.tone)
    if (!tone) return ['span', {}, 0]
    return [
      'span',
      {
        'data-text-color': tone,
        class: `knowledge-text-color knowledge-text-color--${tone}`,
      },
      0,
    ]
  },
})
