import { Mark, mergeAttributes } from '@tiptap/core'

export const ConfirmationMark = Mark.create({
  name: 'confirmation',

  parseHTML() {
    return [{ tag: 'span[data-confirmation="true"]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes, { 'data-confirmation': 'true' }), 0]
  },
})
