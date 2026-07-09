<template>
  <div class="matching">
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
        v-for="(match, i) in flow.matches.value" :key="match.wig_id"
        class="card" :class="{ zhizhen: match.series === 'zhizhen', sel: flow.selectedWigId.value === match.wig_id }"
        :style="{ animationDelay: `${0.15 + i * 0.25}s` }"
        @click="pickWig(match.wig_id)"
      >
        <span v-if="match.series === 'zhizhen'" class="badge">至臻系列</span>
        <div class="thumb">
          <img v-if="match.cover_url" :src="match.cover_url" alt="" />
          <span v-else class="thumb-ph">莱莎</span>
        </div>
        <div class="info">
          <div class="no">{{ match.model_no }}</div>
          <div class="nm">{{ match.name }}</div>
          <div class="why">{{ match.reason }}</div>
        </div>
        <div class="pct">{{ Math.round(match.score) }}<small>匹配</small></div>
        <span class="tick" :class="{ on: flow.selectedWigId.value === match.wig_id }">✓</span>
      </div>
    </div>

    <button v-if="flow.canSwapMatches.value" class="swap" @click="flow.swapMatches()">
      换一批候选 ⟳
    </button>

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
        ><img v-if="c.swatch_url" class="sw" :src="c.swatch_url" alt="" />
          <i v-else class="sw" :style="{ background: c.hex || 'var(--xk-ink-2)' }" />{{ c.name }}</button>
      </div>
    </div>

    <div v-if="flow.tryonScenes.value.length" class="scene-pick">
      <div class="cp-title">生成场景<small>左右滑动选择 · 场景图仅示意</small></div>
      <div ref="trackRef" class="scene-track" @scroll="onSceneScroll">
        <button
          v-for="(s, i) in flow.tryonScenes.value" :key="s.key"
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

    <button class="xk-btn go" :disabled="!flow.selectedWigId.value" @click="flow.generate()">
      生成我的试戴效果
    </button>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

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
  flow.selectedWigId.value = id
  flow.touch()
}

function pickColor(id) {
  flow.selectedColorId.value = id
  flow.touch()
}

// ── 生成场景滑动选择器（居中卡=选中；原生 scroll-snap 吃触摸惯性，选中卡放大） ──
const trackRef = ref(null)
const sceneActive = ref(0)
let scRaf = 0

// 占位卡图标（无示意图时用）；后台把实拍/AI 图丢进 uploads/expo/scenes/<key>.* 即替换为真图
const SCENE_EMOJI = {
  whitecollar: '💼', teacher: '📚', shopowner: '🛍️',
  civilservant: '🏛️', doctor: '🩺', home: '🛋️', gathering: '🥂',
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
  const key = flow.tryonScenes.value[best]?.key
  if (key && key !== flow.selectedTryonScene.value) {
    flow.selectedTryonScene.value = key
    flow.touch()
  }
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
  flow.loadHairColors()
  await flow.loadTryonScenes()
  await nextTick()
  // flow 已把默认选中设为第一个场景；把它瞬时居中（无动画），之后滑动/点击才平滑
  const el = trackRef.value
  if (!el) return
  const idx = flow.tryonScenes.value.findIndex(s => s.key === flow.selectedTryonScene.value)
  sceneActive.value = idx < 0 ? 0 : idx
  const card = el.querySelectorAll('.scard')[sceneActive.value]
  if (card) el.scrollLeft = cardCenterOffset(el, card)
})

onBeforeUnmount(() => { if (scRaf) cancelAnimationFrame(scRaf) })
</script>

<style scoped>
.matching { flex: 1; display: flex; flex-direction: column; align-items: center; padding: 2vh 6vw 3vh; overflow-y: auto; }
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
.color-pick { width: min(88vw, 560px); margin-top: auto; padding-top: 16px; }
.color-pick + .go { margin-top: 16px; }
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

.go { margin-top: auto; margin-bottom: 1vh; min-width: 300px; }
.scene-pick + .go { margin-top: 16px; }
.go:disabled { opacity: 0.4; }
</style>
