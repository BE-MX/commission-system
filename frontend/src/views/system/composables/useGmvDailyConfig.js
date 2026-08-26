import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  getGmvDailyConfig,
  previewGmvDailyReport,
  saveGmvDailyConfig,
  sendGmvDailyReport,
} from '@/api/dingtalk'


function clone(value) {
  return JSON.parse(JSON.stringify(value))
}


export function useGmvDailyConfig() {
  const loading = ref(false)
  const saving = ref(false)
  const sending = ref(false)
  const config = reactive({ teams: [], admin_recipient_user_ids: [], persisted: false })
  const options = reactive({ departments: [], captains: [], members: [], admin_recipients: [] })
  const memberSelections = reactive({})
  const newDepartmentId = ref(null)
  const reportDate = ref(null)
  const previewVisible = ref(false)
  const preview = ref(null)
  const activePreview = ref('admin')
  const lastSavedFingerprint = ref('')

  const usedDepartmentIds = computed(() => new Set(config.teams.map(team => team.department_id)))
  const availableDepartments = computed(() => options.departments.filter(
    department => !usedDepartmentIds.value.has(department.department_id),
  ))

  function buildPayload() {
    return {
      teams: config.teams.map(team => ({
        department_id: team.department_id,
        name: team.name,
        captain_okki_user_id: team.captain_okki_user_id,
        is_active: team.is_active,
        members: team.members.map(member => ({
          okki_user_id: member.okki_user_id,
          name: member.name,
          exclude_from_total: member.exclude_from_total,
          is_active: member.is_active,
        })),
      })),
      admin_recipient_user_ids: [...config.admin_recipient_user_ids],
    }
  }

  const hasUnsavedChanges = computed(() => (
    Boolean(lastSavedFingerprint.value)
    && lastSavedFingerprint.value !== JSON.stringify(buildPayload())
  ))

  function replaceReactive(target, source) {
    Object.keys(target).forEach(key => delete target[key])
    Object.assign(target, clone(source))
  }

  async function load() {
    loading.value = true
    try {
      const response = await getGmvDailyConfig()
      replaceReactive(config, response.data.config)
      replaceReactive(options, response.data.options)
      lastSavedFingerprint.value = JSON.stringify(buildPayload())
    } finally {
      loading.value = false
    }
  }

  function captainLabel(option) {
    const ding = option.has_dingtalk ? '已绑钉钉' : '未绑钉钉'
    return `${option.name} · ${option.okki_user_id} · ${ding}`
  }

  function adminLabel(option) {
    return `${option.name} · ${option.has_dingtalk ? '已绑钉钉' : '未绑钉钉'}`
  }

  function addTeam() {
    const department = options.departments.find(item => item.department_id === newDepartmentId.value)
    if (!department) return
    config.teams.push({
      department_id: department.department_id,
      name: department.name,
      captain_okki_user_id: '',
      is_active: true,
      members: [],
    })
    newDepartmentId.value = null
  }

  async function removeTeam(team) {
    await ElMessageBox.confirm(`确认移除队伍“${team.name}”的日报配置？`, '移除队伍', { type: 'warning' })
    const index = config.teams.indexOf(team)
    if (index >= 0) config.teams.splice(index, 1)
  }

  function availableMembers(team) {
    const used = new Set(config.teams.flatMap(item => item.members.map(member => member.okki_user_id)))
    return options.members.filter(member => !used.has(member.okki_user_id)
      || team.members.some(current => current.okki_user_id === member.okki_user_id))
  }

  function addMember(team) {
    const userId = memberSelections[team.department_id]
    const option = options.members.find(item => item.okki_user_id === userId)
    if (!option || team.members.some(member => member.okki_user_id === userId)) return
    team.members.push({
      okki_user_id: option.okki_user_id,
      name: option.name,
      exclude_from_total: false,
      is_active: true,
    })
    memberSelections[team.department_id] = null
  }

  function removeMember(team, member) {
    const index = team.members.indexOf(member)
    if (index >= 0) team.members.splice(index, 1)
  }

  function validate() {
    if (!config.teams.length) return '至少保留一个队伍'
    if (!config.admin_recipient_user_ids.length) return '请至少选择一名管理员日报接收人'
    for (const team of config.teams) {
      if (!team.captain_okki_user_id) return `请为“${team.name}”选择队长`
      if (!team.members.length) return `“${team.name}”尚未配置成员`
    }
    return ''
  }

  async function save() {
    const error = validate()
    if (error) {
      ElMessage.warning(error)
      return
    }
    saving.value = true
    try {
      const response = await saveGmvDailyConfig(buildPayload())
      replaceReactive(config, response.data)
      lastSavedFingerprint.value = JSON.stringify(buildPayload())
      ElMessage.success(response.message || '日报配置已保存')
    } finally {
      saving.value = false
    }
  }

  async function showPreview() {
    if (hasUnsavedChanges.value) {
      ElMessage.warning('当前配置有未保存修改，请先保存后再预览')
      return
    }
    const response = await previewGmvDailyReport(reportDate.value)
    preview.value = response.data
    activePreview.value = 'admin'
    previewVisible.value = true
  }

  async function sendNow() {
    if (!config.persisted) {
      ElMessage.warning('请先核对名单、选择管理员接收人并保存配置')
      return
    }
    if (hasUnsavedChanges.value) {
      ElMessage.warning('当前配置有未保存修改，请先保存后再发送')
      return
    }
    const dateLabel = reportDate.value || '昨天'
    await ElMessageBox.confirm(
      `确认发送${dateLabel}的 GMV 日报？已成功发送的接收人会自动跳过。`,
      '发送钉钉日报',
      { type: 'warning', confirmButtonText: '确认发送' },
    )
    sending.value = true
    try {
      const response = await sendGmvDailyReport(reportDate.value)
      const deliveries = response.data.deliveries || []
      if (response.data.status === 'skipped') {
        ElMessage.warning('同一日期已有发送任务正在执行，本次未重复发送')
        return
      }
      const success = deliveries.filter(item => item.status === 'success').length
      const skipped = deliveries.filter(item => item.status === 'skipped').length
      const failed = deliveries.filter(item => item.status === 'failed').length
      const summary = `发送完成：成功 ${success}，已发送跳过 ${skipped}，失败 ${failed}`
      if (response.data.status === 'partial_failure' || failed) ElMessage.warning(summary)
      else ElMessage.success(summary)
    } finally {
      sending.value = false
    }
  }

  onMounted(load)

  return {
    activePreview,
    addMember,
    addTeam,
    adminLabel,
    availableDepartments,
    availableMembers,
    captainLabel,
    config,
    hasUnsavedChanges,
    load,
    loading,
    memberSelections,
    newDepartmentId,
    options,
    preview,
    previewVisible,
    removeMember,
    removeTeam,
    reportDate,
    save,
    saving,
    sendNow,
    sending,
    showPreview,
  }
}
