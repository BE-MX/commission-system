import { readonly, ref, shallowRef } from 'vue'
import { errorMessage } from '../../utils/errors.js'

/** A server-prepared command keeps every selected identity/version on retries. */
export function useMigrationActivation(api, keyFactory = () => crypto.randomUUID()) {
  const pending = ref(false), uncertain = ref(false), failure = ref(''), review = shallowRef(null), result = shallowRef(null)
  async function prepare(recordIds) {
    if (pending.value || uncertain.value) return false
    pending.value = true
    review.value = result.value = null
    failure.value = ''
    try {
      const ids = [...new Set(recordIds)].sort((a, b) => a - b)
      if (!ids.length) throw new Error('请先选择待放行的订单或生产责任')
      const key = keyFactory()
      const { data } = await api.prepare({ request_key: key, record_ids: ids }, { suppressToast: true })
      if (data?.command?.request_key !== key || typeof data?.report?.can_activate !== 'boolean'
          || !Array.isArray(data.report.conflicts) || !Array.isArray(data.descriptions)) throw new Error('责任核对结果不完整，请重新核对')
      review.value = data
      return true
    } catch (error) { failure.value = errorMessage(error, '责任核对失败，请重试'); return false }
    finally { pending.value = false }
  }
  async function activate() {
    if (pending.value || !review.value?.report.can_activate || result.value) return false
    pending.value = true
    failure.value = ''
    try {
      const body = JSON.parse(JSON.stringify(review.value.command))
      const { data } = await api.activate(body, { suppressToast: true })
      if (data?.request_key !== body.request_key) throw new Error('放行结果不完整，请重试原请求核对')
      result.value = data
      uncertain.value = false
      return true
    } catch (error) {
      uncertain.value = !error?.response || error.response.status >= 500
      failure.value = errorMessage(error, '放行失败，请重新核对责任')
      if (!uncertain.value) review.value = null
      return false
    } finally { pending.value = false }
  }
  function clear() {
    if (pending.value || uncertain.value) return false
    review.value = result.value = null
    failure.value = ''
    return true
  }
  return { pending: readonly(pending), uncertain: readonly(uncertain), failure: readonly(failure),
    review: readonly(review), result: readonly(result), prepare, activate, clear }
}
