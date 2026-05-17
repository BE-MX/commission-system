/**
 * 业务员案例库 — 业务逻辑 composable
 *
 * 集中:
 *   - 列表加载 + 筛选 + 排序 + 视图模式
 *   - 案例详情 (openDetail / getCaseDetail)
 *   - 表单 Dialog (manual create / edit / AI upload 三种入口)
 *   - AI 草稿 Dialog (loadDraft + confirmPublishDraft + corrections)
 *   - 点赞 + 删除
 *   - 权限判断 (canEdit: 本人或 admin)
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listCases, getCaseDetail, manualCreateCase, uploadCase, publishCase,
  updateCase, deleteCase, toggleCaseLike,
} from '@/api/insight'
import { useAuthStore } from '@/stores/auth'


export const TAGS = ['开发跟进', '谈判技巧', '定制流程', '物流处理', '纠纷解决', '竞品应对']

export const dimensionMap = {
  response_speed: { label: '响应时效' },
  talk_track_quality: { label: '话术专业度' },
  needs_alignment: { label: '需求匹配度' },
  deal_momentum: { label: '谈判推进力' },
  emotional_engagement: { label: '情感连接度' },
  compliance_risk: { label: '合规与风控' },
}

export function resultTagType(result) {
  if (result === '成交') return 'success'
  if (result === '未成交') return 'danger'
  if (result === '流失') return 'info'
  return 'warning'
}

export function correctionLabel(key) {
  const map = {
    title: '标题', scenario: '场景背景', what_was_done: '做了什么', result: '结果',
    customer_name: '客户名称', customer_country: '客户国家', customer_type: '客户类型',
    communication_channel: '沟通渠道', communication_period: '沟通时段',
    total_rounds: '总回合数', final_result: '最终结果',
    'dimension_scores.response_speed': '响应时效',
    'dimension_scores.talk_track_quality': '话术专业度',
    'dimension_scores.needs_alignment': '需求匹配度',
    'dimension_scores.deal_momentum': '谈判推进力',
    'dimension_scores.emotional_engagement': '情感连接度',
    'dimension_scores.compliance_risk': '合规与风控',
  }
  return map[key] || key
}

export function formatDateOnly(s) {
  if (!s) return ''
  return s.slice(0, 10)
}


export function useCaseLibrary() {
  const authStore = useAuthStore()

  const cases = ref([])
  const loading = ref(false)
  const search = ref('')
  const tagFilter = ref('all')
  const sortBy = ref('date')
  const viewMode = ref('grid')
  const localLikes = ref({})

  const detailVisible = ref(false)
  const currentCase = ref(null)

  // 表单 Dialog
  const formDialogVisible = ref(false)
  const formMode = ref('add') // 'add' | 'edit'
  const addTab = ref('manual')
  const submitting = ref(false)

  const formData = reactive({
    title: '', customer_name: '', customer_country: '', customer_type: '',
    communication_channel: '', communication_period: '', total_rounds: null,
    final_result: '', background_check_status: '',
    scenario: '', what_was_done: '', result: '',
    tags: [], share_person: '', share_date: '',
  })

  const aiText = ref('')
  const aiSharePerson = ref('')
  const aiShareDate = ref('')
  const aiFile = ref(null)

  // AI 草稿
  const draftDialogVisible = ref(false)
  const draftCase = ref(null)
  const draftTagsArr = ref([])
  const draftCorrections = reactive({})
  const publishing = ref(false)

  const submitButtonText = computed(() => {
    if (addTab.value === 'manual') return '发布'
    return 'AI 整理'
  })

  function reload() {
    loading.value = true
    const params = { page: 1, page_size: 60, sort: sortBy.value }
    if (search.value) params.q = search.value
    if (tagFilter.value !== 'all') params.tag = tagFilter.value
    listCases(params).then((res) => {
      cases.value = res.data.items || []
    }).finally(() => {
      loading.value = false
    })
  }

  async function openDetail(c) {
    detailVisible.value = true
    try {
      const res = await getCaseDetail(c.id)
      currentCase.value = res.data
    } catch (e) {
      currentCase.value = c
    }
  }

  function canEdit(c) {
    return c && (c.is_owner || authStore.hasPermission('insight:admin'))
  }

  function openAddDialog() {
    formMode.value = 'add'
    formDialogVisible.value = true
    addTab.value = 'manual'
    resetForm()
    aiText.value = ''
    aiSharePerson.value = ''
    aiShareDate.value = ''
    aiFile.value = null
  }

  function resetForm() {
    Object.assign(formData, {
      title: '', customer_name: '', customer_country: '', customer_type: '',
      communication_channel: '', communication_period: '', total_rounds: null,
      final_result: '', background_check_status: '',
      scenario: '', what_was_done: '', result: '',
      tags: [], share_person: '', share_date: '',
    })
  }

  function openEdit(c) {
    formMode.value = 'edit'
    formDialogVisible.value = true
    Object.assign(formData, {
      title: c.title || '',
      customer_name: c.customer_name || '',
      customer_country: c.customer_country || '',
      customer_type: c.customer_type || '',
      communication_channel: c.communication_channel || '',
      communication_period: c.communication_period || '',
      total_rounds: c.total_rounds || null,
      final_result: c.final_result || '',
      background_check_status: c.background_check_status || '',
      scenario: c.scenario || '',
      what_was_done: c.what_was_done || '',
      result: c.result || '',
      tags: Array.isArray(c.tags) ? [...c.tags] : [],
      share_person: c.share_person || '',
      share_date: c.share_date || '',
    })
    formData._editId = c.id
  }

  function openEditFromDetail() {
    if (!currentCase.value) return
    detailVisible.value = false
    openEdit(currentCase.value)
  }

  function handleFileChange(file) {
    aiFile.value = file.raw
  }

  async function submitCase() {
    if (formMode.value === 'edit') {
      submitting.value = true
      try {
        const payload = { ...formData }
        delete payload._editId
        await updateCase(formData._editId, payload)
        ElMessage.success('案例已更新')
        formDialogVisible.value = false
        reload()
      } finally {
        submitting.value = false
      }
      return
    }

    if (addTab.value === 'manual') {
      submitting.value = true
      try {
        await manualCreateCase({ ...formData, share_date: formData.share_date || undefined })
        ElMessage.success('案例已发布')
        formDialogVisible.value = false
        reload()
      } finally {
        submitting.value = false
      }
    } else if (addTab.value === 'text') {
      if (!aiText.value || aiText.value.trim().length < 10) {
        ElMessage.warning('请粘贴至少 10 个字符的原始文本')
        return
      }
      submitting.value = true
      try {
        const fd = new FormData()
        fd.append('source_type', 'text_paste')
        fd.append('text', aiText.value)
        if (aiSharePerson.value) fd.append('share_person', aiSharePerson.value)
        if (aiShareDate.value) fd.append('share_date', aiShareDate.value)
        const res = await uploadCase(fd)
        const caseId = res.data.case_id
        await loadDraft(caseId)
        formDialogVisible.value = false
      } finally {
        submitting.value = false
      }
    } else if (addTab.value === 'screenshot') {
      if (!aiFile.value) {
        ElMessage.warning('请先上传图片')
        return
      }
      submitting.value = true
      try {
        const fd = new FormData()
        fd.append('source_type', 'screenshot')
        fd.append('file', aiFile.value)
        if (aiSharePerson.value) fd.append('share_person', aiSharePerson.value)
        if (aiShareDate.value) fd.append('share_date', aiShareDate.value)
        const res = await uploadCase(fd)
        const caseId = res.data.case_id
        await loadDraft(caseId)
        formDialogVisible.value = false
      } finally {
        submitting.value = false
      }
    }
  }

  async function loadDraft(caseId) {
    const res = await getCaseDetail(caseId)
    const d = { ...res.data }
    if (!d.dimension_scores) {
      d.dimension_scores = {}
    }
    for (const key of Object.keys(dimensionMap)) {
      if (!d.dimension_scores[key]) {
        d.dimension_scores[key] = { score: null, comment: '' }
      }
    }
    draftCase.value = d
    draftTagsArr.value = Array.isArray(res.data.tags) ? [...res.data.tags] : []
    Object.keys(draftCorrections).forEach(k => delete draftCorrections[k])
    draftDialogVisible.value = true
  }

  async function confirmPublishDraft() {
    if (!draftCase.value) return
    publishing.value = true
    try {
      const corrections = {}
      for (const [k, v] of Object.entries(draftCorrections)) {
        if (v && String(v).trim()) corrections[k] = String(v).trim()
      }
      const payload = {
        title: draftCase.value.title,
        customer_name: draftCase.value.customer_name,
        customer_country: draftCase.value.customer_country,
        customer_type: draftCase.value.customer_type,
        communication_channel: draftCase.value.communication_channel,
        communication_period: draftCase.value.communication_period,
        total_rounds: draftCase.value.total_rounds,
        final_result: draftCase.value.final_result,
        background_check_status: draftCase.value.background_check_status,
        scenario: draftCase.value.scenario,
        what_was_done: draftCase.value.what_was_done,
        result: draftCase.value.result,
        tags: draftTagsArr.value,
      }
      if (Object.keys(corrections).length) {
        payload.user_corrections = corrections
      }
      await publishCase(draftCase.value.id, payload)
      ElMessage.success('已发布')
      draftDialogVisible.value = false
      reload()
    } finally {
      publishing.value = false
    }
  }

  async function toggleLike(c) {
    const liked = !!localLikes.value[c.id]
    const delta = liked ? -1 : 1
    try {
      const res = await toggleCaseLike(c.id, delta)
      localLikes.value[c.id] = !liked
      c.like_count = res.data.like_count
      if (currentCase.value && currentCase.value.id === c.id) {
        currentCase.value.like_count = res.data.like_count
      }
    } catch (e) {
      // ignore
    }
  }

  async function handleDelete(c) {
    await ElMessageBox.confirm('确认删除此案例?删除后不可恢复。', '请确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteCase(c.id)
    ElMessage.success('已删除')
    reload()
  }

  async function deleteCurrentCase() {
    if (!currentCase.value) return
    await handleDelete(currentCase.value)
    detailVisible.value = false
  }

  onMounted(reload)

  return {
    TAGS, dimensionMap,
    resultTagType, correctionLabel, formatDateOnly,
    // state
    cases, loading, search, tagFilter, sortBy, viewMode, localLikes,
    detailVisible, currentCase,
    formDialogVisible, formMode, addTab, submitting,
    formData,
    aiText, aiSharePerson, aiShareDate, aiFile,
    draftDialogVisible, draftCase, draftTagsArr, draftCorrections, publishing,
    submitButtonText,
    // methods
    reload, openDetail, canEdit,
    openAddDialog, openEdit, openEditFromDetail,
    handleFileChange, submitCase,
    loadDraft, confirmPublishDraft,
    toggleLike, handleDelete, deleteCurrentCase,
  }
}
