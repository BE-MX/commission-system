import { onUnmounted, ref, watch } from 'vue'
import { createWhatsAppBindSession, getWhatsAppBindSession, updateWhatsAppConsent, listWhatsAppReaderCandidates } from '@/api/whatsapp'
import { msgSuccessText, msgWarning } from '@/utils/feedback'

export function useWhatsAppBinding(loadAccounts) {
  const bindDialogVisible = ref(false), bindSession = ref(null), bindBusy = ref(false)
  const bindingAccount = ref(null), companyAccount = ref(false), shareCRM = ref(false)
  const consentDialogVisible = ref(false), consentAccount = ref(null), consentBusy = ref(false)
  const consentForm = ref({}), readerCandidates = ref([])
  let poll, generation = 0, disposed = false, failures = 0
  function clearTimer() { clearTimeout(poll); poll = null }
  function stop() { generation++; clearTimer(); bindDialogVisible.value = false; consentDialogVisible.value = false; bindSession.value = null }
  onUnmounted(() => { disposed = true; stop() })
  watch(bindDialogVisible, visible => { if (!visible) { generation++; clearTimer(); bindSession.value = null } })

  function openBind(account = null) {
    generation++; clearTimer(); failures = 0
    bindingAccount.value = account
    bindSession.value = null
    companyAccount.value = false
    shareCRM.value = Boolean(account?.crm_shared)
    bindDialogVisible.value = true
  }
  function schedule(id) {
    if (id !== generation || disposed || !bindDialogVisible.value) return
    clearTimer()
    if (!['active', 'expired', 'error', 'revoking', 'revoke_pending', 'revoked', 'reconnect_required', 'paused', 'protected', 'blocked'].includes(bindSession.value?.status)) {
      poll = setTimeout(() => refresh(id), 3000)
    }
  }
  async function create() {
    if (bindBusy.value || !companyAccount.value) return
    const id = generation
    bindBusy.value = true
    try {
      const result = await createWhatsAppBindSession({ account_uid: bindingAccount.value?.account_uid,
        company_account: companyAccount.value, crm_shared: shareCRM.value })
      if (id !== generation || disposed) return
      bindSession.value = result.data
      await loadAccounts()
      schedule(id)
    } finally { bindBusy.value = false }
  }
  async function refresh(id = generation) {
    const uid = bindSession.value?.bind_session_uid
    if (!uid || id !== generation || disposed) return
    try {
      const result = await getWhatsAppBindSession(uid, { showLoading: false, suppressToast: true })
      if (id !== generation || disposed || !bindDialogVisible.value) return
      failures = 0
      bindSession.value = result.data
      if (result.data?.status === 'active') {
        clearTimer(); msgSuccessText('关联成功，已同步范围会在对话中显示'); await loadAccounts()
      } else schedule(id)
    } catch {
      if (id !== generation || disposed || !bindDialogVisible.value) return
      // A read-only status query is safe to retry; a short network blip must not freeze the QR.
      if (++failures < 3) { clearTimer(); poll = setTimeout(() => refresh(id), 3000 * failures); return }
      clearTimer()
      msgWarning('连接状态暂时无法查询，请点击刷新状态重试')
    }
  }
  async function searchReaders(q = '') {
    if (!consentAccount.value) return
    const uid = consentAccount.value.account_uid
    const result = await listWhatsAppReaderCandidates(uid, q, { showLoading: false, suppressToast: true })
    if (consentAccount.value?.account_uid === uid) readerCandidates.value = result.data || []
  }
  async function openConsent(account) {
    consentAccount.value = account
    consentForm.value = { enabled: account.consent_state === 'active', company_account: false,
      crm_shared: Boolean(account.crm_shared), ai_egress_allowed: Boolean(account.ai_egress_allowed),
      reader_user_ids: [...(account.reader_user_ids || [])] }
    readerCandidates.value = []
    consentDialogVisible.value = true
    await searchReaders()
  }
  async function saveConsent() {
    if (consentBusy.value || !consentAccount.value) return
    consentBusy.value = true
    try {
      await updateWhatsAppConsent(consentAccount.value.account_uid, consentForm.value)
      consentDialogVisible.value = false
      msgSuccessText('授权已更新'); await loadAccounts()
    } finally { consentBusy.value = false }
  }
  return { bindDialogVisible, bindSession, bindBusy, bindingAccount, companyAccount, shareCRM,
    consentDialogVisible, consentAccount, consentForm, consentBusy, readerCandidates,
    openBind, create, refresh, openConsent, searchReaders, saveConsent, stop }
}
