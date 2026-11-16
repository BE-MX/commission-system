<template>
  <Teleport to="body">
    <div ref="root" class="churn-stage" role="dialog" aria-modal="true" aria-label="客户流失态势" tabindex="-1" @keydown.tab="trapFocus">
      <div ref="stage" class="churn-stage__main">
        <canvas v-if="use3d" ref="canvas" class="churn-stage__canvas" aria-hidden="true"
                @pointermove="onPointerMove" @pointerleave="onPointerLeave" @click="onCanvasClick" />
        <ChurnDeck2d v-else class="churn-stage__flat" :model="ship.model.value" :version="ship.state.version" :selected-id="selectedId"
                     :focus="ship.state.focus" :filter="ship.filter.value" @select="item => select(item)" @focus="toggleFocus" />
        <div v-if="use3d" class="churn-stage__labels" aria-hidden="true">
          <template v-for="label in ship.regionLabels.value" :key="label.key">
            <button type="button" tabindex="-1" :ref="el => (labelEls[label.key] = el)"
                    :class="['churn-lbl', { 'is-on': ship.state.focus === label.key }]" @click="toggleFocus(label.key, $event)">
              <b>{{ label.key }}</b> {{ label.owned }} 家<span v-if="label.critical" class="churn-lbl__crit">临界 {{ label.critical }}</span>
            </button>
            <span :ref="el => (buoyEls[label.key] = el)" class="churn-buoy">{{ label.key }} 公海 {{ label.publicTotal }}<i v-if="label.fallenRecent">近 30 天 +{{ label.fallenRecent }}</i></span>
          </template>
        </div>
        <header class="churn-stage__head">
          <div class="churn-card churn-stage__title">
            <h2>客户流失态势</h2>
            <p>数据时间 {{ data?.generated_at?.replace('T', ' ') || '—' }}<span v-if="!rule.follow_enforced" class="churn-preview">「1 个月未跟进」{{ rule.launch_date ? `${rule.launch_date} 生效，当前为预演` : '尚未生效，当前为预演' }}</span></p>
          </div>
          <div class="churn-card churn-kpis">
            <div class="churn-kpi is-crit"><b>{{ ship.kpis.value.critical }}</b><span>临界（3 天内）</span></div>
            <div class="churn-kpi is-warn"><b>{{ ship.kpis.value.within14 }}</b><span>14 天内将落海</span></div>
            <div class="churn-kpi"><b>{{ ship.kpis.value.fallen }}</b><span>近 30 天已落海</span></div>
          </div>
          <el-select v-if="canReadAll" :model-value="ship.userId.value" class="churn-owner" placeholder="全部归属人" clearable filterable
                     aria-label="按归属人筛选" @change="value => ship.load(value || null)">
            <el-option v-for="option in data?.owners || []" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <button type="button" class="churn-btn churn-close" aria-label="关闭客户流失态势" @click="close">关闭 Esc</button>
          <div class="churn-stage__filters">
            <button type="button" class="churn-chip" :aria-pressed="ship.state.onlySA" @click="ship.state.onlySA = !ship.state.onlySA">只看 S/A 级</button>
            <button type="button" class="churn-chip" :aria-pressed="ship.state.onlyCritical" @click="ship.state.onlyCritical = !ship.state.onlyCritical">只看临界</button>
            <button v-if="ship.state.focus" type="button" class="churn-chip" @click="toggleFocus(null, $event)">返回全景</button>
          </div>
        </header>
        <div :class="['churn-mark', { 'is-on': ship.mode.value !== 'live', 'is-proj': ship.mode.value === 'projection' }]" aria-live="polite">{{ markText }}</div>
        <div class="churn-card churn-timeline">
          <div class="churn-timeline__row">
            <b>{{ dayLabel(ship.state.t, data?.today) }}</b><span class="churn-muted">{{ modeText }}</span><span class="churn-spacer" />
            <button type="button" class="churn-btn" @click="togglePlay('replay')">{{ ship.state.playing === 'replay' ? '停止' : `回放近 ${REPLAY_DAYS} 天` }}</button>
            <button type="button" class="churn-btn" @click="togglePlay('projection')">{{ ship.state.playing === 'projection' ? '停止' : '播放推演' }}</button>
            <button type="button" class="churn-btn is-primary" :disabled="ship.mode.value === 'live' && !ship.state.playing" @click="backToToday">回到今天</button>
          </div>
          <input type="range" :min="-REPLAY_DAYS" :max="PROJECTION_DAYS" step="1" :value="Math.round(ship.state.t)" aria-label="时间：左侧回放，右侧推演" @input="onSlide" />
          <div class="churn-ticks"><span>{{ REPLAY_DAYS }} 天前</span><span>今天</span><span>+7 天</span><span>+{{ PROJECTION_DAYS }} 天</span></div>
        </div>
        <div ref="tip" :class="['churn-tip', { 'is-on': tipInfo }]" aria-hidden="true">
          <template v-if="tipInfo"><b>{{ tipInfo.title }}</b><span v-for="line in tipInfo.lines" :key="line.text" :class="{ 'churn-tip__d': line.strong }">{{ line.text }}</span></template>
        </div>
        <el-alert v-if="ship.state.error" class="churn-error" type="error" :title="ship.state.error" :closable="false" />
      </div>
      <ChurnSidePanel :ship="ship" :selected="selectedItem" :can-claim="canClaim" :claiming="claiming" :can-read-all="canReadAll"
                      @select="select" @back="select(null)" @record="row => $emit('record', row)" @timeline="id => $emit('timeline', id)" @claim="claim" />
    </div>
  </Teleport>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { claimCustomer } from '@/api/domestic'
import { apiError } from '@/api/domesticFollowup'
import { msgError, msgSuccessText, msgWarning } from '@/utils/feedback'
import ChurnDeck2d from './ChurnDeck2d.vue'
import ChurnSidePanel from './ChurnSidePanel.vue'
import { DECK, PROJECTION_DAYS, REPLAY_DAYS } from './shipLayout'
import { dayLabel, prefers3d } from './churnFormat'

const props = defineProps({ ship: { type: Object, required: true }, canReadAll: Boolean, canClaim: Boolean })
const emit = defineEmits(['close', 'record', 'timeline'])
const ship = props.ship
const data = computed(() => ship.data.value)
const rule = computed(() => data.value?.rule || {})
const use3d = ref(prefers3d())
const root = ref(null), stage = ref(null), canvas = ref(null), tip = ref(null)
const labelEls = reactive({}), buoyEls = reactive({})
const selectedId = ref(null), tipInfo = ref(null), claiming = ref(false)
const scene = shallowRef(null)
let observer, returnFocus = null, pointerEvent = null
// 条目由 shipLayout 原地更新（非响应式），每次时间变化给侧栏一份新快照，否则推演时客户卡停在旧天数
const selectedItem = computed(() => {
  ship.state.version
  const item = ship.model.value.items.find(entry => entry.id === selectedId.value)
  return item ? { ...item } : null
})
const modeText = computed(() => ({ live: '今天', replay: `回放 · ${-Math.round(ship.state.t)} 天前`, projection: `推演 · +${Math.round(ship.state.t)} 天` }[ship.mode.value]))
const markText = computed(() => (ship.mode.value === 'replay' ? `回放：${dayLabel(ship.state.t, data.value?.today)} 的真实状态`
  : ship.mode.value === 'projection' ? `推演：若期间不跟进不下单 · ${dayLabel(ship.state.t, data.value?.today)}` : ''))

function placeLabels(project) {
  for (const region of ship.model.value.regions) {
    const index = ship.model.value.regions.indexOf(region)
    const label = labelEls[region.key], buoy = buoyEls[region.key]
    if (label) { const p = project(region.xc, 1.6 + (index % 2 ? 6.6 : 4.2), -DECK.HALF); label.style.transform = `translate(${p.x}px, ${p.y}px) translate(-50%, -50%)` }
    if (buoy) { const p = project(region.xc, 3.2, DECK.HALF + 15.5); buoy.style.transform = `translate(${p.x}px, ${p.y}px) translate(-50%, -50%)` }
  }
}

async function mount3d() {
  try {
    const { createShipScene } = await import('./shipScene')
    if (!canvas.value) return
    scene.value = createShipScene(canvas.value, { reduced: matchMedia('(prefers-reduced-motion: reduce)').matches, onFrame: placeLabels })
    scene.value.setModel(ship.model.value)
    scene.value.start()
  } catch (error) {
    console.warn('[churn] 三维场景初始化失败，改用 2D 甲板图', error)
    use3d.value = false
  }
}
watch(() => ship.model.value, model => scene.value?.setModel(model))
watch(() => ship.filter.value, fn => scene.value?.setFilter(fn))
watch(selectedId, id => scene.value?.setSelected(id))

function select(item) {
  selectedId.value = item?.id ?? null
}
function toggleFocus(key, event) {
  const next = ship.state.focus === key ? null : key
  ship.state.focus = next
  scene.value?.setFocus(next)
  if (event?.detail === 0) scene.value?.jumpCamera() // 键盘触发不播镜头动画
}
function onSlide(event) {
  ship.stopPlay()
  const next = Number(event.target.value)
  if (Math.abs(next - ship.state.t) > 4) scene.value?.jump()
  ship.setTime(next)
}
function togglePlay(kind) {
  if (ship.state.playing === kind) { ship.stopPlay(); ship.setTime(Math.round(ship.state.t)); return }
  if (kind === 'replay' || Math.round(ship.state.t) !== 0) scene.value?.jump()
  ship.startPlay(kind)
}
function backToToday() { ship.stopPlay(); scene.value?.jump(); ship.setTime(0) }

function onPointerMove(event) {
  if (pointerEvent) { pointerEvent = event; return }
  pointerEvent = event
  requestAnimationFrame(() => {
    const e = pointerEvent
    pointerEvent = null
    if (!scene.value || !e) return
    const hit = scene.value.pick(e.clientX, e.clientY)
    const item = hit?.itemId != null ? ship.model.value.items.find(i => i.id === hit.itemId) : null
    scene.value.setHovered(item?.id ?? null)
    canvas.value.style.cursor = hit ? 'pointer' : 'default'
    tipInfo.value = item ? tipFor(item) : hit?.region ? { title: hit.region, lines: [{ text: '点击推近这个市场' }] } : null
    if (!tipInfo.value || !tip.value) return
    const rect = stage.value.getBoundingClientRect()
    const x = Math.min(e.clientX - rect.left + 14, rect.width - tip.value.offsetWidth - 8)
    const y = Math.min(e.clientY - rect.top + 14, rect.height - tip.value.offsetHeight - 8)
    tip.value.style.transform = `translate(${x}px, ${y}px)`
  })
}
function onPointerLeave() { tipInfo.value = null; scene.value?.setHovered(null) }
function onCanvasClick(event) {
  const hit = scene.value?.pick(event.clientX, event.clientY)
  if (hit?.itemId != null) select(ship.model.value.items.find(item => item.id === hit.itemId))
  else if (hit?.region) toggleFocus(hit.region, event)
}
function tipFor(item) {
  const row = item.row
  const title = `${row.shop_name} · ${row.level || '未定级'}`
  if (item.tier === 'fallen') return { title, lines: [{ text: `已落海 ${Math.max(0, Math.round(-item.remaining))} 天` }] }
  return { title, lines: [
    { text: `距释放 ${Math.ceil(item.remaining)} 天 · ${row.clock === 'follow' ? '跟进钟' : '订单钟'}`, strong: true },
    { text: `上次跟进 ${row.last_followup_date || '无记录'}${row.strap === 'loose' ? ' · 已超跟进频率' : ''}` },
  ] }
}

async function claim(item) {
  if (claiming.value) return
  claiming.value = true
  try {
    const res = await claimCustomer(item.id)
    ;(res?.data?.order_expired ? msgWarning : msgSuccessText)(res?.message || '已认领')
    await ship.load()
  } catch (error) {
    msgError(apiError(error, '认领失败'), error)
  } finally {
    claiming.value = false
  }
}

function onKeydown(event) {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  if (event.target?.closest?.('.el-select, .el-select__wrapper')) return // 先关下拉框，再按一次才退出
  // 抽屉、下拉等浮层挂在 body 上，Esc 先交给它们
  if (!root.value || (document.activeElement && document.activeElement !== document.body && !root.value.contains(document.activeElement))) return
  onEsc()
}
function trapFocus(event) {
  const focusable = [...root.value.querySelectorAll('button:not([disabled]), input, [tabindex="0"], .el-select__wrapper')]
    .filter(el => el.offsetParent !== null)
  if (!focusable.length) return
  const first = focusable[0], last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
function onEsc() {
  if (selectedId.value != null) select(null)
  else if (ship.state.focus) toggleFocus(null)
  else close()
}
function close() { emit('close') }

onMounted(async () => {
  returnFocus = document.activeElement
  await nextTick()
  root.value?.focus()
  if (use3d.value) await mount3d()
  observer = new ResizeObserver(() => scene.value?.resize())
  if (stage.value) observer.observe(stage.value)
  document.addEventListener('visibilitychange', onVisibility)
  document.addEventListener('keydown', onKeydown)
  playIntro()
})
// 进入时回放一次「昨天至今」真实落海的客户；没有就不播，减少动态时不播
function playIntro() {
  const recent = ship.model.value.items.some(item => item.fallen && item.rem0 >= -1)
  if (!recent || matchMedia('(prefers-reduced-motion: reduce)').matches || ship.mode.value !== 'live') return
  scene.value?.jump()
  ship.setTime(-2) // 昨天落海的 rem0 = -1，要从前天开始才看得到它掉下去
  setTimeout(() => { if (ship.state.t === -2) ship.startPlay('intro') }, 600)
}
function onVisibility() { if (document.hidden) scene.value?.stop(); else scene.value?.start() }
onDeactivated(close) // 页面被 KeepAlive 缓存（切走路由）时关闭沉浸层，停止渲染
onBeforeUnmount(() => {
  ship.stopPlay()
  observer?.disconnect()
  document.removeEventListener('visibilitychange', onVisibility)
  document.removeEventListener('keydown', onKeydown)
  scene.value?.dispose()
  scene.value = null
  returnFocus?.focus?.()
})
</script>
<style src="./churn.css"></style>
