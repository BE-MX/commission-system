<template>
  <div class="result">
    <!-- 生成中：进度表演（进度环 + 流光条 + 品牌卡轮播，长等待用品牌内容填充） -->
    <div v-if="!current" class="waiting">
      <div class="halo-wrap">
        <div class="ring" />
        <div class="ring ring2" />
        <div class="halo" />
        <div class="spark s1" /><div class="spark s2" /><div class="spark s3" />
        <span class="halo-count">{{ doneCount }}<i>/{{ totalCount }}</i></span>
      </div>
      <div class="wait-title">
        {{ isScene ? '正在为您生成场景大片' : '正在为您合成试戴效果' }}
        <small>预计 1-2 分钟 · AI 精细处理中</small>
      </div>
      <!-- 随机专业语句：给长等待注入"正在做正经事"的质感（纯观感文案，非流程承诺） -->
      <Transition name="phrase" mode="out-in">
        <div class="phrase" :key="phraseIdx"><i class="live" />{{ phrases[phraseIdx] }}</div>
      </Transition>
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
        <!-- 切换新效果图时对焦式揭晓：keyed Transition 让旧图淡出、新图 blur→sharp 登场 -->
        <!-- kiosk 一律走压缩展示版（display_url）：原 PNG 3~5MB 经 frp 隧道回源是现场卡顿主因；
             历史结果无展示版时回退原图 -->
        <Transition name="swap">
          <img :key="current.id" :src="current.display_url || current.image_url" class="img after" :style="{ clipPath: `inset(0 0 0 ${sliderPct}%)` }" alt="佩戴后" />
        </Transition>
        <div class="divider" :style="{ left: `${sliderPct}%` }"><span class="knob">⇔</span></div>
        <span class="lbl b">{{ isScene ? '现场实拍' : '佩戴前' }}</span>
        <span class="lbl a">{{ isScene ? '莱莎 · 场景大片' : '莱莎 · 佩戴后' }}</span>
        <!-- 预览框 cover 会裁掉比例不合的部分；查看完整图走灯箱。
             pointerdown.stop 防止触发对比滑块的拖拽手势 -->
        <button class="zoom-btn" aria-label="查看完整效果图" @pointerdown.stop @click="lightboxOpen = true">⤢ 查看大图</button>
      </div>

      <!-- 二次生成：已有成品在展示，新款在后台合成，用胶囊提示不打断浏览。
           入场 fade+上移、金光横扫表达"进行中"，完成时淡出 -->
      <Transition name="pill">
        <div v-if="flow.generating.value" class="gen-pill"><i />正在合成新选择 · 完成后自动切换</div>
      </Transition>

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
      <!-- 一键打印：平板 APK 里走原生桥（存相册→确认→开打印App）；普通浏览器兜底开图 -->
      <button class="xk-btn print" @click="printCurrent">🖨 打印这张</button>

      <!-- 分享二维码独立黑金卡片，不与照片重叠；返回主页在外壳头部（全屏统一导航） -->
      <div v-if="shareUrl" class="share-row">
        <div class="qr-card">
          <canvas ref="qrEl" width="84" height="84" />
          <div class="qr-txt">
            <b>扫码带走</b>
            <span>试戴效果存入手机 · 随时分享</span>
          </div>
        </div>
      </div>

      <!-- 完整图灯箱：contain 不裁切，轻触任意处关闭 -->
      <Transition name="lb">
        <div v-if="lightboxOpen && current" class="lightbox" @click="lightboxOpen = false">
          <img :src="current.display_url || current.image_url" class="lb-img" alt="完整效果图" />
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

// 等待中轮换的"专业工序"语句：标题说真话（正在生成），这排短语堆专业质感。
// 按模式给不同工序词 + 通用词，2.6s 换一句、随机不重复。
const PHRASE_POOL = {
  tryon: ['正在渲染发丝细节', '正在匹配肤色与发色', '正在优化面部融合', '正在校准佩戴贴合度'],
  scene: ['正在生成 AI 场景', '正在设计服饰形象', '正在布置场景光线', '正在构建空间氛围'],
  common: ['正在调整光影效果', '正在润色整体色调', '正在精修画面细节', '正在校准色彩平衡', '正在合成高清成片'],
}
const phrases = computed(() => [
  ...(flow.mode.value === 'scene' ? PHRASE_POOL.scene : PHRASE_POOL.tryon),
  ...PHRASE_POOL.common,
])
const phraseIdx = ref(0)
function nextPhrase() {
  const n = phrases.value.length
  if (n <= 1) return
  let i = phraseIdx.value
  while (i === phraseIdx.value) i = Math.floor(Math.random() * n)
  phraseIdx.value = i
}

let brandTimer = null
let phraseTimer = null
function syncWaitTimers(waiting) {
  if (waiting) {
    if (!brandTimer) brandTimer = setInterval(() => {
      brandIdx.value = (brandIdx.value + 1) % BRAND_CARDS.length
    }, 6000)
    if (!phraseTimer) phraseTimer = setInterval(nextPhrase, 2600)
  } else {
    if (brandTimer) { clearInterval(brandTimer); brandTimer = null }
    if (phraseTimer) { clearInterval(phraseTimer); phraseTimer = null }
  }
}
onBeforeUnmount(() => syncWaitTimers(false))

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
watch(() => !current.value, syncWaitTimers, { immediate: true })
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

// 一键打印：把当前合成「原图」（非压缩展示版，保打印清晰度）交给平板 APK 原生桥，
// 由它存进系统相册并确认后再打开打印 App；非 APK 环境（普通浏览器）兜底新开图便于取用
function printCurrent() {
  const r = current.value
  if (!r?.image_url) return
  const url = r.image_url.startsWith('http') ? r.image_url : location.origin + r.image_url
  const bridge = window.Android
  if (bridge && typeof bridge.printPhoto === 'function') {
    bridge.printPhoto(url)
  } else {
    window.open(url, '_blank')
  }
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
// 二维码是给**客户手机**扫的，而展位平板自己走 https 只是为了拿 secure context 开相机——
// IP 签不到 CA 证书，服务器挂的是自签证书，客户手机（尤其微信内置浏览器）根本不认，扫出来是白屏。
// 所以 host 为裸 IP 时把分享链接降回 http；将来换成备案域名（正规证书）则保持 https。
const IPV4_HOST = /^\d{1,3}(\.\d{1,3}){3}$/
const shareUrl = computed(() => {
  if (!current.value?.short_code) return ''
  // 只处理标准端口：带显式端口时无从推断对应的 http 端口，宁可原样不猜
  const base = IPV4_HOST.test(location.hostname) && !location.port
    ? `http://${location.hostname}`
    : location.origin
  return `${base}/api/expo/share/${current.value.short_code}`
})
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
.waiting { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 26px; }
.halo-wrap { position: relative; width: 200px; height: 200px; display: flex; align-items: center; justify-content: center; }
.halo {
  position: absolute; inset: 10px; border-radius: 50%;
  border: 1px solid var(--xk-gold-line);
  background: radial-gradient(circle, rgba(232, 196, 121, 0.22), transparent 68%);
  animation: halo 2.2s ease-in-out infinite;
}
@keyframes halo { 0%, 100% { transform: scale(0.92); opacity: 0.55; } 50% { transform: scale(1.08); opacity: 1; } }
/* 匀速旋转的金弧：constant motion 用 linear。主弧顺时针，内弧反向更细，叠出"精密仪器"感 */
.ring {
  position: absolute; inset: 0; border-radius: 50%;
  background: conic-gradient(from 0deg, transparent 0 280deg, rgba(232, 196, 121, 0.95) 332deg, transparent 360deg);
  -webkit-mask: radial-gradient(closest-side, transparent calc(100% - 3px), #000 0);
  mask: radial-gradient(closest-side, transparent calc(100% - 3px), #000 0);
  animation: ring-spin 2.4s linear infinite;
}
.ring2 {
  inset: 15%;
  background: conic-gradient(from 180deg, transparent 0 300deg, rgba(247, 227, 176, 0.75) 342deg, transparent 360deg);
  -webkit-mask: radial-gradient(closest-side, transparent calc(100% - 2px), #000 0);
  mask: radial-gradient(closest-side, transparent calc(100% - 2px), #000 0);
  animation: ring-spin 3.6s linear infinite reverse;
}
@keyframes ring-spin { to { transform: rotate(360deg); } }
/* 三颗环绕光点：不同半径 + 不同速度 + 有正反，营造"多线程处理"的动感 */
.spark { position: absolute; inset: 0; border-radius: 50%; }
.spark::after {
  content: ''; position: absolute; top: -2px; left: 50%; margin-left: -3px;
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--xk-gold-hi); box-shadow: 0 0 12px var(--xk-gold);
}
.s1 { animation: ring-spin 3.2s linear infinite; }
.s2 { inset: 15%; animation: ring-spin 4.8s linear infinite reverse; }
.s3 { inset: 30%; animation: ring-spin 2.3s linear infinite; }
.halo-count { position: relative; font-family: 'Noto Serif SC', serif; font-size: 38px; color: var(--xk-gold-hi); }
.halo-count i { font-style: normal; font-size: 16px; color: var(--xk-mut); margin-left: 3px; }
.wait-title {
  text-align: center; font-family: 'Noto Serif SC', serif;
  font-size: 20px; letter-spacing: 0.22em; color: var(--xk-gold-hi);
}
.wait-title small { display: block; margin-top: 10px; font-size: 12px; color: var(--xk-mut); letter-spacing: 0.14em; }
/* 随机工序短语：live 点脉冲表达"进行中"，换句用 blur 掩护交叉 */
.phrase {
  display: flex; align-items: center; gap: 10px; min-height: 24px;
  font-size: 16px; letter-spacing: 0.18em; color: var(--xk-gold);
}
.phrase .live {
  width: 7px; height: 7px; border-radius: 50%; flex: none;
  background: var(--xk-gold-hi); box-shadow: 0 0 10px var(--xk-gold);
  animation: halo-fade 1.1s ease-in-out infinite;
}
.phrase-enter-active { transition: opacity 360ms cubic-bezier(0.23, 1, 0.32, 1), transform 360ms cubic-bezier(0.23, 1, 0.32, 1), filter 360ms ease; }
.phrase-leave-active { transition: opacity 200ms ease, transform 200ms ease, filter 200ms ease; }
.phrase-enter-from { opacity: 0; transform: translateY(8px); filter: blur(5px); }
.phrase-leave-to { opacity: 0; transform: translateY(-6px); filter: blur(5px); }
/* 不确定进度流光条：匀速 linear，宽度恒定只动 transform */
.bar { width: min(60vw, 360px); height: 3px; border-radius: 3px; background: rgba(232, 196, 121, 0.14); overflow: hidden; }
.bar i {
  display: block; height: 100%; width: 38%; border-radius: 3px;
  background: linear-gradient(90deg, transparent, var(--xk-gold), transparent);
  animation: bar-slide 1.5s linear infinite;
}
@keyframes bar-slide { from { transform: translateX(-110%); } to { transform: translateX(380%); } }
.stages { display: flex; gap: 40px; font-size: 14px; letter-spacing: 0.2em; color: var(--xk-mut); }
.stages .on { color: var(--xk-gold); border-bottom: 1px solid var(--xk-gold); padding-bottom: 8px; }
.brand-card {
  width: min(80vw, 560px); padding: 18px 24px;
  border: 1px solid var(--xk-gold-line); border-radius: 16px;
  background: rgba(232, 196, 121, 0.05);
  display: flex; align-items: center; gap: 14px;
  font-size: 14.5px; color: var(--xk-mut); line-height: 1.8; letter-spacing: 0.06em;
}
.brand-card b { color: var(--xk-gold); font-weight: 400; letter-spacing: 0.16em; flex: none; }
/* 卡片轮换：入场强 ease-out + blur 掩护交叉，出场更快（非对称时长） */
.bcard-enter-active { transition: opacity 420ms cubic-bezier(0.23, 1, 0.32, 1), transform 420ms cubic-bezier(0.23, 1, 0.32, 1), filter 420ms ease; }
.bcard-leave-active { transition: opacity 200ms ease, transform 200ms ease, filter 200ms ease; }
.bcard-enter-from { opacity: 0; transform: translateY(12px); filter: blur(6px); }
.bcard-leave-to { opacity: 0; transform: translateY(-8px); filter: blur(6px); }
.wait-actions { display: flex; gap: 14px; margin-top: 8px; }
.wait-actions .xk-btn { height: 52px; padding: 0 34px; font-size: 15px; }
@media (prefers-reduced-motion: reduce) {
  .ring, .ring2, .spark, .bar i { animation: none; }
  .spark { display: none; }
  .halo { animation-name: halo-fade; }
  .bcard-enter-from, .bcard-leave-to, .phrase-enter-from, .phrase-leave-to { transform: none; filter: none; }
}
@keyframes halo-fade { 0%, 100% { opacity: 0.6; } 50% { opacity: 1; } }

.stage {
  position: relative; width: min(72vw, 460px); flex: 1; min-height: 0; max-height: 52vh;
  border-radius: 24px; overflow: hidden; touch-action: none;
  background: radial-gradient(60% 55% at 50% 40%, #34291c, #17110c 78%);
}
.img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
/* 新效果图对焦式揭晓：blur→sharp + 从 1.03 收束（像照片显影），旧图更快淡出（非对称时长）。
   两张 after 图同 clip-path 叠放，crossfade 由 blur 掩护双影，只动 opacity/transform/filter */
.swap-enter-active { transition: opacity 440ms cubic-bezier(0.23, 1, 0.32, 1), transform 440ms cubic-bezier(0.23, 1, 0.32, 1), filter 440ms ease-out; z-index: 1; }
.swap-leave-active { transition: opacity 260ms cubic-bezier(0.23, 1, 0.32, 1), filter 260ms ease-out; }
.swap-enter-from { opacity: 0; transform: scale(1.03); filter: blur(10px); }
.swap-leave-to { opacity: 0; filter: blur(6px); }
@media (prefers-reduced-motion: reduce) {
  .swap-enter-from { transform: none; filter: none; }
  .swap-leave-to { filter: none; }
}
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
.gen-pill {
  position: relative; overflow: hidden;
  margin-top: 12px; padding: 7px 16px; border-radius: 20px;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.07);
  font-size: 11px; letter-spacing: 0.16em; color: var(--xk-gold);
  display: flex; align-items: center; gap: 8px;
}
/* 金光横扫：表达"合成进行中"的持续动作，constant motion 用 linear，只动 transform */
.gen-pill::after {
  content: ''; position: absolute; top: 0; bottom: 0; left: 0; width: 45%;
  background: linear-gradient(90deg, transparent, rgba(247, 227, 176, 0.22), transparent);
  transform: translateX(-120%);
  animation: gen-sweep 1.6s linear infinite;
}
.gen-pill i {
  width: 6px; height: 6px; border-radius: 50%; background: var(--xk-gold);
  box-shadow: 0 0 6px var(--xk-gold);
  animation: halo-fade 1.4s ease-in-out infinite;
}
@keyframes gen-sweep { to { transform: translateX(370%); } }
/* 胶囊出入场：入场 fade+上移强 ease-out，完成时更快淡出（非对称） */
.pill-enter-active { transition: opacity 300ms cubic-bezier(0.23, 1, 0.32, 1), transform 300ms cubic-bezier(0.23, 1, 0.32, 1); }
.pill-leave-active { transition: opacity 200ms cubic-bezier(0.23, 1, 0.32, 1), transform 200ms cubic-bezier(0.23, 1, 0.32, 1); }
.pill-enter-from, .pill-leave-to { opacity: 0; transform: translateY(8px); }
@media (prefers-reduced-motion: reduce) {
  .gen-pill::after { animation: none; }
  .gen-pill i { animation-name: halo-fade; }
  .pill-enter-from, .pill-leave-to { transform: none; }
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
.dots i {
  width: 7px; height: 7px; border-radius: 50%; background: #4a4234; cursor: pointer;
  transition: width 260ms cubic-bezier(0.23, 1, 0.32, 1), background 200ms ease, box-shadow 200ms ease;
}
.dots i.on { width: 20px; border-radius: 5px; background: var(--xk-gold); box-shadow: 0 0 8px var(--xk-gold); }
@media (prefers-reduced-motion: reduce) { .dots i { transition: background 200ms ease; } }
.reacts { display: flex; gap: 12px; margin-top: 14px; width: min(72vw, 460px); }
.react {
  flex: 1; height: 44px; border-radius: 14px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: transparent;
  color: var(--xk-mut); font-size: 13px; letter-spacing: 0.12em;
}
.react.liked { color: var(--xk-ink); border: none; background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi)); }
.actions { display: flex; gap: 12px; margin-top: 14px; width: min(72vw, 460px); }
.actions .xk-btn { flex: 1; padding: 0; height: 48px; font-size: 13px; }
.xk-btn.print { width: min(72vw, 460px); height: 48px; margin-top: 12px; font-size: 14px; letter-spacing: 0.1em; }
</style>
