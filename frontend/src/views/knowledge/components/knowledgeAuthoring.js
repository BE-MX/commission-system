import { Mark, Node } from '@tiptap/core'
import { normalizeTextColorTone } from './TextColorMark.js'

export const FONT_SIZES = [12, 13, 14, 15, 16, 19, 22, 24, 29, 32, 40, 48]
export const TEXT_ALIGNMENTS = [
  { value: 'left', label: '左对齐' },
  { value: 'center', label: '居中' },
  { value: 'right', label: '右对齐' },
  { value: 'justify', label: '两端对齐' },
]
export const HIGHLIGHT_COLORS = {
  gold: 'var(--button-primary-soft)',
  danger: 'var(--button-danger-soft)',
  success: 'var(--tag-success-bg)',
  info: 'var(--tag-info-bg)',
}

export const KnowledgeTextSize = Mark.create({
  name: 'knowledgeTextSize',

  addAttributes() {
    return { size: { default: null, rendered: false } }
  },

  parseHTML() {
    return [{
      tag: 'span[data-knowledge-size]',
      getAttrs: element => {
        const size = Number(element.getAttribute('data-knowledge-size'))
        return FONT_SIZES.includes(size) ? { size } : false
      },
    }]
  },

  renderHTML({ mark }) {
    const { size } = mark.attrs
    return FONT_SIZES.includes(size)
      ? ['span', { 'data-knowledge-size': size, style: `font-size: ${size}px` }, 0]
      : ['span', 0]
  },
})

export const KnowledgeHighlight = Mark.create({
  name: 'knowledgeHighlight',

  addAttributes() {
    return { tone: { default: null, rendered: false } }
  },

  parseHTML() {
    return [{
      tag: 'mark[data-knowledge-highlight]',
      getAttrs: element => {
        const tone = normalizeTextColorTone(element.getAttribute('data-knowledge-highlight'))
        return tone ? { tone } : false
      },
    }]
  },

  renderHTML({ mark }) {
    const tone = normalizeTextColorTone(mark.attrs.tone)
    return tone ? ['mark', { 'data-knowledge-highlight': tone }, 0] : ['span', 0]
  },
})

export const KnowledgeCallout = Node.create({
  name: 'knowledgeCallout',
  group: 'block',
  content: 'block+',
  defining: true,

  addAttributes() {
    return { tone: { default: 'info', rendered: false } }
  },

  parseHTML() {
    return [{
      tag: 'aside[data-knowledge-callout]',
      getAttrs: element => {
        const tone = normalizeTextColorTone(element.getAttribute('data-knowledge-callout'))
        return tone ? { tone } : false
      },
    }]
  },

  renderHTML({ node }) {
    return ['aside', { 'data-knowledge-callout': normalizeTextColorTone(node.attrs.tone) || 'info' }, 0]
  },
})
