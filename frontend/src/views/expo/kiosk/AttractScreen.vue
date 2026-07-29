<template>
  <div class="attract">
    <div class="orbit-wrap">
      <div class="orbit"><i /></div>
      <div class="orbit o2"><i /></div>
      <img class="face" :src="logoGold" alt="莱莎 LESHINE" />
    </div>
    <div class="brand-name">
      <span class="en">L E S H I N E</span>
      莱 莎 · 健 康 假 发
    </div>
    <h2 class="slogan">AI 试戴大模型<br />门店<em>智能成交</em>系统</h2>
    <div class="line">一套门店引流与辅助成交工具</div>
    <button class="xk-btn cta" @click="$emit('start', 'tryon')">AI 试戴新发型</button>
    <button class="xk-btn ghost cta2" @click="$emit('start', 'scene')">
      已佩戴 · 拍场景大片
      <small>实拍生成商务 / 晚宴 / 旅行等场景效果</small>
    </button>
    <!-- 合作政策：面向门店老板的次级入口，不与体验主 CTA 争视觉权重 -->
    <button class="member-link" @click="memberOpen = true">首发合作与价格 ›</button>

    <LaunchOfferDialog :open="memberOpen" @close="memberOpen = false" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
// 品牌 LOGO 黑金重制版：原绿色 LOGO 经去底 + 亮度映射到主题金色阶（脚本处理，源图见品牌物料）
import logoGold from '@/assets/expo-logo-gold.png'
// 2026-07-28 起入口指向首发合作方案（2999 首发 / 1500 押金 7 天试用）；
// 年费旧方案封存于 MembershipDialog.vue，换回改此行即可
import LaunchOfferDialog from './LaunchOfferDialog.vue'

defineEmits(['start'])

const memberOpen = ref(false)
</script>

<style scoped>
.attract {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  /* safe center：小尺寸平板上内容超高时退化为顶对齐 + 滚动，
     不会像纯 center 那样把顶部（LOGO/品牌名）裁掉；不支持的内核忽略此行回退到上面的 center */
  justify-content: safe center;
  overflow-y: auto;
  gap: 26px;
  padding-bottom: 4vh;
}
/* 大平板竖屏下内容占比偏小、显空——整体放大约 1.35x，并解除 orbit 的 320px 上限 */
.orbit-wrap { position: relative; width: min(62vw, 460px); aspect-ratio: 1; }
.orbit {
  position: absolute; inset: 0; border-radius: 50%;
  border: 1px solid var(--xk-gold-line);
  animation: xk-spin 26s linear infinite;
}
.orbit.o2 { inset: 9%; border-style: dashed; opacity: 0.6; animation: xk-spin 18s linear infinite reverse; }
.orbit i {
  position: absolute; top: -3px; left: 50%;
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--xk-gold); box-shadow: 0 0 12px var(--xk-gold);
}
@keyframes xk-spin { to { transform: rotate(360deg); } }
.face {
  position: absolute; inset: 15%;
  width: 70%; height: 70%; object-fit: contain;
  filter: drop-shadow(0 0 22px rgba(232, 196, 121, 0.28));
  animation: breathe 4.5s ease-in-out infinite;
}
@keyframes breathe {
  0%, 100% { opacity: 0.82; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.035); }
}
.brand-name {
  display: flex; flex-direction: column; align-items: center; gap: 9px;
  margin-top: -4px;
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 22px; color: var(--xk-gold-hi);
  letter-spacing: 0.42em; text-indent: 0.42em; /* 补偿末字间距保证视觉居中 */
}
.brand-name .en {
  font-family: 'PingFang SC', sans-serif;
  font-size: 13px; letter-spacing: 0.6em; text-indent: 0.6em;
  color: var(--xk-gold-dim);
}
.slogan {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: clamp(34px, 7.4vw, 60px);
  font-weight: 600; text-align: center; line-height: 1.4; margin: 0;
}
.slogan em { font-style: italic; color: var(--xk-gold); }
.line { font-size: 16px; letter-spacing: 0.3em; color: var(--xk-mut); }
/* 覆盖全局 .xk-btn 尺寸（scoped [data-v] 特异性高于全局）：主 CTA 放大更醒目 */
.cta { position: relative; margin-top: 18px; height: 64px; padding: 0 58px; font-size: 18px; }
.cta::after {
  content: ''; position: absolute; inset: -8px; border-radius: 36px;
  border: 1px solid var(--xk-gold-line);
  animation: pulse 2.4s ease-out infinite;
}
@keyframes pulse {
  0% { opacity: 1; transform: scale(0.96); }
  70%, 100% { opacity: 0; transform: scale(1.12); }
}
.cta2 {
  height: auto;
  flex-direction: column;
  gap: 5px;
  padding: 16px 46px;
  letter-spacing: 0.18em;
  font-size: 15px;
}
.cta2 small {
  font-size: 12px;
  letter-spacing: 0.12em;
  color: var(--xk-mut);
}
/* 次级入口：无边框纯文字，靠 cta2 收紧（负 margin 抵掉一半父级 gap），
   仍留 44px 触摸高度保证平板可点 */
.member-link {
  margin-top: -14px;
  padding: 12px 18px;
  border: none;
  background: none;
  color: var(--xk-gold-dim);
  font-size: 13px;
  letter-spacing: 0.2em;
  cursor: pointer;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), color 160ms ease;
}
.member-link:active { transform: scale(0.97); color: var(--xk-gold-hi); }
@media (hover: hover) and (pointer: fine) {
  .member-link:hover { color: var(--xk-gold); }
}

/* 手机竖屏：整屏纵向内容按平板比例排下来约 774px，而 390x844 的手机扣掉顶栏与安全区
   只剩 ~714px。徽标环是最大的一块（62vw=242px），压到 46vw 就能把全屏塞回一屏内，
   不必靠滚动——首屏要的是一眼看完并按下 CTA */
@media (max-width: 560px) {
  .attract { gap: 20px; }
  .orbit-wrap { width: min(46vw, 300px); }
  .brand-name { font-size: 18px; letter-spacing: 0.32em; text-indent: 0.32em; }
  .cta { height: 56px; padding: 0 36px; font-size: 16px; }
  .cta2 { padding: 14px 28px; }
  .member-link { margin-top: -10px; }
}
</style>
