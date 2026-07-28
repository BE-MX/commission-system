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
              <b>¥{{ plan.price }}</b>
              <span class="xm-slash">/</span>
              <span class="xm-unit">{{ plan.unit }}</span>
            </div>
            <p class="xm-pitch">{{ plan.pitch }}</p>
            <div v-if="plan.inherit" class="xm-inherit">{{ plan.inherit }}</div>
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
// 老门店卡用继承线声明一致，不重复 11 行。
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
    inherit: '权益与新门店会员完全一致',
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
.xm-slash { font-size: 16px; line-height: 1; color: var(--xk-gold-dim); }
.xm-unit {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 16px; font-weight: 500; line-height: 1;
  letter-spacing: 0.08em; color: var(--xk-gold-dim);
}
.xm-pitch { margin: 16px 0 0; font-size: 13px; letter-spacing: 0.08em; color: var(--xk-paper); opacity: 0.86; }
.xm-inherit {
  margin-top: 16px; padding-bottom: 12px;
  border-bottom: 1px dashed var(--xk-gold-line);
  font-size: 12px; letter-spacing: 0.14em; color: var(--xk-gold-dim);
}
/* 老门店卡无权益清单，继承线是最后一行：收掉虚线免得像被裁掉的半截 */
.xm-inherit:last-child { border-bottom: none; padding-bottom: 0; }
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
}
</style>
