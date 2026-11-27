import { reactive, ref, computed } from 'vue'
import { clientDeskApi as api } from '@/api/clientDesk'
import { msgError, msgSuccessText, confirmAction, isFeedbackCancelled } from '@/utils/feedback'
import { errorText, latestRequestGate } from './deskController'
import { IGNORE_CONFIRM_TEXT, latestReview, reviewSections, sameThread, sortProspects, threadCard, validateProspectForm } from './unlinkedLeadsModel'

// Unlinked-leads (B track) state. TM and WhatsApp threads arrive in one list; each card carries its channel label.
export function useUnlinkedLeads() {
  const subView = ref('pending')
  const threads = ref([])
  const loading = ref(false)
  const error = ref('')
  const busyId = ref(null)
  const focusId = ref(null)
  const review = ref(null)
  const reviewLoading = ref(false)
  const reviewError = ref('')
  const generating = ref(false)
  const prospectId = ref(null)
  const prospectForm = reactive({ next_followup_date: '', next_followup_remark: '' })
  const prospectErrors = ref({})
  const threadGate = latestRequestGate(), reviewGate = latestRequestGate()

  const pendingCards = computed(() => threads.value.map(thread => threadCard(thread)))
  const prospectCards = computed(() => sortProspects(threads.value).map(thread => threadCard(thread)))
  const sections = computed(() => reviewSections(review.value))

  async function loadThreads() {
    const token = threadGate.next()
    loading.value = true; error.value = ''
    try {
      const view = subView.value === 'prospect' ? 'prospect' : 'active'
      const data = await api.unlinkedThreads({ view })
      if (!threadGate.current(token)) return
      threads.value = data.items || []
    } catch (e) {
      if (threadGate.current(token)) error.value = errorText(e)
    } finally {
      if (threadGate.current(token)) loading.value = false
    }
  }

  async function loadReview() {
    const token = reviewGate.next()
    reviewLoading.value = true; reviewError.value = ''
    try {
      const data = await api.unlinkedWeeklyReviews()
      if (!reviewGate.current(token)) return
      review.value = latestReview(data.items || [])
    } catch (e) {
      if (reviewGate.current(token)) reviewError.value = errorText(e)
    } finally {
      if (reviewGate.current(token)) reviewLoading.value = false
    }
  }

  function setSubView(key) {
    subView.value = key
    focusId.value = null
    closeProspect()
    if (key === 'review') return loadReview()
    return loadThreads()
  }

  function closeProspect() {
    prospectId.value = null
    prospectErrors.value = {}
    prospectForm.next_followup_date = ''
    prospectForm.next_followup_remark = ''
  }

  function openProspect(id, initial = {}) {
    closeProspect()
    prospectId.value = id
    prospectForm.next_followup_date = initial.date || ''
    prospectForm.next_followup_remark = initial.remark || ''
  }

  // Validation errors stay inside the form; the request only fires when both fields are present.
  async function submitProspect(id) {
    if (busyId.value) return
    const checked = validateProspectForm(prospectForm)
    prospectErrors.value = checked.errors
    if (!checked.ok) return
    busyId.value = id
    try {
      await api.unlinkedProspect(id, checked.payload)
      msgSuccessText('已加入未建档潜客')
      closeProspect()
      await loadThreads()
    } catch (e) {
      msgError(errorText(e), e)
    } finally {
      busyId.value = null
    }
  }

  // Shared runner for the one-click actions: busy guard, feedback, then refresh the list.
  async function run(id, request, successText) {
    if (busyId.value) return
    busyId.value = id
    try {
      await request()
      msgSuccessText(successText)
      if (subView.value === 'review') await loadReview()
      else await loadThreads()
    } catch (e) {
      msgError(errorText(e), e)
    } finally {
      busyId.value = null
    }
  }

  function bind(id, companyId) {
    return run(id, () => api.unlinkedBind(id, { company_id: String(companyId) }), '已绑定到私海客户')
  }
  function analyze(id) {
    return run(id, () => api.unlinkedAnalyze(id), '分析已排队')
  }
  function handled(id) {
    return run(id, () => api.unlinkedHandled(id), '已标记为在其他渠道处理')
  }
  async function ignore(id) {
    try {
      await confirmAction(IGNORE_CONFIRM_TEXT, '不是客户确认', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
    } catch (e) {
      if (!isFeedbackCancelled(e)) msgError('操作未完成，请重试', e)
      return
    }
    return run(id, () => api.unlinkedIgnore(id), '已标记为不是客户')
  }

  // Review rows: "open" jumps to the pending list; bind and ignore reuse the same endpoints as the cards.
  async function actOnReviewRow(row) {
    if (row.action === 'open') return openFromReview(row.threadId)
    if (row.action === 'bind') return bind(row.threadId, row.matchedCompanyId)
    if (row.action === 'ignore') return ignore(row.threadId)
  }
  async function openFromReview(threadId) {
    subView.value = 'pending'
    focusId.value = threadId
    await loadThreads()
    if (subView.value !== 'pending' || error.value || threads.value.some(thread => sameThread(thread.id, threadId))) return
    subView.value = 'prospect'
    await loadThreads()
    if (subView.value === 'prospect' && !error.value && !threads.value.some(thread => sameThread(thread.id, threadId))) {
      focusId.value = null
      msgError('该线索当前不可处理')
    }
  }

  async function generateReview() {
    if (generating.value) return
    generating.value = true
    try {
      const generated = await api.unlinkedGenerateWeeklyReview()
      await loadReview()
      if (generated.status === 'succeeded') msgSuccessText('周报已生成')
      else msgError('周报暂未生成，请稍后重试')
    } catch (e) {
      msgError(errorText(e), e)
    } finally {
      generating.value = false
    }
  }

  async function copyDraft(text) {
    try {
      await navigator.clipboard.writeText(text)
      msgSuccessText('草稿已复制（占位符需先核对）')
    } catch {
      msgError('复制失败，请手动选中草稿复制')
    }
  }

  return {
    subView, loading, error, busyId, focusId, threads, pendingCards, prospectCards,
    review, reviewLoading, reviewError, generating, sections,
    prospectId, prospectForm, prospectErrors,
    setSubView, loadThreads, loadReview, openProspect, closeProspect, submitProspect,
    bind, analyze, handled, ignore, actOnReviewRow, generateReview, copyDraft,
  }
}
