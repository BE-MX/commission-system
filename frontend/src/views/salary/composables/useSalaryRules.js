/**
 * 薪资规则配置页编排（职级表 / 规则参数 / 部门映射三块）。
 *
 * 改口径的正确姿势是新建生效日版本，不是原地改历史行——所以职级表编辑
 * 弹窗里 effective_from 可改，upsert 按 (scheme, grade_code, effective_from) 落。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  STD_SALARY_SCHEMES,
  listDeptMappings,
  listGrades,
  listParams,
  updateParam,
  upsertDeptMapping,
  upsertGrade,
} from '@/api/salary'

const EMPTY_GRADE = {
  scheme: 'resource', grade_code: '',
  base_salary: null, perf_full: null, std_salary: null,
  perf_target_monthly: null, new_sign_min: null, team_rate: null,
  effective_from: '', effective_to: null,
}

export function useSalaryRules() {
  const activeTab = ref('grades')
  const loading = ref(false)

  const grades = ref([])
  const params = ref([])
  const deptMappings = ref([])
  // 赛道选项来自接口（前端不写死枚举，见 api/salary.js）
  const schemeOptions = ref([])
  const schemeLabels = computed(() =>
    Object.fromEntries(schemeOptions.value.map(o => [o.value, o.label])),
  )

  const schemeFilter = ref('')
  const filteredGrades = computed(() =>
    schemeFilter.value ? grades.value.filter(g => g.scheme === schemeFilter.value) : grades.value,
  )

  // 管理岗赛道填 std_salary，其余填 base_salary——表格列跟着切，别让 HR 对着空列发呆
  function salaryOf(row) {
    return STD_SALARY_SCHEMES.includes(row.scheme) ? row.std_salary : row.base_salary
  }

  async function fetchAll() {
    loading.value = true
    try {
      // 规则页要看得到历史版本（档案页不要，那边下拉按 grade_code 做 key 会重）
      const [g, p, d] = await Promise.all([
        listGrades({ include_history: 1 }), listParams(), listDeptMappings(),
      ])
      grades.value = g.data?.items || []
      schemeOptions.value = (g.data?.schemes || []).map(s => ({ value: s.code, label: s.label }))
      params.value = p.data || []
      deptMappings.value = d.data || []
    } finally {
      loading.value = false
    }
  }

  // --- 职级表 ---
  const gradeDialog = ref(false)
  const gradeSaving = ref(false)
  const gradeFormRef = ref()
  const gradeForm = reactive({ ...EMPTY_GRADE })
  const gradeRules = {
    scheme: [{ required: true, message: '请选择赛道', trigger: 'change' }],
    grade_code: [{ required: true, message: '请输入职级编码', trigger: 'blur' }],
    effective_from: [{ required: true, message: '请选择生效日', trigger: 'change' }],
  }

  // 从已有行进来时记住原生效日：提交时如果没改，说明 HR 是想原地覆盖现行版本，
  // 而弹窗里写着「改口径请新建生效日版本」——两者矛盾，必须让人确认一次。
  const gradeOriginFrom = ref('')

  function openGrade(row) {
    Object.assign(gradeForm, EMPTY_GRADE)
    gradeOriginFrom.value = ''
    if (row) {
      Object.keys(EMPTY_GRADE).forEach(k => { gradeForm[k] = row[k] ?? EMPTY_GRADE[k] })
      gradeOriginFrom.value = row.effective_from || ''
    }
    gradeDialog.value = true
  }

  async function submitGrade() {
    const valid = await gradeFormRef.value?.validate().catch(() => false)
    if (!valid) return
    // 同 (赛道,职级,生效日) 是 upsert 键：生效日没变 = 直接改写现行底薪，
    // 影响的是这条职级下所有人的下个月工资，不能静默发生。
    if (gradeOriginFrom.value && gradeForm.effective_from === gradeOriginFrom.value) {
      const goOn = await ElMessageBox.confirm(
        `生效日未变，将直接覆盖 ${gradeForm.effective_from} 起生效的现行版本，`
        + '该职级下所有人的底薪口径立即改变。若只是调整新一轮标准，请把生效日改成新的日期。',
        '确认覆盖现行版本',
        { type: 'warning', confirmButtonText: '仍然覆盖', cancelButtonText: '返回修改' },
      ).catch(() => false)
      if (!goOn) return
    }
    gradeSaving.value = true
    try {
      await upsertGrade({ ...gradeForm })
      ElMessage.success('已保存')
      gradeDialog.value = false
      fetchAll()
    } catch {
      // 拦截器已提示
    } finally {
      gradeSaving.value = false
    }
  }

  // --- 规则参数（行内编辑，只改值与说明）---
  const editingParamId = ref(null)
  const paramDraft = reactive({ param_value: '', description: '' })

  function startEditParam(row) {
    editingParamId.value = row.id
    paramDraft.param_value = row.param_value
    paramDraft.description = row.description || ''
  }

  function cancelEditParam() {
    editingParamId.value = null
  }

  async function saveParam(row) {
    try {
      await updateParam(row.id, { ...paramDraft })
      ElMessage.success('已保存')
      editingParamId.value = null
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  // --- 部门映射 ---
  const deptDialog = ref(false)
  const deptSaving = ref(false)
  const deptFormRef = ref()
  const deptForm = reactive({ dept_detail: '', dept_group: '', sort_order: 0 })
  const deptRules = {
    dept_detail: [{ required: true, message: '请输入明细部门', trigger: 'blur' }],
    dept_group: [{ required: true, message: '请输入汇总大部门', trigger: 'blur' }],
  }

  function openDept(row) {
    Object.assign(deptForm, { dept_detail: '', dept_group: '', sort_order: 0 })
    if (row) Object.assign(deptForm, {
      dept_detail: row.dept_detail, dept_group: row.dept_group, sort_order: row.sort_order || 0,
    })
    deptDialog.value = true
  }

  async function submitDept() {
    const valid = await deptFormRef.value?.validate().catch(() => false)
    if (!valid) return
    deptSaving.value = true
    try {
      await upsertDeptMapping({ ...deptForm })
      ElMessage.success('已保存')
      deptDialog.value = false
      fetchAll()
    } catch {
      // 拦截器已提示
    } finally {
      deptSaving.value = false
    }
  }

  onMounted(fetchAll)

  return {
    activeTab, loading, fetchAll,
    grades, params, deptMappings,
    schemeFilter, filteredGrades, salaryOf, schemeOptions, schemeLabels,
    gradeDialog, gradeSaving, gradeFormRef, gradeForm, gradeRules, openGrade, submitGrade,
    editingParamId, paramDraft, startEditParam, cancelEditParam, saveParam,
    deptDialog, deptSaving, deptFormRef, deptForm, deptRules, openDept, submitDept,
  }
}
