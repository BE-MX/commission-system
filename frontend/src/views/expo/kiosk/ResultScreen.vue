<template>
  <div class="result">
    <!-- 生成中：进度表演 -->
    <div v-if="!current" class="waiting">
      <div class="halo" />
      <div class="wait-text">
        {{ isScene ? '正在为您生成场景大片' : '正在为您合成试戴效果' }}
        <small>{{ doneCount }} / {{ totalCount }} 完成 · 好的效果值得几十秒等待</small>
      </div>
      <div v-if="!isScene" class="stages"><span>解析面容</span><span>甄选发型</span><span class="on">生成效果</span></div>
      <div v-else class="stages"><span>佩戴实拍</span><span>场景甄选</span><span class="on">生成大片</span></div>
      <!-- 整批失败：轮询已停且无成品时给出重来出口，不让客户干等 idle -->
      <div v-if="!flow.generating.value" class="wait-actions">
        <button class="xk-btn ghost" @click="retryGenerate">重新生成</button>
        <button class="xk-btn" @click="flow.openSales()">呼叫顾问</button>
      </div>
    </div>

    <!-- 前后对比滑块 -->
    <template v-else>
      <div ref="stageEl" class="stage" @pointerdown="dragStart" @pointermove="dragMove" @pointerup="dragEnd" @pointercancel="dragEnd">
        <img :src="photoUrl" class="img before" alt="佩戴前" />
        <img :src="current.image_url" class="img after" :style="{ clipPath: `inset(0 0 0 ${sliderPct}%)` }" alt="佩戴后" />
        <div class="divider" :style="{ left: `${sliderPct}%` }"><span class="knob">⇔</span></div>
        <span class="lbl b">{{ isScene ? '现场实拍' : '佩戴前' }}</span>
        <span class="lbl a">{{ isScene ? '莱莎 · 场景大片' : '莱莎 · 佩戴后' }}</span>
        <div v-if="shareUrl" class="qr">
          <canvas ref="qrEl" width="92" height="92" />
          <span>扫码带走</span>
        </div>
      </div>

      <div class="meta">
        <span class="nm">{{ current.wig_name }}</span>
        <span v-if="current.hair_color" class="color-tag">
          <i :style="{ background: current.hair_color.hex || 'var(--xk-ink-2)' }" />{{ current.hair_color.name }}
        </span>
        <span class="md">{{ metaLine }}</span>
      </div>

      <div v-if="!isScene" class="evidence"><b>久戴如新</b>同款保鳞原生辫发 · 12-18 个月光泽如初 · SGS 安全认证</div>
      <div v-else class="evidence"><b>专属大片</b>以您此刻的佩戴状态生成 · 扫码带走随时分享</div>

      <div class="dots">
        <i v-for="(r, i) in doneList" :key="r.id" :class="{ on: i === currentIndex }" @click="currentIndex = i" />
      </div>

      <div class="reacts">
        <button class="react" :class="{ liked: current.reaction === 'loved' }" @click="flow.react(current.id, 'loved')">♥ 心动</button>
        <button class="react" :class="{ liked: current.reaction === 'soso' }" @click="flow.react(current.id, 'soso')">再看看</button>
      </div>

      <div class="actions">
        <button v-if="isScene" class="xk-btn ghost" :disabled="flow.generating.value" @click="flow.reselectScenes()">再选场景</button>
        <button v-else class="xk-btn ghost" :disabled="flow.generating.value || !flow.canNextBatch.value" @click="flow.generate(flow.batch.value + 1)">换一批</button>
        <button class="xk-btn" @click="flow.openSales()">请顾问过来</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, ref, watch } from 'vue'

const flow = inject('tryonFlow')

const photoUrl = computed(() => flow.session.value?.photo_url || '')
const doneList = computed(() => flow.doneResults.value)
const doneCount = computed(() => doneList.value.length)
const totalCount = computed(() => flow.results.value.length || 3)
const isScene = computed(() => flow.mode.value === 'scene')

const currentIndex = ref(0)
const current = computed(() => doneList.value[currentIndex.value] || null)
const metaLine = computed(() => {
  const pos = `${currentIndex.value + 1}/${doneCount.value}`
  return current.value?.model_no ? `${current.value.model_no} · ${pos}` : pos
})

function retryGenerate() {
  if (isScene.value) flow.reselectScenes()
  else flow.generate(flow.batch.value)
}

// ── 前后对比滑块 ──
const stageEl = ref(null)
const sliderPct = ref(46)
let dragging = false
function dragStart(e) { dragging = true; updatePct(e) }
function dragMove(e) { if (dragging) updatePct(e) }
function dragEnd() { dragging = false }
function updatePct(e) {
  const rect = stageEl.value.getBoundingClientRect()
  const pct = ((e.clientX - rect.left) / rect.width) * 100
  sliderPct.value = Math.min(92, Math.max(8, pct))
}

// ── 分享二维码（qrcode 动态引入，失败静默降级为不显示） ──
const qrEl = ref(null)
const shareUrl = computed(() =>
  current.value?.short_code ? `${location.origin}/api/expo/share/${current.value.short_code}` : '',
)
watch([shareUrl, qrEl], async () => {
  if (!shareUrl.value) return
  await nextTick()
  if (!qrEl.value) return
  try {
    const QRCode = (await import('qrcode')).default
    await QRCode.toCanvas(qrEl.value, shareUrl.value, {
      width: 92, margin: 1,
      color: { dark: '#0c0a08', light: '#f3ead9' },
    })
  } catch (e) { /* 依赖缺失时不显示二维码，不阻断流程 */ }
}, { immediate: true })
</script>

<style scoped>
.result { flex: 1; display: flex; flex-direction: column; align-items: center; padding: 0 5vw 2.5vh; overflow-y: auto; }
.waiting { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 22px; }
.halo {
  width: 140px; height: 140px; border-radius: 50%;
  border: 1px solid var(--xk-gold-line);
  background: radial-gradient(circle, rgba(232, 196, 121, 0.18), transparent 70%);
  animation: halo 2.2s ease-in-out infinite;
}
@keyframes halo { 0%, 100% { transform: scale(0.94); opacity: 0.6; } 50% { transform: scale(1.06); opacity: 1; } }
.wait-text { text-align: center; font-size: 15px; letter-spacing: 0.2em; color: var(--xk-gold-hi); }
.wait-text small { display: block; margin-top: 10px; font-size: 11px; color: var(--xk-mut); letter-spacing: 0.14em; }
.stages { display: flex; gap: 30px; font-size: 11px; letter-spacing: 0.2em; color: var(--xk-mut); }
.stages .on { color: var(--xk-gold); border-bottom: 1px solid var(--xk-gold); padding-bottom: 6px; }
.wait-actions { display: flex; gap: 12px; margin-top: 8px; }
.wait-actions .xk-btn { height: 44px; padding: 0 28px; font-size: 13px; }

.stage {
  position: relative; width: min(72vw, 460px); flex: 1; min-height: 0; max-height: 52vh;
  border-radius: 24px; overflow: hidden; touch-action: none;
  background: radial-gradient(60% 55% at 50% 40%, #34291c, #17110c 78%);
}
.img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.divider {
  position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; z-index: 3;
  background: linear-gradient(180deg, transparent, var(--xk-gold), transparent);
}
.knob {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 40px; height: 40px; border-radius: 50%;
  border: 1px solid var(--xk-gold); background: rgba(12, 10, 8, 0.85);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; color: var(--xk-gold);
}
.lbl { position: absolute; top: 16px; font-size: 10px; letter-spacing: 0.24em; padding: 6px 14px; border-radius: 20px; z-index: 2; }
.lbl.b { left: 14px; color: var(--xk-mut); border: 1px solid rgba(141, 131, 113, 0.4); }
.lbl.a { right: 14px; color: var(--xk-ink); background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi)); }
.qr {
  position: absolute; right: 14px; bottom: 14px; z-index: 4;
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.qr canvas { border-radius: 10px; border: 1px solid var(--xk-gold-line); }
.qr span { font-size: 9px; letter-spacing: 0.2em; color: var(--xk-gold-dim); }

.meta { width: min(72vw, 460px); display: flex; justify-content: space-between; align-items: baseline; margin-top: 14px; }
.meta .nm { font-family: 'Noto Serif SC', serif; font-size: 20px; color: var(--xk-gold-hi); }
.meta .md { font-size: 11px; letter-spacing: 0.2em; color: var(--xk-mut); }
.color-tag {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 10px; letter-spacing: 0.14em; color: var(--xk-gold-dim);
  border: 1px solid var(--xk-gold-line); border-radius: 12px; padding: 3px 10px;
}
.color-tag i { width: 10px; height: 10px; border-radius: 50%; border: 1px solid var(--xk-gold-line); }
.evidence {
  width: min(72vw, 460px); margin-top: 10px; padding: 10px 14px;
  border: 1px solid var(--xk-gold-line); border-radius: 12px;
  background: rgba(232, 196, 121, 0.05);
  font-size: 11px; color: var(--xk-mut); line-height: 1.7;
  display: flex; align-items: center; gap: 10px;
}
.evidence b { color: var(--xk-gold); font-weight: 400; letter-spacing: 0.12em; flex: none; }
.dots { display: flex; gap: 10px; margin-top: 12px; }
.dots i { width: 7px; height: 7px; border-radius: 50%; background: #4a4234; cursor: pointer; }
.dots i.on { width: 20px; border-radius: 5px; background: var(--xk-gold); box-shadow: 0 0 8px var(--xk-gold); }
.reacts { display: flex; gap: 12px; margin-top: 14px; width: min(72vw, 460px); }
.react {
  flex: 1; height: 44px; border-radius: 14px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: transparent;
  color: var(--xk-mut); font-size: 13px; letter-spacing: 0.12em;
}
.react.liked { color: var(--xk-ink); border: none; background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi)); }
.actions { display: flex; gap: 12px; margin-top: 14px; width: min(72vw, 460px); }
.actions .xk-btn { flex: 1; padding: 0; height: 48px; font-size: 13px; }
</style>
