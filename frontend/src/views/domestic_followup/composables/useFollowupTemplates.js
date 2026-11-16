import { computed, ref } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError, msgSuccessText } from '@/utils/feedback'

const blankField = () => ({ key: '', label: '', kind: 'text', emphasis: 'more', nature: 'business_fact', options: null, hint: '', show_when: null })
const clone = value => JSON.parse(JSON.stringify(value))
const DEFAULT_PARAMS = { prep_minutes: [3, 5], talk_minutes: [5, 8], wechat_sentences: [2, 4], recontact_workdays: [3, 5] }

export function useFollowupTemplates() {
  const templates = ref([])
  const selectedCode = ref('')
  const draft = ref(null)
  const loading = ref(false)
  const saving = ref(false)
  const historyVisible = ref(false)
  const historyRows = ref([])
  const historyPreview = ref(null)
  const fieldVisible = ref(false)
  const fieldGroup = ref('record_fields')
  const fieldIndex = ref(-1)
  const fieldForm = ref(blankField())
  const fieldOptionsText = ref('')
  const current = computed(() => templates.value.find(row => row.code === selectedCode.value) || null)

  async function load(preferCode) {
    loading.value = true
    try {
      templates.value = await followupApi.templates()
      const code = preferCode || selectedCode.value || templates.value[0]?.code
      if (code) await select(code)
    } catch (e) { msgError(apiError(e, '模板加载失败'), e) }
    finally { loading.value = false }
  }

  async function select(code) {
    selectedCode.value = code
    const row = clone(await followupApi.template(code))
    row.params = Object.fromEntries(Object.entries(DEFAULT_PARAMS).map(([key, fallback]) => [key, row.params?.[key] || fallback]))
    row.prep_fields ||= []
    row.record_fields ||= []
    row.avoid ||= []
    draft.value = row
  }

  function openField(group, index = -1) {
    fieldGroup.value = group
    fieldIndex.value = index
    fieldForm.value = index >= 0 ? clone(draft.value[group][index]) : blankField()
    fieldOptionsText.value = (fieldForm.value.options?.inline || []).join('，')
    fieldVisible.value = true
  }

  function saveField() {
    const field = { ...clone(fieldForm.value), label: fieldForm.value.label.trim(), key: fieldForm.value.key.trim() }
    if (!field.key || !field.label) return msgError('请填写字段名称和 key')
    if (!/^[a-z][a-z0-9_]*$/.test(field.key)) return msgError('key 请使用小写 snake_case')
    const options = fieldOptionsText.value.split(/[，,]/).map(v => v.trim()).filter(Boolean)
    field.options = options.length ? { inline: options } : null
    const rows = draft.value[fieldGroup.value]
    if (fieldIndex.value >= 0) rows.splice(fieldIndex.value, 1, field)
    else rows.push(field)
    fieldVisible.value = false
  }

  function removeField(group, index) { draft.value[group].splice(index, 1) }
  function addAvoid() { draft.value.avoid.push({ rule: '', keywords: [] }) }

  async function save() {
    saving.value = true
    try {
      const saved = await followupApi.saveTemplate(selectedCode.value, draft.value)
      draft.value = clone(saved)
      templates.value = templates.value.map(row => row.code === saved.code ? saved : row)
      msgSuccessText(`已保存为 v${saved.version}，新准备卡立即使用`)
    } catch (e) {
      msgError(apiError(e, '模板保存失败'), e)
      if (e?.response?.status === 409) await load(selectedCode.value)
    } finally { saving.value = false }
  }

  async function openHistory() {
    historyVisible.value = true
    historyPreview.value = null
    try { historyRows.value = await followupApi.templateVersions(selectedCode.value) }
    catch (e) { msgError(apiError(e, '版本历史加载失败'), e) }
  }

  async function previewVersion(row) {
    historyPreview.value = await followupApi.template(selectedCode.value, row.version)
  }

  return {
    templates, selectedCode, draft, current, loading, saving, historyVisible, historyRows, historyPreview,
    fieldVisible, fieldGroup, fieldIndex, fieldForm, fieldOptionsText,
    load, select, openField, saveField, removeField, addAvoid, save, openHistory, previewVersion,
  }
}
