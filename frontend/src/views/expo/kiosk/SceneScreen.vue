<template>
  <div class="scene">
    <h2 class="xk-title">选择您的<em>场景大片</em></h2>
    <div class="xk-sub">保持此刻佩戴效果 · 最多选 3 个场景</div>

    <div class="cards">
      <button
        v-for="(s, i) in flow.scenes.value" :key="s.key"
        class="card" :class="{ on: selected(s.key) }"
        :style="{ animationDelay: `${0.1 + i * 0.12}s` }"
        @click="flow.toggleScene(s.key)"
      >
        <span class="mark">{{ selected(s.key) ? '✓' : '' }}</span>
        <span class="lb">{{ s.label }}</span>
        <span class="tg">{{ s.tagline }}</span>
      </button>
    </div>

    <button
      class="xk-btn go"
      :disabled="!flow.selectedSceneKeys.value.length"
      @click="flow.generateScenes()"
    >
      生成场景大片（{{ flow.selectedSceneKeys.value.length }}）
    </button>
  </div>
</template>

<script setup>
import { inject, onMounted } from 'vue'

const flow = inject('tryonFlow')

onMounted(() => flow.loadScenes())

function selected(key) {
  return flow.selectedSceneKeys.value.includes(key)
}
</script>

<style scoped>
.scene { flex: 1; display: flex; flex-direction: column; align-items: center; padding: 2vh 6vw 3vh; overflow-y: auto; }
.cards {
  width: min(88vw, 560px);
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;
  margin-top: 3vh;
}
.card {
  position: relative; display: flex; flex-direction: column; align-items: flex-start; gap: 6px;
  padding: 18px 16px; border-radius: 18px; cursor: pointer; text-align: left;
  border: 1px solid var(--xk-gold-line);
  background: linear-gradient(120deg, rgba(232, 196, 121, 0.06), rgba(232, 196, 121, 0.015));
  color: var(--xk-paper);
  opacity: 0; transform: perspective(600px) rotateX(24deg) translateY(14px);
  transform-origin: top;
  animation: scene-in 0.9s cubic-bezier(0.2, 0.9, 0.3, 1.2) forwards;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease;
}
@keyframes scene-in { to { opacity: 1; transform: none; } }
.card:active { transform: scale(0.97); }
.card.on {
  border-color: rgba(232, 196, 121, 0.55);
  background: linear-gradient(120deg, rgba(232, 196, 121, 0.14), rgba(232, 196, 121, 0.03));
}
.mark {
  position: absolute; top: 12px; right: 14px;
  width: 22px; height: 22px; border-radius: 50%;
  border: 1px solid var(--xk-gold-line);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: var(--xk-ink);
  transition: background 160ms ease;
}
.card.on .mark { background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi)); border: none; }
.lb { font-family: 'Noto Serif SC', serif; font-size: 18px; color: var(--xk-gold-hi); }
.tg { font-size: 11px; letter-spacing: 0.12em; color: var(--xk-mut); }
.go { margin-top: auto; margin-bottom: 1vh; min-width: 300px; }
.go:disabled { opacity: 0.4; }
</style>
