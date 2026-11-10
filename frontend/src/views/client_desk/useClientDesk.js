import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { clientDeskApi as api } from '@/api/clientDesk'
import { msgSuccessText } from '@/utils/feedback'
import { currentBeijingDate, formatBeijingDateTime } from '@/utils/datetime'
import { errorText, requestKey, latestRequestGate, normalizeDetail } from './deskController'

export function useClientDesk(route) {
  const mode = ref('suggested'), filter = ref(''), keyword = ref(''), page = ref(1), pageSize = ref(20), total = ref(0)
  const rows = ref([]), today = ref({}), selected = ref(null), detail = ref(null), reading = ref(false)
  const loading = ref(false), detailLoading = ref(false), error = ref(''), detailError = ref('')
  const source = ref('all'), events = ref([]), cursor = ref(null), timelineLoading = ref(false)
  const evidence = ref(null), evidenceOpen = ref(false), evidenceError = ref(''), evidenceLoading = ref(false)
  const dialog = ref(''), form = ref({}), saving = ref(false), saveError = ref(''), conflict = ref(null)
  const linkOptions = ref([]), linkKeyword = ref(''), scope = ref(''), selectedChat = ref(null)
  const listGate = latestRequestGate(), detailGate = latestRequestGate(), eventGate = latestRequestGate(), evidenceGate = latestRequestGate()
  let aborter, timer, poller
  const suggestion = computed(() => detail.value?.suggestion)
  const state = computed(() => detail.value?.personal_state || {})
  const busyAnalysis = computed(() => ['queued', 'running'].includes(suggestion.value?.status))
  const id = () => String(selected.value)
  async function refreshToday() { today.value = await api.today() }
  async function loadList() {
    const token = listGate.next(); loading.value = true; error.value = ''; rows.value = []
    try {
      const params = { keyword: keyword.value, page: page.value, page_size: pageSize.value }
      const data = mode.value === 'unlinked' ? await api.conversations({ ...params, scope: scope.value || undefined }) : await api.customers({ ...params, filter: mode.value === 'suggested' ? 'suggested' : filter.value || 'all', reason: mode.value === 'suggested' ? filter.value || undefined : undefined })
      if (!listGate.current(token)) return
      rows.value = (data.items || []).map(row => mode.value === 'unlinked' ? { ...row, link_id: row.link?.id, phone_masked: row.phone_masked || row.phone, last_touch_at: row.last_at } : row); total.value = data.total || 0
      if (mode.value !== 'unlinked' && !reading.value && rows.value.length && !selected.value) void select(rows.value[0], false)
    } catch (e) { if (listGate.current(token)) error.value = errorText(e) }
    finally { if (listGate.current(token)) loading.value = false }
  }
  async function select(row, mobile = true) {
    aborter?.abort(); aborter = new AbortController(); const token = detailGate.next(); evidenceGate.invalidate(); eventGate.invalidate()
    detail.value = null; events.value = []; cursor.value = null; evidence.value = null; evidenceOpen.value = false; detailError.value = ''; selectedChat.value = null
    if (mobile) reading.value = true
    if (mode.value === 'unlinked') { selectedChat.value = row; selected.value = null; return }
    selected.value = String(row.company_id); detailLoading.value = true; source.value = 'all'
    try {
      const data = await api.customer(id(), aborter.signal)
      if (!detailGate.current(token)) return
      detail.value = normalizeDetail(data); await loadTimeline(false)
      clearTimeout(poller)
      if (busyAnalysis.value) poller = setTimeout(() => select({ company_id: selected.value }, false), 5000)
    } catch (e) { if (detailGate.current(token) && e.code !== 'ERR_CANCELED') { detail.value = null; detailError.value = errorText(e) } }
    finally { if (detailGate.current(token)) detailLoading.value = false }
  }
  async function loadTimeline(more = false) {
    if (!selected.value) return
    const token = eventGate.next(), customer = id(); timelineLoading.value = true
    if (!more) { events.value = []; cursor.value = null }
    try {
      const data = await api.timeline(customer, { source: source.value, cursor: more ? cursor.value : undefined, limit: 20 }, aborter?.signal)
      if (!eventGate.current(token) || customer !== id()) return
      events.value = more ? [...events.value, ...data.items] : data.items || []; cursor.value = data.next_cursor
    } catch (e) { if (eventGate.current(token) && e.code !== 'ERR_CANCELED') detailError.value = errorText(e) }
    finally { if (eventGate.current(token)) timelineLoading.value = false }
  }
  async function openEvidence(key) {
    const token = evidenceGate.next(), customer = id(); evidence.value = null; evidenceError.value = ''; evidenceOpen.value = true; evidenceLoading.value = true
    try { const data = await api.evidence(customer, key, aborter?.signal); if (evidenceGate.current(token) && customer === id()) evidence.value = data }
    catch (e) { if (evidenceGate.current(token)) evidenceError.value = errorText(e) }
    finally { if (evidenceGate.current(token)) evidenceLoading.value = false }
  }
  function open(kind) {
    saveError.value = ''; conflict.value = null; dialog.value = kind
    form.value = kind === 'note' ? { remark: state.value.remark || '', expected_version: state.value.manual_version } : kind === 'date' ? { next_followup_date: state.value.next_followup_date || '', next_followup_remark: state.value.next_followup_remark || '', expected_version: state.value.manual_version } : kind === 'grade' ? { grade: detail.value.grade, expected_grade: detail.value.grade } : kind === 'record' ? { channel: 'phone', content: '', happened_at: formatBeijingDateTime(new Date()).replace(' ', 'T'), next_followup_date: '', client_request_id: requestKey(), suggestion_id: suggestion.value?.id } : kind === 'snooze' ? { date: '', value: 'snoozed' } : { company_id: '', client_request_id: requestKey() }
    if (kind === 'link') searchLinks()
  }
  async function searchLinks() { try { linkOptions.value = (await api.customers({ filter: 'all', keyword: linkKeyword.value, page_size: 50 })).items || [] } catch (e) { saveError.value = errorText(e) } }
  async function save() {
    if (saving.value) return
    saving.value = true; saveError.value = ''; const customer = selected.value, kind = dialog.value
    try {
      const payload = { ...form.value }
      if (kind === 'record') { if (!payload.content.trim() || !payload.happened_at) throw new Error('请填写内容和发生时间'); if (payload.happened_at > formatBeijingDateTime(new Date()).replace(' ', 'T')) throw new Error('发生时间不能晚于当前'); payload.next_followup_date ||= null }
      if (kind === 'snooze' && (!payload.date || payload.date <= currentBeijingDate())) throw new Error('请选择未来日期')
      if (kind === 'date') payload.next_followup_date ||= null
      if (kind === 'link') {
        if (!payload.company_id) throw new Error('请手动选择本人私海客户')
        await api.link({ account_uid: selectedChat.value.account_uid, conversation_uid: selectedChat.value.conversation_uid, link_type: 'linked', company_id: payload.company_id, expected_link_id: selectedChat.value.link_id || null })
      } else if (kind === 'record') await api.followup(customer, payload)
      else if (kind === 'grade') await api.grade(customer, payload)
      else if (kind === 'snooze') await api.feedback(suggestion.value.id, payload)
      else await api.state(customer, payload)
      dialog.value = ''; msgSuccessText('已保存'); if (customer && selected.value === customer) await select({ company_id: customer }, false)
      if (kind === 'link') { selectedChat.value = null; reading.value = false }
      await Promise.all([loadList(), refreshToday()])
    } catch (e) { saveError.value = errorText(e); if (e.response?.status === 409) conflict.value = e.response.data.detail?.latest || e.response.data.data || e.response.data.detail }
    finally { saving.value = false }
  }
  async function feedback(value) {
    if (saving.value) return; saving.value = true; saveError.value = ''
    try { await api.feedback(suggestion.value.id, { value }); await select({ company_id: selected.value }, false); await Promise.all([refreshToday(), loadList()]) }
    catch (e) { detailError.value = errorText(e) } finally { saving.value = false }
  }
  let analysisKey
  async function reanalyze() {
    if (saving.value || busyAnalysis.value) return; saving.value = true
    try { analysisKey ||= requestKey(); await api.reanalyze(id(), { client_request_id: analysisKey }); analysisKey = null; await select({ company_id: selected.value }, false); msgSuccessText('已加入分析队列') }
    catch (e) { detailError.value = errorText(e) } finally { saving.value = false }
  }
  async function ignoreChat() {
    if (saving.value) return; saving.value = true
    try { const chat = selectedChat.value; if (chat.link_id) await api.unlink(chat.link_id); else await api.link({ account_uid: chat.account_uid, conversation_uid: chat.conversation_uid, link_type: 'ignored', company_id: null, expected_link_id: null }); selectedChat.value = null; reading.value = false; await Promise.all([loadList(), refreshToday()]) }
    catch (e) { detailError.value = errorText(e) } finally { saving.value = false }
  }
  function reloadFirstPage() {
    if (page.value === 1) void loadList()
    else page.value = 1
  }
  watch([mode, filter, scope], () => { detailLoading.value = false; aborter?.abort(); detailGate.invalidate(); eventGate.invalidate(); evidenceGate.invalidate(); evidence.value = null; evidenceOpen.value = false; clearTimeout(poller); clearTimeout(timer); selected.value = null; detail.value = null; selectedChat.value = null; reading.value = false; reloadFirstPage() })
  watch(keyword, () => { listGate.invalidate(); clearTimeout(timer); timer = setTimeout(reloadFirstPage, 250) })
  watch(page, loadList); watch(pageSize, () => { if (page.value === 1) loadList(); else page.value = 1 }); watch(source, () => loadTimeline(false))
  onBeforeUnmount(() => { aborter?.abort(); listGate.invalidate(); detailGate.invalidate(); evidenceGate.invalidate(); clearTimeout(timer); clearTimeout(poller) })
  async function init() {
    try {
      await refreshToday()
      if (route.query.company_id) void select({ company_id: String(route.query.company_id) })
      await loadList()
    } catch (e) { error.value = errorText(e) }
  }
  return { mode, filter, keyword, page, pageSize, total, rows, today, selected, detail, reading, loading, detailLoading, error, detailError, source, events, cursor, timelineLoading, evidence, evidenceOpen, evidenceError, evidenceLoading, dialog, form, saving, saveError, conflict, linkOptions, linkKeyword, scope, selectedChat, suggestion, state, busyAnalysis, init, loadList, select, loadTimeline, openEvidence, open, save, feedback, reanalyze, ignoreChat, searchLinks }
}
