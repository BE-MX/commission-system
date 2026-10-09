<script setup>
import { computed } from 'vue'
const props = defineProps({ document: { type: Object, required: true }, live: Boolean })
const fees = computed(() => props.document.fees || props.document)
const terms = computed(() => props.document.payment_terms_snapshot || props.document.payment_terms)
const headers = { invoice_no: 'PI 编号', customer_name: 'PI 客户名称', invoice_date: 'PI 日期', express_channel: '运输方式', contact_email: '客户邮箱', sales_user_name: '业务员', sales_phone: '业务员电话', sales_email: '业务员邮箱', packaging_quantity: '包装数量' }
const address = { contact_name: '收货人', phone: '电话', formatted_address: '完整地址', address_line1: '地址', address_line2: '补充地址', city: '城市', region: '省 / 州', postal_code: '邮编', country_code: '国家' }
const value = input => input == null || input === '' ? '未填写' : String(input)
</script>
<template>
  <section class="pi-document" role="region" :aria-label="live ? '当前方舟 PI 完整条款' : '客户 PI 快照完整条款'" tabindex="0">
    <dl class="pi-fields"><template v-for="(label, key) in headers" :key="key"><div v-if="document.commercial_header && document.commercial_header[key] != null"><dt>{{ label }}</dt><dd>{{ value(document.commercial_header[key]) }}</dd></div></template></dl>
    <h3>{{ live ? '当前方舟 PI 商品（标准名称）' : '客户商品快照' }}</h3>
    <article v-for="line in document.items" :key="line.line_key"><strong>{{ line.display_snapshot.model_name }} / {{ line.display_snapshot.color_name }}</strong><p>{{ line.display_snapshot.customer_sku || '' }} · 长度 {{ value(line.display_snapshot.length) }} · 克重 {{ value(line.display_snapshot.weight) }}</p><p v-if="live">标准商品 ID {{ value(line.product_id) }} / SKU ID {{ value(line.sku_id) }}</p><p>数量 {{ line.quantity }} {{ line.display_snapshot.unit }} · 单价 {{ value(line.unit_price) }} · 优惠 {{ value(line.discount_amount) }} · 行金额 {{ value(line.line_amount) }}</p></article>
    <p>币种：{{ document.currency }}</p>
    <dl class="pi-fields"><div><dt>商品小计</dt><dd>{{ value(document.product_amount) }}</dd></div><div><dt>运费</dt><dd>{{ value(fees.shipping_amount) }}</dd></div><div><dt>包装费</dt><dd>{{ value(fees.packaging_amount) }}</dd></div><div><dt>{{ fees.surcharge_name || '附加费' }}</dt><dd>{{ value(fees.surcharge_amount) }}</dd></div><div><dt>总额</dt><dd><strong>{{ value(document.total_amount) }}</strong></dd></div></dl>
    <h3>付款与交付</h3><p>{{ value(terms?.display_text) }}<template v-if="terms?.deposit_percent != null"> · 订金 {{ terms.deposit_percent }}%</template></p>
    <dl class="pi-fields"><template v-for="(label, key) in address" :key="key"><div v-if="document.delivery?.[key]"><dt>{{ label }}</dt><dd>{{ document.delivery[key] }}</dd></div></template></dl>
    <p class="prewrap">备注：{{ document.remark || '无' }}</p>
  </section>
</template>
<style scoped>
.pi-document { padding: 16px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--toolbar-bg); overflow-wrap: anywhere; }
.pi-document:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
h3 { font-size: 15px; margin: 20px 0 12px; } p { margin: 8px 0; }
article { padding: 12px 0; border-bottom: 1px solid var(--border-color); }
.pi-fields div { display: flex; justify-content: space-between; gap: 20px; margin: 8px 0; }
dt { color: var(--text-secondary); flex-shrink: 0; max-width: 45%; } dd { margin: 0; text-align: right; white-space: pre-wrap; min-width: 0; }
.prewrap { white-space: pre-wrap; }
</style>
