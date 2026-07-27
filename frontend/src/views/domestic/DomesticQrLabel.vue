<template>
  <div class="label-page">
    <div v-if="loadError" class="hint-state">{{ loadError }}</div>
    <div v-else-if="!card" class="hint-state">
      <el-icon class="is-loading" :size="28"><Loading /></el-icon>
      <span>加载中…</span>
    </div>

    <template v-else>
      <!-- 30mm × 20mm 不干胶：左 LOGO 右二维码，没有第三样东西 -->
      <div class="label">
        <img class="label-logo" :src="logoUrl" alt="莱莎健康假发" />
        <img v-if="card.qr_code_base64" class="label-qr" :src="card.qr_code_base64" alt="报工二维码" />
        <div v-else class="label-qr label-qr--fallback">{{ card.qr_data }}</div>
      </div>

      <div class="no-print toolbar">
        <div class="meta">
          <div class="meta-line"><strong>{{ card.item?.product_name }}</strong></div>
          <div class="meta-line">{{ card.domestic_no }} · {{ card.customer_name }} · {{ card.item?.order_qty }} 件</div>
        </div>
        <div class="actions">
          <el-input-number v-model="copies" :min="1" :max="50" size="small" />
          <span class="copies-hint">份</span>
          <el-button type="primary" @click="doPrint">打印标签</el-button>
        </div>
        <p class="tip">
          打印前把打印机纸张设为 <strong>30 × 20 mm</strong>、缩放选「实际大小 / 100%」，
          否则标签会被缩到 A4 页面中间。
        </p>
      </div>

      <!-- 多份打印：同一张标签复制 N 次，每份独占一页 -->
      <div v-if="copies > 1" class="extra-labels">
        <div v-for="n in copies - 1" :key="n" class="label">
          <img class="label-logo" :src="logoUrl" alt="莱莎健康假发" />
          <img v-if="card.qr_code_base64" class="label-qr" :src="card.qr_code_base64" alt="报工二维码" />
          <div v-else class="label-qr label-qr--fallback">{{ card.qr_data }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
/**
 * 内贸报工二维码标签（30×20mm 不干胶）。
 * 与流转卡是两个用途：流转卡是随货走的作业单（带图文要求和工序表），
 * 标签是贴在货品/周转筐上的扫码入口，只要认得出品牌 + 扫得动。
 */
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { getPrintCard } from '@/api/domestic'
import logoUrl from '@/assets/domestic-logo.png'

const route = useRoute()
const card = ref(null)
const loadError = ref('')
const copies = ref(1)

function doPrint() {
  window.print()
}

onMounted(async () => {
  try {
    const res = await getPrintCard(route.params.id)
    card.value = res.data
  } catch {
    loadError.value = '这张标签对应的明细已经不存在了（订单可能已被删除）'
  }
})
</script>

<style scoped>
/* 标签是物理产物：尺寸用 mm、颜色用确定墨色，不走主题变量
   （同 DomesticPrintCard.vue，宪法 13 的既有打印例外） */
.label-page {
  padding: 24px;
  background: #f5f5f5;
  min-height: 100vh;
}

.hint-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 80px 0;
  color: #666;
}

.label {
  width: 30mm;
  height: 20mm;
  margin: 0 auto;
  padding: 1mm;
  box-sizing: border-box;
  background: #fff;
  display: flex;
  align-items: center;
  gap: 0.8mm;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
}

/* 左侧 LOGO：竖版图，按高度撑满、宽度自适应 */
.label-logo {
  height: 100%;
  width: 10mm;
  object-fit: contain;
  flex-shrink: 0;
}

/* 右侧二维码：吃满剩余宽度，尽量大 —— 小标签上扫得动比好看重要。
   宽度算式：30 − 左右各 1 内边距 − LOGO 10 − 间距 0.8 = 17.2 */
.label-qr {
  height: 100%;
  width: 17.2mm;
  object-fit: contain;
  flex-shrink: 0;
  image-rendering: pixelated;   /* 缩放时不做平滑，保住码点边缘 */
}

.label-qr--fallback {
  font-size: 1.4mm;
  line-height: 1.2;
  word-break: break-all;
  border: 0.2mm dashed #666;
  display: flex;
  align-items: center;
  padding: 0.5mm;
}

.extra-labels .label {
  margin-top: 6mm;
}

.toolbar {
  max-width: 420px;
  margin: 24px auto 0;
  padding: 16px;
  background: #fff;
  border-radius: 10px;
  text-align: center;
}

.meta-line {
  font-size: 13px;
  color: #444;
  margin-bottom: 4px;
}

.actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
}

.copies-hint {
  font-size: 13px;
  color: #666;
  margin-right: 8px;
}

.tip {
  margin: 12px 0 0;
  font-size: 12px;
  color: #888;
  line-height: 1.6;
}

@media print {
  /* 标签打印机按这个尺寸走纸，零页边距 */
  @page {
    size: 30mm 20mm;
    margin: 0;
  }

  .label-page {
    padding: 0;
    background: #fff;
    min-height: 0;
  }

  .no-print { display: none !important; }

  .label {
    box-shadow: none;
    margin: 0;
    page-break-after: always;
  }

  .extra-labels .label { margin-top: 0; }

  /* 最后一张不要多吐一页空白 */
  .extra-labels .label:last-child { page-break-after: auto; }
}
</style>
