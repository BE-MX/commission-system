<template>
  <Transition name="xmem">
    <div v-if="open" class="xk-member" @click.self="$emit('close')" @pointerdown="armIdle">
      <div class="xm-panel">
        <button class="xm-close" aria-label="关闭" @click="$emit('close')">×</button>

        <header class="xm-head">
          <div class="xm-kicker">L E S H I N E · 门 店 合 作</div>
          <h3 class="xm-title">门店 AI <em>智能试戴</em> 会员</h3>
          <p class="xm-sub">把路过变成进店，把「看看」变成成交</p>
        </header>

        <div class="xm-body">
          <section
            v-for="(plan, i) in plans" :key="plan.name"
            class="xm-card" :class="{ hot: plan.hot }" :style="{ '--stagger': `${i * 70}ms` }"
          >
            <div v-if="plan.badge" class="xm-badge">{{ plan.badge }}</div>
            <div class="xm-name">{{ plan.name }}</div>
            <div class="xm-price">
              <span v-if="plan.prefix" class="xm-prefix">{{ plan.prefix }}</span>
              <span class="xm-cur">¥</span><b>{{ plan.price }}</b>
              <span class="xm-slash">/</span>
              <span class="xm-unit">{{ plan.unit }}</span>
            </div>
            <div v-if="plan.chips" class="xm-chips">
              <span v-for="chip in plan.chips" :key="chip" class="xm-chip">{{ chip }}</span>
            </div>
            <div v-if="plan.daily" class="xm-daily">{{ plan.daily }}</div>
            <p class="xm-pitch">{{ plan.pitch }}</p>
            <ul v-if="plan.items.length" class="xm-list">
              <li v-for="item in plan.items" :key="item">{{ item }}</li>
            </ul>
          </section>
        </div>

        <footer class="xm-foot">现场登记即可开通 · 详情请咨询展位顾问</footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { onBeforeUnmount, watch } from 'vue'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])

// 空闲自动收起：attract 屏本身不挂 idle 定时器（useTryOnFlow.touch 在 attract 直接 return），
// 弹窗不自己兜底就会一直挂着，下一位观众走过来看到的是价格表而不是试戴入口。
// 60s 对齐 kiosk 全局空闲约定；面板内任何触摸都重新计时。
const IDLE_MS = 60000
let idleTimer = null
function clearIdle() {
  if (idleTimer) { clearTimeout(idleTimer); idleTimer = null }
}
function armIdle() {
  clearIdle()
  idleTimer = setTimeout(() => emit('close'), IDLE_MS)
}
watch(() => props.open, v => (v ? armIdle() : clearIdle()))
onBeforeUnmount(clearIdle)

// 会员权益为展会现场固定物料，不走后台配置：改价改权益的频率远低于一次展会周期，
// 落 DB 反而多一层同步成本。调整直接改此处文案。
// 两档只有价格差（新店 4999 / 老店 3999），权益完全一致：清单只在新门店卡展示一份，
// 老门店卡用对比筹码声明一致，不重复 11 行；日均换算 3999/365≈10.95，改价记得同步。
const plans = [
  {
    name: '新门店会员',
    price: '4999',
    unit: '年',
    pitch: '把试戴沉淀成门店自己的获客资产',
    items: [
      '单门店授权使用',
      'AI 生成图 500 张额度',
      'AI 场景试戴：商务 / 晚宴 / 旅行等成片直接出',
      '品牌现有产品库全量开放，想试哪款试哪款',
      '会员期内产品库持续更新，品牌上新即到店',
      '门店专属二维码，顾客扫码进的是你的店',
      '试戴页展示门店名称，每张成片都带着你的招牌传播',
      '试戴照片保存与分享，顾客发一次朋友圈就是一次曝光',
      '基础使用培训，店员当天上手',
      '标准版门店引流海报，打印即用',
      '试戴入口可发给顾客，人不在店也能试',
    ],
  },
  {
    name: '老门店会员',
    price: '3999',
    unit: '年',
    prefix: '仅需',
    pitch: '已合作门店，老朋友直接开通',
    hot: true,
    badge: '老店专享',
    chips: ['比新门店少 ¥1000', '权益一条不少'],
    daily: '折合每天不到 ¥11，店里多一位全年无休的 AI 试戴顾问',
    items: [],
  },
]
</script>

<style scoped>
/* z 76：压过返回主页确认层 75（两者互斥，仅为顺序确定），低于灯箱 80 */
.xk-member {
  position: fixed; inset: 0; z-index: 76;
  display: flex; align-items: center; justify-content: center;
  padding:
    calc(16px + env(safe-area-inset-top)) calc(14px + env(safe-area-inset-right))
    calc(16px + env(safe-area-inset-bottom)) calc(14px + env(safe-area-inset-left));
  background: rgba(6, 5, 3, 0.78);
  -webkit-backdrop-filter: blur(5px); backdrop-filter: blur(5px);
}
.xm-panel {
  position: relative;
  display: flex; flex-direction: column;
  width: min(100%, 1040px); max-height: 100%;
  padding: 30px 30px 22px; border-radius: 22px;
  border: 1px solid var(--xk-gold-line);
  background: linear-gradient(160deg, var(--xk-ink-2), var(--xk-ink));
  box-shadow: 0 26px 76px rgba(0, 0, 0, 0.55), 0 0 44px rgba(232, 196, 121, 0.12);
}
.xm-close {
  position: absolute; top: 14px; right: 16px;
  width: 38px; height: 38px; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.05);
  color: var(--xk-gold); font-size: 22px; line-height: 1;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease;
}
.xm-close:active { transform: scale(0.94); }

.xm-head { flex: none; text-align: center; padding-right: 34px; }
.xm-kicker { font-size: 11px; letter-spacing: 0.34em; color: var(--xk-gold-dim); }
.xm-title {
  margin: 12px 0 0;
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: clamp(22px, 3.4vw, 30px); font-weight: 600;
  letter-spacing: 0.08em; color: var(--xk-gold-hi);
}
.xm-title em { font-style: italic; color: var(--xk-gold); }
.xm-sub { margin: 10px 0 0; font-size: 13px; letter-spacing: 0.14em; color: var(--xk-mut); }

.xm-body {
  flex: 1; min-height: 0; margin-top: 24px;
  display: grid; grid-template-columns: 1fr; gap: 18px;
  overflow-y: auto; -webkit-overflow-scrolling: touch;
}
@media (min-width: 900px) {
  .xm-body { grid-template-columns: 1fr 1fr; align-items: start; }
}

.xm-card {
  position: relative;
  padding: 22px 22px 24px; border-radius: 16px;
  border: 1px solid var(--xk-gold-line);
  background: rgba(232, 196, 121, 0.03);
  /* 卡片依次入场：短 stagger 让两档权益有先后节奏，不阻塞任何交互 */
  opacity: 0; transform: translateY(10px);
  animation: xm-rise 320ms cubic-bezier(0.23, 1, 0.32, 1) var(--stagger) forwards;
}
.xm-card.hot {
  border-color: rgba(232, 196, 121, 0.55);
  background: rgba(232, 196, 121, 0.07);
  box-shadow: inset 0 0 40px rgba(232, 196, 121, 0.06);
}
@keyframes xm-rise { to { opacity: 1; transform: translateY(0); } }
.xm-badge {
  position: absolute; top: 16px; right: 18px;
  padding: 4px 12px; border-radius: 12px;
  background: linear-gradient(110deg, var(--xk-gold-dim), var(--xk-gold) 45%, var(--xk-gold-hi));
  color: var(--xk-ink); font-size: 11px; letter-spacing: 0.16em;
}
.xm-name {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 18px; letter-spacing: 0.2em; color: var(--xk-gold-hi);
}
.xm-price { display: flex; align-items: baseline; gap: 7px; margin-top: 12px; }
.xm-price b {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 40px; font-weight: 600; line-height: 1; color: var(--xk-gold);
}
/* 价格恢复明码后回到常规定价层级：数字是主角，「仅需」与「/ 年」都退为注脚 */
.xm-prefix { font-size: 13px; letter-spacing: 0.2em; color: var(--xk-gold-dim); }
.xm-cur { font-family: 'Noto Serif SC', 'STSong', serif; font-size: 22px; line-height: 1; color: var(--xk-gold); }
.xm-slash { font-size: 16px; line-height: 1; color: var(--xk-gold-dim); }
.xm-unit {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 16px; font-weight: 500; line-height: 1;
  letter-spacing: 0.08em; color: var(--xk-gold-dim);
}
/* 老店卡把 3999 抬成全场最大字号：与 4999 拉开一整档，价差本身就是卖点 */
.xm-card.hot .xm-prefix { font-size: 15px; color: var(--xk-gold); }
.xm-card.hot .xm-cur { font-size: 30px; }
.xm-card.hot .xm-price b {
  font-size: 56px;
  /* 高光带扫过数字（背面渐变裁进文字）：常速运动用 linear；两端同色保证平铺无缝。
     background-position 非合成器属性，但作用面只有一个词的文字区域，实测无压力 */
  background: linear-gradient(110deg,
    var(--xk-gold) 0%, var(--xk-gold) 42%,
    var(--xk-gold-hi) 50%,
    var(--xk-gold) 58%, var(--xk-gold) 100%);
  background-size: 200% 100%;
  background-position: 100% 0;
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: xm-shimmer 3.6s linear 1.2s infinite;
}
/* 100% → -100% 恰好平移一个平铺周期（bg 宽 200%），循环首尾帧一致 */
@keyframes xm-shimmer { to { background-position: -100% 0; } }
/* 对比筹码：胶囊形数字锚点，回答「3999 到底值在哪」 */
.xm-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.xm-chip {
  padding: 5px 12px; border-radius: 999px;
  border: 1px solid rgba(232, 196, 121, 0.35);
  background: rgba(232, 196, 121, 0.08);
  font-size: 12.5px; letter-spacing: 0.08em; color: var(--xk-gold-hi);
}
.xm-daily { margin-top: 14px; font-size: 13px; line-height: 1.7; letter-spacing: 0.05em; color: var(--xk-paper); opacity: 0.78; }
.xm-pitch { margin: 16px 0 0; font-size: 13px; letter-spacing: 0.08em; color: var(--xk-paper); opacity: 0.86; }
/* 老店卡子元素接力入场：接在卡片 rise（70ms 起、320ms 止）尾部，逐行 70ms 落位；
   纯装饰不阻塞交互，复用 xm-rise 与全 kiosk 同一条 ease-out 曲线 */
.xm-card.hot .xm-price,
.xm-card.hot .xm-chips,
.xm-card.hot .xm-daily,
.xm-card.hot .xm-pitch {
  opacity: 0; transform: translateY(8px);
  animation: xm-rise 300ms cubic-bezier(0.23, 1, 0.32, 1) forwards;
}
.xm-card.hot .xm-price { animation-delay: 240ms; }
.xm-card.hot .xm-chips { animation-delay: 310ms; }
.xm-card.hot .xm-daily { animation-delay: 380ms; }
.xm-card.hot .xm-pitch { animation-delay: 450ms; }
.xm-list { margin: 16px 0 0; padding: 0; list-style: none; }
.xm-list li {
  position: relative; padding-left: 22px;
  font-size: 13px; line-height: 1.75; letter-spacing: 0.03em;
  color: var(--xk-paper); opacity: 0.9;
}
.xm-list li + li { margin-top: 9px; }
/* 金色菱钻项目符号：与镜框四角饰件同一母题 */
.xm-list li::before {
  content: ''; position: absolute; left: 4px; top: 9px;
  width: 6px; height: 6px; transform: rotate(45deg);
  background: var(--xk-gold); box-shadow: 0 0 6px rgba(232, 196, 121, 0.55);
}

.xm-foot {
  flex: none; margin-top: 20px; padding-top: 16px;
  border-top: 1px solid var(--xk-gold-line);
  text-align: center; font-size: 12px; letter-spacing: 0.18em; color: var(--xk-mut);
}

/* 模态入场对齐 kiosk 既有 xconfirm 手感：240ms 强 ease-out 进、160ms 出（非对称） */
.xmem-enter-active { transition: opacity 240ms cubic-bezier(0.23, 1, 0.32, 1); }
.xmem-enter-active .xm-panel { transition: transform 240ms cubic-bezier(0.23, 1, 0.32, 1); }
.xmem-leave-active { transition: opacity 160ms cubic-bezier(0.23, 1, 0.32, 1); }
.xmem-enter-from, .xmem-leave-to { opacity: 0; }
.xmem-enter-from .xm-panel { transform: scale(0.96); }
@media (prefers-reduced-motion: reduce) {
  .xmem-enter-from .xm-panel { transform: none; }
  .xm-card { opacity: 1; transform: none; animation: none; }
  .xm-card.hot .xm-price,
  .xm-card.hot .xm-chips,
  .xm-card.hot .xm-daily,
  .xm-card.hot .xm-pitch { opacity: 1; transform: none; animation: none; }
  /* 减动效下高光带停在静止金色，字号层级保留 */
  .xm-card.hot .xm-price b { animation: none; background: none; -webkit-text-fill-color: var(--xk-gold); }
}
</style>
