import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import TextAlign from '@tiptap/extension-text-align'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Table } from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableHeader from '@tiptap/extension-table-header'
import TableCell from '@tiptap/extension-table-cell'
import { Details, DetailsContent, DetailsSummary } from '@tiptap/extension-details'
import { ConfirmationMark } from './ConfirmationMark.js'
import { TextColorMark } from './TextColorMark.js'
import { KnowledgeImage } from './KnowledgeImage.js'
import { KnowledgeCallout, KnowledgeHighlight, KnowledgeTextSize, TEXT_ALIGNMENTS } from './knowledgeAuthoring.js'

export function createKnowledgeExtensions({ editing = false, structuredAuthoring = true } = {}) {
  return [
    StarterKit.configure({ link: false, underline: structuredAuthoring ? {} : false }),
    Link.configure({ openOnClick: !editing, protocols: ['http', 'https', 'mailto'] }),
    ConfirmationMark,
    TextColorMark,
    KnowledgeImage,
    TaskList, TaskItem.configure({ nested: true }),
    Table.configure({ resizable: editing }), TableRow, TableHeader, TableCell,
    ...(structuredAuthoring ? [
      TextAlign.configure({ types: ['paragraph', 'heading'], alignments: TEXT_ALIGNMENTS.map(item => item.value) }),
      KnowledgeTextSize,
      KnowledgeHighlight,
      KnowledgeCallout,
      Details.configure({
        renderToggleButton: ({ element, isOpen }) => {
          element.setAttribute('aria-label', isOpen ? '收起折叠块' : '展开折叠块')
          element.setAttribute('aria-expanded', String(isOpen))
        },
      }),
      DetailsSummary,
      DetailsContent,
    ] : []),
  ]
}
