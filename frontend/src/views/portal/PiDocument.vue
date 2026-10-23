<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ document: { type: Object, required: true }, live: Boolean })
const fees = computed(() => props.document.fees || props.document)
const terms = computed(() => props.document.payment_terms_snapshot || props.document.payment_terms)
const headers = { invoice_no: 'PI 编号', customer_name: 'PI 客户名称', invoice_date: 'PI 日期', express_channel: '运输方式', contact_email: '客户邮箱', sales_user_name: '业务员', sales_phone: '业务员电话', sales_email: '业务员邮箱', packaging_quantity: '包装数量' }
const address = { contact_name: '收货人', phone: '电话', formatted_address: '完整地址', address_line1: '地址', address_line2: '补充地址', city: '城市', region: '省 / 州', postal_code: '邮编', country_code: '国家' }
const sort = ref({ key: '', direction: '' })
const columns = [{ key: 'product', label: '商品 / 规格' }, { key: 'quantity', label: '数量' }, { key: 'unit_price', label: '单价' }, { key: 'discount_amount', label: '优惠' }, { key: 'line_amount', label: '金额' }]
function changeSort(key) {
  sort.value = sort.value.key !== key ? { key, direction: 'ascending' } : sort.value.direction === 'ascending' ? { key, direction: 'descending' } : { key: '', direction: '' }
}
const displayLines = computed(() => {
  const lines = [...props.document.items]
  if (!sort.value.key) return lines
  const key = sort.value.key, direction = sort.value.direction === 'ascending' ? 1 : -1
  return lines.sort((a, b) => direction * (key === 'product'
    ? String(a.display_snapshot.model_name || '').localeCompare(String(b.display_snapshot.model_name || ''), 'zh-CN', { numeric: true })
    : Number(a[key] ?? 0) - Number(b[key] ?? 0)))
})
const value = input => input == null || input === '' ? '未填写' : String(input)
</script>
<template>
  <section class="pi-document" role="region" :aria-label="live ? '当前方舟 PI 完整条款' : '客户 PI 快照完整条款'" tabindex="0">
    <header class="pi-sheet-head"><div><span class="pi-sheet-kind">形式发票</span><h3>{{ document.commercial_header?.invoice_no || 'PI 条款' }}</h3><p>{{ document.commercial_header?.customer_name || '客户名称未填写' }}</p></div><div class="pi-sheet-date"><span>开票日期</span><strong>{{ value(document.commercial_header?.invoice_date) }}</strong></div></header>
    <details class="pi-commercial"><summary>运输、业务员与联系信息</summary><dl class="pi-fields pi-contact-fields"><template v-for="(label, key) in headers" :key="key"><div v-if="!['invoice_no', 'customer_name', 'invoice_date'].includes(key) && document.commercial_header?.[key] != null && document.commercial_header[key] !== ''"><dt>{{ label }}</dt><dd>{{ value(document.commercial_header[key]) }}</dd></div></template></dl></details>
    <div class="pi-section-heading"><h4>{{ live ? '当前方舟 PI 商品（标准名称）' : '客户商品快照' }}</h4><span>{{ document.items.length }} 项</span></div>
    <div class="pi-lines-scroll" role="region" aria-label="PI 商品明细表" tabindex="0"><table class="pi-lines"><thead><tr><th v-for="column in columns" :key="column.key" scope="col" :aria-sort="sort.key === column.key ? sort.direction : 'none'"><button type="button" @click="changeSort(column.key)">{{ column.label }} <span aria-hidden="true">{{ sort.key === column.key ? sort.direction === 'ascending' ? '↑' : '↓' : '↕' }}</span></button></th></tr></thead><tbody><tr v-for="line in displayLines" :key="line.line_key"><td><strong>{{ line.display_snapshot.model_name }}</strong><p>{{ line.display_snapshot.color_name }} · 长度 {{ value(line.display_snapshot.length) }} · 克重 {{ value(line.display_snapshot.weight) }}</p><p v-if="line.display_snapshot.customer_sku">客户货号 {{ line.display_snapshot.customer_sku }}</p><details v-if="live" class="pi-source"><summary>商品来源标识</summary><p>标准商品 ID {{ value(line.product_id) }} / SKU ID {{ value(line.sku_id) }}</p></details></td><td>{{ line.quantity }} {{ line.display_snapshot.unit }}</td><td>{{ value(line.unit_price) }}</td><td>{{ value(line.discount_amount) }}</td><td><strong>{{ value(line.line_amount) }}</strong></td></tr></tbody></table></div>
    <div class="pi-settlement"><div class="pi-payment"><h4>付款条件</h4><p>{{ value(terms?.display_text) }}<template v-if="terms?.deposit_percent != null"> · 订金 {{ terms.deposit_percent }}%</template></p></div><dl class="pi-totals"><div><dt>商品小计</dt><dd>{{ value(document.product_amount) }}</dd></div><div><dt>运费</dt><dd>{{ value(fees.shipping_amount) }}</dd></div><div><dt>包装费</dt><dd>{{ value(fees.packaging_amount) }}</dd></div><div><dt>{{ fees.surcharge_name || '附加费' }}</dt><dd>{{ value(fees.surcharge_amount) }}</dd></div><div class="pi-grand-total"><dt>总额 <span>{{ document.currency }}</span></dt><dd>{{ value(document.total_amount) }}</dd></div></dl></div>
    <section class="pi-delivery"><h4>收货信息</h4><dl class="pi-fields"><template v-for="(label, key) in address" :key="key"><div v-if="document.delivery?.[key]"><dt>{{ label }}</dt><dd>{{ document.delivery[key] }}</dd></div></template></dl></section>
    <section v-if="document.remark" class="pi-notes"><h4>备注</h4><p class="prewrap">{{ document.remark }}</p></section>
  </section>
</template>
<style scoped>
.pi-document { padding: 28px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--card-bg); color: var(--text-primary); overflow-wrap: anywhere; font-size: 14px; line-height: 1.65; }
.pi-document:focus-visible, .pi-lines-scroll:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.pi-sheet-head { display: flex; justify-content: space-between; gap: 24px; padding-bottom: 20px; border-bottom: 2px solid var(--text-primary); }
.pi-sheet-kind, .pi-sheet-date span { color: var(--text-secondary); font-size: 13px; }
.pi-sheet-head h3 { margin: 8px 0; font-size: 25px; line-height: 1.3; letter-spacing: -.02em; }
.pi-sheet-head p { margin: 0; }.pi-sheet-date { flex-shrink: 0; text-align: right; }.pi-sheet-date strong { display: block; margin-top: 8px; font-weight: 500; }
h4 { margin: 0; font-size: 14px; font-weight: 600; } p { margin: 6px 0; }
.pi-commercial { margin-top: 16px; color: var(--text-secondary); font-size: 13px; }.pi-commercial summary { cursor: pointer; }.pi-commercial dd { color: var(--text-primary); }
.pi-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px; margin: 20px 0; }
.pi-fields div { min-width: 0; }dt { color: var(--text-secondary); font-size: 13px; }dd { margin: 3px 0 0; white-space: pre-wrap; min-width: 0; }
.pi-section-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; margin: 28px 0 12px; }.pi-section-heading span { color: var(--text-secondary); }
.pi-lines-scroll { overflow-x: auto; }.pi-lines { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.pi-lines th button { border: 0; padding: 4px 0; background: transparent; color: inherit; font: inherit; cursor: pointer; min-height: 36px; }.pi-lines th button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.pi-lines th { background: var(--toolbar-bg); color: var(--text-secondary); font-size: 13px; font-weight: 500; }
.pi-lines th, .pi-lines td { padding: 12px 10px; border-bottom: 1px solid var(--border-color); text-align: right; vertical-align: top; white-space: nowrap; }
.pi-lines th:first-child, .pi-lines td:first-child { text-align: left; min-width: 200px; max-width: 360px; white-space: normal; }.pi-lines td p { color: var(--text-secondary); font-size: 13px; }
.pi-source { font-size: 13px; color: var(--text-secondary); }.pi-source summary { cursor: pointer; width: fit-content; }
.pi-settlement { display: grid; grid-template-columns: 1fr minmax(220px, .9fr); gap: 28px; padding: 24px 0; }.pi-payment p { white-space: pre-wrap; }
.pi-totals { margin: 0; font-variant-numeric: tabular-nums; }.pi-totals div { display: flex; justify-content: space-between; gap: 16px; padding: 5px 0; }.pi-totals dd { margin: 0; text-align: right; }.pi-grand-total { border-top: 1px solid var(--text-primary); margin-top: 10px; padding-top: 14px !important; }.pi-grand-total dt { color: var(--text-primary); }.pi-grand-total dd { font-size: 24px; font-weight: 600; line-height: 1.3; }
.pi-delivery, .pi-notes { border-top: 1px solid var(--border-color); padding-top: 20px; }.pi-delivery .pi-fields { margin-bottom: 20px; }.prewrap { white-space: pre-wrap; }
@media (max-width: 700px) { .pi-document { padding: 18px; }.pi-sheet-head { flex-direction: column; gap: 12px; }.pi-sheet-date { text-align: left; }.pi-sheet-date strong { display: inline; margin-left: 12px; }.pi-settlement, .pi-fields { grid-template-columns: 1fr; gap: 16px; }.pi-lines th, .pi-lines td { padding-inline: 8px; } }
</style>
