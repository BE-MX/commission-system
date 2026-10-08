<template>
  <section>
    <div class="detail-metrics">
      <div v-for="metric in metrics" :key="metric[0]"><span>{{ metric[1] }} · {{ currency }}</span><strong>{{ amount(panel.summary?.[metric[0]]) }}</strong></div>
    </div>
    <p v-if="Number(panel.summary?.overpaid_amount) > 0" class="detail-warning">超收 {{ currency }} {{ amount(panel.summary.overpaid_amount) }}，请核对原单。</p>
    <div v-if="panel.freight" class="detail-note">运费独立结算，不计入商品款进度。<br />应收 {{ amount(panel.freight.total_amount) }} · 已生效 {{ amount(panel.freight.effective_amount) }} · 已登记 {{ amount(panel.freight.registered_amount) }}<p v-if="panel.freight.state !== 'ready'">{{ panel.freight.message }}</p></div>
    <p v-if="panel.batch_balance" class="detail-note">当前批次可登记余额：{{ currency }} {{ amount(panel.batch_balance.remaining_amount) }}（商品款 {{ amount(panel.batch_balance.goods_remaining) }} / 运费 {{ amount(panel.batch_balance.freight_remaining) }}）</p>
    <div class="detail-filter"><h3>关联回款单 <small>{{ filtered.length }} 笔</small></h3><el-select v-model="purpose" aria-label="筛选回款用途"><el-option label="全部用途" value="" /><el-option label="商品款 / 预付款" value="goods" /><el-option label="独立运费" value="freight" /></el-select><el-input v-model="keyword" clearable placeholder="搜索回款单号" aria-label="搜索关联回款单" /></div>
    <el-table v-sticky-scrollbar :data="filtered" row-key="key" class="list-table" border>
      <el-table-column label="回款单号 / 日期" min-width="220" max-width="280"><template #default="{row}"><button type="button" class="detail-link" :disabled="!row.id" @click="openReceipt(row)">{{ row.receipt_no }}</button><p>{{ row.collection_date || '—' }}</p><small v-if="row.source === 'remote'">小满独有记录</small></template></el-table-column>
      <el-table-column label="用途 / 批次" min-width="130" max-width="170"><template #default="{row}">{{ purposeLabel(row.purpose) }}<p v-if="row.batch_id">付款批次 #{{ row.batch_id }}</p></template></el-table-column>
      <el-table-column label="回款金额" min-width="140" max-width="170" align="right"><template #default="{row}">{{ amount(row.amount) }}<p>手续费 {{ amount(row.bank_charge) }}</p><small>{{ row.source === 'remote' ? '远端净额' : '方舟含费金额' }}</small></template></el-table-column>
      <el-table-column label="同步 / 记录状态" min-width="140" max-width="180"><template #default="{row}"><StatusBadge :type="detailStatus(row.sync_status).type">{{ detailStatus(row.sync_status).label }}</StatusBadge><p v-if="row.status !== 'active'">{{ detailStatus(row.status).label }}</p></template></el-table-column>
      <el-table-column label="财务状态" min-width="120" max-width="160"><template #default="{row}">{{ row.status !== 'active' ? '历史记录' : row.verified && String(row.collect_status) === '1' ? '已生效' : row.verified && String(row.collect_status) === '0' ? '未生效' : '待核验' }}</template></el-table-column>
      <el-table-column label="凭证" min-width="110" max-width="130"><template #default="{row}"><el-button v-if="row.attachment_count" link type="primary" @click="openReceipt(row)"><el-icon><Picture /></el-icon>{{ row.attachment_count }} 张</el-button><span v-else>未关联凭证</span></template></el-table-column>
      <template #empty><el-empty description="没有符合条件的回款记录" :image-size="64" /></template>
    </el-table>
    <section v-if="selected" class="detail-document" aria-live="polite">
      <div class="detail-filter"><h3>{{ selected.receipt_no }}</h3><el-button link @click="closeReceipt"><el-icon><Close /></el-icon>收起资料</el-button></div>
      <p v-if="detailLoading">正在加载回款资料…</p><p v-else-if="detailError" role="alert">{{ detailError }}</p>
      <template v-else-if="detail"><p>净额 {{ amount(Number(detail.amount) - Number(detail.bank_charge)) }} · 手续费 {{ amount(detail.bank_charge) }}</p><p>{{ detail.remark || '暂无备注' }}</p><p v-if="detail.last_error" class="detail-warning">{{ detail.last_error }}</p><ReceiptProofs :model-value="(detail.attachments || []).map(a => a.id)" readonly /></template>
    </section>
  </section>
</template>
<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { Picture, Close } from '@element-plus/icons-vue'
import { getReceipt } from '@/api/receipt'
import ReceiptProofs from '@/views/receipt/ReceiptProofs.vue'
import { formatMoney } from '@/utils/money'
import { purposeLabel, detailStatus } from './invoiceDetailLabels'
const props = defineProps({ panel: {type:Object,required:true}, currency: String, presale:Boolean })
const purpose = ref(''), keyword = ref(''), selected = ref(null), detail = ref(null), detailLoading = ref(false), detailError = ref('')
let generation = 0
const amount = value => formatMoney(value, {missing:'—'})
const metrics = computed(() => [['effective_amount','已生效回款'],['pending_amount','待生效回款'],['unpaid_amount','未结清金额'],['remaining_amount',props.presale ? '主单未登记金额' : '可登记余额']])
const filtered = computed(() => (props.panel.items || []).filter(r => (!purpose.value || (purpose.value === 'freight' ? r.purpose === 'freight' : r.purpose !== 'freight')) && (!keyword.value || `${r.receipt_no} ${r.xiaoman_receipt_no || ''}`.toLowerCase().includes(keyword.value.trim().toLowerCase()))))
async function openReceipt(row) {
  const current = ++generation; selected.value = row; detail.value = null; detailLoading.value = true; detailError.value = ''
  try { const data = await getReceipt(row.id); if (current === generation) detail.value = data }
  catch { if(current === generation) detailError.value = '回款资料加载失败，请点击原单重试' }
  finally { if(current === generation) detailLoading.value = false }
}
function closeReceipt() { generation++; selected.value = null; detail.value = null }
watch(() => props.panel, closeReceipt)
onUnmounted(closeReceipt)
</script>
