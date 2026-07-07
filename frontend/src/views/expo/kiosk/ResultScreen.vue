<template>
  <div class="result">
    <!-- 生成中：进度表演（进度环 + 流光条 + 品牌卡轮播，长等待用品牌内容填充） -->
    <div v-if="!current" class="waiting">
      <div class="halo-wrap">
        <div class="ring" />
        <div class="halo" />
        <span class="halo-count">{{ doneCount }}<i>/{{ totalCount }}</i></span>
      </div>
      <div class="wait-text">
        {{ isScene ? '正在为您生成场景大片' : '正在为您合成试戴效果' }}
        <small>AI 正在精细处理发丝与光影 · 约需 2 分钟</small>
      </div>
      <div class="bar" aria-hidden="true"><i /></div>
      <div v-if="!isScene" class="stages"><span>解析面容</span><span>甄选发型</span><span class="on">生成效果</span></div>
      <div v-else class="stages"><span>佩戴实拍</span><span>场景甄选</span><span class="on">生成大片</span></div>
      <Transition name="bcard" mode="out-in">
        <div class="brand-card" :key="brandIdx">
          <b>{{ BRAND_CARDS[brandIdx].tag }}</b>
          <span>{{ BRAND_CARDS[brandIdx].text }}</span>
        </div>
      </Transition>
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
        <!-- 预览框 cover 会裁掉比例不合的部分；查看完整图走灯箱。
             pointerdown.stop 防止触发对比滑块的拖拽手势 -->
        <button class="zoom-btn" aria-label="查看完整效果图" @pointerdown.stop @click="lightboxOpen = true">⤢ 查看大图</button>
      </div>

      <!-- 二次生成：已有成品在展示，新款在后台合成，用胶囊提示不打断浏览 -->
      <div v-if="flow.generating.value" class="gen-pill"><i />正在合成新选择 · 完成后自动切换</div>

      <div class="meta">
        <span class="nm">{{ current.wig_name }}</span>
        <span v-if="current.hair_color" class="color-tag">
          <i :style="{ background: current.hair_color.hex || 'var(--xk-ink-2)' }" />{{ current.hair_color.name }}
        </span>
        <span v-if="current.scene && current.wig_id" class="color-tag">{{ current.scene.label }}</span>
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
        <button v-else class="xk-btn ghost" :disabled="flow.generating.value" @click="flow.backToMatching()">试试其他发型</button>
        <button class="xk-btn" @click="flow.openSales()">请顾问过来</button>
      </div>

      <!-- 分享与返回：二维码独立黑金卡片，不与照片重叠；返回主页仅手动触发 -->
      <div class="share-row">
        <div v-if="shareUrl" class="qr-card">
          <canvas ref="qrEl" width="84" height="84" />
          <div class="qr-txt">
            <b>扫码带走</b>
            <span>试戴效果存入手机 · 随时分享</span>
          </div>
        </div>
        <button class="home-btn" @click="flow.resetAll()">⌂ 返回主页</button>
      </div>

      <!-- 完整图灯箱：contain 不裁切，轻触任意处关闭 -->
      <Transition name="lb">
        <div v-if="lightboxOpen && current" class="lightbox" @click="lightboxOpen = false">
          <img :src="current.image_url" class="lb-img" alt="完整效果图" />
          <button class="lb-close" aria-label="关闭">✕</button>
          <span class="lb-hint">轻触任意处返回</span>
        </div>
      </Transition>
    </template>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'

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
let brandTimer = null
function syncBrandTimer(waiting) {
  if (waiting && !brandTimer) {
    brandTimer = setInterval(() => {
      brandIdx.value = (brandIdx.value + 1) % BRAND_CARDS.length
    }, 6000)
  } else if (!waiting && brandTimer) {
    clearInterval(brandTimer)
    brandTimer = null
  }
}
onBeforeUnmount(() => syncBrandTimer(false))

const photoUrl = computed(() => flow.session.value?.photo_url || '')
const doneList = computed(() => flow.doneResults.value)
const doneCount = computed(() => doneList.value.length)
const totalCount = computed(() => flow.results.value.length || 3)
const isScene = computed(() => flow.mode.value === 'scene')

const currentIndex = ref(0)
const current = computed(() => doneList.value[currentIndex.value] || null)
const lightboxOpen = ref(false)
// 成品被清空（重新生成/清场）时收起灯箱，避免空引用的黑屏遮罩
watch(current, v => { if (!v) lightboxOpen.value = false })
watch(() => !current.value, syncBrandTimer, { immediate: true })
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
    // 墨色码点 + 暖米底：黑金语系里可扫性最稳的组合（反色码部分扫码器不认）
    await QRCode.toCanvas(qrEl.value, shareUrl.value, {
      width: 84, margin: 1,
      color: { dark: '#0c0a08', light: '#f3ead9' },
    })
  } catch (e) { /* 依赖缺失时不显示二维码，不阻断流程 */ }
}, { immediate: true })
</script>

<style scoped>
.result { flex: 1; display: flex; flex-direction: column; align-items: center; padding: 0 5vw 2.5vh; overflow-y: auto; }
.waiting { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px; }
.halo-wrap { position: relative; width: 150px; height: 150px; display: flex; align-items: center; justify-content: center; }
.halo {
  position: absolute; inset: 6px; border-radius: 50%;
  border: 1px solid var(--xk-gold-line);
  background: radial-gradient(circle, rgba(232, 196, 121, 0.18), transparent 70%);
  animation: halo 2.2s ease-in-out infinite;
}
@keyframes halo { 0%, 100% { transform: scale(0.94); opacity: 0.6; } 50% { transform: scale(1.06); opacity: 1; } }
/* 匀速旋转的金弧：constant motion 用 linear */
.ring {
  position: absolute; inset: 0; border-radius: 50%;
  background: conic-gradient(from 0deg, transparent 0 286deg, rgba(232, 196, 121, 0.9) 330deg, transparent 360deg);
  -webkit-mask: radial-gradient(closest-side, transparent calc(100% - 2.5px), #000 0);
  mask: radial-gradient(closest-side, transparent calc(100% - 2.5px), #000 0);
  animation: ring-spin 2.2s linear infinite;
}
@keyframes ring-spin { to { transform: rotate(360deg); } }
.halo-count { position: relative; font-family: 'Noto Serif SC', serif; font-size: 28px; color: var(--xk-gold-hi); }
.halo-count i { font-style: normal; font-size: 13px; color: var(--xk-mut); margin-left: 2px; }
.wait-text { text-align: center; font-size: 15px; letter-spacing: 0.2em; color: var(--xk-gold-hi); }
.wait-text small { display: block; margin-top: 10px; font-size: 11px; color: var(--xk-mut); letter-spacing: 0.14em; }
/* 不确定进度流光条：匀速 linear，宽度恒定只动 transform */
.bar { width: min(52vw, 300px); height: 2px; border-radius: 2px; background: rgba(232, 196, 121, 0.14); overflow: hidden; }
.bar i {
  display: block; height: 100%; width: 38%; border-radius: 2px;
  background: linear-gradient(90deg, transparent, var(--xk-gold), transparent);
  animation: bar-slide 1.5s linear infinite;
}
@keyframes bar-slide { from { transform: translateX(-110%); } to { transform: translateX(380%); } }
.stages { display: flex; gap: 30px; font-size: 11px; letter-spacing: 0.2em; color: var(--xk-mut); }
.stages .on { color: var(--xk-gold); border-bottom: 1px solid var(--xk-gold); padding-bottom: 6px; }
.brand-card {
  width: min(72vw, 460px); padding: 14px 18px;
  border: 1px solid var(--xk-gold-line); border-radius: 14px;
  background: rgba(232, 196, 121, 0.05);
  display: flex; align-items: center; gap: 12px;
  font-size: 12px; color: var(--xk-mut); line-height: 1.8; letter-spacing: 0.06em;
}
.brand-card b { color: var(--xk-gold); font-weight: 400; letter-spacing: 0.16em; flex: none; }
/* 卡片轮换：入场强 ease-out + blur 掩护交叉，出场更快（非对称时长） */
.bcard-enter-active { transition: opacity 420ms cubic-bezier(0.23, 1, 0.32, 1), transform 420ms cubic-bezier(0.23, 1, 0.32, 1), filter 420ms ease; }
.bcard-leave-active { transition: opacity 200ms ease, transform 200ms ease, filter 200ms ease; }
.bcard-enter-from { opacity: 0; transform: translateY(12px); filter: blur(6px); }
.bcard-leave-to { opacity: 0; transform: translateY(-8px); filter: blur(6px); }
.wait-actions { display: flex; gap: 12px; margin-top: 8px; }
.wait-actions .xk-btn { height: 44px; padding: 0 28px; font-size: 13px; }
@media (prefers-reduced-motion: reduce) {
  .ring, .bar i { animation: none; }
  .halo { animation-name: halo-fade; }
  .bcard-enter-from, .bcard-leave-to { transform: none; filter: none; }
}
@keyframes halo-fade { 0%, 100% { opacity: 0.6; } 50% { opacity: 1; } }

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
.zoom-btn {
  position: absolute; right: 14px; bottom: 14px; z-index: 4;
  padding: 8px 16px; border-radius: 20px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: rgba(12, 10, 8, 0.72);
  color: var(--xk-gold); font-size: 11px; letter-spacing: 0.14em;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.zoom-btn:active { transform: scale(0.96); }

/* ── 完整图灯箱（z-index 80：压过魔法镜框装饰层 60 与错误条 70） ── */
.lightbox {
  position: fixed; inset: 0; z-index: 80;
  background: rgba(12, 10, 8, 0.92);
  -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  display: flex; align-items: center; justify-content: center;
}
.lb-img {
  max-width: 94vw; max-height: 92vh; object-fit: contain;
  border-radius: 12px;
  box-shadow: 0 12px 60px rgba(0, 0, 0, 0.6);
}
.lb-close {
  position: absolute; top: 18px; right: 18px;
  width: 44px; height: 44px; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: rgba(12, 10, 8, 0.7);
  color: var(--xk-gold); font-size: 15px;
  display: flex; align-items: center; justify-content: center;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.lb-close:active { transform: scale(0.94); }
.lb-hint {
  position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%);
  font-size: 11px; letter-spacing: 0.24em; color: var(--xk-mut);
}
/* 灯箱是模态：transform-origin 保持居中；入场 240ms 强 ease-out，出场更快 160ms（非对称时长） */
.lb-enter-active { transition: opacity 240ms cubic-bezier(0.23, 1, 0.32, 1); }
.lb-enter-active .lb-img { transition: transform 240ms cubic-bezier(0.23, 1, 0.32, 1); }
.lb-leave-active { transition: opacity 160ms cubic-bezier(0.23, 1, 0.32, 1); }
.lb-enter-from, .lb-leave-to { opacity: 0; }
.lb-enter-from .lb-img { transform: scale(0.96); }
@media (prefers-reduced-motion: reduce) {
  .lb-enter-from .lb-img { transform: none; }
}
.share-row {
  width: min(72vw, 460px); margin-top: 14px;
  display: flex; align-items: stretch; gap: 12px;
}
.qr-card {
  flex: 1; display: flex; align-items: center; gap: 14px;
  padding: 10px 14px; border-radius: 14px;
  border: 1px solid var(--xk-gold-line);
  background: linear-gradient(120deg, rgba(232, 196, 121, 0.1), rgba(232, 196, 121, 0.02));
}
.qr-card canvas {
  border-radius: 8px; flex: none;
  border: 1px solid var(--xk-gold);
  box-shadow: 0 0 14px rgba(232, 196, 121, 0.16);
}
.qr-txt { display: flex; flex-direction: column; gap: 5px; }
.qr-txt b {
  font-family: 'Noto Serif SC', serif; font-weight: 400;
  font-size: 14px; letter-spacing: 0.22em; color: var(--xk-gold-hi);
}
.qr-txt span { font-size: 10px; letter-spacing: 0.14em; color: var(--xk-mut); }
.home-btn {
  flex: none; align-self: stretch; padding: 0 18px; border-radius: 14px; cursor: pointer;
  border: 1px solid rgba(141, 131, 113, 0.45); background: transparent;
  color: var(--xk-mut); font-size: 12px; letter-spacing: 0.16em;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), color 160ms ease, border-color 160ms ease;
}
.home-btn:active { transform: scale(0.96); }

.gen-pill {
  margin-top: 12px; padding: 7px 16px; border-radius: 20px;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.07);
  font-size: 11px; letter-spacing: 0.16em; color: var(--xk-gold);
  display: flex; align-items: center; gap: 8px;
}
.gen-pill i {
  width: 6px; height: 6px; border-radius: 50%; background: var(--xk-gold);
  animation: halo-fade 1.4s ease-in-out infinite;
}
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
