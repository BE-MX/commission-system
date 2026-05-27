/**
 * 设计管理页 — 业务逻辑 composable
 *
 * 集中四个 tab (Pending/Scheduled/Completed/Designers) + 5+ Dialog 的 state + 方法:
 *   - 字典加载 (shoot_type / customer_level)
 *   - 各 tab fetch + 筛选
 *   - Edit dialogs: expect-date / remark / shoot-type / task-date / designer-inline
 *   - Confirm dialog (排期确认 + 选择设计师)
 *   - Task actions (start/complete/cancel)
 *   - Designer CRUD + 启用切换
 *   - Gantt reschedule callback
 *   - Excel import
 *
 * 主文件保留 template + style + composable destructure + 子组件 import。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getRequests, getTaskList, getDesigners, createDesigner, updateDesigner,
  actionRequest, rescheduleTask, importRequests,
  updateExpectDate, updateRequestRemark, updateRequestShootType, updateTaskShootType,
  triggerShootReminderScan,
} from '@/api/design'
import { getDictMap } from '@/utils/dict'
import { useTableSort } from '@/composables/useTableSort'


const PERIOD_LABELS = { am: '上午', pm: '下午' }
const TASK_STATUS_MAP = {
  scheduled: '已排期',
  in_progress: '进行中',
  completed: '已完成',
  cancelled: '已取消',
}
const TASK_STATUS_TAG = {
  scheduled: '',
  in_progress: '',
  completed: 'success',
  cancelled: 'info',
}

function periodLabel(p) { return PERIOD_LABELS[p] || '' }


export function useDesignManage() {
  // ── 排序 ──────────────────────────────────────────────
  const pendingSort = useTableSort()
  const scheduledSort = useTableSort()
  const completedSort = useTableSort()

  // ── 字典 ──────────────────────────────────────────────
  const shootTypeMap = ref({})
  const customerLevelMap = ref({})
  async function loadShootTypeDict() {
    shootTypeMap.value = await getDictMap('shoot_type')
    customerLevelMap.value = await getDictMap('customer_level')
  }
  function customerLevelLabel(code) {
    if (!code) return '-'
    return customerLevelMap.value[code] || code
  }
  function getDesignerName(id) {
    const d = designerData.value.find(d => d.id === id)
    return d ? d.name : id || '-'
  }

  // ── Tab / Detail drawer ───────────────────────────────
  const activeTab = ref('pending')
  const tabMaxHeight = ref(700)
  const detailVisible = ref(false)
  const detailRequestId = ref(null)

  function openDetail(requestId) {
    detailRequestId.value = requestId
    detailVisible.value = true
  }

  // ── Edit expect date (pending) ────────────────────────
  const editDateVisible = ref(false)
  const editDateSaving = ref(false)
  const editDateRow = ref(null)
  const editDateForm = reactive({ startDate: '', startPeriod: 'am', endDate: '', endPeriod: 'pm' })

  function openEditDateDialog(row) {
    editDateRow.value = row
    editDateForm.startDate = row.expect_start_date || ''
    editDateForm.startPeriod = row.expect_start_period || 'am'
    editDateForm.endDate = row.expect_end_date || ''
    editDateForm.endPeriod = row.expect_end_period || 'pm'
    editDateVisible.value = true
  }

  async function submitEditDate() {
    if (!editDateForm.startDate || !editDateForm.endDate) {
      ElMessage.warning('请选择日期')
      return
    }
    editDateSaving.value = true
    try {
      await updateExpectDate(editDateRow.value.id, {
        expect_start_date: editDateForm.startDate,
        expect_start_period: editDateForm.startPeriod,
        expect_end_date: editDateForm.endDate,
        expect_end_period: editDateForm.endPeriod,
      })
      ElMessage.success('期望日期已更新')
      editDateVisible.value = false
      fetchPending()
    } finally {
      editDateSaving.value = false
    }
  }

  // ── Edit remark (pending) ─────────────────────────────
  const remarkVisible = ref(false)
  const remarkSaving = ref(false)
  const remarkRow = ref(null)
  const remarkForm = reactive({ remark: '' })

  function openRemarkDialog(row) {
    remarkRow.value = row
    remarkForm.remark = row.remark || ''
    remarkVisible.value = true
  }

  async function submitRemark() {
    remarkSaving.value = true
    try {
      await updateRequestRemark(remarkRow.value.id, {
        remark: remarkForm.remark,
        operator_id: 1,
        operator_name: '管理员',
      })
      ElMessage.success('备注已更新')
      remarkVisible.value = false
      fetchPending()
    } finally {
      remarkSaving.value = false
    }
  }

  // ── Edit shoot type (both tabs) ───────────────────────
  const shootTypeVisible = ref(false)
  const shootTypeSaving = ref(false)
  const shootTypeRow = ref(null)
  const shootTypeTarget = ref('request')
  const shootTypeForm = reactive({ shoot_type: [] })

  function openShootTypeDialog(row, target) {
    shootTypeRow.value = row
    shootTypeTarget.value = target
    shootTypeForm.shoot_type = row.shoot_type ? row.shoot_type.split(',').filter(Boolean) : []
    shootTypeVisible.value = true
  }

  async function submitShootType() {
    if (!shootTypeForm.shoot_type || shootTypeForm.shoot_type.length === 0) {
      ElMessage.warning('请选择拍摄类型')
      return
    }
    shootTypeSaving.value = true
    try {
      const shootTypeStr = shootTypeForm.shoot_type.join(',')
      if (shootTypeTarget.value === 'request') {
        await updateRequestShootType(shootTypeRow.value.id, {
          shoot_type: shootTypeStr,
          operator_id: 1,
          operator_name: '管理员',
        })
        fetchPending()
      } else {
        await updateTaskShootType(shootTypeRow.value.id, {
          shoot_type: shootTypeStr,
          operator_id: 1,
          operator_name: '管理员',
        })
        fetchScheduled()
      }
      ElMessage.success('拍摄类型已更新')
      shootTypeVisible.value = false
    } finally {
      shootTypeSaving.value = false
    }
  }

  // ── Designer inline edit (scheduled tab) ──────────────
  const editingDesignerId = ref(null)
  const editingDesignerValue = ref(null)

  function startEditDesigner(row) {
    editingDesignerId.value = row.id
    editingDesignerValue.value = row.designer_id
  }

  function cancelEditDesigner() {
    editingDesignerId.value = null
    editingDesignerValue.value = null
  }

  async function saveDesigner(row) {
    if (editingDesignerValue.value === row.designer_id) {
      editingDesignerId.value = null
      return
    }
    try {
      await rescheduleTask(row.id, {
        designer_id: editingDesignerValue.value,
        plan_start_date: row.plan_start_date,
        plan_start_period: row.plan_start_period || 'am',
        plan_end_date: row.plan_end_date,
        plan_end_period: row.plan_end_period || 'pm',
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      ElMessage.success('设计师已更新')
      fetchScheduled()
    } catch { /* handled by interceptor */ }
    editingDesignerId.value = null
  }

  // ── Edit task date (scheduled tab) ────────────────────
  const editTaskDateVisible = ref(false)
  const editTaskDateSaving = ref(false)
  const editTaskDateRow = ref(null)
  const editTaskDateForm = reactive({
    startDate: '', startPeriod: 'am', endDate: '', endPeriod: 'pm', comment: '',
  })

  function openEditTaskDateDialog(row) {
    editTaskDateRow.value = row
    editTaskDateForm.startDate = row.plan_start_date || ''
    editTaskDateForm.startPeriod = row.plan_start_period || 'am'
    editTaskDateForm.endDate = row.plan_end_date || ''
    editTaskDateForm.endPeriod = row.plan_end_period || 'pm'
    editTaskDateForm.comment = ''
    editTaskDateVisible.value = true
  }

  async function submitEditTaskDate() {
    if (!editTaskDateForm.startDate || !editTaskDateForm.endDate) {
      ElMessage.warning('请选择日期')
      return
    }
    editTaskDateSaving.value = true
    try {
      await rescheduleTask(editTaskDateRow.value.id, {
        plan_start_date: editTaskDateForm.startDate,
        plan_start_period: editTaskDateForm.startPeriod,
        plan_end_date: editTaskDateForm.endDate,
        plan_end_period: editTaskDateForm.endPeriod,
        comment: editTaskDateForm.comment,
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      ElMessage.success('排期日期已更新')
      editTaskDateVisible.value = false
      fetchScheduled()
    } finally {
      editTaskDateSaving.value = false
    }
  }

  // ── Pending tab ───────────────────────────────────────
  const pendingTableRef = ref()
  const pendingData = ref([])
  const pendingLoading = ref(false)
  const pendingPage = ref(1)
  const pendingPageSize = ref(50)
  const pendingTotal = ref(0)
  const pendingFilters = reactive({ salesperson_name: '', shoot_type: '', expectDateRange: null })

  async function fetchPending() {
    pendingLoading.value = true
    try {
      const params = {
        status: 'pending_design',
        page: pendingPage.value,
        page_size: pendingPageSize.value,
        operator_id: 1,
        operator_role: 'design_staff',
        ...pendingSort.sortParams.value,
      }
      if (pendingFilters.salesperson_name) params.salesperson_name = pendingFilters.salesperson_name
      if (pendingFilters.shoot_type) params.shoot_type = pendingFilters.shoot_type
      if (pendingFilters.expectDateRange?.length === 2) {
        params.expect_start_date = pendingFilters.expectDateRange[0]
        params.expect_end_date = pendingFilters.expectDateRange[1]
      }
      const res = await getRequests(params)
      const data = res.data
      pendingData.value = data?.items || data || []
      pendingTotal.value = data?.total || 0
    } finally {
      pendingLoading.value = false
    }
  }

  async function handleScanShootReminders() {
    try {
      await ElMessageBox.confirm(
        '将立即扫描今日待确认和已排期任务并向相关人员推送钉钉拍摄提醒，是否继续？',
        '预约任务扫描',
        { type: 'info', confirmButtonText: '开始扫描', cancelButtonText: '取消' },
      )
    } catch { return }
    try {
      await triggerShootReminderScan()
      ElMessage.success('扫描已完成，相关提醒已推送')
    } catch { /* handled by interceptor */ }
  }

  // ── Scheduled tab ─────────────────────────────────────
  const scheduledTableRef = ref()
  const scheduledData = ref([])
  const scheduledLoading = ref(false)
  const scheduledPage = ref(1)
  const scheduledPageSize = ref(50)
  const scheduledTotal = ref(0)
  const scheduledFilters = reactive({ salesperson_name: '', shoot_type: '', designer_id: null, planDateRange: null })

  async function fetchScheduled() {
    scheduledLoading.value = true
    try {
      const params = {
        status: 'scheduled,in_progress',
        page: scheduledPage.value,
        page_size: scheduledPageSize.value,
        operator_id: 1,
        operator_role: 'design_staff',
        ...scheduledSort.sortParams.value,
      }
      if (scheduledFilters.salesperson_name) params.salesperson_name = scheduledFilters.salesperson_name
      if (scheduledFilters.shoot_type) params.shoot_type = scheduledFilters.shoot_type
      if (scheduledFilters.designer_id) params.designer_id = scheduledFilters.designer_id
      if (scheduledFilters.planDateRange?.length === 2) {
        params.plan_start_date = scheduledFilters.planDateRange[0]
        params.plan_end_date = scheduledFilters.planDateRange[1]
      }
      const res = await getTaskList(params)
      const data = res.data
      scheduledData.value = data?.items || data || []
      scheduledTotal.value = data?.total || 0
    } finally {
      scheduledLoading.value = false
    }
  }

  // ── Completed tab ─────────────────────────────────────
  const completedTableRef = ref()
  const completedData = ref([])
  const completedLoading = ref(false)
  const completedPage = ref(1)
  const completedPageSize = ref(50)
  const completedTotal = ref(0)
  const completedFilters = reactive({ salesperson_name: '', shoot_type: '', designer_id: null, planDateRange: null })

  async function fetchCompleted() {
    completedLoading.value = true
    try {
      const params = {
        status: 'completed',
        page: completedPage.value,
        page_size: completedPageSize.value,
        operator_id: 1,
        operator_role: 'design_staff',
        ...completedSort.sortParams.value,
      }
      if (completedFilters.salesperson_name) params.salesperson_name = completedFilters.salesperson_name
      if (completedFilters.shoot_type) params.shoot_type = completedFilters.shoot_type
      if (completedFilters.designer_id) params.designer_id = completedFilters.designer_id
      if (completedFilters.planDateRange?.length === 2) {
        params.plan_start_date = completedFilters.planDateRange[0]
        params.plan_end_date = completedFilters.planDateRange[1]
      }
      const res = await getTaskList(params)
      const data = res.data
      completedData.value = data?.items || data || []
      completedTotal.value = data?.total || 0
    } finally {
      completedLoading.value = false
    }
  }

  // ── Designers tab ─────────────────────────────────────
  const designerData = ref([])
  const designerLoading = ref(false)

  async function fetchDesigners() {
    designerLoading.value = true
    try {
      const res = await getDesigners()
      designerData.value = res.data || []
    } finally {
      designerLoading.value = false
    }
  }

  // ── Tab change ────────────────────────────────────────
  function onTabChange(tab) {
    if (tab === 'pending') fetchPending()
    else if (tab === 'scheduled') fetchScheduled()
    else if (tab === 'completed') fetchCompleted()
    else if (tab === 'designers') fetchDesigners()
  }

  // ── Designer create/edit ──────────────────────────────
  const designerDialogVisible = ref(false)
  const designerSaving = ref(false)
  const designerForm = reactive({
    id: null, name: '', email: '', dingtalk_id: '', is_active: true,
  })

  function openDesignerDialog(row) {
    if (row) {
      designerForm.id = row.id
      designerForm.name = row.name
      designerForm.email = row.email || ''
      designerForm.dingtalk_id = row.dingtalk_id || ''
      designerForm.is_active = row.is_active
    } else {
      designerForm.id = null
      designerForm.name = ''
      designerForm.email = ''
      designerForm.dingtalk_id = ''
      designerForm.is_active = true
    }
    designerDialogVisible.value = true
  }

  async function submitDesigner() {
    if (!designerForm.name.trim()) {
      ElMessage.warning('请输入设计师姓名')
      return
    }
    designerSaving.value = true
    try {
      const payload = {
        name: designerForm.name.trim(),
        email: designerForm.email || null,
        dingtalk_id: designerForm.dingtalk_id || null,
        is_active: designerForm.is_active,
      }
      if (designerForm.id) {
        await updateDesigner(designerForm.id, payload)
      } else {
        await createDesigner(payload)
      }
      ElMessage.success('保存成功')
      designerDialogVisible.value = false
      fetchDesigners()
    } finally {
      designerSaving.value = false
    }
  }

  async function toggleDesignerActive(row) {
    const action = row.is_active ? '停用' : '启用'
    try {
      await ElMessageBox.confirm(`确定${action}设计师「${row.name}」？`, '确认', { type: 'warning' })
    } catch { return }

    try {
      await updateDesigner(row.id, { is_active: !row.is_active })
      ElMessage.success(`${action}成功`)
      fetchDesigners()
    } catch { /* handled */ }
  }

  // ── Confirm scheduling dialog ─────────────────────────
  const confirmVisible = ref(false)
  const confirmRow = ref(null)
  const confirming = ref(false)
  const confirmForm = reactive({
    designer_id: null,
    startDate: '', startPeriod: 'am',
    endDate: '', endPeriod: 'pm',
    comment: '',
    sync_unavailable: true,
  })

  function openConfirmDialog(row) {
    confirmRow.value = row
    confirmForm.designer_id = row.preferred_designer_id || null
    confirmForm.startDate = row.expect_start_date || ''
    confirmForm.startPeriod = row.expect_start_period || 'am'
    confirmForm.endDate = row.expect_end_date || ''
    confirmForm.endPeriod = row.expect_end_period || 'pm'
    confirmForm.comment = ''
    confirmVisible.value = true
    if (!designerData.value.length) fetchDesigners()
  }

  async function submitConfirm() {
    if (!confirmForm.designer_id) {
      ElMessage.warning('请选择设计师')
      return
    }
    if (!confirmForm.startDate || !confirmForm.endDate) {
      ElMessage.warning('请选择排期日期')
      return
    }
    confirming.value = true
    try {
      await actionRequest(confirmRow.value.id, {
        action: 'confirm',
        designer_id: confirmForm.designer_id,
        plan_start_date: confirmForm.startDate,
        plan_start_period: confirmForm.startPeriod,
        plan_end_date: confirmForm.endDate,
        plan_end_period: confirmForm.endPeriod,
        comment: confirmForm.comment,
        sync_unavailable: confirmForm.sync_unavailable,
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      ElMessage.success('排期确认成功')
      confirmVisible.value = false
      fetchPending()
    } finally {
      confirming.value = false
    }
  }

  // ── Task actions ──────────────────────────────────────
  async function handleTaskAction(row, action) {
    const labels = { start: '开始执行', complete: '标记完成', cancel: '取消任务' }
    try {
      await ElMessageBox.confirm(`确定${labels[action]}？`, '确认', {
        type: action === 'cancel' ? 'warning' : 'info',
      })
    } catch { return }

    try {
      await actionRequest(row.request_id || row.id, {
        action,
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      ElMessage.success('操作成功')
      fetchScheduled()
    } catch { /* handled by interceptor */ }
  }

  // ── Gantt reschedule callback ─────────────────────────
  async function handleReschedule({ taskId, planStartDate, planStartPeriod, planEndDate, planEndPeriod, task }) {
    const pLabels = { am: '上午', pm: '下午' }
    try {
      await ElMessageBox.confirm(
        `确定将任务 "${task.task_name || task.task_no}" 的排期调整为 ${planStartDate} ${pLabels[planStartPeriod] || ''} ~ ${planEndDate} ${pLabels[planEndPeriod] || ''}？`,
        '调整排期',
        { type: 'warning' },
      )
    } catch { return }

    try {
      await rescheduleTask(taskId, {
        plan_start_date: planStartDate,
        plan_start_period: planStartPeriod || 'am',
        plan_end_date: planEndDate,
        plan_end_period: planEndPeriod || 'pm',
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'design_staff',
      })
      ElMessage.success('排期已调整')
      fetchScheduled()
    } catch { /* handled by interceptor */ }
  }

  // ── Layout util ───────────────────────────────────────
  function updateTabMaxHeight() {
    tabMaxHeight.value = Math.max(400, window.innerHeight - 200)
  }

  // ── Excel import ──────────────────────────────────────
  const uploadRef = ref()
  const importFile = ref(null)
  const importing = ref(false)
  const importResultVisible = ref(false)
  const importResult = ref(null)

  function onFileChange(file) {
    importFile.value = file.raw
  }

  async function submitImport() {
    if (!importFile.value) return
    importing.value = true
    try {
      const formData = new FormData()
      formData.append('file', importFile.value)
      const res = await importRequests(formData, {
        operator_id: 1,
        operator_name: '管理员',
        operator_role: 'salesperson',
      })
      importResult.value = res.data
      importResultVisible.value = true
      importFile.value = null
      if (uploadRef.value) uploadRef.value.clearFiles()
      if (activeTab.value === 'pending') fetchPending()
    } catch {
      // handled by interceptor
    } finally {
      importing.value = false
    }
  }

  // ── Lifecycle ─────────────────────────────────────────
  onMounted(() => {
    updateTabMaxHeight()
    window.addEventListener('resize', updateTabMaxHeight)
    loadShootTypeDict()
    fetchPending()
    fetchDesigners()
  })

  return {
    // 字典 / 工具
    shootTypeMap, customerLevelMap, customerLevelLabel, getDesignerName,
    periodLabel, TASK_STATUS_MAP, TASK_STATUS_TAG,
    // Tab + Detail
    activeTab, tabMaxHeight, detailVisible, detailRequestId, openDetail, onTabChange,
    // Edit dialogs
    editDateVisible, editDateSaving, editDateForm, openEditDateDialog, submitEditDate,
    remarkVisible, remarkSaving, remarkForm, openRemarkDialog, submitRemark,
    shootTypeVisible, shootTypeSaving, shootTypeTarget, shootTypeForm,
    openShootTypeDialog, submitShootType,
    editingDesignerId, editingDesignerValue,
    startEditDesigner, cancelEditDesigner, saveDesigner,
    editTaskDateVisible, editTaskDateSaving, editTaskDateForm,
    openEditTaskDateDialog, submitEditTaskDate,
    // Pending tab
    pendingTableRef, pendingData, pendingLoading,
    pendingPage, pendingPageSize, pendingTotal, pendingFilters,
    fetchPending, handleScanShootReminders, pendingSort,
    // Scheduled tab
    scheduledTableRef, scheduledData, scheduledLoading,
    scheduledPage, scheduledPageSize, scheduledTotal, scheduledFilters,
    fetchScheduled, scheduledSort,
    // Completed tab
    completedTableRef, completedData, completedLoading,
    completedPage, completedPageSize, completedTotal, completedFilters,
    fetchCompleted, completedSort,
    // Designers tab
    designerData, designerLoading, fetchDesigners,
    designerDialogVisible, designerSaving, designerForm,
    openDesignerDialog, submitDesigner, toggleDesignerActive,
    // Confirm dialog
    confirmVisible, confirmRow, confirming, confirmForm,
    openConfirmDialog, submitConfirm,
    // Task action / Gantt
    handleTaskAction, handleReschedule,
    // Import
    uploadRef, importFile, importing,
    importResultVisible, importResult,
    onFileChange, submitImport,
  }
}
