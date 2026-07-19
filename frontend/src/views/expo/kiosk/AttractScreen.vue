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
    <h2 class="slogan">莱莎帮你<br />遇到<em>最喜欢的自己</em></h2>
    <div class="line">AI 佩戴大模型 · 场景式智能引流</div>
    <button class="xk-btn cta" @click="$emit('start', 'tryon')">AI 试戴新发型</button>
    <button class="xk-btn ghost cta2" @click="$emit('start', 'scene')">
      已佩戴 · 拍场景大片
      <small>实拍生成商务 / 晚宴 / 旅行等场景效果</small>
    </button>
  </div>
</template>

<script setup>
// 品牌 LOGO 黑金重制版：原绿色 LOGO 经去底 + 亮度映射到主题金色阶（脚本处理，源图见品牌物料）
import logoGold from '@/assets/expo-logo-gold.png'

defineEmits(['start'])
</script>

<style scoped>
.attract {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  padding-bottom: 6vh;
}
.orbit-wrap { position: relative; width: min(46vw, 320px); aspect-ratio: 1; }
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
  display: flex; flex-direction: column; align-items: center; gap: 7px;
  margin-top: -4px;
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 17px; color: var(--xk-gold-hi);
  letter-spacing: 0.42em; text-indent: 0.42em; /* 补偿末字间距保证视觉居中 */
}
.brand-name .en {
  font-family: 'PingFang SC', sans-serif;
  font-size: 10px; letter-spacing: 0.6em; text-indent: 0.6em;
  color: var(--xk-gold-dim);
}
.slogan {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: clamp(28px, 5vw, 44px);
  font-weight: 600; text-align: center; line-height: 1.4; margin: 0;
}
.slogan em { font-style: italic; color: var(--xk-gold); }
.line { font-size: 13px; letter-spacing: 0.3em; color: var(--xk-mut); }
.cta { position: relative; margin-top: 14px; }
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
  gap: 4px;
  padding: 12px 36px;
  letter-spacing: 0.18em;
  font-size: 13px;
}
.cta2 small {
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--xk-mut);
}
</style>
