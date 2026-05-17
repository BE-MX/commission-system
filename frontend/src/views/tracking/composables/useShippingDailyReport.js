/**
 * 物流日报页 — 业务逻辑 composable
 *
 * 集中:
 *   - 日历 state (calendarYear/calendarMonth/selectedDate)
 *   - 日报获取 (fetchReport + parseStatsFromHtml — 从 HTML 内容反向提取统计)
 *   - 手动生成 (handleGenerate)
 *   - 月度统计 (fetchMonthStats)
 *   - watch selectedDate 自动刷新报告
 */
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getDailyReport, generateDailyReport, getTrackingStats, getShipmentList } from '@/api/tracking'


const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

function formatDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}


export function useShippingDailyReport() {
  const now = new Date()
  const calendarYear = ref(now.getFullYear())
  const calendarMonth = ref(now.getMonth())
  const selectedDate = ref(formatDate(now))
  const loading = ref(false)
  const generating = ref(false)
  const reportExists = ref(false)
  const reportHtml = ref('')
  const reportData = ref(null)
  const reportShipments = ref([])
  const reportStats = ref({ total: 0, transit: 0, delivered: 0, exception: 0 })
  const reportSummary = ref('')
  const monthTotal = ref('0')
  const monthRate = ref('0%')

  // ── 日历 ──────────────────────────────────────────────
  const calendarDays = computed(() => {
    const year = calendarYear.value
    const month = calendarMonth.value
    const firstDay = new Date(year, month, 1).getDay()
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const daysInPrevMonth = new Date(year, month, 0).getDate()
    const todayStr = formatDate(new Date())
    const days = []

    for (let i = firstDay - 1; i >= 0; i--) {
      const d = daysInPrevMonth - i
      const prevMonth = month === 0 ? 11 : month - 1
      const prevYear = month === 0 ? year - 1 : year
      const fd = `${prevYear}-${String(prevMonth + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
      days.push({ date: d, isCurrent: false, isToday: false, fullDate: fd, hasData: false })
    }
    for (let d = 1; d <= daysInMonth; d++) {
      const fd = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
      days.push({ date: d, isCurrent: true, isToday: fd === todayStr, fullDate: fd, hasData: false })
    }
    const remaining = 42 - days.length
    for (let d = 1; d <= remaining; d++) {
      const nextMonth = month === 11 ? 0 : month + 1
      const nextYear = month === 11 ? year + 1 : year
      const fd = `${nextYear}-${String(nextMonth + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
      days.push({ date: d, isCurrent: false, isToday: false, fullDate: fd, hasData: false })
    }
    return days
  })

  function goPrevMonth() {
    if (calendarMonth.value === 0) {
      calendarYear.value--
      calendarMonth.value = 11
    } else {
      calendarMonth.value--
    }
  }

  function goNextMonth() {
    if (calendarMonth.value === 11) {
      calendarYear.value++
      calendarMonth.value = 0
    } else {
      calendarMonth.value++
    }
  }

  function goToday() {
    const t = new Date()
    calendarYear.value = t.getFullYear()
    calendarMonth.value = t.getMonth()
    selectedDate.value = formatDate(t)
  }

  function selectDate(dateStr) {
    selectedDate.value = dateStr
  }

  // ── 数据加载 ──────────────────────────────────────────
  async function fetchReport() {
    loading.value = true
    try {
      const res = await getDailyReport(selectedDate.value)
      const data = res.data
      reportExists.value = data?.exists || false
      reportHtml.value = data?.html || ''
      reportData.value = data

      if (reportExists.value && reportHtml.value) {
        parseStatsFromHtml(reportHtml.value)
      } else {
        reportStats.value = { total: 0, transit: 0, delivered: 0, exception: 0 }
        reportShipments.value = []
        reportSummary.value = ''
      }
    } catch (e) {
      reportExists.value = false
      reportStats.value = { total: 0, transit: 0, delivered: 0, exception: 0 }
      reportShipments.value = []
    } finally {
      loading.value = false
    }
  }

  async function handleGenerate() {
    generating.value = true
    try {
      const res = await generateDailyReport(selectedDate.value)
      if (res.code === 200) {
        ElMessage.success('日报生成成功')
        await fetchReport()
      } else {
        ElMessage.warning(res.message || '生成失败')
      }
    } catch (e) {
      ElMessage.error('生成日报失败')
    } finally {
      generating.value = false
    }
  }

  // 反向解析日报 HTML 内的统计数据(后端模板生成,前端再读)
  function parseStatsFromHtml(html) {
    const totalMatch = html.match(/共 (\d+) 票运单/)
    const alertMatch = html.match(/需关注.*?— (\d+) 票/)
    const deliveringMatch = html.match(/派送中.*?— (\d+) 票/)
    const transitMatch = html.match(/运输中.*?— (\d+) 票/)

    const total = totalMatch ? parseInt(totalMatch[1]) : 0
    const alert = alertMatch ? parseInt(alertMatch[1]) : 0
    const delivering = deliveringMatch ? parseInt(deliveringMatch[1]) : 0
    const transit = transitMatch ? parseInt(transitMatch[1]) : 0

    reportStats.value = {
      total,
      transit: delivering + transit,
      delivered: total - alert - delivering - transit,
      exception: alert,
    }

    reportSummary.value = `${selectedDate.value} 共 ${total} 票运单，${delivering} 单派送中，${alert} 单需关注`

    // 从 HTML 表格中解析运单列表
    const shipments = []
    const rowRegex = /<tr>\s*<td><strong>([^<]+)<\/strong><\/td>\s*<td>([^<]*)<\/td>\s*<td>([^<]*)<\/td>\s*<td><span[^>]*class="status-tag status-([^"]+)"[^>]*>([^<]+)<\/span><\/td>\s*<td>([^<]*)<\/td>\s*<\/tr>/g
    let match
    while ((match = rowRegex.exec(html)) !== null) {
      shipments.push({
        waybill_no: match[1],
        carrier_name: match[2] || '-',
        receiver_country: match[3] || '-',
        unified_status: match[4],
        status_label: match[5],
        estimated_delivery_date: match[6] || '-',
      })
    }
    reportShipments.value = shipments
  }

  async function fetchMonthStats() {
    try {
      const [statsRes] = await Promise.all([
        getTrackingStats(),
        getShipmentList({ page: 1, page_size: 1 }),
      ])

      const stats = statsRes.data
      if (stats) {
        monthTotal.value = String(stats.total || 0)
        const delivered = stats.delivered || 0
        const total = stats.total || 1
        monthRate.value = `${((delivered / total) * 100).toFixed(1)}%`
      }
    } catch (e) {
      // ignore
    }
  }

  watch(selectedDate, () => {
    fetchReport()
  })

  watch([calendarYear, calendarMonth], () => {
    fetchMonthStats()
  })

  onMounted(() => {
    fetchReport()
    fetchMonthStats()
  })

  return {
    WEEKDAYS,
    calendarYear, calendarMonth, selectedDate,
    loading, generating,
    reportExists, reportHtml, reportData,
    reportShipments, reportStats, reportSummary,
    monthTotal, monthRate,
    calendarDays,
    goPrevMonth, goNextMonth, goToday, selectDate,
    fetchReport, handleGenerate,
  }
}
