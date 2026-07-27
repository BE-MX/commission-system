<template>
  <div class="print-card-page">
    <div v-if="!card" class="loading-state">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <span>加载打印数据…</span>
    </div>
    <template v-else>
      <div class="card">
        <div class="header">
          <div>
            <h1>内贸流转卡</h1>
            <div class="order-no">{{ card.domestic_no }} · 客户订单号 {{ card.order_no }}</div>
          </div>
          <div v-if="card.order_type_label === '特单'" class="special-badge">特单</div>
        </div>

        <div class="body">
          <div class="left">
            <table class="info-table">
              <tr><td>客户店名</td><td><strong>{{ card.customer_name }}</strong></td></tr>
              <tr><td>产品</td><td><strong>{{ item.product_name }}</strong></td></tr>
              <tr><td>生产数量</td><td><span class="qty-value">{{ item.order_qty }}</span> 件</td></tr>
              <tr><td>下单日期</td><td>{{ card.order_date }}</td></tr>
            </table>
          </div>
          <div class="qr-section">
            <img v-if="card.qr_code_base64" :src="card.qr_code_base64" alt="报工二维码" />
            <div v-else class="qr-fallback">{{ card.qr_data }}</div>
            <div class="qr-hint">扫码报工<br>可按数量拆批</div>
          </div>
        </div>

        <!-- 图文要求印在卡上：车间对着卡就能看到参考图，不用再找跟单要 -->
        <div v-for="section in visibleSections" :key="section.key" class="req-section">
          <div class="req-label">{{ section.label }}</div>
          <div v-if="item[section.key]" class="req-text">{{ item[section.key] }}</div>
          <DomesticImages :paths="item[section.imageKey]" />
        </div>

        <div v-if="item.steps?.length" class="process-section">
          <h3>工序流转（每道做完扫码报工，可只报部分数量）</h3>
          <table class="process-table">
            <thead>
              <tr><th>#</th><th>工序</th><th>已完成</th><th>本次数量</th><th>经手人</th></tr>
            </thead>
            <tbody>
              <tr v-for="step in item.steps" :key="step.progress_id">
                <td>{{ step.step_order }}</td>
                <td>{{ step.process_name }}</td>
                <td>{{ step.completed_qty }} / {{ item.order_qty }}</td>
                <td class="sign-cell" />
                <td class="sign-cell" />
              </tr>
            </tbody>
          </table>
        </div>

        <div class="footer">
          <span>莱莎方舟平台 · 内贸生产</span>
          <span>打印时间：{{ card.printed_at }}</span>
          <span>卡号：{{ card.qr_data }}</span>
        </div>
      </div>

      <div class="no-print print-btn-wrap">
        <el-button type="primary" size="large" @click="doPrint">打印此卡</el-button>
      </div>
    </template>
  </div>
</template>

<script setup>
/** 内贸流转卡。二维码前缀 ARK-D，与外贸 ARK-P 分流互不干扰。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { DETAIL_SECTIONS, getPrintCard } from '@/api/domestic'
import DomesticImages from '@/components/domestic/DomesticImages.vue'

const route = useRoute()
const card = ref(null)

const item = computed(() => card.value?.item || {})

const visibleSections = computed(
  () => DETAIL_SECTIONS.filter(s => item.value[s.key] || item.value[s.imageKey]?.length),
)

function doPrint() {
  window.print()
}

onMounted(async () => {
  const res = await getPrintCard(route.params.id)
  card.value = res.data
})
</script>

<style scoped>
/* 打印页刻意用裸 hex 而非 tokens.css 变量（宪法 13 的既有例外，同 production/PrintCard.vue）：
   纸面输出要的是确定的黑白墨色，主题变量会随明暗主题变，打出来深浅不可控。 */
.print-card-page {
  padding: 20px;
  background: #f5f5f5;
  min-height: 100vh;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 80px 0;
  color: var(--el-text-color-secondary);
}

.card {
  width: 210mm;
  min-height: 148mm;
  margin: 0 auto;
  padding: 12mm;
  background: #fff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  color: #000;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 2px solid #000;
  padding-bottom: 8px;
}

.header h1 {
  margin: 0;
  font-size: 22px;
}

.order-no {
  margin-top: 4px;
  font-size: 13px;
}

.special-badge {
  padding: 4px 12px;
  border: 2px solid #000;
  font-weight: 700;
}

.body {
  display: flex;
  gap: 16px;
  margin-top: 10px;
}

.left { flex: 1; }

.info-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.info-table td {
  border: 1px solid #333;
  padding: 6px 8px;
}

.info-table td:first-child {
  width: 90px;
  background: #f0f0f0;
}

.qty-value {
  font-size: 20px;
  font-weight: 700;
}

.qr-section {
  width: 130px;
  text-align: center;
}

.qr-section img {
  width: 120px;
  height: 120px;
}

.qr-fallback {
  font-size: 11px;
  word-break: break-all;
  border: 1px dashed #666;
  padding: 6px;
}

.qr-hint {
  font-size: 11px;
  margin-top: 4px;
}

.req-section {
  margin-top: 10px;
  border: 1px solid #333;
  padding: 6px 8px;
}

.req-label {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 4px;
}

.req-text {
  font-size: 13px;
  white-space: pre-wrap;
  margin-bottom: 6px;
}

.process-section { margin-top: 12px; }

.process-section h3 {
  font-size: 14px;
  margin: 0 0 6px;
}

.process-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.process-table th,
.process-table td {
  border: 1px solid #333;
  padding: 6px 8px;
  text-align: left;
}

.process-table th { background: #f0f0f0; }

.sign-cell { height: 28px; }

.footer {
  display: flex;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 6px;
  border-top: 1px solid #999;
  font-size: 11px;
  color: #555;
}

.print-btn-wrap {
  text-align: center;
  margin-top: 20px;
}

@media print {
  .print-card-page { padding: 0; background: #fff; }
  .card { box-shadow: none; width: auto; margin: 0; }
  .no-print { display: none !important; }
}
</style>
