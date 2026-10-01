/** 任务中心页内确认/输入对话框（单例，Promise 化）。ask() 返回 true / 输入值；取消返回 null。 */
import { reactive } from 'vue'

const DEFAULTS = { open: false, title: '', message: '', input: false, placeholder: '', confirmText: '确定', value: '', error: '', validate: null }
const dialog = reactive({ ...DEFAULTS })
let resolver = null

function settle(result) {
  dialog.open = false
  const resolve = resolver
  resolver = null
  resolve?.(result)
}

export function useTaskDialog() {
  function ask(options) {
    resolver?.(null)
    Object.assign(dialog, DEFAULTS, options, { open: true })
    return new Promise(resolve => { resolver = resolve })
  }

  function confirm() {
    if (!dialog.input) return settle(true)
    const value = dialog.value.trim()
    const error = dialog.validate?.(value) || ''
    if (error) {
      dialog.error = error
      return undefined
    }
    return settle(value)
  }

  return { dialog, ask, confirm, cancel: () => settle(null) }
}
