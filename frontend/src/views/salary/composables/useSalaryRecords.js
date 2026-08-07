/**
 * 工资明细（M3-f）——计算结果表格的数据拉取、整批计算、行内人工改数的编排。
 *
 * 工作台的三条规矩在这里同样适用，但有两个变形：
 *
 * 1. **并发护栏分两层，别混用。** 整批计算带的是批次的 status_version（409 =
 *    批次被人动过，全量刷新）；行内改数带的是行级 row_version（409 只是这一行
 *    被人动过，只刷新明细，批次状态可能根本没变）。
 *
 * 2. **行内编辑写空 = 清除覆盖，不是写 0。** el-input-number 清空给出 null，
 *    传上去就是「撤掉人工值、回落引擎值」；真要发 0 元奖金得在框里敲 0。
 *    这条语义在表格组件的 placeholder 里也写给了用户，两头不一致就会误清。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { calculatePeriod, editRecordManual, listRecords, money } from '@/api/salary'
import { useAuthStore } from '@/stores/auth'
import { msgSuccess } from '@/utils/feedback'

// 可算薪的三个状态：imported 首算；calculated / reviewing 是改完考勤、导入后重算
const CALCULABLE = ['imported', 'calculated', 'reviewing']
// 手动列只在算完之后有意义：没算过的行连引擎值都没有，人工覆盖无处附着
const EDITABLE = ['calculated', 'reviewing']

export function useSalaryRecords({ periodId, period, activeTab, refreshAll }) {
  const auth = useAuthStore()

  const records = ref({ items: [], total: 0, totals: null, truncated: false })
  const recordsKeyword = ref('')
  const recordsLoading = ref(false)
  const calculating = ref(false)

  const canCalculate = computed(() =>
    !!period.value?.writable && CALCULABLE.includes(period.value?.status))

  // v-permission 只能整块摘掉元素，管不到「只读但可见」，所以权限在这里并进
  // editable：没 salary:write 的人看到的是只读表，而不是被挖掉五列的表
  const recordsEditable = computed(() =>
    !!period.value?.writable && EDITABLE.includes(period.value?.status)
    && auth.hasPermission('salary:write'))

  // silent：行内保存成功后只要刷合计行，不想让整表转圈（HR 会逐行连改）
  async function fetchRecords({ silent = false } = {}) {
    if (!silent) recordsLoading.value = true
    try {
      const res = await listRecords(periodId, {
        keyword: recordsKeyword.value || undefined,
      })
      records.value = res.data || { items: [], total: 0, totals: null, truncated: false }
    } finally {
      if (!silent) recordsLoading.value = false
    }
  }

  // 明细不在 refreshAll 里（没算过的批次拉它也是空的），切到 tab 才拉；
  // 每次切过来都重拉——中间可能有人在别的页改了考勤又重算过
  watch(activeTab, name => {
    if (name === 'records') fetchRecords()
  }, { immediate: true })

  async function doCalculate() {
    calculating.value = true
    try {
      const res = await calculatePeriod(periodId, {
        expected_version: period.value?.status_version ?? 0,
      })
      await refreshAll()   // 状态、异常清单、时间线全变了
      await fetchRecords({ silent: true })
      showSummary(res.data.summary)
    } catch (err) {
      if (err?.response?.status === 409) {
        await refreshAll()
        ElMessage.warning('这个批次刚被其他人改过，页面已刷新，请确认后重试')
      }
      // 400（还有 blocking 异常 / 状态不对）的 detail 拦截器已原样弹出，不追加
    } finally {
      calculating.value = false
    }
  }

  // 报三类必须处理的（负数行、覆盖漂移、名单外残行）+ 一行带过的规则内调整。
  // 其余细节明细表里都能逐行看到，不重复念。
  function showSummary(s) {
    const lines = [`共计算 ${s.calculated} 人，实发合计 ${money(s.total_net)} 元。`]
    if (s.negative_net?.length) {
      lines.push(
        `${s.negative_net.length} 人实发为负：`
        + s.negative_net.slice(0, 10)
          .map(n => `${n.name}（${money(n.net_salary)}）`).join('、')
        + (s.negative_net.length > 10 ? ` 等 ${s.negative_net.length} 人` : '')
        + '。这几行已在明细表里标红，发钱前必须逐条处理。',
      )
    }
    if (s.override_changed?.length) {
      lines.push(
        `${s.override_changed.length} 项人工覆盖与新算出的引擎值不一致：`
        + s.override_changed.slice(0, 8)
          .map(o => `${o.name} ${o.field_label}（引擎 ${money(o.auto_new)}，人工 ${money(o.manual)}）`)
          .join('；')
        + (s.override_changed.length > 8 ? ` 等 ${s.override_changed.length} 项` : '')
        + '。重算不会冲掉人工值，请确认这些覆盖还有效。',
      )
    }
    if (s.stale_records?.length) {
      // stale 项只有 {employee_id, record_id} 没有姓名，报数 + 指路，不硬编名字
      lines.push(
        `${s.stale_records.length} 人已不在发薪名单却还有明细行，这批行不计入合计。`
        + '请到异常面板 / 明细表核对是离职未清还是名单漏人。',
      )
    }
    // 保底补差与月中折算是规则内调整（info 性质），一行带过让人知道发生过
    if (s.guaranteed_topup?.length || s.mid_month_weighted?.length) {
      lines.push(
        `另：${s.guaranteed_topup?.length ?? 0} 人触发保底补差、`
        + `${s.mid_month_weighted?.length ?? 0} 人按月中入离职折算，`
        + '属规则内调整，明细表可逐行查看。',
      )
    }
    ElMessageBox.alert(lines.join('\n'), '计算完成', {
      type: s.negative_net?.length ? 'warning' : 'success',
      confirmButtonText: '知道了',
    })
  }

  /**
   * 保存一个手动列。value 为 null = 清除覆盖（回落引擎值）。
   * 成功：后端回整行，原地替换，再静默刷一次拿新合计；409：该行被他人改过，
   * 只刷新明细（行级冲突，别动批次）。返回成功与否，供表格决定关不关输入框。
   */
  async function saveManual(row, field, value) {
    try {
      const res = await editRecordManual(periodId, row.employee_id, {
        [field]: value,
        expected_row_version: row.row_version,
      })
      const idx = records.value.items.findIndex(i => i.id === res.data.id)
      if (idx !== -1) records.value.items.splice(idx, 1, res.data)
      msgSuccess('保存')
      fetchRecords({ silent: true })   // 合计行变了；故意不 await，不挡下一格编辑
      return true
    } catch (err) {
      if (err?.response?.status === 409) {
        ElMessage.warning('该行已被他人修改，已刷新为最新数据')
        await fetchRecords({ silent: true })
      }
      return false
    }
  }

  return {
    records, recordsKeyword, recordsLoading, fetchRecords,
    canCalculate, calculating, doCalculate,
    recordsEditable, saveManual,
  }
}
