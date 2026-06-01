<template>
  <div class="print-card-page">
    <div v-if="!cardData" class="loading-state">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <span>加载打印数据...</span>
    </div>
    <template v-else>
      <div class="card" id="print-card">
        <!-- 顶部 -->
        <div class="header">
          <div class="header-left">
            <h1>工艺流转卡</h1>
            <div class="order-no">订单号：{{ cardData.order_no }}</div>
          </div>
          <div v-if="cardData.is_urgent" class="urgent-badge">🔴 紧急</div>
        </div>

        <!-- 产品信息 -->
        <div class="product-info">
          <table class="info-table">
            <tr><td>产品名称</td><td><strong>{{ cardData.product_name }}</strong></td></tr>
            <tr v-if="cardData.model"><td>型号</td><td>{{ cardData.model }}</td></tr>
            <tr v-if="cardData.spec_info"><td>规格</td><td>{{ cardData.spec_info }}</td></tr>
            <tr><td>生产数量</td><td><span class="qty-value">{{ cardData.order_qty }}</span> 件</td></tr>
            <tr v-if="cardData.expected_delivery_date"><td>交货日期</td><td><strong>{{ cardData.expected_delivery_date }}</strong></td></tr>
            <tr v-if="cardData.remark"><td>备注</td><td>{{ cardData.remark }}</td></tr>
          </table>
        </div>

        <!-- 二维码 -->
        <div class="qr-section">
          <img :src="cardData.qr_code_base64" alt="报工二维码" />
          <div class="qr-hint">📷 微信拍照<br>报工扫码</div>
        </div>

        <!-- 工序列表 -->
        <div v-if="cardData.process_steps.length > 0" class="process-section">
          <h3>工序路线（按序完成，完成后扫码报工）</h3>
          <div class="process-list">
            <div v-for="step in cardData.process_steps" :key="step.step_order" class="process-item">
              <span class="step-num">{{ step.step_order }}</span>
              <span class="step-name">{{ step.process_name }}</span>
              <span class="sign-area"></span>
            </div>
          </div>
        </div>

        <!-- 底部 -->
        <div class="footer">
          <span>方舟生产管理系统</span>
          <span>打印时间：{{ cardData.printed_at }}</span>
          <span>流转卡编号：OP-{{ cardData.order_product_id }}</span>
        </div>
      </div>

      <!-- 打印按钮（屏幕可见，打印隐藏） -->
      <div class="no-print print-btn-wrap">
        <el-button type="primary" size="large" @click="doPrint">🖨️ 打印此卡</el-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/production'

const route = useRoute()
const cardData = ref(null)

async function loadCard() {
  try {
    const id = route.params.id || route.query.id
    if (!id) { ElMessage.error('缺少订单产品ID'); return }
    const res = await api.getPrintCardData(id)
    cardData.value = res
    await nextTick()
  } catch (e) {
    ElMessage.error('加载打印数据失败')
  }
}

function doPrint() {
  window.print()
}

onMounted(async () => {
  await loadCard()
  // 自动打印
  setTimeout(() => { window.print() }, 800)
})
</script>

<style scoped>
.print-card-page { padding: 20px; display: flex; flex-direction: column; align-items: center; }
.loading-state { display: flex; align-items: center; gap: 8px; padding: 60px; color: #909399; }

.card {
  width: 210mm; min-height: 148mm; background: #fff; border: 2px solid #333;
  padding: 8mm 10mm; display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto auto 1fr auto;
  gap: 3mm; position: relative; box-shadow: 0 2px 10px rgba(0,0,0,0.1);
}

.header { grid-column: 1 / 3; display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1.5px solid #333; padding-bottom: 3mm; }
.header-left h1 { font-size: 16pt; font-weight: bold; color: #1a1a1a; margin: 0; }
.header-left .order-no { font-size: 11pt; color: #555; margin-top: 1mm; }
.urgent-badge { background: #e53e3e; color: white; font-size: 12pt; font-weight: bold; padding: 2mm 5mm; border-radius: 3mm; }
.product-info { grid-column: 1 / 2; }
.info-table { width: 100%; border-collapse: collapse; font-size: 10pt; }
.info-table td { padding: 1.5mm 2mm; vertical-align: top; }
.info-table td:first-child { font-weight: bold; color: #555; white-space: nowrap; width: 22mm; }
.qty-value { font-size: 14pt; font-weight: bold; color: #2d3748; }

.qr-section { grid-column: 2 / 3; grid-row: 2 / 4; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 2px dashed #333; border-radius: 3mm; padding: 3mm; min-width: 38mm; text-align: center; }
.qr-section img { width: 35mm; height: 35mm; display: block; }
.qr-hint { font-size: 8pt; color: #555; margin-top: 2mm; font-weight: bold; }

.process-section { grid-column: 1 / 2; }
.process-section h3 { font-size: 9pt; color: #555; font-weight: bold; margin-bottom: 1.5mm; border-bottom: 1px solid #ccc; padding-bottom: 1mm; }
.process-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1mm 3mm; }
.process-item { display: flex; align-items: center; gap: 1.5mm; font-size: 9pt; border-bottom: 0.5px dotted #aaa; padding: 1mm 0; }
.step-num { background: #4a5568; color: white; border-radius: 50%; width: 5mm; height: 5mm; display: flex; align-items: center; justify-content: center; font-size: 7pt; flex-shrink: 0; }
.step-name { flex: 1; font-weight: 600; }
.sign-area { flex: 1; border-bottom: 0.5px solid #999; min-width: 15mm; height: 4mm; }

.footer { grid-column: 1 / 3; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #ccc; padding-top: 2mm; font-size: 7.5pt; color: #777; }

.print-btn-wrap { margin-top: 20px; text-align: center; }

@media print {
  body { background: white; }
  .print-card-page { padding: 0; }
  .card { box-shadow: none; border: 1.5px solid #333; page-break-after: always; }
  .no-print { display: none !important; }
  @page { size: A5 landscape; margin: 5mm; }
}
</style>
