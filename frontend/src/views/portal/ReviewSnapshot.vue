<script setup>
const props = defineProps({ order: { type: Object, required: true }, customer: { type: Object, required: true }, standards: { type: Array, required: true } })
const standard = key => props.standards.find(line => line.line_key === key)
const labels = { contact_name: '联系人', phone: '电话', formatted_address: '完整地址', address_line1: '地址', address_line2: '补充地址', city: '城市', region: '省 / 州', postal_code: '邮编', country_code: '国家' }
const amount = value => value == null ? '待确认' : value
</script>
<template>
  <section class="review-snapshot" aria-label="当前审核快照">
    <h3>当前版本完整条款</h3>
    <p><strong>建票客户：{{ customer.company_name }}</strong></p><p>方舟客户 ID：{{ customer.customer_id }} · OKKI 公司 ID：{{ customer.okki_company_id }} · 当前业务员 ID：{{ customer.sales_user_id }}</p>
    <div v-for="line in order.items" :key="line.line_key" class="snapshot-line"><strong>客户显示：{{ line.display_snapshot.model_name }} / {{ line.display_snapshot.color_name }}</strong><p>{{ line.display_snapshot.customer_sku || '无客户货号' }} · {{ line.display_snapshot.length }} · {{ line.display_snapshot.weight }}</p><p v-if="standard(line.line_key)">方舟标准：{{ standard(line.line_key).standard.product_display || standard(line.line_key).standard.model }} / {{ standard(line.line_key).standard.color }} · 商品 ID {{ standard(line.line_key).product_id }} / SKU ID {{ standard(line.line_key).sku_id }}</p><p>{{ line.quantity }} {{ line.display_snapshot.unit }} × {{ amount(line.unit_price) }}；优惠 {{ amount(line.discount_amount) }}；行金额 {{ amount(line.line_amount) }}</p></div>
    <p>币种 {{ order.currency }} · 商品 {{ amount(order.product_amount) }} · 运费 {{ amount(order.fees?.shipping_amount) }} · 包装 {{ amount(order.fees?.packaging_amount) }} · {{ order.fees?.surcharge_name || '附加费' }} {{ amount(order.fees?.surcharge_amount) }}</p>
    <p><strong>总额 {{ amount(order.total_amount) }}</strong></p>
    <p>付款条件：{{ order.payment_terms_snapshot?.display_text || '待确认' }}<template v-if="order.payment_terms_snapshot?.deposit_percent != null"> · 订金比例 {{ order.payment_terms_snapshot.deposit_percent }}%</template></p>
    <dl><template v-for="(label, key) in labels" :key="key"><div v-if="order.delivery?.[key]"><dt>{{ label }}</dt><dd>{{ order.delivery[key] }}</dd></div></template></dl>
    <p class="remark">备注：{{ order.remark || '无' }}</p>
  </section>
</template>
<style scoped>
.review-snapshot { padding: 16px; margin-bottom: 20px; background: var(--toolbar-bg); border: 1px solid var(--border-color); border-radius: 12px; overflow-wrap: anywhere; }
h3 { font-size: 15px; margin-top: 0; }
.snapshot-line { padding: 8px 0; border-bottom: 1px solid var(--border-color); }
p { margin: 8px 0; }
dl div { display: flex; gap: 12px; margin: 6px 0; } dt { flex-shrink: 0; color: var(--text-secondary); } dd { margin: 0; }
.remark { white-space: pre-wrap; }
</style>
