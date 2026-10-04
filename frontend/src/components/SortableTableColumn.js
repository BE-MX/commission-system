import { getCurrentInstance } from 'vue'
import { ElTableColumn } from 'element-plus'
import { compareTableValues, getSortValue } from '../utils/tableSort.js'

/** Extend the existing column in place: retain its table/group registration,
 * slots, tree support and refs. Explicit custom sorting remains server owned.
 */
export const SortableTableColumn = {
  ...ElTableColumn,
  props: {
    ...ElTableColumn.props,
    sortable: {
      ...ElTableColumn.props.sortable,
      default: props => Boolean((props.prop || props.property || props.sortBy || props['sort-by'] || props.sortMethod || props['sort-method']) && (!props.type || props.type === 'default')
        && !String(props.className || props['class-name'] || '').includes('table-action-column')),
    },
  },
  setup(props, context) {
    const instance = getCurrentInstance()
    const compareRows = (left, right) => {
      const fields = props.sortBy ? (Array.isArray(props.sortBy) ? props.sortBy : [props.sortBy]) : [props.prop || props.property]
      for (const field of fields) {
        const read = row => typeof field === 'function' ? field(row) : getSortValue(row, field)
        const result = compareTableValues(read(left), read(right), instance.columnConfig?.value.order)
        if (result) return result
      }
      return 0
    }
    const columnProps = new Proxy(props, {
      get(target, key) {
        if (key === 'sortMethod' && !target.sortMethod && target.sortable === true) return compareRows
        return Reflect.get(target, key)
      },
    })
    return ElTableColumn.setup(columnProps, context)
  },
}

export function registerSortableTables(app) {
  app.component('ElTableColumn', SortableTableColumn)
}
