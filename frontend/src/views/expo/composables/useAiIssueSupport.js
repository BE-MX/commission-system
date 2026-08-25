import { computed, ref } from 'vue'
import { contactExpoAdmin } from '@/api/expo'

/** 展会 AI 异常的公开状态与人工支持通知。 */
export function useAiIssueSupport({ session, sessionId, errorText }) {
  const contactAdminPending = ref(false)
  const aiIssue = computed(() => session.value?.ai_issue || null)

  function resetAiIssueSupport() {
    contactAdminPending.value = false
  }

  async function contactAdmin() {
    if (!sessionId.value || contactAdminPending.value || aiIssue.value?.notified) return
    contactAdminPending.value = true
    errorText.value = ''
    try {
      await contactExpoAdmin(sessionId.value)
      if (session.value?.ai_issue) session.value.ai_issue.notified = true
    } catch (e) {
      errorText.value = '管理员通知发送失败，请直接拨打下方电话'
    } finally {
      contactAdminPending.value = false
    }
  }

  return { aiIssue, contactAdmin, contactAdminPending, resetAiIssueSupport }
}
