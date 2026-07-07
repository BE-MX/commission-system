/**
 * 展会试戴 kiosk 流程状态机（双入口）。
 *
 * tryon：attract → register → capture → analyzing → matching(可选发色) → result ⇄ sales
 * scene：attract → register → capture → scene(选场景) → result ⇄ sales
 * 轮询 GET /sessions/{id} 驱动 analyzing/generating 的状态推进；
 * 60 秒无操作自动回 attract 并清空上一位客户状态（隐私 + 交接下一位）；
 * 例外：result 展示页不自动清场，仅「返回主页」手动触发（见 NO_IDLE_STEPS）。
 */
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import {
  createSession, generateResults, getHairColors, getScenes, getSession,
  registerCustomer, setReaction, submitFeedback,
} from '@/api/expo'

const POLL_MS = 2000
const IDLE_MS = 60000
// 不判 idle 的步骤：analyzing=客户在等待不算离开；result=展示页只允许手动返回主页，
// 不自动跳回（用户指令 2026-07-07——客户慢慢看图/扫码，不能被清场）
const NO_IDLE_STEPS = ['analyzing', 'result']

export function useTryOnFlow() {
  const step = ref('attract')
  const mode = ref('tryon')          // tryon=AI 换发试戴 / scene=佩戴实拍场景大片
  const customerId = ref(null)
  const sessionId = ref(null)
  const session = ref(null)          // GET /sessions/{id} 的最新载荷
  const generating = ref(false)
  const errorText = ref('')
  const selectedWigId = ref(null)    // 单选：从推荐中挑一款生成
  const matchPage = ref(0)           // 候选页：0=Top3 / 1=第4~6名
  const hairColors = ref([])         // 发色选择项（色板库）
  const selectedColorId = ref(null)  // null = 保持发型原色
  const scenes = ref([])             // 场景大片可选场景
  const selectedSceneKeys = ref([])
  const tryonScenes = ref([])        // tryon 生成场景选项（居家/办公/聚会）
  const selectedTryonScene = ref(null) // null = 保持原照片背景

  const regForm = reactive({
    name: '', phone: '', wechat_id: '',
    primary_need: 'volume', style_pref: '知性优雅',
    consent: false,
    expo_code: '2026-08-expo',
  })

  let pollTimer = null
  let idleTimer = null

  const analysis = computed(() => session.value?.analysis || null)
  const allMatches = computed(() => session.value?.matches || []) // 后端给前 6 名
  const matches = computed(() => allMatches.value.slice(matchPage.value * 3, matchPage.value * 3 + 3))
  const canSwapMatches = computed(() => allMatches.value.length > 3)
  const results = computed(() => session.value?.results || [])
  const doneResults = computed(() => results.value.filter(r => r.status === 'done'))

  // ── 空闲回归 ──
  function touch() {
    if (idleTimer) clearTimeout(idleTimer)
    if (step.value === 'attract') return
    if (NO_IDLE_STEPS.includes(step.value) || generating.value) return
    idleTimer = setTimeout(resetAll, IDLE_MS)
  }

  function resetAll() {
    stopPolling()
    if (idleTimer) clearTimeout(idleTimer)
    step.value = 'attract'
    mode.value = 'tryon'
    customerId.value = null
    sessionId.value = null
    session.value = null
    generating.value = false
    errorText.value = ''
    selectedWigId.value = null
    matchPage.value = 0
    selectedColorId.value = null
    selectedSceneKeys.value = []
    selectedTryonScene.value = null
    Object.assign(regForm, {
      name: '', phone: '', wechat_id: '',
      primary_need: 'volume', style_pref: '知性优雅', consent: false,
    })
  }

  // ── 流程动作 ──
  function start(nextMode = 'tryon') {
    mode.value = nextMode
    step.value = 'register'
    touch()
  }

  async function submitRegister() {
    errorText.value = ''
    if (!regForm.name.trim() || !regForm.phone.trim()) {
      errorText.value = '请填写称呼和手机号'
      return false
    }
    if (!regForm.consent) {
      errorText.value = '需勾选同意拍照存储'
      return false
    }
    const res = await registerCustomer({ ...regForm })
    customerId.value = res.data.customer_id
    step.value = 'capture'
    touch()
    return true
  }

  async function submitPhoto(blob) {
    errorText.value = ''
    const res = await createSession(customerId.value, blob, mode.value)
    sessionId.value = res.data.session_id
    if (mode.value === 'scene') {
      step.value = 'scene'
      loadScenes()
      touch()
      return
    }
    step.value = 'analyzing'
    // 清掉 capture 屏残留的 idle 定时器：全局 @pointerdown 先于按钮 click 触发 touch()，
    // 彼时忙态还没置位会武装一个 60s 定时器，长分析/生成中途到点就整页跳回首页
    touch()
    startPolling()
  }

  // ── 发色 / 场景选项（弱网失败静默降级：不选也能走通） ──
  async function loadHairColors() {
    if (hairColors.value.length) return
    try {
      const res = await getHairColors()
      hairColors.value = res.data || []
    } catch (e) { /* 无色板数据时只保留“原色” */ }
  }

  async function loadTryonScenes() {
    if (tryonScenes.value.length) return
    try {
      const res = await getScenes({ mode: 'tryon' })
      tryonScenes.value = res.data || []
    } catch (e) { /* 加载失败只保留"原景"，不阻断 */ }
  }

  async function loadScenes() {
    if (scenes.value.length) return
    try {
      const res = await getScenes()
      scenes.value = res.data || []
      selectedSceneKeys.value = scenes.value.slice(0, 3).map(s => s.key)
    } catch (e) {
      errorText.value = '场景加载失败，请呼叫顾问'
    }
  }

  function toggleScene(key) {
    const idx = selectedSceneKeys.value.indexOf(key)
    if (idx >= 0) selectedSceneKeys.value.splice(idx, 1)
    else if (selectedSceneKeys.value.length < 3) selectedSceneKeys.value.push(key)
    touch()
  }

  function startPolling() {
    stopPolling()
    pollTimer = setInterval(poll, POLL_MS)
    poll()
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
  }

  async function poll() {
    if (!sessionId.value) return
    try {
      const res = await getSession(sessionId.value)
      session.value = res.data
      const status = res.data.status

      if (step.value === 'analyzing' && status === 'analyzed') {
        step.value = 'matching'
        matchPage.value = 0
        // 不让用户思考：默认选中匹配度第一的款，轻触可换
        selectedWigId.value = (res.data.matches || [])[0]?.wig_id || null
        loadHairColors()
        touch()
      }
      if (status === 'failed') {
        errorText.value = '现场网络拥堵，请稍后重试或呼叫顾问'
        stopPolling()
        generating.value = false
        // analyzing 属 BUSY_STEPS 不挂 idle 定时器，停在原地会永久卡屏——退回拍摄可重拍
        if (step.value === 'analyzing') step.value = 'capture'
        touch()
      }
      if (status === 'done') {
        generating.value = false
        stopPolling()
        // 整批效果图全部失败：给出明确反馈，ResultScreen 等待区会露出重试/呼叫顾问
        const anyDone = (res.data.results || []).some(r => r.status === 'done')
        if (!anyDone) errorText.value = '本次生成未成功，可重试或呼叫顾问'
        touch()
      }
    } catch (e) {
      // 轮询单次失败不打断流程，下一轮继续
    }
  }

  // 单选生成：只合成用户选中的那一款（发色可选）
  async function generate() {
    if (generating.value || !selectedWigId.value) return
    errorText.value = ''
    generating.value = true
    step.value = 'result'
    touch() // 忙态已置位：只清残留 idle 定时器不再武装（防 pointerdown 先于 click 的竞态跳屏）
    try {
      await generateResults(sessionId.value, {
        wigIds: [selectedWigId.value], hairColorId: selectedColorId.value,
        sceneKey: selectedTryonScene.value,
      })
      startPolling()
    } catch (e) {
      generating.value = false
      errorText.value = '生成请求失败，请呼叫顾问'
    }
  }

  // 候选换一批：Top3 ⇄ 第 4~6 名，切换后默认选中新页第一款
  function swapMatches() {
    matchPage.value = matchPage.value ? 0 : 1
    selectedWigId.value = matches.value[0]?.wig_id || null
    touch()
  }

  // 结果屏回到匹配屏再选一款（历史成品保留在结果轮播里）
  function backToMatching() {
    step.value = 'matching'
    touch()
  }

  async function generateScenes() {
    if (!selectedSceneKeys.value.length) return
    errorText.value = ''
    generating.value = true
    step.value = 'result'
    touch() // 同 generate：清残留 idle 定时器
    try {
      await generateResults(sessionId.value, { sceneKeys: [...selectedSceneKeys.value] })
      startPolling()
    } catch (e) {
      generating.value = false
      errorText.value = '生成请求失败，请呼叫顾问'
    }
  }

  function reselectScenes() {
    step.value = 'scene'
    touch()
  }

  async function react(resultId, reaction) {
    const target = results.value.find(r => r.id === resultId)
    if (target) target.reaction = reaction // 乐观更新
    try {
      await setReaction(resultId, reaction)
    } catch (e) { /* 展位弱网下不打断体验 */ }
    touch()
  }

  // ── 销售面板 ──
  // 不再拉 internal 载荷：kiosk 是与客户共享的屏幕，话术/发况只在试戴线索台
  //（顾问自己的设备）展示，本机不落任何内部数据（2026-07-07 用户指令）
  function openSales() {
    step.value = 'sales'
    touch()
  }

  async function submitSales({ intent_level, notes, next_action }) {
    await submitFeedback(customerId.value, {
      session_id: sessionId.value, intent_level, notes, next_action,
    })
    resetAll()
  }

  onBeforeUnmount(() => {
    stopPolling()
    if (idleTimer) clearTimeout(idleTimer)
  })

  return {
    step, mode, regForm, errorText, generating,
    session, analysis, matches, results, doneResults,
    selectedWigId, canSwapMatches, swapMatches, backToMatching,
    customerId, sessionId,
    hairColors, selectedColorId, scenes, selectedSceneKeys,
    tryonScenes, selectedTryonScene, loadTryonScenes,
    start, submitRegister, submitPhoto, generate, react,
    loadHairColors, loadScenes, toggleScene, generateScenes, reselectScenes,
    openSales, submitSales, resetAll, touch,
  }
}
