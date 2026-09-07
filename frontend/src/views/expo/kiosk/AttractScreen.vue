<template>
  <section class="attract" aria-labelledby="atelier-title">
    <div class="hero-photo" aria-hidden="true"><img :src="hero" alt="" fetchpriority="high" /><div class="soft-light" /></div>
    <div class="hero-content">
      <p class="eyebrow">THE PRIVATE ATELIER <span>莱莎 · 私享造型</span></p>
      <h1 id="atelier-title">天生是您，<br /><span>美得更从容</span></h1>
      <p class="hero-description">找到与气质相衬的发型，<br />看见属于自己的精致与从容。</p>
      <div class="hero-actions">
        <button class="xk-btn cta" @click="$emit('start', 'tryon')">AI 试戴新发型 <span aria-hidden="true">→</span></button>
        <button class="xk-btn ghost cta2" @click="$emit('start', 'scene')">已佩戴 · 拍场景大片 <span aria-hidden="true">↗</span></button>
        <button class="member-link" @click="memberOpen = true">首发合作与价格 <span aria-hidden="true">›</span></button>
      </div>
    </div>
    <div class="hero-foot"><span>因你而美 · 自然有型</span><small>人像为 AI 示意素材</small></div>
    <LaunchOfferDialog :open="memberOpen" @close="memberOpen = false" />
  </section>
</template>

<script setup>
import { ref } from 'vue'
import hero from '@/assets/expo/atelier-hero.webp'
import LaunchOfferDialog from './LaunchOfferDialog.vue'
defineEmits(['start'])
const memberOpen = ref(false)
</script>

<style scoped>
.attract { position: relative; flex: 1; min-height: 0; overflow-y: auto; isolation: isolate; display: flex; flex-direction: column; justify-content: center; justify-content: safe center; background: var(--xk-surface); }
.hero-photo { position: absolute; inset: 0; z-index: -1; overflow: hidden; }
.hero-photo img { width: 100%; height: 100%; object-fit: cover; object-position: center; animation: portrait-arrive 1200ms var(--xk-ease) backwards; }
.hero-photo::after { content: ''; position: absolute; inset: 0; background: linear-gradient(90deg, var(--xk-ink) 0%, var(--xk-glow) 28%, var(--xk-transparent) 65%); }
.soft-light { position: absolute; z-index: 1; inset: -20%; pointer-events: none; background: linear-gradient(115deg, transparent 30%, var(--xk-glow) 50%, transparent 67%); animation: warm-light 1600ms var(--xk-ease) both; }
.hero-content { width: min(52%, 760px); padding: 48px clamp(30px, 6vw, 110px) 80px; }
.eyebrow { margin: 0 0 38px; font-size: 12px; letter-spacing: 0.22em; color: var(--xk-gold-dim); }
.eyebrow span { display: block; margin-top: 12px; letter-spacing: 0.25em; }
h1 { font: 500 clamp(38px, 5.3vw, 80px)/1.35 var(--xk-serif); letter-spacing: 0.03em; margin: 0; text-wrap: nowrap; animation: copy-arrive 800ms 70ms var(--xk-ease) backwards; }
h1 span { display: inline-block; padding-left: 0.8em; }
.hero-description { color: var(--xk-gold-dim); line-height: 1.9; margin: 26px 0 32px; font-size: 16px; animation: copy-arrive 800ms 140ms var(--xk-ease) backwards; }
.hero-actions { max-width: 420px; display: flex; flex-direction: column; gap: 12px; animation: copy-arrive 800ms 210ms var(--xk-ease) backwards; }
.cta, .cta2 { justify-content: space-between; width: 100%; min-height: 58px; }
.cta span, .cta2 span { font-size: 23px; }
.cta2 { background: var(--xk-glow); }
.member-link { min-height: 48px; border: 0; background: transparent; color: var(--xk-gold-dim); font-size: 14px; cursor: pointer; letter-spacing: 0.09em; }
.member-link span { margin-left: 8px; }
.hero-foot { pointer-events: none; position: absolute; left: 0; right: 0; bottom: 0; padding: 20px clamp(24px, 4vw, 60px); display: flex; justify-content: space-between; font-size: 12px; color: var(--xk-gold-dim); letter-spacing: 0.1em; background: linear-gradient(0deg, var(--xk-ink), var(--xk-transparent)); }
.hero-foot small { font-size: 11px; }
@keyframes warm-light { from { opacity: 0; transform: translateX(-50%); } 35% { opacity: 0.55; } to { opacity: 0; transform: translateX(50%); } }
@keyframes portrait-arrive { from { transform: scale(1.045); opacity: 0.6; } }
@keyframes copy-arrive { from { opacity: 0; transform: translateY(12px); } }
@media (max-aspect-ratio: 1/1) {
  .attract { justify-content: flex-end; justify-content: safe flex-end; min-height: 0; }
  .hero-photo img { object-position: 72% top; }
  .hero-photo::after { background: linear-gradient(0deg, var(--xk-ink) 0%, var(--xk-ink) 18%, var(--xk-transparent) 70%); }
  .hero-content { width: 100%; padding: 30px 8vw 54px; margin-top: min(35vh, 360px); }
  .eyebrow { margin-bottom: 14px; font-size: 11px; }
  .eyebrow span { display: none; }
  h1 { font-size: clamp(40px, 6.6vw, 68px); }
  .hero-description { margin: 14px 0 22px; font-size: 15px; }
  .hero-description br { display: none; }
  .hero-actions { max-width: none; }
  .hero-foot { padding: 12px 8vw; }
}
@media (max-width: 600px) {
  .hero-content { padding: 20px 24px 38px; margin-top: 26vh; }
  .hero-description { margin: 10px 0 18px; font-size: 14px; }
  .hero-actions { gap: 8px; }
  .cta, .cta2 { min-height: 50px; }
  .hero-foot { padding: 10px 24px; font-size: 10px; }
  h1 { font-size: 40px; }
}
@media (max-height: 600px) and (min-aspect-ratio: 1/1) {
  .attract { justify-content: flex-start; }
  .hero-content { flex: none; padding-top: 24px; padding-bottom: 16px; width: 60%; }
  .hero-foot { position: static; flex: none; width: 100%; padding-top: 8px; padding-bottom: 8px; }
  .eyebrow { margin-bottom: 12px; }
  .eyebrow span, .hero-description { display: none; }
  h1 { font-size: 38px; margin-bottom: 16px; }
  .hero-actions { gap: 6px; }
  .cta, .cta2 { min-height: 48px; padding: 8px 18px; }
}
</style>
