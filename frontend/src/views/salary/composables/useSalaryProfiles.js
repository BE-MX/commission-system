import { alertAction, msgError, msgSuccessText } from '@/utils/feedback'
import { beijingCalendarDate, currentBeijingDate } from '@/utils/datetime'
/**
 * 员工薪资档案页编排（宪法 12：state + 方法全在这里，.vue 留薄壳）。
 *
 * 两个口径与后端 service.py 一致，前端只做展示、不重算：
 * - dept_group / base_salary_effective 都由后端推导后下发
 * - 身份证/银行卡只有脱敏串，编辑时留空 = 不改，填了才覆盖
 */
import { computed, h, onMounted, reactive, ref, watch } from 'vue'

import {
  createProfile,
  getProfile,
  listDeptMappings,
  listGrades,
  listProfiles,
  updateProfile,
} from '@/api/salary'
import { useListPage } from '@/composables/useListPage'
import { useTableSort } from '@/composables/useTableSort'

// 决定底薪费率的三列，与后端 service.RATE_FIELDS 一致。改了它们就得说清
// 「从哪天起」——编辑日不是生效日，补录上月、预录下月的调薪都靠这个日期分月
const RATE_FIELDS = ['base_salary_override', 'grade_scheme', 'grade_code']

// 空串 / null / undefined 都是「没填」。定薪按数值比（接口回 '5000.00'，输入框给 5000）；
// 赛道/职级按字符串比，与后端一致——职级 '01' 和 '1' 是两个职级
function normRate(field, v) {
  if (v === '' || v === null || v === undefined) return null
  return field === 'base_salary_override' ? Number(v) : String(v)
}

// 生效日快捷项：调薪绝大多数从月初起，补录上月的从上月 1 日起
function monthStart(offset) {
  // 纯年月算术，不经过本地时区的 Date（宪法 23）
  const [y, m] = currentBeijingDate().split('-').map(Number)
  const idx = y * 12 + (m - 1) + offset
  const month = String((idx % 12) + 1).padStart(2, '0')
  return beijingCalendarDate(`${Math.floor(idx / 12)}-${month}-01`)
}
export const EFFECTIVE_DATE_SHORTCUTS = [
  { text: '本月 1 日', value: () => monthStart(0) },
  { text: '下月 1 日', value: () => monthStart(1) },
  { text: '上月 1 日', value: () => monthStart(-1) },
  { text: '今天', value: () => beijingCalendarDate() },
]

const EMPTY_FORM = {
  emp_no: '', name: '', status: 'active',
  hire_date: null, regular_date: null, leave_date: null,
  dept_detail: '', dept_group_override: '', position: '',
  grade_scheme: '', grade_code: '',
  base_salary_override: null, probation_salary: null, probation_note: '',
  guaranteed_salary: null, guaranteed_from: null, guaranteed_to: null,
  insurance_entity: '', payroll_included: 1, fund_included: 1,
  id_card: '', bank_card: '', bank_name: '',
  dingtalk_userid: '', mobile: '', remark: '',
}

export function useSalaryProfiles() {
  const { sortField, sortOrder, onSortChange } = useTableSort('emp_no', 'asc')

  const page = useListPage(
    async (params, { signal, isCurrent }) => {
      const res = await listProfiles(params, { signal, suppressToast: true })
      return res.data
    },
    { pageSize: 20, sortParams: { sort_field: 'emp_no', sort_order: 'asc' }, searchForm: { keyword: '', dept_detail: '', status: '' } },
  )

  // 职级下拉按赛道分组：选了赛道才给对应职级，避免把 P1 填进跟单岗
  const grades = ref([])
  const deptOptions = ref([])
  // 赛道选项由接口下发，前端不写死（见 api/salary.js 注释）
  const schemeOptions = ref([])
  const schemeLabels = computed(() =>
    Object.fromEntries(schemeOptions.value.map(o => [o.value, o.label])),
  )

  const gradeCodeOptions = computed(() => {
    const scheme = form.grade_scheme
    if (!scheme || scheme === 'none') return []
    return grades.value
      .filter(g => g.scheme === scheme)
      .map(g => ({
        value: g.grade_code,
        // 管理岗职级表填的是 std_salary，标签上直接把生效值给出来，省得 HR 再翻规则页
        label: `${g.grade_code}（${g.base_salary ?? g.std_salary ?? '-'} 元）`,
      }))
  })

  async function loadOptions() {
    try {
      // 不传 include_history：档案页只要当前生效版本，否则同一个 P1 会出现新旧两行
      const [g, d] = await Promise.all([listGrades(), listDeptMappings()])
      grades.value = g.data?.items || []
      schemeOptions.value = (g.data?.schemes || []).map(s => ({ value: s.code, label: s.label }))
      deptOptions.value = d.data || []
    } catch {
      // 拦截器已提示；下拉空不阻塞列表浏览
    }
  }

  // --- 弹窗表单 ---
  const dialogVisible = ref(false)
  const saving = ref(false)
  const isEdit = ref(false)
  const editId = ref(null)
  const formRef = ref()
  const form = reactive({ ...EMPTY_FORM })
  // 打开编辑时的费率三列原值，用来判断这次有没有动定薪/职级
  const originalRate = ref(null)
  const payChange = reactive({ kind: 'adjust', effectiveDate: null })
  const rateChanged = computed(() =>
    isEdit.value && originalRate.value !== null
    && RATE_FIELDS.some(f => normRate(f, form[f]) !== normRate(f, originalRate.value[f])),
  )

  const formRules = {
    emp_no: [{ required: true, message: '请输入工号', trigger: 'blur' }],
    name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  }

  function resetForm(row) {
    Object.assign(form, EMPTY_FORM)
    if (!row) return
    Object.keys(EMPTY_FORM).forEach(k => {
      if (row[k] !== undefined && row[k] !== null) form[k] = row[k]
    })
    // PII 不回填：接口只给脱敏串，回填进去会被当成新值原样加密
    form.id_card = ''
    form.bank_card = ''
    clearIdCard.value = false
    clearBankCard.value = false
    originalRate.value = Object.fromEntries(RATE_FIELDS.map(f => [f, row[f]]))
    payChange.kind = 'adjust'
    payChange.effectiveDate = null
  }

  function openCreate() {
    isEdit.value = false
    editId.value = null
    resetForm(null)
    dialogVisible.value = true
  }

  async function openEdit(row) {
    // 用最新档案开表单：列表可能是几分钟前的，别人刚调过薪的话，前端判断「没改定薪」
    // 而后端判断「改了」，用户会卡在一个看不见的必选项上
    let fresh = row
    try {
      fresh = (await getProfile(row.id)).data || row
    } catch {
      // 拦截器已提示；退回列表行，后端仍会兜底校验
    }
    isEdit.value = true
    editId.value = row.id
    resetForm(fresh)
    dialogVisible.value = true
  }

  // 显式清除开关：留空=不改，勾了才把该列清成 NULL。
  // 没有这个开关，HR 录错一张银行卡后就只能覆盖成另一张、永远清不掉。
  const clearIdCard = ref(false)
  const clearBankCard = ref(false)

  function buildPayload() {
    const data = { ...form }
    // 后端契约：字段缺席=不动，传空串=清除（service._apply_pii）
    if (!data.id_card) {
      if (clearIdCard.value) data.id_card = ''
      else delete data.id_card
    }
    if (!data.bank_card) {
      if (clearBankCard.value) data.bank_card = ''
      else delete data.bank_card
    }
    if (isEdit.value) delete data.emp_no // 工号是唯一键，改工号等于换人
    if (rateChanged.value) {
      data.pay_change_kind = payChange.kind
      if (payChange.kind === 'adjust') data.pay_effective_date = payChange.effectiveDate
    }
    return data
  }

  async function submit() {
    const valid = await formRef.value?.validate().catch(() => false)
    if (!valid) return
    if (rateChanged.value && payChange.kind === 'adjust' && !payChange.effectiveDate) {
      msgError('改了定薪或职级，请填写调薪生效日期')
      return
    }
    saving.value = true
    try {
      if (isEdit.value) {
        const res = await updateProfile(editId.value, buildPayload())
        const warnings = res.data?.pay_change_warnings || []
        // 改档案不会回写已算过的批次——不说清楚，HR 会以为改完就生效
        if (warnings.length) {
          // 纯文本 message 会把换行压成一行，逐条列出要用 VNode
          const message = h('div', [h('p', '已保存。以下批次不会自动跟上：'),
            h('ul', warnings.map(w => h('li', w)))])
          alertAction(message, '底薪已调整',
                      { type: 'warning', confirmButtonText: '知道了' }).catch(() => {})
        } else {
          msgSuccessText('已保存')
        }
      } else {
        await createProfile(buildPayload())
        msgSuccessText('已创建')
      }
      dialogVisible.value = false
      await (isEdit.value ? page.refreshUpdate() : page.refreshCreate())
    } catch {
      // 409 唯一性冲突的中文提示由后端给，拦截器已弹
    } finally {
      saving.value = false
    }
  }

  function handleSortChange(evt) {
    onSortChange(evt)
    return page.handleSortChange({ sort_field: sortField.value, sort_order: sortOrder.value })
  }

  watch(() => [page.appliedSort.value.sort_field, page.appliedSort.value.sort_order], ([field, order]) => { sortField.value = field; sortOrder.value = order }, { flush: 'sync' })

  onMounted(loadOptions)

  return {
    ...page,
    sortField, sortOrder, handleSortChange,
    grades, deptOptions, gradeCodeOptions, schemeOptions, schemeLabels,
    dialogVisible, saving, isEdit, formRef, form, formRules,
    clearIdCard, clearBankCard, rateChanged, payChange,
    openCreate, openEdit, submit,
  }
}
