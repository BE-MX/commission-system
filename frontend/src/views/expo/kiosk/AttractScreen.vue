<template>
  <div class="attract">
    <div class="orbit-wrap">
      <div class="orbit"><i /></div>
      <div class="orbit o2"><i /></div>
      <svg class="face" viewBox="0 0 100 120">
        <ellipse cx="50" cy="58" rx="30" ry="38" />
        <path d="M20 50 Q18 12 50 10 Q82 12 80 50 Q84 28 66 20 Q50 14 34 20 Q16 28 20 50" />
        <polyline points="34,52 42,50 48,53" /><polyline points="52,53 58,50 66,52" />
        <polyline points="50,58 47,70 53,70" /><polyline points="40,82 50,86 60,82" />
        <circle cx="34" cy="52" r="1.3" /><circle cx="66" cy="52" r="1.3" />
        <circle cx="50" cy="70" r="1.3" /><circle cx="50" cy="86" r="1.3" />
        <circle cx="50" cy="10" r="1.3" /><circle cx="20" cy="50" r="1.3" /><circle cx="80" cy="50" r="1.3" />
      </svg>
    </div>
    <h2 class="slogan">戴上那一刻<br /><em>状态</em>就回来了</h2>
    <div class="line">AI 智能试戴 · 60 秒遇见更好的自己</div>
    <button class="xk-btn cta" @click="$emit('start', 'tryon')">AI 试戴新发型</button>
    <button class="xk-btn ghost cta2" @click="$emit('start', 'scene')">
      已佩戴 · 拍场景大片
      <small>实拍生成商务 / 晚宴 / 旅行等场景效果</small>
    </button>
  </div>
</template>

<script setup>
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
.face { position: absolute; inset: 16%; animation: breathe 4.5s ease-in-out infinite; }
@keyframes breathe {
  0%, 100% { opacity: 0.75; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.035); }
}
.face polyline, .face path, .face ellipse { fill: none; stroke: var(--xk-gold); stroke-width: 0.8; }
.face circle { fill: var(--xk-gold-hi); }
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
