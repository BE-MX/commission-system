import { computed, ref } from 'vue'
import { recordToEditForm } from '../followupEdit.js'
import { errorMessage } from '../../../utils/errors.js'

export function useFollowupEditor(api, onSaved = () => {}) {
  const visible = ref(false), loading = ref(false), saving = ref(false)
  const error = ref(''), conflict = ref(false), uncertain = ref(false), record = ref(null), form = ref(null), dicts = ref({})
  let generation = 0, original = '', currentId
  let retryPayload = null
  const dirty = computed(() => form.value && JSON.stringify(form.value) !== original)
  async function open(id) {
    const run = ++generation
    currentId = id
    visible.value = loading.value = true
    record.value = form.value = null
    error.value = ''
    conflict.value = false
    uncertain.value = false
    retryPayload = null
    try {
      const [row, values] = await Promise.all([api.followup(id), api.dicts()])
      if (run !== generation) return
      if (!row.can_edit) throw new Error('没有修改这条记录的权限')
      record.value = row
      dicts.value = values
      form.value = recordToEditForm(row)
      original = JSON.stringify(form.value)
    } catch (failure) { if (run === generation) error.value = errorMessage(failure) }
    finally { if (run === generation) loading.value = false }
  }
  function close() {
    if (saving.value) return
    generation++
    visible.value = false
  }
  async function save() {
    if (saving.value || !form.value || conflict.value) return false
    if (!form.value.reason.trim()) { error.value = '请填写修改原因'; return false }
    if (!form.value.result_code?.trim()) { error.value = '请选择本次结果'; return false }
    saving.value = true
    error.value = ''
    // A transport retry must use exactly the same idempotent payload.
    retryPayload ||= {
      ...JSON.parse(JSON.stringify(form.value)),
      items: form.value.items.map(({ key, ...item }) => ({ ...item })),
    }
    try {
      const result = await api.editFollowup(currentId, retryPayload)
      visible.value = false
      onSaved(result)
      retryPayload = null
      return true
    } catch (failure) {
      conflict.value = failure?.response?.status === 409
      error.value = errorMessage(failure, '保存失败，请重试')
      uncertain.value = !failure?.response?.status || failure.response.status >= 500
      if (uncertain.value) error.value += '；保存结果尚未确认，请重试同一次修改或重新载入核实。'
      else retryPayload = null
      return false
    } finally { saving.value = false }
  }
  const reload = () => open(currentId)
  return { visible, loading, saving, error, conflict, uncertain, record, form, dicts, dirty, open, close, save, reload }
}
