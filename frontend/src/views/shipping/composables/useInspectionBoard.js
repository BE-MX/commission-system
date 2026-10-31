// 看板运行态：轮询、时钟、等比缩放、新签弹框队列与提示音。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getInspectionBoard } from '@/api/shipping'
import { currentBeijingDate, formatBeijingTime } from '@/utils/datetime'
import { detectNewDeals, sortPending, summarize } from './inspectionBoard'

const POLL_MS = 30000
const PAGE_MS = 10000
const ALERT_MS = 20000
const STALE_MS = 3 * 60000
const WEEK = '日一二三四五六'

// 纯日历换算：YYYY-MM-DD 按 UTC 解析只用于取星期，不涉及时区（Beijing calendar contract）
export const weekdayOf = day => WEEK[new Date(`${day}T00:00:00Z`).getUTCDay()]

function chime() {
  try {
    const Context = window.AudioContext || window.webkitAudioContext
    if (!Context) return
    const ac = new Context()
    ;[880, 1175, 1568].forEach((freq, i) => {
      const osc = ac.createOscillator(), gain = ac.createGain()
      osc.frequency.value = freq
      osc.connect(gain); gain.connect(ac.destination)
      const t = ac.currentTime + i * 0.18
      gain.gain.setValueAtTime(0.0001, t)
      gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.5)
      osc.start(t); osc.stop(t + 0.55)
    })
    setTimeout(() => ac.close(), 1500)
  } catch (err) {
    // 浏览器未授权自动播放时静默降级，弹框本身仍然出现
    console.warn('[inspection-board] chime blocked', err)
  }
}

const STORE_KEY = 'ark_qc_board_seen_deals'

function readKnown() {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    return raw ? new Set(JSON.parse(raw)) : null
  } catch (err) {
    console.warn('[inspection-board] seen deals unreadable', err)
    return null
  }
}

function saveKnown(set) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify([...set]))
  } catch (err) {
    console.warn('[inspection-board] seen deals not saved', err)
  }
}

export function useInspectionBoard() {
  const data = ref(null)
  const now = ref(Date.now())
  const lastOk = ref(0)
  const error = ref('')
  const page = ref(0)
  const scale = ref(1)
  const offset = ref({ x: 0, y: 0 })
  const alertQueue = ref([])
  const freshIds = ref(new Set())
  let known = readKnown()
  let knownDone = null
  let timers = []
  let alertTimer = null

  const pending = computed(() => sortPending(data.value?.pending || [], now.value))
  const summary = computed(() => summarize(data.value?.pending || [], now.value))
  const currentAlert = computed(() => alertQueue.value[0] || null)
  const stale = computed(() => !lastOk.value || now.value - lastOk.value > STALE_MS)
  const clock = computed(() => formatBeijingTime(new Date(now.value)))
  const today = computed(() => {
    const day = currentBeijingDate(new Date(now.value))
    const [y, m, d] = day.split('-')
    return { text: `${y}年${Number(m)}月${Number(d)}日`, week: `星期${weekdayOf(day)}` }
  })

  function scheduleAlertClose() {
    clearTimeout(alertTimer)
    if (currentAlert.value) alertTimer = setTimeout(dismissAlert, ALERT_MS)
  }

  function dismissAlert() {
    alertQueue.value = alertQueue.value.slice(1)
    scheduleAlertClose()
    if (currentAlert.value) chime()
  }

  async function load() {
    try {
      const res = await getInspectionBoard()
      const next = res.data
      const detected = detectNewDeals(next.pending || [], known)
      known = detected.known
      saveKnown(known)
      const doneIds = new Set((next.done || []).map(row => row.outbound_record_id))
      freshIds.value = knownDone ? new Set([...doneIds].filter(id => !knownDone.has(id))) : new Set()
      knownDone = doneIds
      data.value = next
      lastOk.value = Date.now()
      error.value = ''
      if (detected.alerts.length) {
        const wasIdle = !currentAlert.value
        alertQueue.value = [...alertQueue.value, ...detected.alerts]
        page.value = 0
        if (wasIdle) { chime(); scheduleAlertClose() }
      }
    } catch (err) {
      error.value = err?.response?.data?.detail || err?.message || '数据刷新失败'
      console.warn('[inspection-board] load failed', err)
    }
  }

  function fit() {
    const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080)
    scale.value = s
    offset.value = { x: (window.innerWidth - 1920 * s) / 2, y: (window.innerHeight - 1080 * s) / 2 }
  }

  onMounted(() => {
    fit()
    window.addEventListener('resize', fit)
    load()
    timers = [
      setInterval(() => { now.value = Date.now() }, 1000),
      setInterval(load, POLL_MS),
      setInterval(() => { page.value += 1 }, PAGE_MS),
    ]
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', fit)
    timers.forEach(clearInterval)
    clearTimeout(alertTimer)
  })

  return {
    data, now, pending, summary, page, scale, offset, error, stale, lastOk, clock, today,
    currentAlert, alertQueue, dismissAlert, freshIds, alertMs: ALERT_MS,
  }
}
