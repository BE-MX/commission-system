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
  createSession, generateResults, getScenes, getSession, getWigColors,
  registerCustomer, setReaction, submitFeedback, updateCustomer,
} from '@/api/expo'

const POLL_MS = 2000
const IDLE_MS = 60000
// 轮询连续失败 5 次（约 10s）才提示网络拥堵——单次抖动不打扰客户；恢复后自动撤下
const POLL_FAIL_HINT_AT = 5
const NET_CONGESTION_HINT = '现场网络拥堵，生成仍在继续，请稍候…'
// 不判 idle 的步骤：analyzing=客户在等待不算离开；matching=甄选发型/发色是客户慢慢挑的
// 决策页；result=展示页。三者都只允许手动返回主页，不自动跳回
//（用户指令 2026-07-07 result / 2026-07-08 matching——挑款看图不能被清场）
const NO_IDLE_STEPS = ['analyzing', 'matching', 'result']

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
  const salesReturnStep = ref('result') // 销售面板的来源屏（单击品牌字任意屏可进，含 attract）
  const guideShown = ref(false)      // 拍摄示范浮层一客只自动弹一次（register↔capture 往返不重弹）
  const tryonScenes = ref([])        // tryon 生成场景选项（职业/生活场景，滑动选择）
  const selectedTryonScene = ref(null) // 默认选中第一个；仅弱网加载失败时留 null=原景兜底

  const regForm = reactive({
    name: '', phone: '', wechat_id: '',
    primary_need: 'volume', style_pref: '知性优雅',
    consent: false,
    expo_code: '2026-08-expo',
  })

  let pollTimer = null
  let idleTimer = null
  let pollBusy = false   // 在途守卫：上一轮未返回不发新请求
  let pollFails = 0      // 连续失败计数，成功即清零
  let pollGen = 0        // 轮询代际：旧会话的迟到响应不许解锁新会话的 pollBusy
  let registerPromise = null // 乐观切换：后台建档 promise，submitPhoto 前 await 兑现
  let registerGen = 0        // 建档代际：resetAll(换客户/idle)后，旧后台建档的迟到结果不许回写 customerId
  let registerInFlight = false // 防「下一步」双击建双档：在途期间忽略二次提交

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
    registerPromise = null
    registerInFlight = false
    registerGen += 1 // 作废在途后台建档：其迟到结果不再回写（防污染下一位客户）
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
    salesReturnStep.value = 'result'
    guideShown.value = false
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
    // 乐观切换：立即进拍摄页，register 放后台跑（与相机启动并行）——frp 隧道每请求 ~1.5-2s，
    // 傻等 register 返回才切页会卡 ~3s；这段延迟被拍摄引导浮层 + 相机启动天然盖住。
    // 真正的登记结果在 submitPhoto 拍完照 await 时兑现（那时早已完成）。
    if (registerInFlight) return true // 双击守卫：在途建档未完成前不重复提交
    registerInFlight = true
    step.value = 'capture'
    touch()
    registerPromise = doRegister().finally(() => { registerInFlight = false })
    registerPromise.catch(() => {}) // 吞掉未处理 rejection 警告；错误在 submitPhoto 暴露
    return true
  }

  // 建档/更新（一客一档：有 customerId 走更新，悬空引用降级重建）
  async function doRegister() {
    const gen = registerGen  // 代际快照：resetAll 后迟到结果丢弃，不回写 customerId
    const form = { ...regForm } // 表单快照：await 期间即使 regForm 被清场也用提交时的值
    if (customerId.value) {
      try {
        await updateCustomer(customerId.value, form)
        return
      } catch (e) {
        if (e?.response?.status !== 404) throw e
        if (gen === registerGen) customerId.value = null // 客户已被线索台删除 → 降级重新建档
      }
    }
    const res = await registerCustomer(form)
    if (gen !== registerGen) return // 已换客户/idle 清场，丢弃这次建档结果
    customerId.value = res.data.customer_id
  }

  // ── 全流程导航：每屏「上一步」的目标（2026-07-13） ──
  // analyzing/matching/scene 都回 capture 重拍：analyzing 的旧会话弃之不管
  //（服务端照常跑完，无副作用），重拍会创建新会话
  function goBack() {
    const cur = step.value
    errorText.value = ''
    if (cur === 'register') {
      resetAll() // 登记页的上一步就是主页：清空表单保护下一位客户隐私
      return
    }
    if (cur === 'capture') {
      step.value = 'register' // 表单与 customerId 保留，可修改后重新提交
    } else if (cur === 'analyzing' || cur === 'matching' || cur === 'scene') {
      stopPolling()
      generating.value = false
      step.value = 'capture'
    } else if (cur === 'result') {
      if (generating.value) return // 生成中禁退：回甄选页选了款也按不了生成，徒增困惑
      if (mode.value === 'scene') reselectScenes()
      else backToMatching()
      return
    } else if (cur === 'sales') {
      let target = salesReturnStep.value || 'result'
      // 停留 sales 期间分析失败（轮询已停）时回 analyzing 是永不推进的假加载屏 → 落 capture 重拍
      if (target === 'analyzing' && (!pollTimer || session.value?.status === 'failed')) target = 'capture'
      step.value = target
    }
    touch()
  }

  async function submitPhoto(blob) {
    errorText.value = ''
    // 乐观切换下 register 可能仍在后台跑：先确保它完成拿到 customerId
    if (registerPromise) {
      try {
        await registerPromise
      } catch (e) {
        errorText.value = '登记提交失败，请返回上一步重试'
        return
      }
    }
    if (!customerId.value) {
      errorText.value = '登记未完成，请返回上一步重试'
      return
    }
    let res
    try {
      res = await createSession(customerId.value, blob, mode.value)
    } catch (e) {
      // 停留拍摄页：photoBlob 还在，用户可直接重按「确认」重传
      errorText.value = '照片上传失败，请再试一次或呼叫顾问'
      return
    }
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

  // ── 发型选择：换发型即换发色可选集（发色随发型过滤，2026-07-15） ──
  // 「原色」永远可选（=发型自身多角度图，不上色），故换发型统一先回原色
  function selectWig(id) {
    selectedWigId.value = id
    selectedColorId.value = null
    loadWigColors(id)
  }

  // ── 发色 / 场景选项（弱网失败静默降级：不选也能走通） ──
  // 只列该发型已备三角度图的发色；无图发色不出现，客户选不到无图组合
  async function loadWigColors(wigId) {
    hairColors.value = []
    if (!wigId) return
    try {
      const res = await getWigColors(wigId)
      // 代际守卫：快速换发型时，旧发型的迟到响应不覆盖当前发型的发色集
      if (selectedWigId.value !== wigId) return
      hairColors.value = res.data || []
    } catch (e) { /* 弱网失败：发色列表留空，只保留原色 */ }
  }

  async function loadTryonScenes() {
    if (!tryonScenes.value.length) {
      try {
        const res = await getScenes({ mode: 'tryon' }, { kiosk: true })
        tryonScenes.value = res.data || []
      } catch (e) { /* 加载失败留空 → 退回原景兜底(selectedTryonScene=null)，不阻断 */ }
    }
    // 原景已作为独立选项移除：每次进甄选页默认选中第一个场景（不让用户思考，可滑动改选）。
    // resetAll 会把 selectedTryonScene 清回 null，故默认选中须放在缓存守卫之外每次重设
    if (!selectedTryonScene.value && tryonScenes.value.length) {
      selectedTryonScene.value = tryonScenes.value[0].key
    }
  }

  async function loadScenes() {
    if (scenes.value.length) return
    try {
      const res = await getScenes(undefined, { kiosk: true })
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
    pollBusy = false
    pollFails = 0
    pollGen += 1
    pollTimer = setInterval(poll, POLL_MS)
    poll()
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
  }

  async function poll() {
    // 在途守卫：上一轮还没返回就跳过本轮——弱网下 2s 间隔会把几十条请求堆进
    // 拥堵链路（frp 隧道），越堆越死；getSession 已单配 10s 超时兜住占坑上限
    if (!sessionId.value || pollBusy) return
    pollBusy = true
    const gen = pollGen         // 代际快照：finally 只许解锁自己那一代的 busy
    const sid = sessionId.value // 代际守卫：响应落地时校验仍是当前会话
    try {
      const res = await getSession(sid)
      // 上一步重拍/返回主页后，弃用会话的迟到响应直接丢弃——否则旧会话的
      // analyzed 会把状态机拽去 matching 展示旧照片的匹配结果（对抗性审查 S1）
      if (sid !== sessionId.value) return
      pollFails = 0
      // 网络恢复即撤下拥堵提示；其他来源的 errorText 不动
      if (errorText.value === NET_CONGESTION_HINT) errorText.value = ''
      session.value = res.data
      const status = res.data.status

      if (step.value === 'analyzing' && status === 'analyzed') {
        step.value = 'matching'
        matchPage.value = 0
        // 不让用户思考：默认选中匹配度第一的款，轻触可换（selectWig 顺带加载该款发色）
        selectWig((res.data.matches || [])[0]?.wig_id || null)
        // 甄选页载荷不再变化且客户可停留数分钟：停轮询省隧道带宽，
        // 也避免此阶段弱网累计出「生成仍在继续」的错位提示；generate 会重启轮询
        stopPolling()
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
      if (sid !== sessionId.value) return // 弃用会话的迟到失败不计数（finally 仍会执行）
      // 会话已被线索台删除（级联删光）：再轮询永远 404，还会把失败计数
      // 顶成误导性的「拥堵」提示——给明确出口
      if (e?.response?.status === 404) {
        stopPolling()
        generating.value = false
        errorText.value = '会话已失效，请返回主页重新开始'
        if (step.value === 'analyzing') step.value = 'capture'
        touch()
        return
      }
      // 轮询单次失败不打断流程，下一轮继续；连续多次失败才给中文提示
      //（不 stopPolling：后台合成不受前端网络影响，恢复后照常收到结果）
      pollFails += 1
      if (pollFails >= POLL_FAIL_HINT_AT && !errorText.value) {
        errorText.value = NET_CONGESTION_HINT
      }
    } finally {
      if (gen === pollGen) pollBusy = false
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

  // 候选换一批：Top3 ⇄ 第 4~6 名，切换后默认选中新页第一款（顺带换发色可选集）
  function swapMatches() {
    matchPage.value = matchPage.value ? 0 : 1
    selectWig(matches.value[0]?.wig_id || null)
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
  // 2026-07-13 起面板=线索列表+话术查看（/kiosk/* 专用端点，手机号脱敏）；
  // internal 发况与客户流程屏话术仍禁止（2026-07-07 红线保留一半，见 cerebrum）
  function openSales() {
    if (step.value !== 'sales') salesReturnStep.value = step.value
    step.value = 'sales'
    touch()
  }

  async function submitSales({ intent_level, notes, next_action }) {
    try {
      await submitFeedback(customerId.value, {
        session_id: sessionId.value, intent_level, notes, next_action,
      })
    } catch (e) {
      // 留在面板不清场：表单内容还在，顾问可直接重按提交
      errorText.value = '反馈提交失败，请再试一次'
      return
    }
    resetAll()
  }

  onBeforeUnmount(() => {
    stopPolling()
    if (idleTimer) clearTimeout(idleTimer)
  })

  return {
    step, mode, regForm, errorText, generating,
    session, analysis, matches, results, doneResults,
    selectedWigId, selectWig, canSwapMatches, swapMatches, backToMatching, goBack,
    customerId, sessionId,
    hairColors, selectedColorId, scenes, selectedSceneKeys, guideShown,
    tryonScenes, selectedTryonScene, loadTryonScenes,
    start, submitRegister, submitPhoto, generate, react,
    loadScenes, toggleScene, generateScenes, reselectScenes,
    openSales, submitSales, resetAll, touch,
  }
}
