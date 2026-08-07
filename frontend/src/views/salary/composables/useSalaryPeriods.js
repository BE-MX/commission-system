/**
 * 工资批次列表编排（M2-f）。
 *
 * 这一页只做两件事：看哪些月份在跑、进到某个月的工作台。批次内的动作
 * （同步/导入/跃迁/锁定）全在详情页——列表页放动作按钮的话，HR 会在
 * 没看到异常清单的情况下点「下一步」，而异常清单正是该不该往下走的依据。
 */
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createPeriod, listPeriods } from '@/api/salary'
import { msgSuccess } from '@/utils/feedback'

export function useSalaryPeriods() {
  const router = useRouter()
  const loading = ref(false)
  const list = ref([])
  const statusFilter = ref('')

  async function fetchList() {
    loading.value = true
    try {
      const res = await listPeriods({ status: statusFilter.value || undefined })
      list.value = res.data || []
    } finally {
      loading.value = false
    }
  }

  const dialogVisible = ref(false)
  const saving = ref(false)
  const formRef = ref()
  const form = reactive({ year_month: '', workday_count: null, remark: '' })
  const formRules = {
    year_month: [
      { required: true, message: '请选择月份', trigger: 'change' },
      { pattern: /^\d{4}-(0[1-9]|1[0-2])$/, message: '格式应为 YYYY-MM', trigger: 'change' },
    ],
  }

  function openCreate() {
    // 默认上个月：工资在次月发，HR 打开这一页十有八九是要建上月的批次
    const d = new Date()
    d.setDate(1)
    d.setMonth(d.getMonth() - 1)
    form.year_month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    form.workday_count = null
    form.remark = ''
    dialogVisible.value = true
  }

  async function submit() {
    await formRef.value?.validate()
    saving.value = true
    try {
      const res = await createPeriod({
        year_month: form.year_month,
        // 留空 = 让后端按周一~五推算。推算值带 needs_review 标记，
        // 详情页会显示「待复核」角标提醒 HR 扣掉法定节假日。
        workday_count: form.workday_count || undefined,
        remark: form.remark || undefined,
      })
      dialogVisible.value = false
      msgSuccess('创建')
      // 建完直接进工作台：建批次不是目的，跑完这个月才是
      router.push(`/salary/periods/${res.data.id}`)
    } finally {
      saving.value = false
    }
  }

  function openPeriod(row) {
    router.push(`/salary/periods/${row.id}`)
  }

  onMounted(fetchList)

  return {
    loading, list, statusFilter, fetchList,
    dialogVisible, saving, formRef, form, formRules, openCreate, submit,
    openPeriod,
  }
}
