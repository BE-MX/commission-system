import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { currentBeijingDate } from '@/utils/datetime'
import { msgError, msgSuccessText, msgWarning } from '@/utils/feedback'
import { draftToForm, emptyForm, formToPayload, imageFilesFromClipboard, newRequestId } from '../followupDraft'

const MAX_ATTACHMENTS = 9
const POLL_MS = 1500
const POLL_LIMIT = 60 // 90 秒

export function useFollowupComposer({ onSaved, onClosed } = {}) {
  const visible = ref(false)
  const step = ref('input') // input | parsing | review
  const saving = ref(false)
  const dicts = reactive({ domestic_followup_state_change: [], domestic_followup_category: [], domestic_followup_channel: [] })
  const form = ref(emptyForm(currentBeijingDate()))
  const attachments = ref([]) // { id, file_name, ocr_status, ocr_text, previewUrl, uploading }
  const customerOptions = ref([])
  const searching = ref(false)
  const openTasks = ref([])
  const openItems = ref([])
  const aiFailed = ref(false)
  let requestId = newRequestId()
  let pollTimer = null

  const uploading = computed(() => attachments.value.some(a => a.uploading))
  const canSubmit = computed(() => !saving.value && !uploading.value
    && (form.value.raw_text.trim() || attachments.value.length))

  async function loadDicts() {
    if (dicts.domestic_followup_channel.length) return
    try { Object.assign(dicts, await followupApi.dicts()) } catch (e) { msgError(apiError(e, '字典加载失败'), e) }
  }

  function reset(preset = {}) {
    stopPolling()
    attachments.value.forEach(a => a.previewUrl && URL.revokeObjectURL(a.previewUrl))
    attachments.value = []
    form.value = { ...emptyForm(currentBeijingDate()), ...preset }
    customerOptions.value = preset.customer ? [preset.customer] : []
    if (preset.customer) form.value.customer_id = preset.customer.id
    step.value = 'input'
    aiFailed.value = false
    requestId = newRequestId()
  }

  async function open(preset = {}) {
    reset(preset)
    visible.value = true
    await loadDicts()
    if (form.value.customer_id) await loadCustomerContext(form.value.customer_id)
  }

  async function addFiles(files) {
    const room = MAX_ATTACHMENTS - attachments.value.length
    if (files.length > room) msgWarning(`一次最多 ${MAX_ATTACHMENTS} 张截图，多出的已忽略`)
    for (const file of files.slice(0, Math.max(room, 0))) {
      const row = reactive({ id: null, file_name: file.name, previewUrl: URL.createObjectURL(file), uploading: true, ocr_status: 'pending' })
      attachments.value.push(row)
      try {
        Object.assign(row, await followupApi.upload(file), { uploading: false })
      } catch (e) {
        attachments.value = attachments.value.filter(a => a !== row)
        URL.revokeObjectURL(row.previewUrl)
        msgError(apiError(e, `${file.name} 上传失败`), e)
      }
    }
  }

  function onPaste(event) {
    const files = imageFilesFromClipboard(event)
    if (files.length) {
      // 剪贴板同时有文字（如从 Word 复制）时不拦截，文字照常进文本框
      if (!Array.from(event.clipboardData?.types || []).includes('text/plain')) event.preventDefault()
      addFiles(files)
    }
  }

  function removeAttachment(row) {
    if (row.previewUrl) URL.revokeObjectURL(row.previewUrl)
    attachments.value = attachments.value.filter(a => a !== row)
  }

  async function searchCustomers(q) {
    searching.value = true
    try { customerOptions.value = await followupApi.searchCustomers(q || '') } catch (e) { msgError(apiError(e, '客户搜索失败'), e) } finally { searching.value = false }
  }

  async function createProspect(name) {
    try {
      const customer = await followupApi.createProspect(name)
      customerOptions.value = [customer, ...customerOptions.value]
      form.value.customer_id = customer.id
      msgSuccessText(`已建潜在客户「${customer.shop_name}」`)
      await loadCustomerContext(customer.id)
    } catch (e) { msgError(apiError(e, '建档失败'), e) }
  }

  async function loadCustomerContext(customerId) {
    openTasks.value = []
    openItems.value = []
    form.value.closeTaskIds = []
    form.value.resolvedItems = []  // 换客户后旧客户的勾选会让后端报「不属于该客户」
    if (!customerId) return
    try {
      const [tasks, timeline] = await Promise.all([
        followupApi.tasks({ customer_id: customerId, scope: 'visible', due: 'all', page_size: 50 }),
        followupApi.timeline(customerId),
      ])
      openTasks.value = tasks.items.filter(t => ['plan', 'receipt'].includes(t.task_type))
      openItems.value = timeline.open_items
      // AI 认出的客户不在搜索结果里时，用时间线头部补一个选项，下拉框才显示店名而不是 ID
      const head = timeline.customer
      if (!customerOptions.value.some(o => o.id === head.id)) customerOptions.value = [head, ...customerOptions.value]
      // 从待办发起或当天到期的回访/约定，默认勾「本次一并完成」
      form.value.closeTaskIds = openTasks.value
        .filter(t => t.id === form.value.source_task_id || t.overdue_days > 0 || t.due_date <= form.value.followup_date)
        .map(t => t.id)
    } catch (e) { msgError(apiError(e, '客户待办加载失败'), e) }
  }

  const basePayload = () => ({
    request_id: requestId,
    raw_text: form.value.raw_text,
    attachment_ids: attachments.value.map(a => a.id).filter(Boolean),
    source: window.matchMedia?.('(max-width: 768px)').matches ? 'mobile' : 'web',
    source_task_id: form.value.source_task_id || null,
  })

  async function saveDirect() {
    if (!form.value.customer_id) return msgWarning('直接保存需要先选客户；不确定客户可以点「AI 整理」')
    saving.value = true
    try {
      await followupApi.directSave({
        ...basePayload(), ...formToPayload(form.value),
        // 输入步看不到待办列表：只关闭发起本次记录的那张，别悄悄关掉用户没看到的
        close_task_ids: form.value.source_task_id ? [form.value.source_task_id] : [],
        resolved_items: [],
      })
      finish('跟进已保存')
    } catch (e) { msgError(apiError(e, '保存失败'), e) } finally { saving.value = false }
  }

  async function startAi() {
    saving.value = true
    try {
      const draft = await followupApi.createDraft({
        ...basePayload(), customer_id: form.value.customer_id || null,
        followup_date: form.value.followup_date, channel: form.value.channel,
      })
      form.value.id = draft.id
      step.value = 'parsing'
      poll(draft.id, 0)
    } catch (e) { msgError(apiError(e, 'AI 整理启动失败'), e) } finally { saving.value = false }
  }

  function poll(id, count) {
    pollTimer = setTimeout(async () => {
      try {
        const draft = await followupApi.draft(id)
        if (draft.ai_status === 'running' && count < POLL_LIMIT) return poll(id, count + 1)
        // AI 失败后后端才开始逐张 OCR：等截图文字出来再停，降级时才有字可抄
        const ocrPending = draft.attachments.some(a => a.ocr_status === 'pending')
        if (draft.ai_status === 'failed' && ocrPending && count < POLL_LIMIT) return poll(id, count + 1)
        applyDraft(draft)
      } catch (e) {
        if (count < POLL_LIMIT) return poll(id, count + 1)
        msgError(apiError(e, '读取 AI 结果失败，已切换为手动填写'), e)
        step.value = 'review'
        aiFailed.value = true
      }
    }, POLL_MS)
  }

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = null
  }

  async function applyDraft(draft) {
    form.value = draftToForm(draft, currentBeijingDate())
    attachments.value = attachments.value.map(a => ({ ...a, ...(draft.attachments.find(d => d.id === a.id) || {}) }))
    aiFailed.value = draft.ai_status !== 'done'
    if (aiFailed.value) msgWarning(draft.ai_error || 'AI 整理未完成，请参考截图文字手动填写')
    step.value = 'review'
    await loadCustomerContext(form.value.customer_id)
  }

  async function confirm() {
    if (!form.value.customer_id) return msgWarning('请选择客户')
    saving.value = true
    try {
      await followupApi.confirmDraft(form.value.id, { version: form.value.version, ...formToPayload(form.value) })
      finish('跟进已确认')
    } catch (e) {
      if (e?.response?.status === 409) {
        // version 只在确认/作废时 +1，所以 409 只可能是草稿已确认或已作废；不覆盖用户手改的内容
        try {
          const latest = await followupApi.draft(form.value.id)
          if (latest.status !== 'draft') {
            msgWarning('这份草稿已经确认或作废了')
            close()
            onSaved?.()
            return
          }
          form.value.version = latest.version
          msgWarning('版本已刷新，请再点一次确认')
        } catch (err) { msgError(apiError(err, '刷新草稿失败'), err) }
      } else {
        msgError(apiError(e, '确认失败'), e)
      }
    } finally { saving.value = false }
  }

  async function discard() {
    if (form.value.id) {
      try { await followupApi.discardDraft(form.value.id) } catch (e) { msgError(apiError(e, '作废失败'), e) }
    }
    close()
  }

  function finish(message) {
    msgSuccessText(message)
    close()
    onSaved?.()
  }

  function close() {
    stopPolling()
    visible.value = false
    onClosed?.()  // 「稍后再看」后草稿条要出现
  }

  const addRow = (section, kind) => form.value[section].push(kind === 'content'
    ? { text: '', origin: 'user' }
    : { text: '', category: null, severity: '一般', origin: 'user', record_only: false })

  function toggleResolved(item, checked) {
    form.value.resolvedItems = checked
      ? [...form.value.resolvedItems, { item_id: item.id, resolution: '' }]
      : form.value.resolvedItems.filter(r => r.item_id !== item.id)
  }

  async function resume(draftId) {
    reset()
    visible.value = true
    await loadDicts()
    const draft = await followupApi.draft(draftId)
    form.value.id = draft.id
    // 恢复的草稿只有附件 id，没有本地预览：缩略图区显示文件名
    attachments.value = draft.attachments.map(a => ({ ...a, previewUrl: '', uploading: false }))
    if (draft.ai_status === 'running') {
      step.value = 'parsing'
      poll(draft.id, 0)
    } else {
      await applyDraft(draft)
    }
  }

  onBeforeUnmount(stopPolling)

  return {
    visible, step, saving, uploading, canSubmit, dicts, loadDicts, form, attachments, customerOptions, searching,
    openTasks, openItems, aiFailed,
    open, resume, close, addFiles, onPaste, removeAttachment, searchCustomers, createProspect, loadCustomerContext,
    saveDirect, startAi, confirm, discard, addRow, toggleResolved,
  }
}
