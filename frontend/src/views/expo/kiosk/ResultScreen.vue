<template>
  <section class="result">
    <div v-if="!current" class="waiting" role="status" aria-live="polite">
      <p class="xk-eyebrow">YOUR PERSONAL PORTRAIT</p>
      <div class="halo-wrap" aria-hidden="true">
        <img v-if="photoUrl" :src="photoUrl" class="waiting-photo" alt="" />
        <div class="halo" /><div class="ring" />
      </div>
      <h2 class="wait-title">{{ isScene ? '您的专属大片，正在成形' : '更适合您的造型，正在成形' }}</h2>
      <p class="wait-sub">{{ flow.generating.value ? 'AI 精细处理中，请稍候' : '本次生成暂未完成，可重试或请顾问协助' }}</p>
      <Transition name="phrase" mode="out-in"><div v-if="flow.generating.value" class="phrase" :key="phraseIdx">{{ phrases[phraseIdx] }}</div></Transition>
      <div v-if="flow.generating.value" class="bar" aria-hidden="true"><i /></div>
      <div class="stages"><span>{{ isScene ? '佩戴实拍' : '解析面容' }}</span><span>{{ isScene ? '场景甄选' : '甄选发型' }}</span><span class="on">生成效果</span></div>
      <Transition name="bcard" mode="out-in"><div class="brand-card" :key="brandIdx"><b>{{ BRAND_CARDS[brandIdx].tag }}</b><span>{{ BRAND_CARDS[brandIdx].text }}</span></div></Transition>
      <div v-if="!flow.generating.value" class="wait-actions"><button class="xk-btn ghost" @click="retryGenerate">重新生成</button><button class="xk-btn" @click="flow.openSales()">呼叫顾问</button></div>
    </div>
    <template v-else>
      <header class="result-heading"><p class="xk-eyebrow">MADE FOR YOUR MOMENT</p><h2 class="xk-title">这一刻，更喜欢自己</h2></header>
      <div class="result-layout">
        <div class="portrait-area">
          <div ref="stageEl" class="stage" @pointerdown="dragStart" @pointermove="dragMove" @pointerup="dragEnd" @pointercancel="dragEnd" @lostpointercapture="dragEnd">
            <img :src="photoUrl" class="img before" alt="佩戴前" draggable="false" />
            <Transition name="swap"><img :key="`${current.id}-${imageAttempt}`" :src="resultImageUrl" class="img after" :class="{ revealed: revealReady }" :data-result-id="current.id" :data-image-attempt="imageAttempt" @load="revealImage" @error="imageFailed" :style="{ clipPath: `inset(0 0 0 ${sliderPct}%)` }" alt="佩戴后" draggable="false" /></Transition>
            <div v-if="!revealReady" class="image-status" role="status" @pointerdown.stop>
              <span>{{ imageError ? '效果图加载失败，请重试' : '正在加载您的效果图…' }}</span>
              <button v-if="imageError" class="xk-btn" @click.stop="retryImage">重新加载图片</button>
            </div>
            <div v-if="revealReady" :key="`reveal-${current.id}`" class="reveal-light" aria-hidden="true" />
            <div v-if="revealReady" class="divider" :style="{ left: `${sliderPct}%` }" aria-hidden="true"><span class="knob">‹ ›</span></div>
            <span v-if="revealReady" class="lbl b">{{ isScene ? '现场实拍' : '佩戴前' }}</span><span v-if="revealReady" class="lbl a">{{ isScene ? '场景大片' : '佩戴后' }}</span>
            <button v-if="revealReady" class="zoom-btn" aria-label="查看完整效果图" @pointerdown.stop @click="lightboxOpen = true">查看大图 ↗</button>
          </div>
          <label v-if="revealReady" class="compare-control"><span>拖动，看看变化</span><input v-model.number="sliderPct" type="range" min="8" max="92" aria-label="前后效果对比" @input="flow.touch()" /></label>
        </div>
        <div class="result-details">
          <Transition name="pill"><div v-if="flow.generating.value" class="gen-pill" role="status"><i />正在合成新选择 · 完成后自动切换</div></Transition>
          <div class="meta"><span class="nm">{{ current.wig_name || (isScene ? '专属场景大片' : '专属试戴') }}</span><span class="md">{{ metaLine }}</span></div>
          <div class="meta-tags"><span v-if="current.hair_color" class="color-tag"><i :style="{ background: current.hair_color.hex || 'var(--xk-gold)' }" />{{ current.hair_color.name }}</span><span v-if="current.scene" class="color-tag">{{ current.scene.label }}</span></div>
          <div class="result-thumbs" aria-label="切换试戴效果"><button v-for="(r, i) in doneList" :key="r.id" :aria-label="`查看第 ${i + 1} 张效果`" :aria-pressed="currentIndex === i" :class="{ on: currentIndex === i }" @click="currentIndex = i; flow.touch()"><img :src="r.display_url || r.image_url" @error="fallbackThumbnail($event, r)" alt="" /><span>{{ i + 1 }}</span></button></div>
          <div class="reacts"><button class="react" :class="{ liked: current.reaction === 'loved' }" :aria-pressed="current.reaction === 'loved'" @click="flow.react(current.id, 'loved')">♡ 心动</button><button class="react" :class="{ liked: current.reaction === 'soso' }" :aria-pressed="current.reaction === 'soso'" @click="flow.react(current.id, 'soso')">再看看</button></div>
          <div v-if="shareUrl" class="share-row"><div class="qr-card"><canvas ref="qrEl" width="112" height="112" aria-label="扫码保存效果图" /><div class="qr-txt"><b>扫码带走效果</b><span>存入手机，随时回看</span><a :href="shareUrl" target="_blank" rel="noopener">打开分享页 ↗</a></div></div></div>
          <div class="actions"><button v-if="isScene" class="xk-btn ghost" :disabled="flow.generating.value" @click="flow.reselectScenes()">再选场景</button><button v-else class="xk-btn ghost" :disabled="flow.generating.value" @click="flow.backToMatching()">试试其他发型</button><button class="xk-btn" @click="flow.openSales()">请顾问过来</button></div>
          <button class="xk-btn ghost print" @click="printCurrent">打印这张 <span aria-hidden="true">↗</span></button>
          <div v-if="!isScene" class="evidence"><b>久戴如新</b><span>同款保鳞原生辫发 · 12-18 个月光泽如初 · SGS 安全认证</span></div><div v-else class="evidence"><b>专属大片</b><span>以您此刻的佩戴状态生成 · 扫码带走随时分享</span></div>
          <p class="result-note">AI 试戴效果仅供参考，请以实际佩戴为准</p>
        </div>
      </div>
      <Transition name="lb"><div v-if="lightboxOpen && current" class="lightbox" role="dialog" aria-modal="true" aria-label="完整效果图" @click="lightboxOpen = false"><img :src="resultImageUrl" class="lb-img" alt="完整效果图" /><button class="lb-close" aria-label="关闭">✕</button><span class="lb-hint">轻触任意处返回</span></div></Transition>
    </template>
  </section>
</template>
<script setup>
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { publicOrigin } from './publicUrl'

const flow = inject('tryonFlow')

// 品牌卡文案：只用话术库既有硬证据，禁用词红线（便宜/划算/性价比/打折/薅羊毛）已核
const BRAND_CARDS = [
  { tag: '匠心选材', text: '22 岁以下原生辫发 · 五道甄选：年龄 / 形态 / 垂感 / 弹性 / 色泽' },
  { tag: '保鳞工艺', text: '不烫不染不酸洗 · 毛鳞片完整如初' },
  { tag: '安全认证', text: 'SGS 安全认证 · 无甲醛无重金属 · 网料医用级亲肤' },
  { tag: '久戴如新', text: '正常保养下佩戴寿命 12-18 个月 · 光泽如初' },
  { tag: '品牌沉淀', text: '1992 年创立 · 33 年专注健康假发 · 远销 164 个国家' },
  { tag: '至臻系列', text: '全手工钩织 · 一顶一匠 · 为重要场合而生' },
]
const brandIdx = ref(0)

// 等待中轮换的"专业工序"语句：标题说真话（正在生成），这排短语堆专业质感。
// 按模式给不同工序词 + 通用词，2.6s 换一句、随机不重复。
const PHRASE_POOL = {
  tryon: ['正在渲染发丝细节', '正在匹配肤色与发色', '正在优化面部融合', '正在校准佩戴贴合度'],
  scene: ['正在生成 AI 场景', '正在设计服饰形象', '正在布置场景光线', '正在构建空间氛围'],
  common: ['正在调整光影效果', '正在润色整体色调', '正在精修画面细节', '正在校准色彩平衡', '正在合成高清成片'],
}
const phrases = computed(() => [
  ...(flow.mode.value === 'scene' ? PHRASE_POOL.scene : PHRASE_POOL.tryon),
  ...PHRASE_POOL.common,
])
const phraseIdx = ref(0)
function nextPhrase() {
  const n = phrases.value.length
  if (n <= 1) return
  let i = phraseIdx.value
  while (i === phraseIdx.value) i = Math.floor(Math.random() * n)
  phraseIdx.value = i
}

let brandTimer = null
let phraseTimer = null
function syncWaitTimers(waiting) {
  if (waiting) {
    if (!brandTimer) brandTimer = setInterval(() => {
      brandIdx.value = (brandIdx.value + 1) % BRAND_CARDS.length
    }, 6000)
    if (!phraseTimer) phraseTimer = setInterval(nextPhrase, 2600)
  } else {
    if (brandTimer) { clearInterval(brandTimer); brandTimer = null }
    if (phraseTimer) { clearInterval(phraseTimer); phraseTimer = null }
  }
}
onBeforeUnmount(() => syncWaitTimers(false))

const photoUrl = computed(() => flow.session.value?.photo_url || '')
const doneList = computed(() => flow.doneResults.value)
const doneCount = computed(() => doneList.value.length)
const isScene = computed(() => flow.mode.value === 'scene')

const currentIndex = ref(0)
const current = computed(() => doneList.value[currentIndex.value] || null)
const lightboxOpen = ref(false)
// The reveal follows the actual image load, never a guessed generation duration.
const revealReady = ref(false)
const imageError = ref(false)
const originalFallback = ref(false)
const imageAttempt = ref(0)
const resultImageUrl = computed(() => originalFallback.value
  ? current.value?.image_url : current.value?.display_url || current.value?.image_url)
watch(() => current.value?.id, () => {
  revealReady.value = false
  imageError.value = false
  originalFallback.value = false
  imageAttempt.value = 0
}, { flush: 'sync' })
function isCurrentImage(event) {
  return event.target.dataset.resultId === String(current.value?.id)
    && event.target.dataset.imageAttempt === String(imageAttempt.value)
}
function revealImage(event) {
  if (!isCurrentImage(event)) return
  imageError.value = false
  revealReady.value = true
}
function imageFailed(event) {
  if (!isCurrentImage(event)) return
  if (!originalFallback.value && current.value?.display_url && current.value?.image_url && current.value.image_url !== current.value.display_url) {
    originalFallback.value = true
  } else imageError.value = true
}
function fallbackThumbnail(event, result) {
  if (result.image_url && event.target.getAttribute('src') !== result.image_url) event.target.src = result.image_url
}
function retryImage() {
  imageError.value = false
  originalFallback.value = false
  revealReady.value = false
  imageAttempt.value++
  flow.touch()
}
// 成品被清空（重新生成/清场）时收起灯箱，避免空引用的黑屏遮罩
watch(current, v => { if (!v) lightboxOpen.value = false })
watch(() => !current.value, syncWaitTimers, { immediate: true })
// 新成品出炉自动切到最新一张（回头再生成第二款时不停留在旧图）
watch(doneCount, (n, old) => {
  if (n > (old || 0)) currentIndex.value = n - 1
})
const metaLine = computed(() => {
  const pos = `${currentIndex.value + 1}/${doneCount.value}`
  return current.value?.model_no ? `${current.value.model_no} · ${pos}` : pos
})

function retryGenerate() {
  if (isScene.value) flow.reselectScenes()
  else flow.generate()
}

// 一键打印：把当前合成「原图」（非压缩展示版，保打印清晰度）交给平板 APK 原生桥，
// 由它存进系统相册并确认后再打开打印 App；非 APK 环境（普通浏览器）兜底新开图便于取用
function printCurrent() {
  const r = current.value
  if (!r?.image_url) return
  const url = r.image_url.startsWith('http') ? r.image_url : location.origin + r.image_url
  const bridge = window.Android
  if (bridge && typeof bridge.printPhoto === 'function') {
    bridge.printPhoto(url)
  } else {
    window.open(url, '_blank')
  }
}

// ── 前后对比滑块 ──
const stageEl = ref(null)
const sliderPct = ref(46)
let dragging = false
function dragStart(e) {
  if (e.button !== 0) return
  dragging = true
  e.currentTarget.setPointerCapture(e.pointerId)
  updatePct(e)
}
function dragMove(e) { if (dragging) updatePct(e) }
function dragEnd() { dragging = false }
function updatePct(e) {
  const rect = stageEl.value.getBoundingClientRect()
  const pct = ((e.clientX - rect.left) / rect.width) * 100
  sliderPct.value = Math.min(92, Math.max(8, pct))
}

// ── 分享二维码（qrcode 动态引入，失败静默降级为不显示） ──
const qrEl = ref(null)
// http 降级规则（客户手机不认展位自签证书）见 publicUrl.js 顶部注释；扫码上传二维码共用同一 helper
const shareUrl = computed(() => {
  if (!current.value?.short_code) return ''
  return `${publicOrigin()}/api/expo/share/${current.value.short_code}`
})
watch([shareUrl, qrEl], async () => {
  if (!shareUrl.value) return
  await nextTick()
  if (!qrEl.value) return
  try {
    const QRCode = (await import('qrcode')).default
    // 墨色码点 + 暖米底：黑金语系里可扫性最稳的组合（反色码部分扫码器不认）
    await QRCode.toCanvas(qrEl.value, shareUrl.value, {
      width: 112, margin: 1,
      color: {
        dark: getComputedStyle(qrEl.value).getPropertyValue('--xk-button').trim(),
        light: getComputedStyle(qrEl.value).getPropertyValue('--xk-ink-2').trim(),
      },
    })
  } catch (e) { /* 依赖缺失时不显示二维码，不阻断流程 */ }
}, { immediate: true })
</script>

<style scoped src="./styles/result.css"></style>
