import { ref } from 'vue'
import { newRequestKey } from '@/utils/requestKey'
import { errorMessage } from '@/utils/errors'
import { isFeedbackCancelled } from '@/utils/feedback'

/** One command identity per unchanged attempt, including uncertain transport failures. */
export function useNativeCommand(keyFactory = newRequestKey) {
  const pending = ref(false), failure = ref('')
  let attempt = null
  function reset() { attempt = null; failure.value = '' }
  async function run({ validate, payload, send, confirm }) {
    if (pending.value) return { ok: false, busy: true }
    pending.value = true
    failure.value = ''
    try {
      if (validate && !await validate()) return { ok: false }
      const body = JSON.parse(JSON.stringify(payload()))
      const signature = JSON.stringify(body)
      if (confirm) await confirm()
      if (!attempt || attempt.signature !== signature) {
        attempt = { signature, body: { ...body, request_key: keyFactory() } }
      }
      const response = await send(attempt.body)
      reset()
      return { ok: true, data: response.data }
    } catch (error) {
      if (!isFeedbackCancelled(error)) failure.value = errorMessage(error)
      return { ok: false, error }
    } finally { pending.value = false }
  }
  return { pending, failure, reset, run }
}
