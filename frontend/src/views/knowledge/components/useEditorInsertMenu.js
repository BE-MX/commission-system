import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { EDITOR_COMMANDS, filterEditorCommands, findSlashQuery, runBlockCommand } from './editorConfig.js'

export function useEditorInsertMenu(selectImage, structuredAuthoring) {
  const open = ref(false)
  const commands = computed(() => EDITOR_COMMANDS.filter(item => !item.structuredAuthoring || structuredAuthoring()))
  const items = computed(() => filterEditorCommands(commands.value, query.value))
  const index = ref(0)
  const position = ref({})
  const query = ref('')
  const range = shallowRef(null)
  let dismissedAt = null
  let button = null

  function place(instance) {
    if (!open.value || !instance?.view) return
    const anchor = button?.getBoundingClientRect() ?? instance.view.coordsAtPos(instance.state.selection.from)
    const below = window.innerHeight - anchor.bottom - 16
    const above = anchor.top - 16
    const opensUp = below < 300 && above > below
    const width = Math.min(290, window.innerWidth - 24)
    position.value = {
      left: `${Math.max(12, Math.min(anchor.left, window.innerWidth - width - 12))}px`,
      ...(opensUp
        ? { bottom: `${window.innerHeight - anchor.top + 6}px` }
        : { top: `${anchor.bottom + 6}px` }),
      width: `${width}px`,
      maxHeight: `${Math.max(60, Math.min(380, opensUp ? above : below))}px`,
    }
  }

  function close(dismiss = false) {
    if (dismiss) dismissedAt = range.value?.from ?? null
    else dismissedAt = null
    open.value = false
    range.value = null
    query.value = ''
    button = null
  }

  function update(instance, canOpen = true) {
    if (!instance.isEditable) return
    if (button) {
      if (canOpen) close()
      return
    }
    const match = findSlashQuery(instance.state.selection)
    if (!match) {
      close()
      return
    }
    if ((!open.value && !canOpen) || match.from === dismissedAt) return
    if (!open.value || query.value !== match.query) index.value = 0
    range.value = { from: match.from, to: match.to }
    query.value = match.query
    open.value = true
    nextTick(() => place(instance))
  }

  function openFromButton(instance, anchor) {
    if (open.value && button === anchor) return close(true)
    close()
    if (!instance?.isEditable) return
    button = anchor
    index.value = 0
    open.value = true
    instance.commands.focus()
    place(instance)
  }

  function select(instance, id) {
    if (!open.value || !instance?.isEditable) return
    const match = range.value && findSlashQuery(instance.state.selection)
    if (range.value && (!match || match.from !== range.value.from || match.to !== range.value.to)) return close()
    const selectedRange = range.value
    close()
    if (id === 'image') {
      if (selectedRange) instance.chain().focus().deleteRange(selectedRange).run()
      selectImage()
      return
    }
    runBlockCommand(instance, id, { range: selectedRange, toggle: !selectedRange })
  }

  function handleKeydown(instance, event) {
    if (!open.value || event.isComposing || event.keyCode === 229) return
    if (event.key === 'Escape') {
      event.preventDefault()
      close(true)
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      const total = items.value.length
      if (!total) return
      event.preventDefault()
      index.value = (index.value + (event.key === 'ArrowDown' ? 1 : -1) + total) % total
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      const item = items.value[index.value]
      if (!item) return close(true)
      event.preventDefault()
      select(instance, item.id)
    }
  }

  function closeOutside(event) {
    if (!open.value || button?.contains(event.target) || event.target.closest?.('.slash-menu')) return
    close(true)
  }

  onMounted(() => document.addEventListener('pointerdown', closeOutside))
  onBeforeUnmount(() => document.removeEventListener('pointerdown', closeOutside))

  return { open, items, index, position, close, update, place, handleKeydown, openFromButton, select }
}
