<template>
  <div class="matching">
    <div class="m-scroll">
      <p class="xk-eyebrow">CURATED FOR YOU</p>
      <h2 class="xk-title">为您甄选，恰好是您</h2>
      <div class="xk-sub">依据您的脸型与气质，为您推荐 {{ flow.matches.value.length }} 款 · 轻触选择</div>

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
        <button type="button"
          v-for="(match, i) in shownMatches" :key="match.wig_id"
          :aria-pressed="flow.selectedWigId.value === match.wig_id"
          class="card" :class="{ zhizhen: match.series === 'zhizhen', custom: match.custom, sel: flow.selectedWigId.value === match.wig_id }"
          :style="{ animationDelay: `${i * 0.07}s` }"
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
          <span class="tick" :class="{ on: flow.selectedWigId.value === match.wig_id }" aria-hidden="true">✓</span>
        </button>
      </div>

      <div class="match-actions">
        <button v-if="flow.canSwapMatches.value" class="swap" @click="doSwap">
          换一批候选 ⟳
        </button>
        <button class="swap lib-entry" @click="openLibrary">从发型库中选择其他款 ›</button>
      </div>

      <!-- 从发型库选择：全部启用发型网格，滑动挑一款 -->
      <div v-if="libraryOpen" class="lib-overlay" @click.self="libraryOpen = false">
        <div class="lib-panel" role="dialog" aria-modal="true" aria-label="从发型库选择">
          <div class="lib-head">
            <span class="lib-title">从发型库选择</span>
            <button class="lib-close" aria-label="关闭发型库" @click="libraryOpen = false">✕</button>
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

    <PromptVersionPicker />

    <button class="xk-btn go" :disabled="!flow.selectedWigId.value || !flow.promptVersionReady.value || flow.generating.value" @click="flow.generate()">
      生成我的试戴效果
    </button>
  </div>
</template>

<script setup>
import PromptVersionPicker from './PromptVersionPicker.vue'
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
  el.scrollTo({ left: cardCenterOffset(el, card), behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
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

<style scoped src="./styles/matching.css"></style>
