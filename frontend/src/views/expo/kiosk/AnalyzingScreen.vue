<template>
  <div class="analyzing">
    <p class="xk-eyebrow">DISCOVER YOUR SIGNATURE</p>
    <h2 class="xk-title">读懂气质，找到适合您的美</h2>
    <p class="xk-sub" role="status">正在分析您的照片，请稍候</p>
    <div class="scan-stage">
      <img v-if="photoUrl" :src="photoUrl" class="photo" alt="" />

      <div class="scanline" />
    </div>

    <div class="readouts">
      <div v-for="(chip, i) in chips" :key="chip.k" class="chip" :style="{ animationDelay: `${0.4 + i * 0.5}s` }">
        <span class="k">{{ chip.k }}</span>
        <span class="v">{{ chip.v }}</span>
      </div>
    </div>

    <div class="proof">
      <transition name="fade" mode="out-in">
        <p :key="proofIndex">{{ ATELIER_NOTES[proofIndex] }}</p>
      </transition>
    </div>

    <div class="stages">
      <span class="on">解析面容</span><span>甄选发型</span><span>生成效果</span>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'

const flow = inject('tryonFlow')

const photoUrl = computed(() => flow.session.value?.photo_url || '')

const FACE_LABELS = { oval: '椭圆脸', round: '圆脸', square: '方脸', heart: '心形脸', long: '长脸', diamond: '菱形脸' }
const DEPTH_LABELS = { fair: '白皙', light: '浅肤', medium: '自然', tan: '健康小麦' }
const TONE_LABELS = { warm: '暖调', cool: '冷调', neutral: '中性调' }
const LENGTH_LABELS = { short: '短发', bob: '波波头', shoulder: '及肩', long: '长发' }

// 分析未出前展示占位脉冲文案；出结果后逐条揭晓真实标签（只呈现正面特征）
const chips = computed(() => {
  const a = flow.analysis.value
  if (!a) {
    return [
      { k: '脸型', v: '识别中 …' },
      { k: '肤色', v: '识别中 …' },
      { k: '气质类型', v: '识别中 …' },
      { k: '适配发长', v: '识别中 …' },
    ]
  }
  return [
    { k: '脸型', v: FACE_LABELS[a.face_shape] || a.face_shape || '—' },
    { k: '肤色', v: `${TONE_LABELS[a.skin_tone?.undertone] || ''} · ${DEPTH_LABELS[a.skin_tone?.depth] || ''}` },
    { k: '气质类型', v: a.temperament || '—' },
    { k: '适配发长', v: LENGTH_LABELS[a.suit_length] || a.suit_length || '—' },
  ]
})

// 等待文案只提供体验引导，不把占位内容呈现为真实客户证言。
const ATELIER_NOTES = [
  '接下来，您可以挑选发型、发色与生成场景。',
  '轻触喜欢的发型，看看它与您的气质如何相衬。',
  '效果生成后，可以拖动对比，并扫码保存到手机。',
]
const proofIndex = ref(0)
let proofTimer = null
onMounted(() => {
  proofTimer = setInterval(() => {
    proofIndex.value = (proofIndex.value + 1) % ATELIER_NOTES.length
  }, 5000)
})
onBeforeUnmount(() => clearInterval(proofTimer))
</script>

<style scoped>
.analyzing { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; align-items: center; padding: 28px 5vw; }
.scan-stage { flex: none; position: relative; width: min(60vw, 360px); height: clamp(230px, 36vh, 440px); border-radius: 180px 180px 12px 12px; overflow: hidden; background: var(--xk-surface); margin-top: 26px; border: 7px solid var(--xk-ink-2); outline: 1px solid var(--xk-gold-line); }
.photo { width: 100%; height: 100%; object-fit: cover; }
.scanline { position: absolute; inset: 0; pointer-events: none; background: linear-gradient(120deg, transparent 25%, var(--xk-glow) 50%, transparent 75%); animation: scan-light 3.6s ease-in-out infinite; }
@keyframes scan-light { from { transform: translateX(-120%); } to { transform: translateX(120%); } }
.readouts { width: min(100%, 760px); display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 26px; }
.chip { padding: 12px; text-align: center; border-bottom: 1px solid var(--xk-gold-line); animation: chip-in 480ms var(--xk-ease) backwards; }
.k { display: block; color: var(--xk-mut); font-size: 12px; margin-bottom: 8px; }
.v { font-size: 16px; color: var(--xk-paper); }
@keyframes chip-in { from { opacity: 0; transform: translateY(8px); } }
.proof { color: var(--xk-mut); text-align: center; font-size: 14px; min-height: 68px; max-width: 640px; margin-top: 18px; }
.stages { display: flex; gap: 28px; color: var(--xk-mut); font-size: 13px; }
.stages .on { color: var(--xk-gold); border-bottom: 1px solid var(--xk-gold); padding-bottom: 8px; }
.fade-enter-active, .fade-leave-active { transition: opacity 300ms ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
@media (max-width: 600px) { .readouts { grid-template-columns: repeat(2, minmax(0, 1fr)); } .scan-stage { width: 65vw; } .analyzing { padding-top: 22px; } }
</style>
