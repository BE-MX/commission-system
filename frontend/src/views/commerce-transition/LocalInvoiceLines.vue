<template>
  <section class="form-card">
    <div class="card-title">商品明细</div>
    <div v-if="form.order_type === 'presale'" class="presale-contract">
      <el-form-item label="合同首款（末批抵扣）"><el-input-number v-model="form.local_deposit_amount" :min="0" :precision="2" /></el-form-item>
      <el-form-item label="首款中所含附加费"><el-input-number v-model="form.local_deposit_charge" :min="0" :precision="2" /></el-form-item>
    </div>
    <el-table :data="form.items" border class="list-table" v-sticky-scrollbar>
      <el-table-column label="本地 SKU" min-width="230"><template #default="{ row }"><SkuPicker v-model="row.local_sku_id" :selected-label="row.product_display" @select="sku => select(row, sku)" /></template></el-table-column>
      <el-table-column label="销售性质" min-width="110"><template #default="{ row }"><el-select v-model="row.commercial_kind"><el-option value="bulk" label="大货" /><el-option value="sample" label="样品" /></el-select></template></el-table-column>
      <el-table-column label="件数" min-width="140"><template #default="{ row }"><el-input-number v-model="row.quantity" :min="1" :precision="0" controls-position="right" @change="update(row)" /></template></el-table-column>
      <el-table-column label="成交单价" min-width="140"><template #default="{ row }"><el-input-number v-model="row.price_per_piece" :min="0" :precision="4" controls-position="right" @change="update(row)" /></template></el-table-column>
      <el-table-column label="行金额" min-width="110"><template #default="{ row }">{{ row.total_price }}</template></el-table-column>
      <el-table-column class-name="table-action-column" label="操作" min-width="80"><template #default="{ $index }"><GlassButton variant="link" left-icon="Delete" link-tone="danger" @click="form.items.splice($index, 1)">移除</GlassButton></template></el-table-column>
    </el-table>
    <GlassButton left-icon="Plus" @click="add">添加商品</GlassButton>
  </section>
</template>
<script setup>
import SkuPicker from '@/views/inventory/components/SkuPicker.vue'
import { normalizeHairRow } from '@/views/invoice/composables/invoiceEditorState'
const props = defineProps({ form: Object })
function add() { props.form.items.push({ ...normalizeHairRow(), quantity: 1, price_per_piece: 0, commercial_kind: 'bulk', local_sku_id: null }) }
function select(row, sku) { row.local_sku_id = sku?.id || null; row.sku_id = sku?.id || null; row.product_display = sku?.label || ''; update(row) }
function update(row) { row.total_price = Math.round((Number(row.quantity || 0) * Number(row.price_per_piece || 0) - Number(row.discount_amount || 0)) * 100) / 100 }
</script>
<style scoped>.presale-contract { display: flex; flex-wrap: wrap; gap: 16px; }</style>
