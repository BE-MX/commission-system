import { onActivated, onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'

export function useInvoiceColumnWidths(table, rows, columns) {
  const widths = shallowRef({})
  let frame
  let active = false

  function measure() {
    const root = table.value?.$el
    if (!root?.clientWidth) return
    const next = {}
    root.classList.add('invoice-table--measuring')
    try {
      for (const column of columns.value.filter(col => col.fitContent)) {
        const selector = `.invoice-col-${column.key} > .cell`
        const header = root.querySelector(`th${selector}`)
        const cells = root.querySelectorAll(`td${selector}`)
        const headerWidth = header ? Math.ceil(header.getBoundingClientRect().width + 2) : 0
        let width = Math.max(column.minWidth, headerWidth)
        for (const cell of cells) {
          const content = cell.firstElementChild
          if (!content) continue
          const style = getComputedStyle(cell)
          const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
          width = Math.max(width, Math.ceil(content.getBoundingClientRect().width + padding + 3))
        }
        next[column.key] = Math.min(width, column.maxWidth)
      }
    } finally {
      root.classList.remove('invoice-table--measuring')
    }
    if (JSON.stringify(widths.value) !== JSON.stringify(next)) widths.value = next
  }

  function schedule() {
    if (!active) return
    cancelAnimationFrame(frame)
    frame = requestAnimationFrame(measure)
  }

  watch([rows, columns], schedule, { flush: 'post' })
  onMounted(() => {
    active = true
    schedule()
    document.fonts?.ready.then(schedule)
  })
  onActivated(schedule)
  onBeforeUnmount(() => {
    active = false
    cancelAnimationFrame(frame)
  })
  return widths
}
