import { computed, onMounted, ref, watch } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'

export function useFollowupGuide(form) {
  const templates = ref([]), template = ref(null), loading = ref(false)
  const quick = computed(() => ['未接通', '未回复'].includes(form.value.result_code))
  const keyFields = computed(() => (template.value?.record_fields || []).filter(field => field.emphasis === 'key'))
  const moreFields = computed(() => (template.value?.record_fields || []).filter(field => field.emphasis !== 'key'))

  function ensureAnswers() {
    if (!form.value.template_answers) form.value.template_answers = { fields: {}, questions: [] }
    form.value.template_answers.fields ||= {}
    form.value.template_answers.questions ||= []
  }

  async function loadTemplate(code, version) {
    if (!code) { template.value = null; return }
    loading.value = true
    try { template.value = await followupApi.template(code, version || undefined) }
    catch (e) { msgError(apiError(e, '场景模板加载失败'), e) }
    finally { loading.value = false }
  }

  async function loadTemplates() {
    try { templates.value = await followupApi.templates() }
    catch (e) { msgError(apiError(e, '场景列表加载失败'), e) }
  }

  function selectTemplate(code) {
    const selected = templates.value.find(row => row.code === code)
    form.value.template_code = selected?.code || null
    form.value.template_version = selected?.version || null
    form.value.template_answers = { fields: {}, questions: [] }
  }

  function useShortForm() {
    if (template.value?.short_form) form.value.raw_text = template.value.short_form
  }

  watch(() => form.value.result_code, () => {
    if (quick.value && !form.value.raw_text?.trim()) useShortForm()
  })
  watch([() => form.value.template_code, () => form.value.template_version], ([code, version], previous) => {
    if (code && (code !== previous?.[0] || version !== previous?.[1])) loadTemplate(code, version)
  })
  onMounted(async () => {
    ensureAnswers()
    await Promise.all([loadTemplates(), loadTemplate(form.value.template_code, form.value.template_version)])
    if (quick.value && !form.value.raw_text?.trim()) useShortForm()
  })
  return { templates, template, loading, quick, keyFields, moreFields, selectTemplate, useShortForm, ensureAnswers }
}
