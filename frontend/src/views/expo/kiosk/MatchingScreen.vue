<template>
  <div class="matching">
    <div class="m-scroll">
      <h2 class="xk-title">为您甄选 <em>{{ flow.matches.value.length }}</em> 款</h2>
      <div class="xk-sub">依据您的脸型 · 肤色 · 气质定制推荐 · 轻触选择一款</div>

      <!-- AI 面容解读：只展示 serialize 剥离 internal 后的正面公开字段 -->
      <div v-if="flow.analysis.value" class="reading">
        <div v-if="flow.analysis.value.display_notes" class="reading-note">{{ flow.analysis.value.display_notes }}</div>
        <div class="reading-chips">
          <span v-if="faceLabel" class="rchip"><b>脸型</b>{{ faceLabel }}</span>
          <span v-if="skinLabel" class="rchip"><b>肤色</b>{{ skinLabel }}</span>
          <span v-if="flow.analysis.value.temperament" class="rchip"><b>气质</b>{{ flow.analysis.value.temperament }}</span>
        </div>
      </div>

      <div class="cards">
        <div
          v-for="(match, i) in shownMatches" :key="match.wig_id"
          class="card" :class="{ zhizhen: match.series === 'zhizhen', custom: match.custom, sel: flow.selectedWigId.value === match.wig_id }"
          :style="{ animationDelay: `${0.15 + i * 0.25}s` }"
          @click="pickWig(match.wig_id)"
        >
          <span v-if="match.custom" class="badge badge-custom">自选</span>
          <span v-else-if="match.series === 'zhizhen'" class="badge">至臻系列</span>
          <div class="thumb">
            <img v-if="match.cover_url" :src="match.thumb_url || match.cover_url" alt="" />
            <span v-else class="thumb-ph">莱莎</span>
          </div>
          <div class="info">
            <div class="no">{{ match.model_no }}</div>
            <div class="nm">{{ match.name }}</div>
            <div class="why">{{ match.reason }}</div>
          </div>
          <div v-if="match.custom" class="pct pct-custom">自选<small>发型库</small></div>
          <div v-else-if="match.must_recommend" class="pct pct-custom">主推<small>为您优选</small></div>
          <div v-else-if="match.score != null" class="pct">{{ Math.round(match.score) }}<small>匹配</small></div>
          <span class="tick" :class="{ on: flow.selectedWigId.value === match.wig_id }">✓</span>
        </div>
      </div>

      <div class="match-actions">
        <button v-if="flow.canSwapMatches.value" class="swap" @click="doSwap">
          换一批候选 ⟳
        </button>
        <button class="swap lib-entry" @click="openLibrary">从发型库中选择其他款 ›</button>
      </div>

      <!-- 从发型库选择：全部启用发型网格，滑动挑一款 -->
      <div v-if="libraryOpen" class="lib-overlay" @click.self="libraryOpen = false">
        <div class="lib-panel">
          <div class="lib-head">
            <span class="lib-title">从发型库选择</span>
            <button class="lib-close" @click="libraryOpen = false">✕</button>
          </div>
          <div v-loading="libraryLoading" class="lib-grid">
            <button
              v-for="w in libraryWigs" :key="w.wig_id"
              class="lib-card" :class="{ on: flow.selectedWigId.value === w.wig_id }"
              @click="pickFromLibrary(w)"
            >
              <span class="lib-thumb">
                <img v-if="w.cover_url" :src="w.thumb_url || w.cover_url" alt="" />
                <span v-else class="lib-ph">莱莎</span>
              </span>
              <span v-if="w.series === 'zhizhen'" class="lib-tag">至臻</span>
              <span class="lib-nm">{{ w.name }}</span>
            </button>
            <div v-if="!libraryLoading && !libraryWigs.length" class="lib-empty">
              发型库加载失败，请关闭后重试或呼叫顾问
            </div>
          </div>
        </div>
      </div>

      <div v-if="flow.hairColors.value.length" class="color-pick">
        <div class="cp-title">甄选发色<small>可选 · 默认保持款式原色</small></div>
        <div class="chips">
          <button
            class="chip" :class="{ on: !flow.selectedColorId.value }"
            @click="pickColor(null)"
          ><i class="sw origin" />原色</button>
          <button
            v-for="c in flow.hairColors.value" :key="c.id"
            class="chip" :class="{ on: flow.selectedColorId.value === c.id }"
            @click="pickColor(c.id)"
          ><img v-if="c.swatch_url" class="sw" :src="c.thumb_url || c.swatch_url" alt="" />
            <i v-else class="sw" :style="{ background: c.hex || 'var(--xk-ink-2)' }" />{{ c.name }}</button>
        </div>
      </div>

      <div v-if="flow.tryonScenes.value.length" class="scene-pick">
        <div class="cp-title">生成场景<small>选类别 · 左右滑动选择 · 场景图仅示意</small></div>
        <div v-if="categories.length > 1" class="scene-cats">
          <button
            v-for="c in categories" :key="c.key"
            class="scene-cat" :class="{ on: selectedCategory === c.key }"
            @click="switchCategory(c.key)"
          >{{ c.label }}</button>
        </div>
        <div ref="trackRef" class="scene-track" @scroll="onSceneScroll">
          <button
            v-for="(s, i) in visibleScenes" :key="s.key"
            class="scard" :class="{ on: sceneActive === i }"
            @click="centerScene(i)"
          >
            <span class="scard-pic">
              <img v-if="s.image" :src="s.image" alt="" />
              <span v-else class="scard-ph"><span class="scard-emoji">{{ sceneEmoji(s.key) }}</span></span>
            </span>
            <span class="scard-cap">
              <span class="scard-lb">{{ s.label }}</span>
              <span class="scard-tg">{{ s.tagline }}</span>
            </span>
          </button>
        </div>
      </div>
    </div>

    <!-- 合成版本：必选项，默认真实版。三版差别在皮肤怎么处理，用光一律打好 -->
    <div class="variant-row">
      <span class="variant-lb">出图风格</span>
      <div class="variant-opts">
        <button
          v-for="v in flow.PROMPT_VARIANTS" :key="v.value"
          class="variant-opt" :class="{ sel: flow.promptVariant.value === v.value }"
          @click="flow.promptVariant.value = v.value"
        >
          <span class="vo-lb">{{ v.label }}</span>
          <span class="vo-hint">{{ v.hint }}</span>
        </button>
      </div>
    </div>

    <button class="xk-btn go" :disabled="!flow.selectedWigId.value" @click="flow.generate()">
      生成我的试戴效果
    </button>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { getWigPicker } from '@/api/expo'

const flow = inject('tryonFlow')

// 客户屏话术用讨喜的中文标签（value 是 AI 分析枚举）
const FACE_LABELS = { oval: '鹅蛋脸', round: '圆脸', square: '方脸', heart: '心形脸', long: '长脸', diamond: '菱形脸' }
const DEPTH_LABELS = { fair: '白皙', light: '白皙', medium: '自然', tan: '小麦' }
const TONE_LABELS = { cool: '冷调', warm: '暖调', neutral: '中性' }

const faceLabel = computed(() => FACE_LABELS[flow.analysis.value?.face_shape] || '')
const skinLabel = computed(() => {
  const skin = flow.analysis.value?.skin_tone || {}
  const parts = [DEPTH_LABELS[skin.depth], TONE_LABELS[skin.undertone]].filter(Boolean)
  return parts.join(' · ')
})

function pickWig(id) {
  flow.selectWig(id) // 换发型即重置为原色并加载该发型可选发色
  flow.touch()
}

function pickColor(id) {
  flow.selectedColorId.value = id
  flow.touch()
}

// ── 从发型库选择（默认 6 推荐外，客户可挑其他款） ──
const libraryOpen = ref(false)
const libraryWigs = ref([])
const libraryLoading = ref(false)
const pickedWig = ref(null)  // 从库选的款，塑成 match 卡形态置于最前

// 展示的发型卡 = 推荐列表；若从库选了款且不在推荐里，则把它插到最前（标「自选」）
const shownMatches = computed(() => {
  const base = flow.matches.value
  const picked = pickedWig.value
  if (!picked || base.some((m) => m.wig_id === picked.wig_id)) return base
  return [picked, ...base]
})

async function openLibrary() {
  libraryOpen.value = true
  flow.touch()
  if (libraryWigs.value.length) return
  libraryLoading.value = true
  try {
    const res = await getWigPicker()
    libraryWigs.value = res.data || []
  } catch (e) { /* 端点已 suppressToast，浮层内嵌空态文案兜底；关闭重开会重试 */ } finally {
    libraryLoading.value = false
  }
}

// 换一批：回到推荐流，清掉自选卡避免"卡还在最前但已取消选中"的半选态（对抗性审查 F4）
function doSwap() {
  pickedWig.value = null
  flow.swapMatches()
}

function pickFromLibrary(w) {
  pickedWig.value = {
    wig_id: w.wig_id, model_no: w.model_no, name: w.name,
    series: w.series, cover_url: w.cover_url,
    reason: '您从发型库选择的款式', score: null, custom: true,
  }
  flow.selectWig(w.wig_id) // 从库选款同样重置原色 + 加载该款发色
  libraryOpen.value = false
  flow.touch()
}

// ── 生成场景滑动选择器（分类 Tab + 居中卡=选中；原生 scroll-snap 吃触摸惯性，选中卡放大） ──
const trackRef = ref(null)
const sceneActive = ref(0)
let scRaf = 0

// 分类分段：20 景分「职场专业/长辈生活」两段展示，避免单行长条（category 由后端返回）
const CATEGORY_LABELS = { career: '职场专业', life: '长辈生活' }
const categories = computed(() => {
  const order = []
  for (const s of flow.tryonScenes.value) {
    const c = s.category || 'career'
    if (!order.includes(c)) order.push(c)
  }
  return order.map(c => ({ key: c, label: CATEGORY_LABELS[c] || c }))
})
const selectedCategory = ref('career')
const visibleScenes = computed(() =>
  flow.tryonScenes.value.filter(s => (s.category || 'career') === selectedCategory.value),
)

// 占位卡图标（无示意图时用）；后台把实拍/AI 图丢进 uploads/expo/scenes/<key>.* 即替换为真图
const SCENE_EMOJI = {
  whitecollar: '💼', teacher: '📚', shopowner: '🛍️',
  civilservant: '🏛️', doctor: '🩺', home: '🛋️', gathering: '🥂',
  lawyer: '⚖️', banker: '🏦', accountant: '📊', director: '📋',
  pharmacist: '💊', propertymanager: '🔑', hsrtravel: '🚄',
  weddinghost: '💐', schoolpickup: '🎒', squaredance: '💃',
  seniorcollege: '🎻', seniorcafe: '☕', parkwalk: '🌳',
}
function sceneEmoji(key) { return SCENE_EMOJI[key] || '✦' }

function cardCenterOffset(el, card) {
  return card.offsetLeft - (el.clientWidth - card.offsetWidth) / 2
}

// 滚动时找离容器中线最近的卡 → 置为选中（rAF 节流，避免频繁改 flow 状态）
function syncScene() {
  const el = trackRef.value
  if (!el) return
  const center = el.scrollLeft + el.clientWidth / 2
  const cards = el.querySelectorAll('.scard')
  let best = 0
  let bestDist = Infinity
  cards.forEach((c, i) => {
    const d = Math.abs(c.offsetLeft + c.offsetWidth / 2 - center)
    if (d < bestDist) { bestDist = d; best = i }
  })
  sceneActive.value = best
  const key = visibleScenes.value[best]?.key
  if (key && key !== flow.selectedTryonScene.value) {
    flow.selectedTryonScene.value = key
    flow.touch()
  }
}

// 切分类：选中该类第一个场景 + 滑动条复位居中
async function switchCategory(catKey) {
  if (catKey === selectedCategory.value) return
  selectedCategory.value = catKey
  flow.touch()
  await nextTick()
  const first = visibleScenes.value[0]
  if (first) { flow.selectedTryonScene.value = first.key; flow.touch() }
  sceneActive.value = 0
  const el = trackRef.value
  const card = el?.querySelectorAll('.scard')[0]
  if (el && card) el.scrollLeft = cardCenterOffset(el, card)
}

function onSceneScroll() {
  if (scRaf) return
  scRaf = requestAnimationFrame(() => { scRaf = 0; syncScene() })
}

// 点卡片 → 平滑滚到居中（snap 会落定，onSceneScroll 顺带更新选中）
function centerScene(i) {
  const el = trackRef.value
  const card = el?.querySelectorAll('.scard')[i]
  if (!el || !card) return
  el.scrollTo({ left: cardCenterOffset(el, card), behavior: 'smooth' })
}

onMounted(async () => {
  // 发色随发型加载（selectWig 在 analyzed→matching 时已触发首个发型的发色）
  await flow.loadTryonScenes()
  // 默认分类 = 默认选中场景（flow 设的首个场景）所属分类
  const cur = flow.tryonScenes.value.find(s => s.key === flow.selectedTryonScene.value)
  selectedCategory.value = cur?.category || categories.value[0]?.key || 'career'
  await nextTick()  // 等 visibleScenes 过滤后的 DOM 就绪
  const el = trackRef.value
  if (!el) return
  const idx = visibleScenes.value.findIndex(s => s.key === flow.selectedTryonScene.value)
  sceneActive.value = idx < 0 ? 0 : idx
  const card = el.querySelectorAll('.scard')[sceneActive.value]
  if (card) el.scrollLeft = cardCenterOffset(el, card)
})

onBeforeUnmount(() => { if (scRaf) cancelAnimationFrame(scRaf) })
</script>

<style scoped>
/* 滚动交给内层 .m-scroll，CTA 留在外层常驻可见——这一屏内容长（解读+6 张卡+发色+场景），
   小屏上按钮跟着内容滚出屏幕后，客户挑完款找不到「生成」。目标是选完就能按下，不是滚到底去找 */
.matching { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; padding: 2vh 6vw 3vh; overflow: hidden; }
.m-scroll {
  flex: 1; min-height: 0; width: 100%;
  display: flex; flex-direction: column; align-items: center;
  overflow-y: auto; -webkit-overflow-scrolling: touch;
}
.reading {
  width: min(88vw, 560px); margin-top: 2vh; padding: 14px 18px;
  border: 1px solid var(--xk-gold-line); border-radius: 16px;
  background: rgba(232, 196, 121, 0.05);
  animation: card-in 0.7s cubic-bezier(0.2, 0.9, 0.3, 1.2) backwards;
}
.reading-note {
  font-family: 'Noto Serif SC', serif; font-size: 14px; line-height: 1.7;
  letter-spacing: 0.06em; color: var(--xk-gold-hi);
}
.reading-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.rchip {
  font-size: 11px; letter-spacing: 0.12em; color: var(--xk-mut);
  border: 1px solid var(--xk-gold-line); border-radius: 14px; padding: 4px 12px;
}
.rchip b { color: var(--xk-gold); font-weight: 400; margin-right: 6px; }
.cards { width: min(88vw, 560px); display: flex; flex-direction: column; gap: 14px; margin-top: 3vh; }
.card {
  position: relative; display: flex; gap: 16px; align-items: center;
  border: 1px solid var(--xk-gold-line); border-radius: 18px; padding: 14px 16px;
  background: linear-gradient(120deg, rgba(232, 196, 121, 0.06), rgba(232, 196, 121, 0.015));
  transform-origin: top;
  /* backwards 填充：入场动画只定义 from，结束后不锁 transform（否则 :active 按压 scale 会被 fill:forwards 持帧覆盖） */
  animation: card-in 0.9s cubic-bezier(0.2, 0.9, 0.3, 1.2) backwards;
}
@keyframes card-in { from { opacity: 0; transform: perspective(600px) rotateX(24deg) translateY(14px); } }
.card.zhizhen {
  border-color: rgba(232, 196, 121, 0.55);
  background: linear-gradient(120deg, rgba(232, 196, 121, 0.14), rgba(232, 196, 121, 0.03));
}
.card { cursor: pointer; transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease, background 160ms ease; }
.card:active { transform: scale(0.98); }
.card.sel {
  border-color: var(--xk-gold);
  background: linear-gradient(120deg, rgba(232, 196, 121, 0.18), rgba(232, 196, 121, 0.05));
  box-shadow: 0 0 18px rgba(232, 196, 121, 0.18);
}
.tick {
  position: absolute; right: 12px; bottom: 10px;
  width: 22px; height: 22px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: var(--xk-ink);
  background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi));
  opacity: 0; transform: scale(0.9);
  transition: opacity 160ms cubic-bezier(0.23, 1, 0.32, 1), transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.tick.on { opacity: 1; transform: scale(1); }
.swap {
  margin-top: 14px; background: transparent; border: none; cursor: pointer;
  font-size: 12px; letter-spacing: 0.18em; color: var(--xk-gold-dim);
  padding: 8px 16px; transition: color 160ms ease, transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.swap:active { transform: scale(0.96); }
.match-actions { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; justify-content: center; margin-top: 14px; }
.match-actions .swap { margin-top: 0; }
.lib-entry { color: var(--xk-gold-hi); border: 1px solid var(--xk-gold-line); border-radius: 20px; }

/* 自选卡（从发型库选的款） */
.card.custom {
  border-color: var(--xk-gold);
  background: linear-gradient(120deg, rgba(232, 196, 121, 0.16), rgba(232, 196, 121, 0.04));
}
.badge-custom { background: linear-gradient(110deg, var(--xk-gold-hi), var(--xk-gold)); }
.pct-custom { font-style: normal; font-size: 15px; }

/* 从发型库选择浮层 */
.lib-overlay {
  position: fixed; inset: 0; z-index: 40; display: flex; align-items: center; justify-content: center;
  /* fixed 不吃 .xk-root 的安全区 padding，自己收口；面板高度随之改成相对本容器的百分比，
     一并解开「vh ≠ 手机可见高度」——地址栏或刘海会把 84vh 的底部推到屏幕外 */
  padding:
    calc(16px + env(safe-area-inset-top)) calc(12px + env(safe-area-inset-right))
    calc(16px + env(safe-area-inset-bottom)) calc(12px + env(safe-area-inset-left));
  background: rgba(6, 5, 3, 0.72); backdrop-filter: blur(4px); animation: lib-fade 200ms ease;
}
@keyframes lib-fade { from { opacity: 0; } to { opacity: 1; } }
.lib-panel {
  width: min(92vw, 720px); max-height: 100%; display: flex; flex-direction: column;
  border: 1px solid var(--xk-gold-line); border-radius: 20px;
  background: linear-gradient(160deg, var(--xk-ink-2), var(--xk-ink));
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.5), 0 0 40px rgba(232, 196, 121, 0.12);
  animation: lib-pop 240ms cubic-bezier(0.23, 1, 0.32, 1);
}
@keyframes lib-pop { from { opacity: 0; transform: scale(0.96); } to { opacity: 1; transform: none; } }
.lib-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px; border-bottom: 1px solid var(--xk-gold-line);
}
.lib-title { font-family: 'Noto Serif SC', serif; font-size: 18px; color: var(--xk-gold-hi); letter-spacing: 0.08em; }
/* 44px 是最小可靠触摸目标：原来 26x34 的裸文字按钮在手机上要点两三次才中 */
.lib-close {
  flex: none; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center;
  background: transparent; border: none; color: var(--xk-mut); font-size: 18px; cursor: pointer;
}
.lib-close:active { transform: scale(0.9); }
.lib-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px; padding: 18px 22px; overflow-y: auto;
}
.lib-empty {
  grid-column: 1 / -1; padding: 40px 0; text-align: center;
  font-size: 12px; letter-spacing: 0.14em; color: var(--xk-mut);
}
.lib-card {
  position: relative; display: flex; flex-direction: column; gap: 8px; padding: 0;
  border: 1px solid var(--xk-gold-line); border-radius: 14px; overflow: hidden;
  background: var(--xk-ink-2); cursor: pointer;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease;
}
.lib-card:active { transform: scale(0.97); }
.lib-card.on { border-color: var(--xk-gold); box-shadow: 0 0 16px rgba(232, 196, 121, 0.2); }
/* img 必须 position:absolute 脱离文档流——否则流内的 <img height:100%> 会用图片自身比例
   撑高缩略框，本机荣耀 WebView 上 aspect-ratio 被架空：2:3 封面把框顶高、名字被挤出
   overflow:hidden 裁掉，只有恰好 3:4 的封面幸免（2026-07-24 CDP 实测定位）。绝对定位后
   框高纯由 aspect-ratio 决定，各卡统一，名字恒可见。 */
/* flex:none 是配套保险——2026-07-24 那次是 img 撑高缩略框把名字挤出 overflow:hidden，
   而缩略框本身作为 flex item 默认可收缩，同样能在名字与图之间挤掉一方。两端都锁死才稳。 */
.lib-thumb { flex: none; position: relative; width: 100%; aspect-ratio: 3 / 4; display: flex; align-items: center; justify-content: center; }
.lib-thumb img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.lib-ph { font-size: 12px; letter-spacing: 0.3em; color: var(--xk-gold-dim); }
.lib-nm { flex: none; font-size: 12px; color: var(--xk-paper); text-align: center; padding: 0 6px 10px; line-height: 1.4; }
.lib-tag {
  position: absolute; top: 8px; right: 8px; font-size: 9px; letter-spacing: 0.1em; color: var(--xk-ink);
  background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi)); padding: 2px 8px; border-radius: 10px;
}
.badge {
  position: absolute; top: -10px; right: 16px;
  font-size: 10px; letter-spacing: 0.24em; color: var(--xk-ink);
  background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi));
  padding: 4px 12px; border-radius: 14px;
}
.thumb {
  width: 76px; height: 92px; flex: none; border-radius: 14px; overflow: hidden;
  border: 1px solid var(--xk-gold-line); background: #1c1610;
  display: flex; align-items: center; justify-content: center;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.thumb-ph { font-size: 12px; letter-spacing: 0.3em; color: var(--xk-gold-dim); }
.info { flex: 1; min-width: 0; }
.info .no { font-size: 10px; letter-spacing: 0.24em; color: var(--xk-gold-dim); }
.info .nm { font-family: 'Noto Serif SC', serif; font-size: 18px; color: var(--xk-gold-hi); margin: 3px 0; }
.info .why { font-size: 12px; color: var(--xk-mut); line-height: 1.7; }
.pct {
  flex: none; font-family: 'Noto Serif SC', serif; font-style: italic;
  font-size: 24px; color: var(--xk-gold); text-align: right;
}
.pct small { display: block; font-style: normal; font-size: 9px; letter-spacing: 0.2em; color: var(--xk-mut); }
/* 发色区与 CTA 作为一组吸底（无色板数据时 CTA 自身吸底，布局同改造前） */
/* margin-top:auto 仍在（把发色区顶到滚动区底部）；原先的 .color-pick + .go 已失效——
   CTA 移出 .m-scroll 后不再是它的兄弟，间距统一由 .go 自己的 margin-top 给 */
.color-pick { width: min(88vw, 560px); margin-top: auto; padding-top: 16px; }
.cp-title {
  font-size: 11px; letter-spacing: 0.24em; color: var(--xk-gold-dim);
  display: flex; align-items: baseline; gap: 10px;
}
.cp-title small { font-size: 10px; letter-spacing: 0.1em; color: var(--xk-mut); }
.chips {
  display: flex; gap: 8px; margin-top: 10px; padding-bottom: 6px;
  overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none;
}
.chips::-webkit-scrollbar { display: none; }
.chip {
  flex: none; display: flex; align-items: center; gap: 7px;
  height: 38px; padding: 0 14px; border-radius: 20px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: transparent;
  color: var(--xk-mut); font-size: 12px; letter-spacing: 0.08em;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease, color 160ms ease;
}
.chip:active { transform: scale(0.96); }
.chip.on { border-color: var(--xk-gold); color: var(--xk-gold-hi); }
.sw {
  width: 16px; height: 16px; border-radius: 50%;
  border: 1px solid var(--xk-gold-line);
  object-fit: cover; flex: none;
}
.sw.origin { background: conic-gradient(var(--xk-ink-2), var(--xk-gold-dim), var(--xk-ink-2)); }
.chip-tag { margin-left: 7px; font-size: 10px; color: var(--xk-gold-dim); letter-spacing: 0.1em; }

/* ── 生成场景滑动选择器（居中卡放大，仅示意不参与合成） ── */
.scene-pick { width: min(88vw, 560px); margin-top: auto; --scard-w: 118px; }
.color-pick + .scene-pick { margin-top: 20px; }
/* 分类分段控件（职场专业 / 长辈生活）：金色胶囊，选中填金 */
.scene-cats { display: flex; gap: 8px; margin-top: 12px; }
.scene-cat {
  flex: none; height: 34px; padding: 0 18px; border-radius: 18px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: transparent;
  color: var(--xk-mut); font-size: 13px; letter-spacing: 0.06em;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease,
    color 160ms ease, background 160ms ease;
}
.scene-cat:active { transform: scale(0.96); }
.scene-cat.on {
  border-color: var(--xk-gold); color: var(--xk-ink);
  background: linear-gradient(110deg, var(--xk-gold-dim), var(--xk-gold) 55%, var(--xk-gold-hi));
}
.scene-cats + .scene-track { margin-top: 10px; }
.scene-track {
  /* 必须定位：让 .scard 的 offsetParent = 本容器，否则 offsetLeft 相对更上层的 xk-root(fixed)
     测量，混入常量偏移，syncScene/centerScene 的居中数学在宽屏错位（2026-07-09 对抗性审查修复） */
  position: relative;
  display: flex; gap: 4px; margin-top: 12px; padding-bottom: 4px;
  padding-inline: calc((100% - var(--scard-w)) / 2);
  overflow-x: auto; scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch; scrollbar-width: none;
}
.scene-track::-webkit-scrollbar { display: none; }
.scard {
  flex: none; width: var(--scard-w); scroll-snap-align: center;
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 0; border: none; background: transparent; cursor: pointer;
  transform: scale(0.82); opacity: 0.5; transform-origin: center bottom;
  transition: transform 240ms cubic-bezier(0.23, 1, 0.32, 1),
    opacity 240ms cubic-bezier(0.23, 1, 0.32, 1);
}
.scard.on { transform: scale(1); opacity: 1; }
.scard-pic {
  width: 100%; aspect-ratio: 3 / 4; border-radius: 16px; overflow: hidden;
  border: 1px solid var(--xk-gold-line); background: var(--xk-ink-2);
  display: flex; align-items: center; justify-content: center;
  transition: border-color 240ms ease, box-shadow 240ms ease, transform 120ms ease-out;
}
.scard.on .scard-pic { border-color: var(--xk-gold); box-shadow: 0 8px 28px rgba(232, 196, 121, 0.22); }
.scard:active .scard-pic { transform: scale(0.97); }
.scard-pic img { width: 100%; height: 100%; object-fit: cover; }
.scard-ph {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  background:
    radial-gradient(circle at 50% 32%, rgba(232, 196, 121, 0.16), rgba(232, 196, 121, 0.02) 62%),
    linear-gradient(160deg, var(--xk-ink-2), var(--xk-ink));
}
.scard-emoji { font-size: 34px; opacity: 0.6; filter: saturate(0.8); }
.scard-cap { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.scard-lb { font-family: 'Noto Serif SC', serif; font-size: 15px; color: var(--xk-mut); transition: color 240ms ease; }
.scard.on .scard-lb { color: var(--xk-gold-hi); }
.scard-tg { font-size: 10px; letter-spacing: 0.14em; color: var(--xk-gold-dim); }

@media (prefers-reduced-motion: reduce) {
  .scard { transition: opacity 200ms ease; transform: none; opacity: 0.55; }
  .scard.on { transform: none; opacity: 1; }
  .scard:active .scard-pic { transform: none; }
}

/* 64px 对齐首屏主 CTA 的分量：这是全流程的终点动作，52px 的通用按钮压不住。
   第二道墨色阴影（向上偏移 + 扩散）把滚动内容在按钮上沿柔化掉——否则卡片被拦腰切断，
   看起来像内容被裁没了，而不是「还能往下滑」 */
/* 出图风格：必选项，横向三档。压在生成按钮上方——客户的决策顺序是「选发型 → 定风格 → 生成」，
   放在按钮之后会被 .go 的上沿阴影盖住，放在卡片区之内又会跟着滚出视野 */
.variant-row {
  flex: none; display: flex; align-items: center; justify-content: center;
  gap: 12px; margin-top: 14px;
}
.variant-lb { font-size: 11px; letter-spacing: 0.2em; color: var(--xk-gold-dim); }
.variant-opts { display: flex; gap: 8px; }
.variant-opt {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 8px 16px; border-radius: 12px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.03);
}
.variant-opt.sel {
  border-color: var(--xk-gold);
  background: rgba(232, 196, 121, 0.12);
  box-shadow: inset 0 0 16px rgba(232, 196, 121, 0.14);
}
.vo-lb { font-size: 14px; color: var(--xk-paper); }
.variant-opt.sel .vo-lb { color: var(--xk-gold-hi); }
.vo-hint { font-size: 10px; letter-spacing: 0.06em; color: var(--xk-mut); }
.go {
  flex: none; margin-top: 16px; margin-bottom: 1vh; min-width: 300px; height: 64px; font-size: 17px;
  box-shadow: 0 6px 26px rgba(232, 196, 121, 0.3), 0 -14px 22px 18px var(--xk-ink);
}
.go:disabled { opacity: 0.4; }
/* ── 手机竖屏（≤560px）── 横向留白让给内容：88vw 在 390px 屏上只剩 343px，
   而卡片内 缩略图76 + 匹配度48 + 两道 gap 是固定开销，发型名与推荐理由被压到不足 160px */
@media (max-width: 560px) {
  /* 三档横排 + 前缀标签在 390px 屏上会挤成两行错位：标签独占一行，选项行居中铺开 */
  .variant-row { flex-direction: column; gap: 6px; margin-top: 10px; }
  .variant-opt { padding: 7px 12px; }

  .matching { padding: 1.5vh 4vw 2vh; }
  .reading, .cards, .color-pick, .scene-pick { width: 100%; }
  .go { min-width: 0; width: 100%; height: 56px; font-size: 16px; }
  .info .nm { font-size: 17px; }
  .pct { font-size: 21px; }
  .lib-head { padding: 14px 16px; }
  .lib-title { font-size: 16px; }
  .lib-grid { padding: 14px 16px; gap: 10px; }
  .lib-nm { font-size: 13px; padding: 0 6px 12px; }
}
</style>
