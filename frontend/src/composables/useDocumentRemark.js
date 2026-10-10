import { computed, onUnmounted, ref, watch } from 'vue'
import { updateInvoiceRemark } from '@/api/invoice'
import { updateReceiptRemark } from '@/api/receipt'
import { msgSuccessText } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'

export function useDocumentRemark(props, emit) {
  const editing = ref(false), saving = ref(false), draft = ref(''), error = ref('')
  let generation = 0, version
  const auth = useAuthStore()
  const authorityKey = computed(() => JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions]))
  const invoice = computed(() => props.kind === 'invoice')
  const permission = computed(() => invoice.value ? 'invoice:write' : 'receipt:write')
  const maxLength = computed(() => invoice.value ? 5000 : 500)
  const editable = computed(() => {
    const row = props.document
    return invoice.value
      ? !['cancelled', 'cancel_pending', 'syncing', 'sync_uncertain'].includes(row.status)
        && !row.linked_sync_id && !['syncing', 'sync_uncertain'].includes(row.sync_status)
      : row.status === 'active' && row.sync_status !== 'syncing'
  })
  function cancel() { generation++; editing.value = false; saving.value = false; error.value = '' }
  function start() {
    if (!editable.value || props.disabled || saving.value) return
    draft.value = props.document.remark || ''; error.value = ''; editing.value = true
    version = invoice.value ? props.document.edit_version : props.document.version
  }
  async function save() {
    if (saving.value || !editable.value || props.disabled) return
    if (draft.value.length > maxLength.value) { error.value = `备注最多 ${maxLength.value} 个字符`; return }
    const ticket = ++generation, id = props.document.id
    const body = { remark: draft.value, ...(invoice.value
      ? { expected_version: version } : { version }) }
    saving.value = true; error.value = ''
    try {
      const row = await (invoice.value ? updateInvoiceRemark(id, body) : updateReceiptRemark(id, body))
      if (ticket !== generation) return
      emit('updated', row); editing.value = false; msgSuccessText('备注已保存')
    } catch (failure) {
      if (ticket === generation) error.value = failure.response?.data?.detail || failure.message || '保存失败，请重试'
    } finally { if (ticket === generation) saving.value = false }
  }
  watch(() => [props.document.id, props.kind], cancel, { flush: 'sync' })
  watch(authorityKey, cancel, { flush: 'sync' })
  onUnmounted(cancel)
  return { editing, saving, draft, error, permission, maxLength, editable, authorityKey, start, save, cancel }
}
