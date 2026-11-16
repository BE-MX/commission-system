import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError, msgSuccessText } from '@/utils/feedback'
import { newRequestId } from '../followupDraft'

export function usePrepCard({ onRecord } = {}) {
  const visible = ref(false), step = ref(1), loading = ref(false), saving = ref(false)
  const context = ref(null), customer = ref(null), prep = ref(null), requestId = ref('')
  const form = ref({}), historyVisible = ref(false)
  let generation = 0, saveTimer = null, pollTimer = null, lastSavedSnapshot = ''
  const template = computed(() => context.value?.templates.find(row => row.code === form.value.template_code) || null)
  const strategy = computed(() => prep.value?.strategy || null)
  const remaining = computed(() => prep.value?.remaining_generations ?? 5)

  function reset() {
    generation += 1
    clearTimeout(saveTimer)
    clearTimeout(pollTimer)
    prep.value = null
    context.value = null
    step.value = 1
    requestId.value = newRequestId()
    lastSavedSnapshot = ''
  }

  async function open(preset) {
    reset()
    customer.value = preset.customer
    visible.value = true
    loading.value = true
    const gen = generation
    try {
      const data = await followupApi.prepContext(preset.customer.id, preset.source_task_id)
      if (gen !== generation) return
      context.value = data
      form.value = {
        template_code: data.recommendation?.code || data.templates[0]?.code,
        goal: preset.goal || '', known_facts: data.carried_facts || [], toConfirmText: '',
        contact_reason: data.source_task?.title || '', reason_source: data.source_task ? 'last_followup' : null,
        reason_date: null, answers: {},
      }
    } catch (e) {
      msgError(apiError(e, '准备资料加载失败'), e)
      visible.value = false
    } finally { loading.value = false }
  }

  function payload() {
    return {
      customer_id: customer.value.id, template_code: form.value.template_code, goal: form.value.goal?.trim(),
      source_task_id: context.value?.source_task?.id || null, contact_reason: form.value.contact_reason || null,
      reason_source: form.value.reason_source || null, reason_date: form.value.reason_date || null,
      known_facts: (form.value.known_facts || []).filter(row => row.text?.trim()).slice(0, 8),
      to_confirm: (form.value.toConfirmText || '').split('\n').map(v => v.trim()).filter(Boolean).slice(0, 5),
      answers: form.value.answers || {},
    }
  }

  async function ensureSaved(silent = false) {
    if (saving.value || (silent && step.value >= 3)) return prep.value
    if (!form.value.goal?.trim()) {
      if (!silent) msgError('请先填写本次只解决的一件事')
      return null
    }
    const data = payload()
    const snapshot = JSON.stringify(data)
    if (prep.value && snapshot === lastSavedSnapshot) return prep.value
    saving.value = true
    try {
      if (!prep.value) prep.value = await followupApi.createPrep({ request_id: requestId.value, ...data })
      else {
        const { customer_id, source_task_id, ...changes } = data
        prep.value = await followupApi.updatePrep(prep.value.id, { version: prep.value.version, ...changes })
      }
      lastSavedSnapshot = snapshot
      return prep.value
    } catch (e) {
      if (!silent) msgError(apiError(e, '准备卡保存失败'), e)
      return null
    } finally { saving.value = false }
  }

  async function next() {
    if (step.value === 1) {
      if (await ensureSaved()) step.value = 2
    } else if (step.value === 2) {
      if (await ensureSaved()) await generate()
    } else {
      visible.value = false
      onRecord?.({ customer: customer.value, prep_id: prep.value.id, prep: prep.value })
    }
  }

  async function generate() {
    const saved = await ensureSaved()
    if (!saved || saved.remaining_generations <= 0 && saved.strategy_status !== 'running') return
    const gen = generation
    try {
      prep.value = await followupApi.generatePrepStrategy(saved.id)
      step.value = 3
      poll(saved.id, 0, gen)
    } catch (e) { msgError(apiError(e, '策略生成失败'), e) }
  }

  function poll(id, count, gen) {
    clearTimeout(pollTimer)
    pollTimer = setTimeout(async () => {
      if (gen !== generation) return
      try {
        const latest = await followupApi.prepStrategy(id)
        if (gen !== generation) return
        prep.value = latest
        if (latest.strategy_status === 'running' && count < 100) poll(id, count + 1, gen)
      } catch (e) {
        if (count < 10) poll(id, count + 1, gen)
        else msgError(apiError(e, '策略状态获取失败'), e)
      }
    }, 1200)
  }

  async function loadPrep(data) {
    generation += 1
    prep.value = data
    customer.value = { id: data.customer_id, shop_name: data.shop_name }
    form.value = {
      template_code: data.template_code, goal: data.goal, known_facts: data.known_facts || [],
      toConfirmText: (data.to_confirm || []).join('\n'), contact_reason: data.contact_reason,
      reason_source: data.reason_source, reason_date: data.reason_date, answers: data.answers || {},
    }
    requestId.value = newRequestId()
    step.value = 2
    try { context.value = await followupApi.prepContext(data.customer_id) }
    catch (e) { msgError(apiError(e, '场景信息加载失败'), e) }
    lastSavedSnapshot = JSON.stringify(payload())
    historyVisible.value = false
    visible.value = true
  }

  function addFact() {
    form.value.known_facts.push({ text: '', source_kind: 'salesperson_observation', source_ref: '', observed_at: context.value?.today || null })
  }

  async function feedback(value) {
    try {
      prep.value = await followupApi.prepFeedback(prep.value.id, value)
      msgSuccessText('反馈已记录')
    } catch (e) { msgError(apiError(e, '反馈保存失败'), e) }
  }

  watch(form, () => {
    if (!prep.value || step.value >= 3 || prep.value.readonly) return
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => ensureSaved(true), 800)
  }, { deep: true })
  onBeforeUnmount(() => { reset() })

  return {
    visible, step, loading, saving, context, customer, prep, form, template, strategy, remaining, historyVisible,
    open, next, generate, loadPrep, addFact, feedback,
    back: () => { if (step.value > 1) step.value -= 1 },
    close: () => { visible.value = false; generation += 1 },
  }
}
