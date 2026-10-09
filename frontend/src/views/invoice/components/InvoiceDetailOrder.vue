<template>
  <section>
    <h3>订单信息</h3>
    <ResponsiveDescriptions :column="3" border>
      <el-descriptions-item v-for="field in fields" :key="field[0]" :label="field[1]">{{ field[0] === 'source_type' ? sourceLabel(order[field[0]]) : order[field[0]] || '—' }}</el-descriptions-item>
    </ResponsiveDescriptions>
    <h3>{{ order.order_type === 'presale' ? '当前批次商品明细' : '商品明细' }} <small>{{ order.items?.length || 0 }} 行</small></h3>
    <el-table v-sticky-scrollbar :data="order.items || []" class="list-table" border>
      <el-table-column label="商品 / 规格" min-width="260" max-width="420">
        <template #default="{row}"><strong>{{ row.product_display || row.product_name }}</strong><p>{{ row.product_kind === 'accessory' ? '配件' : [row.length, row.color, row.curl, row.net_weight_grams].filter(Boolean).join(' / ') }}</p></template>
      </el-table-column>
      <el-table-column prop="quantity" label="订单数量（件）" min-width="120" max-width="140" align="right" />
      <el-table-column label="确认出库（件）" min-width="120" max-width="140" align="right"><template #default="{row}">{{ shipped?.[String(row.id)] ?? '待核验' }}</template></el-table-column>
      <el-table-column label="成交单价" min-width="130" max-width="160" align="right"><template #default="{row}">{{ formatMoney(row.price_per_piece, {precision:4,missing:'—'}) }}</template></el-table-column>
      <el-table-column label="行折扣" min-width="110" max-width="140" align="right"><template #default="{row}">{{ formatMoney(row.discount_amount) }}</template></el-table-column>
      <el-table-column label="小计" min-width="130" max-width="160" align="right"><template #default="{row}">{{ formatMoney(row.total_price) }}</template></el-table-column>
    </el-table>
    <div class="detail-totals"><span v-for="field in amounts" :key="field[0]">{{ field[1] }} <strong>{{ formatMoney(order[field[0]]) }}</strong></span><span>总额 {{ order.currency }} <strong>{{ formatMoney(order.total_amount) }}</strong></span></div>
    <template v-if="order.presale_history?.length">
      <h3>历史已发货明细（保留原出库记录）</h3>
      <el-table v-sticky-scrollbar :data="order.presale_history" class="list-table" border>
        <el-table-column prop="product_name" label="产品" min-width="220" />
        <el-table-column prop="quantity" label="已发数量" min-width="120" max-width="140" />
        <el-table-column label="已发商品款" min-width="150" max-width="180"><template #default="{row}">{{ formatMoney(row.amount) }}</template></el-table-column>
      </el-table>
    </template>
    <h3>备注</h3><p class="detail-remark">{{ order.remark || '暂无备注' }}</p>
  </section>
</template>
<script setup>
import ResponsiveDescriptions from '@/components/ResponsiveDescriptions.vue'
import { formatMoney } from '@/utils/money'
const sourceLabel = value => ({manual:'手工录入',okki_screenshot:'小满截图导入',external_api:'外部站点接入'}[value] || value || '—')
defineProps({ order: { type: Object, required: true }, shipped: { type: Object, default: null } })
const fields = [['customer_name','客户'],['contact_name','联系人'],['invoice_date','发票日期'],['sales_user_name','业务员'],['merchandiser_name','跟单员'],['xiaoman_order_no','小满订单号'],['contact_phone','联系电话'],['contact_email','联系邮箱'],['delivery_address','收货地址'],['payment_term','付款条款'],['express_channel','发货方式'],['source_type','订单来源']]
const amounts = [['product_amount','商品净额'],['internal_accessory','包装费'],['shipping_fee','主单运费'],['surcharge_amount','附加费']]
</script>
