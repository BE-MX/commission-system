<script setup>
import { formatBeijingDateTime } from '@/utils/datetime'
defineProps({ preview: { type: Object, required: true } })
const kinds = { added: '新增', removed: '移除', changed: '有变化', unchanged: '未变化' }
const fields = { quantity: '数量', unit_price: '单价', discount_amount: '折扣', line_amount: '行金额', display_snapshot: '客户展示' }
const fees = { shipping_amount: '运费', packaging_amount: '包装费', surcharge_amount: '附加费' }
const amount = value => value == null ? '待确认' : value
const label = line => line ? `${line.display_snapshot.model_name} / ${line.display_snapshot.color_name} · ${line.display_snapshot.length} · ${line.display_snapshot.weight}` : '—'
</script>

<template>
  <section class="proposal-preview">
    <h3>提案金额与变更预览</h3>
    <el-alert title="这是即时核价参考，不锁价、不锁货，也不代表客户已确认。发送时会再次核算，客户须确认最终收到的完整提案。" type="warning" :closable="false" />
    <p>核算时间 {{ formatBeijingDateTime(preview.calculated_at) }} · {{ preview.currency }} · 有效期 {{ preview.valid_for_hours }} 小时（从正式发送起计算）</p>
    <div class="amount-grid"><div>原商品金额<strong>{{ amount(preview.previous_product_amount) }}</strong></div><div>新商品金额<strong>{{ preview.product_amount }}</strong></div><div>原总额<strong>{{ amount(preview.previous_total_amount) }}</strong></div><div>预览新总额<strong>{{ preview.total_amount }}</strong></div></div>
    <el-table :data="preview.changes" border class="list-table" v-sticky-scrollbar>
      <el-table-column label="变化" min-width="100"><template #default="{ row }">{{ kinds[row.kind] }}<br><small>{{ row.changed_fields.map(key => fields[key] || key).join('、') }}</small></template></el-table-column>
      <el-table-column label="原商品 / 金额" min-width="240"><template #default="{ row }">{{ label(row.before) }}<p v-if="row.before">{{ row.before.quantity }} × {{ row.before.unit_price }} = {{ row.before.line_amount }}</p></template></el-table-column>
      <el-table-column label="新商品 / 金额" min-width="240"><template #default="{ row }">{{ label(row.after) }}<p v-if="row.after">{{ row.after.quantity }} × {{ row.after.unit_price }} = {{ row.after.line_amount }}</p></template></el-table-column>
    </el-table>
    <p v-for="(labelText, key) in fees" :key="key">{{ labelText }}：{{ amount(preview.previous_fees?.[key]) }} → {{ preview.fees[key] }}</p>
    <p>付款条件：{{ preview.previous_payment_terms_snapshot?.display_text || '待确认' }} → {{ preview.payment_terms_snapshot.display_text }}</p>
    <p>收货信息以表单本次填写为准；客户会看到完整条款并重新确认。</p>
  </section>
</template>

<style scoped>
.proposal-preview { margin: 20px 0; padding: 16px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--card-bg); }
.amount-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 16px 0; }
strong { display: block; font-size: 20px; margin-top: 6px; overflow-wrap: anywhere; }
p, small { color: var(--text-secondary); line-height: 1.6; overflow-wrap: anywhere; }
h3 { margin-top: 0; }
</style>
