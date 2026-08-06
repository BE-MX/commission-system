/**
 * 员工薪资档案页编排（宪法 12：state + 方法全在这里，.vue 留薄壳）。
 *
 * 两个口径与后端 service.py 一致，前端只做展示、不重算：
 * - dept_group / base_salary_effective 都由后端推导后下发
 * - 身份证/银行卡只有脱敏串，编辑时留空 = 不改，填了才覆盖
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createProfile,
  listDeptMappings,
  listGrades,
  listProfiles,
  updateProfile,
} from '@/api/salary'
import { useListPage } from '@/composables/useListPage'
import { useTableSort } from '@/composables/useTableSort'

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
  const { sortField, sortOrder, onSortChange, sortParams } = useTableSort('emp_no', 'asc')

  const page = useListPage(
    async params => {
      const res = await listProfiles({ ...params, ...sortParams.value })
      return res.data
    },
    { pageSize: 20, searchForm: { keyword: '', dept_detail: '', status: '' } },
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
  }

  function openCreate() {
    isEdit.value = false
    editId.value = null
    resetForm(null)
    dialogVisible.value = true
  }

  function openEdit(row) {
    isEdit.value = true
    editId.value = row.id
    resetForm(row)
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
    return data
  }

  async function submit() {
    const valid = await formRef.value?.validate().catch(() => false)
    if (!valid) return
    saving.value = true
    try {
      if (isEdit.value) {
        await updateProfile(editId.value, buildPayload())
        ElMessage.success('已保存')
      } else {
        await createProfile(buildPayload())
        ElMessage.success('已创建')
      }
      dialogVisible.value = false
      page.fetchList()
    } catch {
      // 409 唯一性冲突的中文提示由后端给，拦截器已弹
    } finally {
      saving.value = false
    }
  }

  function handleSortChange(evt) {
    onSortChange(evt)
    page.fetchList()
  }

  onMounted(loadOptions)

  return {
    ...page,
    sortField, sortOrder, handleSortChange,
    grades, deptOptions, gradeCodeOptions, schemeOptions, schemeLabels,
    dialogVisible, saving, isEdit, formRef, form, formRules,
    clearIdCard, clearBankCard,
    openCreate, openEdit, submit,
  }
}
