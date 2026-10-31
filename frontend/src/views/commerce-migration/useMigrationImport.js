import { computed, readonly, ref, shallowRef } from 'vue'
import { errorMessage } from '../../utils/errors.js'
import { detectImportKind } from './labels.js'

/** Immutable file identity survives an uncertain response; preview never posts. */
export function useMigrationImport(api) {
  const manifest = shallowRef(null), kind = ref(''), fileName = ref(''), report = shallowRef(null), result = shallowRef(null)
  const pending = ref(false), uncertain = ref(false), failure = ref('')
  const waiting = computed(() => result.value?.status === 'waiting')
  const locked = computed(() => pending.value || uncertain.value || waiting.value)
  const canApply = computed(() => report.value?.can_apply === true && !pending.value && (!result.value || waiting.value))

  async function readFile(file) {
    if (locked.value) return { name: file.name }
    pending.value = true
    manifest.value = report.value = result.value = null
    kind.value = failure.value = ''
    fileName.value = file.name
    try {
      if (!/\.json$/i.test(file.name) || file.size > 4 * 1024 * 1024) throw new Error('请选择不超过4MB的JSON核验清单')
      const body = JSON.parse((await file.text()).replace(/^\uFEFF/, ''))
      if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('核验清单须为JSON对象')
      kind.value = detectImportKind(body)
      manifest.value = body
    } catch (error) { failure.value = errorMessage(error, '清单读取失败，请核对文件') }
    finally { pending.value = false }
    return { name: file.name }
  }

  async function preview() {
    if (locked.value || !manifest.value) return false
    pending.value = true
    report.value = result.value = null
    failure.value = ''
    try {
      const { data } = await api.preview(kind.value, JSON.parse(JSON.stringify(manifest.value)), { suppressToast: true })
      if (typeof data?.can_apply !== 'boolean' || !Array.isArray(data.conflicts)) throw new Error('预览结果不完整，请重新核对')
      report.value = data
      return true
    } catch (error) { failure.value = errorMessage(error, '预览失败，请重试'); return false }
    finally { pending.value = false }
  }

  async function apply() {
    if (!canApply.value) return false
    pending.value = true
    failure.value = ''
    try {
      const { data } = await api.apply(kind.value, JSON.parse(JSON.stringify(manifest.value)), { suppressToast: true })
      const key = kind.value === 'legacy_settlement' ? 'request_key' : 'batch_key'
      if (data?.status === 'waiting') {
        if (!Number.isSafeInteger(data.handover_preparation_id) || data.handover_preparation_id < 1
            || (data[key] !== undefined && data[key] !== manifest.value[key])) throw new Error('待核对请求身份不完整，须核对原清单')
        result.value = data
        uncertain.value = false
        return false
      }
      if (!data || !manifest.value[key] || data[key] !== manifest.value[key]) throw new Error('承接结果不完整，须重试当前清单核对')
      result.value = data
      uncertain.value = false
      return true
    } catch (error) {
      uncertain.value = !error?.response || error.response.status >= 500
      failure.value = errorMessage(error, '承接失败，请核对差异')
      if (!uncertain.value) report.value = null
      return false
    } finally { pending.value = false }
  }

  function clear() {
    if (locked.value) return false
    manifest.value = report.value = result.value = null
    fileName.value = kind.value = failure.value = ''
    return true
  }
  return { manifest: readonly(manifest), kind: readonly(kind), fileName: readonly(fileName),
    report: readonly(report), result: readonly(result), pending: readonly(pending), uncertain: readonly(uncertain),
    failure: readonly(failure), locked, canApply, waiting, readFile, preview, apply, clear }
}
