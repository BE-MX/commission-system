import { Node, mergeAttributes } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import KnowledgeImageView from './KnowledgeImageView.vue'

export const KnowledgeImage = Node.create({
  name: 'knowledgeImage',
  group: 'block',
  atom: true,
  draggable: true,
  selectable: true,

  addAttributes() {
    return {
      assetId: { default: null },
      alt: { default: '' },
      caption: { default: '' },
      uploadId: { default: null, rendered: false },
      uploadStatus: { default: null, rendered: false },
      uploadProgress: { default: 0, rendered: false },
      uploadError: { default: '', rendered: false },
    }
  },

  parseHTML() {
    return [{
      tag: 'figure[data-knowledge-image]',
      getAttrs: element => {
        const assetId = Number(element.getAttribute('data-asset-id'))
        if (!Number.isInteger(assetId) || assetId <= 0) return false
        return {
          assetId,
          alt: element.querySelector('img')?.getAttribute('alt') || '',
          caption: element.querySelector('figcaption')?.textContent || '',
        }
      },
    }]
  },

  renderHTML({ HTMLAttributes }) {
    const assetId = Number(HTMLAttributes.assetId)
    if (!Number.isInteger(assetId) || assetId <= 0) {
      return ['figure', { 'data-knowledge-image-uploading': 'true' }, '图片上传中']
    }
    const attrs = {
      'data-knowledge-image': 'true',
      'data-asset-id': String(assetId),
    }
    return ['figure', mergeAttributes(attrs),
      ['img', { alt: HTMLAttributes.alt || '' }],
      ['figcaption', {}, HTMLAttributes.caption || ''],
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(KnowledgeImageView)
  },
})
