<template>
  <Transition name="xmem">
    <div v-if="open" class="xk-member" @click.self="$emit('close')" @pointerdown="armIdle">
      <div class="xm-panel">
        <button class="xm-close" aria-label="关闭" @click="$emit('close')">×</button>

        <header class="xm-head">
          <div class="xm-kicker">L E S H I N E · 门 店 合 作</div>
          <h3 class="xm-title">门店 AI <em>智能试戴</em> 终端</h3>
          <p class="xm-sub">专用平板 + AI 试戴系统 + 全年服务 · 展会首发，限 50 家种子门店</p>
        </header>

        <div class="xm-body">
          <section
            v-for="(plan, i) in plans" :key="plan.name"
            class="xm-card" :class="{ hot: plan.hot }" :style="{ '--stagger': `${i * 70}ms` }"
          >
            <div v-if="plan.badge" class="xm-badge">{{ plan.badge }}</div>
            <div class="xm-name">{{ plan.name }}</div>
            <div class="xm-price">
              <span class="xm-prefix">{{ plan.prefix }}</span>
              <span class="xm-cur">¥</span><b>{{ plan.price }}</b>
              <template v-if="plan.unit">
                <span class="xm-slash">/</span>
                <span class="xm-unit">{{ plan.unit }}</span>
              </template>
            </div>
            <div v-if="plan.chips" class="xm-chips">
              <span v-for="chip in plan.chips" :key="chip" class="xm-chip">{{ chip }}</span>
            </div>
            <ul class="xm-list">
              <li v-for="item in plan.items" :key="item">{{ item }}</li>
            </ul>
            <div v-if="plan.duties" class="xm-duty">
              <div class="xm-duty-label">{{ plan.dutyLabel }}</div>
              <ul class="xm-duty-list">
                <li v-for="duty in plan.duties" :key="duty">{{ duty }}</li>
              </ul>
            </div>
            <p class="xm-pitch">{{ plan.pitch }}</p>
          </section>
        </div>

        <!-- 从现场到开通的交付时间线：老板最关心「付了钱之后发生什么」 -->
        <div class="xm-steps">
          <div v-for="(step, i) in steps" :key="step.t" class="xm-step">
            <i>{{ i + 1 }}</i>
            <b>{{ step.t }}</b>
            <span>{{ step.d }}</span>
          </div>
        </div>

        <footer class="xm-foot">
          设备暂不提供免费外借 · 详情请咨询展位顾问
          <span class="xm-legal">最终解释权归莱莎公司所有</span>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { onBeforeUnmount, watch } from 'vue'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])

// 空闲自动收起：attract 屏本身不挂 idle 定时器（useTryOnFlow.touch 在 attract 直接 return），
// 弹窗不自己兜底就会一直挂着，下一位观众走过来看到的是方案表而不是试戴入口。
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

// 首发合作方案为展会现场固定物料，不走后台配置，调整直接改此处文案。
// 手写数字联动：首发价 2999 / 押金 1500 / 补差 1499（= 2999 - 1500）三处强关联，改一处必须同步；
// 正式价 3999、次年续费 1999（= 2999 - 1000）、年额度 500 张（2026-07-28 亮哥定）也在此维护。
// 年费旧方案封存于 MembershipDialog.vue，换回改 AttractScreen 的 import 即可。
const plans = [
  {
    name: '首发合作',
    prefix: '展会首发价',
    price: '2999',
    unit: '首年',
    pitch: '首发价换真实案例，只给前 50 家',
    hot: true,
    badge: '限 50 家',
    chips: ['正式价 ¥3999 · 满 50 家后执行', '次年续费 ¥1999'],
    items: [
      '专用平板一台（次年续费无需重复配）',
      'AI 试戴系统 + 标准产品库',
      'AI 生成图 500 张 / 年',
      '全年服务，自系统正式开通当天起算',
      '现场可体验试戴、打印你的 AI 形象照',
    ],
  },
  {
    name: '7 天试用',
    prefix: '押金',
    price: '1500',
    pitch: '先放店里真试七天，再决定要不要同行',
    chips: ['合适 · 补 ¥1499 转首年', '不合适 · 退回平板全额退押金'],
    items: [
      '一个门店账号 · AI 生成 30 次',
      '开放标准产品库',
      '生成图片带轻量品牌标识',
      '不含门店专属页面与品牌定制',
      '到期自动停止生成',
    ],
    // 种子门店的数据回传义务：50 家真实案例的原料就从这六条来
    dutyLabel: '试用期间 · 店面需配合',
    duties: [
      '提供真实顾客体验',
      '记录顾客最喜欢的发型',
      '记录进一步咨询产品的人数',
      '记录最终购买产品的人数',
      '反馈 AI 效果与实物的差异',
      '至少一位员工接受使用培训',
    ],
  },
]

const steps = [
  { t: '现场体验 · 选定方案', d: '完整演示门店使用流程，观看真实门店模拟' },
  { t: '提交资料 · 付款签约', d: '支付订金或全款，即完成签约与名额锁定' },
  { t: '展后安装配置', d: '系统安装 · 门店绑定 · 产品库配置，7–10 个工作日交付' },
  { t: '发货 + 线上培训', d: '统一发货，服务期自正式开通当天起算' },
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
  /* 卡片依次入场：短 stagger 让「合作」与「试用」有先后节奏，不阻塞任何交互 */
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
/* 数字是主角：门槛动作（首发价/押金）作前缀，「/ 首年」退为注脚 */
.xm-price { display: flex; align-items: baseline; gap: 7px; margin-top: 14px; flex-wrap: wrap; }
.xm-prefix { font-size: 13px; letter-spacing: 0.14em; color: var(--xk-gold-dim); }
.xm-cur { font-family: 'Noto Serif SC', 'STSong', serif; font-size: 22px; line-height: 1; color: var(--xk-gold); }
.xm-price b {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 40px; font-weight: 600; line-height: 1; color: var(--xk-gold);
}
.xm-slash { font-size: 16px; line-height: 1; color: var(--xk-gold-dim); }
.xm-unit {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 16px; font-weight: 500; line-height: 1;
  letter-spacing: 0.08em; color: var(--xk-gold-dim);
}
/* 首发卡把 2999 抬成全场最大字号，沿用 kiosk 高光扫动 */
.xm-card.hot .xm-prefix { font-size: 15px; color: var(--xk-gold); }
.xm-card.hot .xm-cur { font-size: 30px; }
.xm-card.hot .xm-price b {
  font-size: 56px;
  /* 高光带扫过数字（背景渐变裁进文字）：常速运动用 linear；两端同色保证平铺无缝。
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
/* 对比筹码：胶囊形数字锚点（价格坐标系 / 押金进退路径） */
.xm-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.xm-chip {
  padding: 5px 12px; border-radius: 999px;
  border: 1px solid rgba(232, 196, 121, 0.35);
  background: rgba(232, 196, 121, 0.08);
  font-size: 12.5px; letter-spacing: 0.08em; color: var(--xk-gold-hi);
}
.xm-pitch { margin: 16px 0 0; font-size: 13px; letter-spacing: 0.08em; color: var(--xk-paper); opacity: 0.86; }
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
/* 首发卡子元素接力入场：接在卡片 rise 尾部，逐行 70ms 落位；
   纯装饰不阻塞交互，复用 xm-rise 与全 kiosk 同一条 ease-out 曲线 */
.xm-card.hot .xm-price,
.xm-card.hot .xm-chips,
.xm-card.hot .xm-list,
.xm-card.hot .xm-pitch {
  opacity: 0; transform: translateY(8px);
  animation: xm-rise 300ms cubic-bezier(0.23, 1, 0.32, 1) forwards;
}
.xm-card.hot .xm-price { animation-delay: 240ms; }
.xm-card.hot .xm-chips { animation-delay: 310ms; }
.xm-card.hot .xm-list { animation-delay: 380ms; }
.xm-card.hot .xm-pitch { animation-delay: 450ms; }

/* 试用义务：与权益清单虚线分隔；「给」用暗金小菱钻区别于「得」的亮金菱钻，双栏收紧高度 */
.xm-duty { margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--xk-gold-line); }
.xm-duty-label { font-size: 12px; letter-spacing: 0.14em; color: var(--xk-gold-dim); }
.xm-duty-list {
  margin: 10px 0 0; padding: 0; list-style: none;
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px;
}
.xm-duty-list li {
  position: relative; padding-left: 16px;
  font-size: 12.5px; line-height: 1.6; letter-spacing: 0.03em;
  color: var(--xk-paper); opacity: 0.85;
}
.xm-duty-list li::before {
  content: ''; position: absolute; left: 2px; top: 7px;
  width: 5px; height: 5px; transform: rotate(45deg);
  background: var(--xk-gold-dim);
}

/* 交付时间线：四步等宽，虚线框呼应「流程」的过程感；窄屏退化为纵向堆叠 */
.xm-steps { flex: none; display: grid; grid-template-columns: 1fr; gap: 10px; margin-top: 18px; }
@media (min-width: 900px) {
  .xm-steps { grid-template-columns: repeat(4, 1fr); }
}
.xm-step {
  position: relative; padding: 12px 14px 12px 40px;
  border: 1px dashed var(--xk-gold-line); border-radius: 12px;
}
.xm-step i {
  position: absolute; left: 12px; top: 13px;
  width: 20px; height: 20px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--xk-gold-line); color: var(--xk-gold);
  font-style: normal; font-size: 11px;
  font-family: 'Noto Serif SC', 'STSong', serif;
}
.xm-step b { display: block; font-size: 12.5px; font-weight: 600; letter-spacing: 0.08em; color: var(--xk-gold-hi); }
.xm-step span { display: block; margin-top: 4px; font-size: 11.5px; line-height: 1.6; letter-spacing: 0.04em; color: var(--xk-mut); }

.xm-foot {
  flex: none; margin-top: 16px; padding-top: 14px;
  border-top: 1px solid var(--xk-gold-line);
  text-align: center; font-size: 12px; letter-spacing: 0.18em; color: var(--xk-mut);
}
/* 免责行：全场最小最暗，惯例居末 */
.xm-legal { display: block; margin-top: 6px; font-size: 11px; letter-spacing: 0.14em; color: var(--xk-mut); opacity: 0.75; }

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
  .xm-card.hot .xm-list,
  .xm-card.hot .xm-pitch { opacity: 1; transform: none; animation: none; }
  /* 减动效下高光带停在静止金色，字号层级保留 */
  .xm-card.hot .xm-price b { animation: none; background: none; -webkit-text-fill-color: var(--xk-gold); }
}
</style>
