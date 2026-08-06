/**
 * 批次工作台编排（M2-f）——一个月工资从建批次到锁定的全过程都在这一页。
 *
 * ## 三条贯穿全页的规矩
 *
 * 1. **每次写操作都要带 status_version，写完立刻用响应里的新版本覆盖本地。**
 *    批次是整个模块的并发边界：HR 在导社保的同时，另一个人可能正在改工作日数。
 *    版本不符后端回 409，这里翻成「已被他人修改，请刷新」——**绝不自动重试**，
 *    自动重试就是拿旧数覆盖新数，而且悄无声息。
 *
 * 2. **能不能进下一步由后端的 ready_to_calculate 说了算**，前端不自己数
 *    blocking_count。两边各数一次，迟早数出不一样的结果，而不一样的那次
 *    就是多发钱的那次。
 *
 * 3. **下一步按钮打哪个端点由 next_steps[].endpoint 决定**，不在前端写
 *    「如果目标是 confirmed 就调 /confirm」。锁定的权限也不同（admin），
 *    这条特例后端知道并通过契约传出来了，前端复制一份就是等着它俩走偏。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  confirmPeriod,
  getPeriod,
  importPeriodFile,
  listAnomalies,
  listAttendance,
  listImportRows,
  listPeriodEvents,
  syncAttendance,
  transitionPeriod,
  unlockPeriod,
  updatePeriodWorkday,
  upsertAttendance,
} from '@/api/salary'
import { confirmDanger, msgSuccess } from '@/utils/feedback'

// 409 = 版本过期，是**可自愈**的（刷新重试就好）；其它错误要人改东西。
// 拦截器已经统一弹过错误了，这里只对 409 追加一次刷新，避免 HR 对着
// 一条本来没问题的操作反复改参数。
function isStale(err) {
  return err?.response?.status === 409
}

export function useSalaryWorkbench() {
  const route = useRoute()
  const periodId = Number(route.params.id)

  const loading = ref(false)
  const period = ref(null)
  const anomalies = ref(null)
  const events = ref([])
  const activeTab = ref('anomalies')

  const version = computed(() => period.value?.status_version ?? 0)
  const writable = computed(() => !!period.value?.writable)

  async function fetchPeriod() {
    const res = await getPeriod(periodId)
    period.value = res.data
  }

  async function fetchAnomalies() {
    const res = await listAnomalies(periodId)
    anomalies.value = res.data
  }

  async function fetchEvents() {
    const res = await listPeriodEvents(periodId)
    events.value = res.data || []
  }

  /** 任一写操作之后都要跑一遍：状态、异常清单、时间线全部会变。 */
  async function refreshAll() {
    loading.value = true
    try {
      await Promise.all([fetchPeriod(), fetchAnomalies(), fetchEvents(),
                         fetchAttendance(), fetchImports()])
    } finally {
      loading.value = false
    }
  }

  /**
   * 写操作统一包装：跑动作 → 全量刷新 → 成功提示；409 时刷新并给可自愈文案。
   * 不在这里 catch 其它错误——拦截器已经弹过，再吞一次会让调用方以为成功了。
   */
  async function guarded(action, label) {
    try {
      const res = await action()
      await refreshAll()
      msgSuccess(label)
      return res
    } catch (err) {
      if (isStale(err)) {
        await refreshAll()
        ElMessage.warning('这个批次刚被其他人改过，页面已刷新，请确认后重试')
      }
      throw err
    }
  }

  // --- 工作日数 ---

  const workdayEditing = ref(false)
  const workdayDraft = ref(null)

  function openWorkdayEdit() {
    workdayDraft.value = period.value?.workday_count ?? null
    workdayEditing.value = true
  }

  async function saveWorkday() {
    await guarded(
      () => updatePeriodWorkday(periodId, { workday_count: Number(workdayDraft.value) }),
      '保存',
    )
    workdayEditing.value = false
  }

  // --- 考勤 ---

  const attendance = ref({ items: [], total: 0, pending_manual_count: 0, unbound: [] })
  const attendanceKeyword = ref('')
  const attendanceOnlyPending = ref(false)
  const syncing = ref(false)
  const lastSync = ref(null)

  async function fetchAttendance() {
    const res = await listAttendance(periodId, {
      keyword: attendanceKeyword.value || undefined,
      only_pending: attendanceOnlyPending.value || undefined,
    })
    attendance.value = res.data || { items: [], total: 0, pending_manual_count: 0, unbound: [] }
  }

  async function doSync() {
    syncing.value = true
    try {
      const res = await guarded(
        () => syncAttendance(periodId, { expected_version: version.value }),
        '同步',
      )
      const s = res.data.summary
      lastSync.value = s
      // **判据是 missing_count，不是 source_count === synced。**
      // 后者拿钉钉自己回的条数当分母：档案撞号导致一个人被覆盖时，钉钉只回一条、
      // 落库也只有一条，两个数恰好相等，界面全绿而那个人考勤是空的。
      // missing = 发薪名单 LEFT JOIN 考勤，谁没落上行都在里面，撞号被吞的那个也在。
      if (s.missing_count > 0 || s.failed > 0) {
        const names = (s.missing || []).slice(0, 10)
          .map(m => m.name + (m.bound ? '' : '（未绑钉钉）')).join('、')
        ElMessageBox.alert(
          `发薪名单 ${s.payroll_headcount} 人，成功落库 ${s.synced} 人，`
          + `${s.missing_count} 人没有考勤记录：${names}`
          + (s.missing_count > 10 ? ` 等 ${s.missing_count} 人` : '') + '。\n'
          + '这些人直接算薪会被当成全勤（不扣缺勤、还发 100 元全勤奖）。'
          + '请补齐钉钉绑定后重新同步，或在考勤页手工录入。',
          '有人没有考勤记录',
          { type: 'warning', confirmButtonText: '知道了' },
        )
      } else if (s.dirty_values?.length) {
        // 脏值不是失败：数落进去了，只是某几列偏小。危险的是 31 天坏 11 天，
        // 聚合出 20.0——看起来完全正常，只是少了 11 天。
        ElMessageBox.alert(
          `${s.dirty_values.length} 人的钉钉考勤里有无法识别的值，对应列的月度合计会偏小：`
          + s.dirty_values.slice(0, 8).map(d => d.name).join('、')
          + '。请到考勤页核对这几人的迟到/旷工天数，必要时手工改正。',
          '钉钉数据有脏值',
          { type: 'warning', confirmButtonText: '知道了' },
        )
      }
    } finally {
      syncing.value = false
    }
  }

  // 人工录入：一次只提交**真正改过的字段**。整行 spread 会把未编辑的 null
  // 当成显式清空传上去，把刚录的病假抹掉（少扣缺勤 + 白发 100 元全勤奖）。
  const editRow = ref(null)
  const editDraft = ref({})
  const editSaving = ref(false)

  const MANUAL_FIELDS = [
    'personal_leave_hours', 'sick_leave_hours', 'annual_leave_days',
    'annual_leave_remain', 'late_count', 'early_leave_count',
    'miss_punch_count', 'absent_count',
  ]

  function openEditAttendance(row) {
    editRow.value = row
    editDraft.value = Object.fromEntries(MANUAL_FIELDS.map(f => [f, row[f] ?? null]))
    editSaving.value = false
  }

  async function saveAttendance() {
    const row = editRow.value
    if (!row) return
    // 逐字段比对原值，只把改动过的塞进 payload
    const patch = {}
    for (const f of MANUAL_FIELDS) {
      const before = row[f] ?? null
      const after = editDraft.value[f] ?? null
      // 数字与字符串混比（后端 Decimal 过 JSON 是 number，输入框给 string），
      // 统一转成字符串比对，避免 8 与 '8' 被当成改动而无谓地重写一遍
      if (String(before ?? '') !== String(after ?? '')) patch[f] = after
    }
    if (!Object.keys(patch).length) {
      editRow.value = null
      return
    }
    editSaving.value = true
    try {
      await guarded(
        () => upsertAttendance(periodId, row.employee_id,
                               { ...patch, expected_version: version.value }),
        '保存',
      )
      editRow.value = null
    } finally {
      editSaving.value = false
    }
  }

  // --- 导入 ---

  const imports = ref({ insurance: null, fund: null })
  const importing = ref('')

  async function fetchImports() {
    const [ins, fund] = await Promise.all([
      listImportRows(periodId, 'insurance', { limit: 500 }),
      listImportRows(periodId, 'fund', { limit: 500 }),
    ])
    imports.value = { insurance: ins.data, fund: fund.data }
  }

  async function doImport(kind, file) {
    importing.value = kind
    try {
      const res = await guarded(() => importPeriodFile(periodId, kind, file), '导入')
      const s = res.data.summary
      // 两个合计分开报：matched 的是真会进工资表的钱，全量的用来跟源表合计行对账。
      // 只看一个数，「文件对得上但工资表少扣了 8 个人」就看不出来。
      ElMessageBox.alert(
        `共 ${s.row_count} 行：已匹配 ${s.match_counts.matched}、`
        + `参保未发薪 ${s.match_counts.not_payroll}、未匹配 ${s.match_counts.unmatched}、`
        + `身份证撞号 ${s.match_counts.duplicate}。\n`
        + `进工资表的个人合计 ${s.personal_total_matched}，源表全量合计 ${s.personal_total_all}。`
        + '请拿全量合计跟 Excel 的合计行对一次。',
        `${s.kind_label}导入完成`,
        { type: 'info', confirmButtonText: '知道了' },
      )
    } finally {
      importing.value = ''
    }
  }

  // --- 状态跃迁 / 锁定 / 解锁 ---

  const stepping = ref('')

  async function doStep(step) {
    // 有 blocking 异常还要往下走，得让人明确知道自己在跳过什么
    if ((anomalies.value?.blocking_count ?? 0) > 0) {
      await ElMessageBox.confirm(
        `还有 ${anomalies.value.blocking_count} 条必须处理的异常没解决。`
        + '带着这些异常往下走，算出来的工资是错的（少扣的钱不会有人来投诉）。确定继续？',
        '异常未清',
        { type: 'warning', confirmButtonText: '仍然继续', cancelButtonText: '先去处理' },
      )
    }
    stepping.value = step.status
    try {
      if (step.endpoint === 'confirm') {
        await confirmDanger('锁定', period.value.year_month + ' 批次',
                            '锁定后全表只读，需要管理员填写原因才能解锁。')
        await guarded(() => confirmPeriod(periodId, { expected_version: version.value }), '锁定')
      } else {
        await guarded(
          () => transitionPeriod(periodId,
                                 { target: step.status, expected_version: version.value }),
          '推进',
        )
      }
    } finally {
      stepping.value = ''
    }
  }

  const unlockVisible = ref(false)
  const unlockReason = ref('')
  const unlocking = ref(false)

  async function doUnlock() {
    if (!unlockReason.value.trim()) {
      ElMessage.error('请填写解锁原因——前次导出会被标记作废，无理由无法审计')
      return
    }
    unlocking.value = true
    try {
      await guarded(
        () => unlockPeriod(periodId,
                           { reason: unlockReason.value.trim(), expected_version: version.value }),
        '解锁',
      )
      unlockVisible.value = false
      unlockReason.value = ''
    } finally {
      unlocking.value = false
    }
  }

  onMounted(refreshAll)

  return {
    periodId, loading, period, version, writable, activeTab, refreshAll,
    anomalies, events,
    workdayEditing, workdayDraft, openWorkdayEdit, saveWorkday,
    attendance, attendanceKeyword, attendanceOnlyPending, fetchAttendance,
    syncing, lastSync, doSync,
    editRow, editDraft, editSaving, openEditAttendance, saveAttendance,
    imports, importing, doImport,
    stepping, doStep,
    unlockVisible, unlockReason, unlocking, doUnlock,
  }
}
