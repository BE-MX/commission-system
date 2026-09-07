<template>
  <div class="scene">
    <div class="s-scroll">
      <p class="xk-eyebrow">YOUR NEXT SCENE</p>
      <h2 class="xk-title">选择您的<em>场景大片</em></h2>
      <div class="xk-sub">保持此刻佩戴效果 · 最多选 3 个场景</div>

      <div class="cards">
        <button
          v-for="(s, i) in flow.scenes.value" :key="s.key"
          :aria-pressed="selected(s.key)"
          class="card" :class="{ on: selected(s.key) }"
          :style="{ animationDelay: `${i * 0.07}s` }"
          @click="flow.toggleScene(s.key)"
        >
          <span class="scene-image"><img v-if="s.image" :src="s.image" alt="" /><span v-else class="scene-number">{{ String(i + 1).padStart(2, '0') }}</span></span>
          <span class="mark">{{ selected(s.key) ? '✓' : '' }}</span>
          <span class="lb">{{ s.label }}</span>
          <span class="tg">{{ s.tagline }}</span>
        </button>
      </div>
    </div>

    <PromptVersionPicker />

    <button
      class="xk-btn go"
      :disabled="!flow.selectedSceneKeys.value.length || !flow.promptVersionReady.value || flow.generating.value"
      @click="flow.generateScenes()"
    >
      生成场景大片（{{ flow.selectedSceneKeys.value.length }}）
    </button>
  </div>
</template>

<script setup>
import PromptVersionPicker from './PromptVersionPicker.vue'
import { inject, onMounted } from 'vue'

const flow = inject('tryonFlow')

onMounted(() => flow.loadScenes())

function selected(key) {
  return flow.selectedSceneKeys.value.includes(key)
}
</script>

<style scoped>
.scene { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; padding: 26px 4vw 20px; }
.s-scroll { flex: 1; min-height: 0; width: 100%; max-width: 1100px; overflow-y: auto; padding: 0 4px 18px; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; margin: 28px auto 0; }
.card { position: relative; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; border: 1px solid transparent; border-radius: 12px; padding: 6px; background: transparent; color: var(--xk-paper); text-align: left; cursor: pointer; animation: scene-in 480ms var(--xk-ease) backwards; }
.card.on { border-color: var(--xk-gold); background: var(--xk-ink-2); }
.scene-image { width: 100%; aspect-ratio: 4/3; background: var(--xk-surface); border-radius: 8px; overflow: hidden; }
.scene-image img { width: 100%; height: 100%; object-fit: cover; }
.scene-number { height: 100%; display: flex; align-items: center; justify-content: center; font: 48px var(--xk-serif); color: var(--xk-gold-dim); }
.mark { position: absolute; top: 16px; right: 16px; width: 28px; height: 28px; display: grid; place-items: center; border-radius: 50%; border: 1px solid var(--xk-gold-line); background: var(--xk-ink-2); }
.card.on .mark { background: var(--xk-button); color: var(--xk-on-dark); }
.lb { font-family: var(--xk-serif); font-size: 23px; padding: 14px 8px 4px; }
.tg { font-size: 14px; color: var(--xk-mut); padding: 0 8px 12px; }
.go { width: min(100%, 760px); margin-top: 12px; flex: none; }
@keyframes scene-in { from { opacity: 0; transform: translateY(16px); } }
@media (max-width: 750px) { .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; } .lb { font-size: 20px; } .scene { padding: 22px 16px 14px; } }
</style>
