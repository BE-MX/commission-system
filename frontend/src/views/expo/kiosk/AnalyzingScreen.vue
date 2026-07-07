<template>
  <div class="analyzing">
    <div class="scan-stage">
      <img v-if="photoUrl" :src="photoUrl" class="photo" alt="" />
      <div class="grid" />
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
        <p :key="proofIndex">“{{ TESTIMONIALS[proofIndex].quote }}”<em> —— {{ TESTIMONIALS[proofIndex].who }}</em></p>
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

// 等待期社会证明：老客户证言轮播（正式素材由市场部提供后替换）
const TESTIMONIALS = [
  { quote: '这不像假发，像我三年前的自己。', who: '45 岁 · 企业管理者 · 莱莎老客户' },
  { quote: '开会的时候再也不会想头发的事了。', who: '莱莎老客户' },
  { quote: '第一次觉得贵，第二次只买莱莎。', who: '两年复购客户' },
]
const proofIndex = ref(0)
let proofTimer = null
onMounted(() => {
  proofTimer = setInterval(() => {
    proofIndex.value = (proofIndex.value + 1) % TESTIMONIALS.length
  }, 5000)
})
onBeforeUnmount(() => clearInterval(proofTimer))
</script>

<style scoped>
.analyzing { flex: 1; display: flex; flex-direction: column; align-items: center; padding: 0 6vw 3vh; }
.scan-stage {
  position: relative; width: min(64vw, 420px); flex: 1; min-height: 0; max-height: 46vh;
  border-radius: 24px; overflow: hidden;
  background: radial-gradient(60% 55% at 50% 45%, #2c251c, #15110c 75%);
}
.photo { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0.85; }
.grid {
  position: absolute; inset: 0; opacity: 0.16;
  background-image:
    linear-gradient(rgba(232, 196, 121, 0.5) 1px, transparent 1px),
    linear-gradient(90deg, rgba(232, 196, 121, 0.5) 1px, transparent 1px);
  background-size: 26px 26px;
}
.scanline {
  position: absolute; left: 0; right: 0; height: 80px; top: -90px;
  background: linear-gradient(180deg, transparent, rgba(232, 196, 121, 0.22) 45%, var(--xk-gold) 50%, rgba(232, 196, 121, 0.22) 55%, transparent);
  animation: scan 3.4s cubic-bezier(0.4, 0, 0.6, 1) infinite;
  mix-blend-mode: screen;
}
@keyframes scan { 0% { top: -90px; } 55%, 100% { top: 105%; } }
.readouts { width: min(64vw, 420px); display: flex; flex-direction: column; gap: 10px; margin-top: 18px; }
.chip {
  display: flex; justify-content: space-between; align-items: center;
  border: 1px solid var(--xk-gold-line); border-radius: 12px;
  padding: 12px 18px; background: rgba(232, 196, 121, 0.04);
  opacity: 0; transform: translateY(10px);
  animation: chip-in 0.7s ease forwards;
}
@keyframes chip-in { to { opacity: 1; transform: none; } }
.chip .k { font-size: 11px; letter-spacing: 0.26em; color: var(--xk-gold-dim); }
.chip .v { font-size: 14px; color: var(--xk-gold-hi); }
.proof {
  margin-top: 18px; min-height: 44px; max-width: 480px; text-align: center;
  font-size: 12px; color: var(--xk-mut); line-height: 1.8;
}
.proof em { font-style: normal; color: var(--xk-gold-dim); }
.fade-enter-active, .fade-leave-active { transition: opacity 0.6s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.stages { display: flex; gap: 30px; margin-top: 12px; font-size: 11px; letter-spacing: 0.2em; color: var(--xk-mut); }
.stages .on { color: var(--xk-gold); border-bottom: 1px solid var(--xk-gold); padding-bottom: 6px; }
</style>
