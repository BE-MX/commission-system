<template>
  <div class="capture">
    <div class="viewport">
      <!-- 相机可用：实时取景；不可用：文件选择兜底 -->
      <video v-show="cameraOn && !previewUrl" ref="videoEl" autoplay playsinline muted
             :class="{ rear: facing === 'environment' }" />
      <img v-if="previewUrl" :src="previewUrl" class="preview" alt="预览"
           @load="onPreviewLoaded" @error="onPreviewError" />
      <div v-if="previewLoading" class="preview-loading">图片加载中…</div>
      <div v-if="flashing" class="flash" aria-hidden="true" />

      <div v-if="!previewUrl" class="guide" />
      <div class="corner tl" /><div class="corner tr" />
      <div class="corner bl" /><div class="corner br" />

      <button v-if="!previewUrl" class="guide-entry" @click="openGuide">拍摄示范 ✦</button>

      <div v-if="!previewUrl" class="tip">
        {{ isScene ? '保持佩戴状态，将面部对准取景框' : '面部对准取景框 · 镜头略高于视线' }}
        <small>{{ isScene ? '发型完整入镜 · 光线充足 · 拍完可重拍' : '微微抬头 · 面部微侧 · 露出肩颈上身' }}</small>
      </div>
      <div v-if="!cameraOn && !previewUrl" class="fallback">
        <label class="xk-btn ghost">
          从相册选择 / 调用系统相机
          <input type="file" accept="image/*" capture="user" hidden @change="onFilePick" />
        </label>
        <!-- 平板摄像头不可用时最需要这条路：客户用自己手机拍/选，比在这台设备上翻相册更从容 -->
        <button class="xk-btn ghost" @click="flow.openQr()">
          <svg class="btn-ico" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="3" width="6" height="6" rx="1" />
            <rect x="15" y="3" width="6" height="6" rx="1" />
            <rect x="3" y="15" width="6" height="6" rx="1" />
            <rect class="blk" x="14.5" y="14.5" width="2.6" height="2.6" />
            <rect class="blk" x="18.5" y="14.5" width="2" height="2" />
            <rect class="blk" x="14.5" y="18.5" width="2" height="2" />
            <rect class="blk" x="18" y="18" width="3" height="3" />
          </svg>
          扫码传照片
        </button>
      </div>
    </div>

    <div class="actions">
      <template v-if="previewUrl">
        <button class="xk-btn ghost" @click="retake">重拍</button>
        <button class="xk-btn" :disabled="submitting" @click="confirm">
          {{ submitting ? '上传中…' : '就用这张' }}
        </button>
      </template>
      <!-- 三槽布局：快门始终居中。右侧槽改双层堆叠（本地相册 + 扫码传照片）而非并列加第 4 项——
           并列会让快门偏左，破坏下面 .side 注释里说的居中约束 -->
      <template v-else-if="cameraOn">
        <button class="xk-btn ghost side" @click="flipCamera">
          <svg class="btn-ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20.5 12a8.5 8.5 0 0 0-8.5-8.5 9 9 0 0 0-6.4 2.6L3.5 8.2" />
            <path d="M3.5 3.6v4.6h4.6" />
            <path d="M3.5 12a8.5 8.5 0 0 0 8.5 8.5 9 9 0 0 0 6.4-2.6l2.1-2.1" />
            <path d="M20.5 20.4v-4.6h-4.6" />
            <circle class="dot" cx="12" cy="12" r="2.2" />
          </svg>
          反转镜头
        </button>
        <button class="shutter" aria-label="拍照" @click="snap"><i /></button>
        <div class="side-stack">
          <label class="xk-btn ghost">
            <svg class="btn-ico" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
              <circle cx="8.6" cy="9.6" r="1.7" />
              <path d="M21 15.4l-4.6-4.6L7 20.2" />
            </svg>
            本地相册
            <input type="file" accept="image/*" hidden @change="onFilePick" />
          </label>
          <button class="xk-btn ghost" @click="flow.openQr()">
            <svg class="btn-ico" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3" y="3" width="6" height="6" rx="1" />
              <rect x="15" y="3" width="6" height="6" rx="1" />
              <rect x="3" y="15" width="6" height="6" rx="1" />
              <rect class="blk" x="14.5" y="14.5" width="2.6" height="2.6" />
              <rect class="blk" x="18.5" y="14.5" width="2" height="2" />
              <rect class="blk" x="14.5" y="18.5" width="2" height="2" />
              <rect class="blk" x="18" y="18" width="3" height="3" />
            </svg>
            扫码传照片
          </button>
        </div>
      </template>
    </div>

    <!-- 最佳拍摄角度示范：进入拍照屏自动展示（kiosk 用户皆为一次性用户），可从取景框顶部按钮重开 -->
    <div v-if="guideOpen" class="gd-overlay" @click.self="closeGuide">
      <div class="gd-panel">
        <div class="gd-title">三步拍出高级感</div>
        <div class="gd-sub">{{ isScene ? '好照片，让场景大片更出彩' : '好照片，让试戴效果更逼真' }}</div>

        <div class="gd-figs">
          <figure class="gd-fig">
            <svg viewBox="0 0 120 96" aria-hidden="true">
              <!-- 人物侧影：头 + 肩身弧 -->
              <circle cx="38" cy="46" r="13" fill="rgba(232, 196, 121, 0.08)" stroke="var(--xk-gold)" stroke-width="1.6" />
              <path d="M16 90 Q38 60 60 90" fill="rgba(232, 196, 121, 0.08)" stroke="var(--xk-gold)" stroke-width="1.6" />
              <circle cx="44" cy="44" r="1.6" fill="var(--xk-gold-hi)" />
              <!-- 相机在右上：略高于视线，连线呈俯角 -->
              <rect x="92" y="12" width="17" height="11" rx="2.5" fill="none" stroke="var(--xk-gold-hi)" stroke-width="1.6" />
              <circle cx="100.5" cy="17.5" r="2.6" fill="none" stroke="var(--xk-gold-hi)" stroke-width="1.2" />
              <line x1="90" y1="22" x2="52" y2="42" stroke="var(--xk-gold-dim)" stroke-width="1.2" stroke-dasharray="4 4" />
              <path d="M56 38 L52 42 L58 43" fill="none" stroke="var(--xk-gold-dim)" stroke-width="1.2" />
            </svg>
            <figcaption>镜头略高于视线<small>微微抬头 · 下颌更清晰</small></figcaption>
          </figure>
          <figure class="gd-fig">
            <svg viewBox="0 0 90 120" aria-hidden="true">
              <!-- 取景框 + 三分线，头部落在上三分之一 -->
              <rect x="3" y="3" width="84" height="114" rx="9" fill="none" stroke="var(--xk-gold)" stroke-width="1.6" />
              <line x1="3" y1="41" x2="87" y2="41" stroke="var(--xk-gold-dim)" stroke-width="1" stroke-dasharray="4 4" opacity="0.7" />
              <line x1="3" y1="79" x2="87" y2="79" stroke="var(--xk-gold-dim)" stroke-width="1" stroke-dasharray="4 4" opacity="0.7" />
              <ellipse cx="45" cy="34" rx="12" ry="14" fill="rgba(232, 196, 121, 0.08)" stroke="var(--xk-gold)" stroke-width="1.6" />
              <path d="M20 117 Q45 58 70 117" fill="rgba(232, 196, 121, 0.08)" stroke="var(--xk-gold)" stroke-width="1.6" />
            </svg>
            <figcaption>头部靠上 · 多露上身<small>面部微侧 · 背景简洁</small></figcaption>
          </figure>
        </div>

        <ul class="gd-tips">
          <li><b>略微俯拍</b>镜头稍高于视线，微微抬头看镜头，眼神更明亮</li>
          <li><b>微侧面容</b>面部与身体带一点角度，露出约四分之三面容，五官更立体</li>
          <li><b>构图靠上</b>头部位于画面上三分之一，露出肩颈与上身，光线柔和均匀</li>
        </ul>

        <button class="xk-btn gd-go" @click="closeGuide">知道了，开始拍摄</button>
      </div>
    </div>

    <!-- 二维码上传浮层：拍摄页的次级入口，快门主路径行为不变。点背景关闭与拍摄示范浮层
         同一套约定；意外点关不丢数据——pending-photo 按 customer_id 查找而非按令牌，
         重新点「扫码传照片」拿新令牌照样能立刻捞到客户手机那边已传完的照片 -->
    <div v-if="flow.qrUrl.value" class="qr-overlay" @click.self="flow.closeQr()">
      <div class="qr-panel">
        <div class="qr-title">用手机上传照片</div>
        <div class="qr-sub">相册里的美照、或用手机拍一张，都比现场更从容</div>
        <canvas ref="qrCanvas" width="220" height="220" class="qr-canvas" />
        <div class="qr-hint">微信扫一扫 · 上传后本屏自动显示 · {{ qrValidMinutes }} 分钟内有效</div>
        <button class="xk-btn ghost" @click="flow.closeQr()">取消，我现场拍</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useCaptureScreen } from '../composables/useCaptureScreen'

const {
  flow, isScene,
  videoEl, cameraOn, previewUrl, submitting,
  guideOpen, openGuide, closeGuide,
  facing, flipCamera,
  qrCanvas, previewLoading, qrValidMinutes,
  onPreviewLoaded, onPreviewError,
  flashing, snap, onFilePick, retake, confirm,
} = useCaptureScreen()
</script>

<style scoped>
.capture { flex: 1; display: flex; flex-direction: column; padding: 0 4vw 3vh; }
.viewport {
  position: relative; flex: 1; min-height: 0;
  border-radius: 26px; overflow: hidden;
  background: radial-gradient(60% 55% at 50% 42%, #2c251c, #15110c);
}
video, .preview {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: cover; transform: scaleX(-1); /* 镜像取景更符合直觉 */
}
.preview { transform: none; }
video.rear { transform: none; } /* 后置不镜像：所见即实景方向 */
/* 快门闪：按下即时反馈，白幕快速淡出 */
.flash { position: absolute; inset: 0; z-index: 6; background: #fff; animation: shutter-flash 180ms ease-out forwards; }
@keyframes shutter-flash { from { opacity: 0.85; } to { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .flash { animation-duration: 90ms; } }
.guide {
  /* 中心 40%：头部落在画面上三分之一附近，下方多容纳肩颈上身（2026-07-13 拍摄构图引导） */
  position: absolute; left: 50%; top: 40%; transform: translate(-50%, -50%);
  width: min(52vw, 300px); aspect-ratio: 0.78; border-radius: 50% / 54%;
  border: 2px dashed rgba(232, 196, 121, 0.75);
  box-shadow: 0 0 0 200vmax rgba(8, 6, 4, 0.55);
  animation: guide-pulse 2.6s ease-in-out infinite;
}
@keyframes guide-pulse {
  0%, 100% { border-color: rgba(232, 196, 121, 0.4); }
  50% { border-color: var(--xk-gold-hi); }
}
.corner { position: absolute; width: 26px; height: 26px; border: 2px solid var(--xk-gold); }
.corner.tl { top: 18px; left: 18px; border-right: 0; border-bottom: 0; border-radius: 8px 0 0 0; }
.corner.tr { top: 18px; right: 18px; border-left: 0; border-bottom: 0; border-radius: 0 8px 0 0; }
.corner.bl { bottom: 18px; left: 18px; border-right: 0; border-top: 0; border-radius: 0 0 0 8px; }
.corner.br { bottom: 18px; right: 18px; border-left: 0; border-top: 0; border-radius: 0 0 8px 0; }
.tip {
  position: absolute; left: 0; right: 0; bottom: 26px; text-align: center;
  font-size: 14px; letter-spacing: 0.2em; color: var(--xk-gold-hi);
}
.tip small { display: block; margin-top: 6px; font-size: 11px; color: var(--xk-mut); letter-spacing: 0.14em; }
.fallback {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  display: flex; flex-direction: column; align-items: center; gap: 12px;
}
.preview-loading {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  padding: 8px 18px; border-radius: 16px; font-size: 12px; letter-spacing: 0.12em;
  color: var(--xk-gold-hi); background: rgba(8, 6, 4, 0.55); backdrop-filter: blur(3px);
}
.actions {
  flex: none; display: flex; justify-content: center; gap: 16px;
  padding-top: 18px; min-height: 88px; align-items: center;
}
/* 快门两侧等宽占位，保证快门绝对居中；相册入口做次级视觉弱化。
   宽度必须容得下「图标 + 四字 + 字距」：xk-btn 自带 padding 0 44px，沿用的话内容区只剩
   112-88=24px，比一个字还窄，四个字会被挤成竖排——这里覆盖掉 padding 并给足宽度。 */
/* box-sizing 必须显式写：button 的 UA 默认是 border-box，label 是 content-box，
   同样的 width 在两者上差出 padding+border（26px），快门就不居中了 */
.side { width: 148px; flex: none; padding: 0 12px; gap: 8px; box-sizing: border-box; }
/* 右侧槽堆叠（本地相册 + 扫码传照片）：外层只管 148px 宽与列排布，
   .side 那份 padding/gap/box-sizing 是给单个按钮内部 icon+文字排布用的，
   堆叠后改由每个子按钮各自套用（撑满 100% 宽），跟左侧反转镜头保持视觉对称 */
.side-stack { width: 148px; flex: none; display: flex; flex-direction: column; gap: 8px; }
.side-stack > .xk-btn {
  width: 100%; padding: 0 12px; gap: 8px; box-sizing: border-box;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
}
.btn-ico {
  width: 18px; height: 18px; flex: none;
  fill: none; stroke: currentColor; stroke-width: 1.6;
  stroke-linecap: round; stroke-linejoin: round;
}
/* 镜头点/二维码数据块画实心：18px 下空心小图形会糊成一团 */
.btn-ico .dot, .btn-ico .blk { fill: currentColor; stroke: none; }
.shutter {
  width: 72px; height: 72px; border-radius: 50%;
  border: 2px solid var(--xk-gold); background: transparent;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
}
.shutter i {
  width: 56px; height: 56px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, var(--xk-gold-hi), var(--xk-gold) 60%, var(--xk-gold-dim));
}
.shutter:active i { transform: scale(0.92); }

/* ── 拍摄示范入口（取景框顶部居中胶囊） ── */
.guide-entry {
  position: absolute; left: 50%; top: 16px; transform: translateX(-50%);
  height: 34px; padding: 0 16px; border-radius: 18px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: rgba(8, 6, 4, 0.45);
  color: var(--xk-gold-hi); font-size: 12px; letter-spacing: 0.14em;
  backdrop-filter: blur(3px);
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease;
}
.guide-entry:active { transform: translateX(-50%) scale(0.96); }

/* ── 拍摄示范浮层（黑金浮层，复用 kiosk lib-overlay 模式） ── */
.gd-overlay {
  position: fixed; inset: 0; z-index: 40; display: flex; align-items: center; justify-content: center;
  /* 同 lib-overlay：fixed 不吃 .xk-root 的安全区，面板高度改为相对本容器（vh ≠ 手机可见高度） */
  padding:
    calc(16px + env(safe-area-inset-top)) calc(12px + env(safe-area-inset-right))
    calc(16px + env(safe-area-inset-bottom)) calc(12px + env(safe-area-inset-left));
  background: rgba(6, 5, 3, 0.72); backdrop-filter: blur(4px); animation: gd-fade 200ms ease;
}
@keyframes gd-fade { from { opacity: 0; } }
.gd-panel {
  width: min(92vw, 560px); max-height: 100%; overflow-y: auto;
  display: flex; flex-direction: column; align-items: center;
  padding: 30px 30px 26px; border: 1px solid var(--xk-gold-line); border-radius: 22px;
  background: linear-gradient(160deg, var(--xk-ink-2), var(--xk-ink));
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.5), 0 0 40px rgba(232, 196, 121, 0.12);
  animation: gd-pop 240ms cubic-bezier(0.23, 1, 0.32, 1);
}
@keyframes gd-pop { from { opacity: 0; transform: scale(0.96); } }
.gd-title {
  font-family: 'Noto Serif SC', serif; font-size: 22px; letter-spacing: 0.14em;
  color: var(--xk-gold-hi);
}
.gd-sub { margin-top: 6px; font-size: 12px; letter-spacing: 0.2em; color: var(--xk-mut); }
.gd-figs { display: flex; flex-wrap: wrap; justify-content: center; gap: 22px; margin-top: 22px; }
.gd-fig {
  display: flex; flex-direction: column; align-items: center; gap: 10px; margin: 0;
  animation: gd-rise 300ms cubic-bezier(0.23, 1, 0.32, 1) backwards;
}
.gd-fig:nth-child(1) { animation-delay: 80ms; }
.gd-fig:nth-child(2) { animation-delay: 140ms; }
.gd-fig svg {
  height: 132px; width: auto; display: block;
  border: 1px solid var(--xk-gold-line); border-radius: 14px; padding: 10px;
  background: rgba(232, 196, 121, 0.04);
}
.gd-fig figcaption {
  font-size: 13px; letter-spacing: 0.1em; color: var(--xk-gold); text-align: center;
}
.gd-fig figcaption small {
  display: block; margin-top: 4px; font-size: 10px; letter-spacing: 0.14em; color: var(--xk-mut);
}
.gd-tips { list-style: none; margin: 20px 0 0; padding: 0; width: 100%; }
.gd-tips li {
  display: flex; align-items: baseline; gap: 10px;
  padding: 7px 0; font-size: 13px; line-height: 1.7; color: var(--xk-mut);
  animation: gd-rise 300ms cubic-bezier(0.23, 1, 0.32, 1) backwards;
}
.gd-tips li:nth-child(1) { animation-delay: 200ms; }
.gd-tips li:nth-child(2) { animation-delay: 260ms; }
.gd-tips li:nth-child(3) { animation-delay: 320ms; }
.gd-tips b {
  flex: none; font-weight: 400; font-size: 12px; letter-spacing: 0.1em; color: var(--xk-gold-hi);
  border: 1px solid var(--xk-gold-line); border-radius: 12px; padding: 2px 10px;
}
@keyframes gd-rise { from { opacity: 0; transform: translateY(8px); } }
.gd-go { margin-top: 22px; min-width: 240px; }

@media (prefers-reduced-motion: reduce) {
  .gd-panel { animation: gd-fade 200ms ease; }
  .gd-fig, .gd-tips li { animation: gd-fade 200ms ease backwards; }
}

/* 手机竖屏：示范浮层收紧内边距，CTA 撑满 */
@media (max-width: 560px) {
  .gd-panel { padding: 22px 18px 20px; }
  .gd-go { min-width: 0; width: 100%; }
}

/* ── 二维码上传浮层 ── */
.qr-overlay {
  position: fixed; inset: 0; z-index: 40; display: flex;
  align-items: center; justify-content: center;
  background: rgba(6, 5, 4, 0.82); backdrop-filter: blur(6px);
}
.qr-panel {
  display: flex; flex-direction: column; align-items: center; gap: 14px;
  padding: 32px 34px; border-radius: 20px;
  border: 1px solid var(--xk-gold-line); background: var(--xk-ink);
}
.qr-title { font-size: 17px; color: var(--xk-gold); letter-spacing: 0.1em; }
.qr-sub { font-size: 12px; color: var(--xk-mut); }
.qr-canvas { border-radius: 12px; }
.qr-hint { font-size: 12px; color: var(--xk-gold-dim); letter-spacing: 0.08em; }
</style>
