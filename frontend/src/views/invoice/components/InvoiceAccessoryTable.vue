<template>
  <section class="accessory-detail-section">
    <div class="line-header">
      <div>
        <strong>配件明细</strong>
        <span>Hair ExtensionsTools Fee · 仅可选择已配置标准价的真实 OKKI SKU</span>
      </div>
      <el-button @click="$emit('add')">
        <el-icon><Plus /></el-icon>
        添加配件
      </el-button>
    </div>
    <div class="line-table-wrap accessory-line-table-wrap">
      <el-table :data="items" border class="list-table line-table accessory-line-table">
        <el-table-column label="#" type="index" min-width="48" max-width="60" fixed />
        <el-table-column label="Name" min-width="190" max-width="300">
          <template #default="{ row }">
            <el-select
              :model-value="identityValue(row)"
              filterable
              remote
              reserve-keyword
              :remote-method="searchOptions"
              :loading="loading"
              placeholder="搜索已配置配件"
              @visible-change="visible => visible && searchOptions('')"
              @change="key => handleSelect(row, key)"
            >
              <el-option
                v-for="option in rowOptions(row)"
                :key="optionKey(option)"
                :label="option.accessory_name"
                :value="optionKey(option)"
              >
                <span>{{ option.accessory_name }} / {{ option.accessory_model }} / {{ option.accessory_color }}</span>
              </el-option>
            </el-select>
            <div v-if="row.sku_id" class="accessory-identity">SKU {{ row.sku_id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Model" min-width="130" max-width="190">
          <template #default="{ row }"><el-input :model-value="row.model" readonly /></template>
        </el-table-column>
        <el-table-column label="Color" min-width="130" max-width="190">
          <template #default="{ row }"><el-input :model-value="row.color" readonly /></template>
        </el-table-column>
        <el-table-column label="标准价" min-width="92" max-width="125" align="right">
          <template #default="{ row }">
            <span v-if="row.standard_price != null" class="std-price">{{ money4(row.standard_price) }}</span>
            <el-tag v-else-if="accessoryStandardPriceState(row) === 'invalid'" size="small" type="warning" effect="plain">需重新配置</el-tag>
            <span v-else class="std-price">—</span>
          </template>
        </el-table-column>
        <el-table-column label="客户价" min-width="135" max-width="175">
          <template #default="{ row }">
            <div :class="['price-cell', row.price_source === 'manual' ? 'is-manual' : '']">
              <span class="customer-price-reference" :title="row.customer_price == null ? '选择客户后解析客户价' : `客户价 ${money4(row.customer_price)}`">
                {{ row.customer_price == null ? '—' : money4(row.customer_price) }}
              </span>
              <el-input-number
                v-model="row.price_per_piece"
                aria-label="成交价"
                :min="0.01"
                :precision="4"
                :controls="false"
                :disabled="row.standard_price == null"
                @change="$emit('change', row)"
              />
              <el-tag v-if="row.price_source === 'manual'" size="small" type="warning" effect="plain">手改</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Quantity" min-width="96" max-width="125">
          <template #default="{ row }">
            <el-input-number v-model="row.quantity" :min="1" :precision="0" :controls="false" @change="$emit('change', row)" />
          </template>
        </el-table-column>
        <el-table-column label="折扣" min-width="105" max-width="140">
          <template #default="{ row }">
            <el-input-number v-model="row.discount_amount" :precision="2" :controls="false" class="line-discount-input" @change="$emit('change', row)" />
          </template>
        </el-table-column>
        <el-table-column label="TotalPrice" min-width="100" max-width="140" align="right">
          <template #default="{ row }">{{ money(row.total_price) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="64" max-width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" aria-label="删除配件" @click="$emit('remove', row)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup>
import { Delete, Plus } from '@element-plus/icons-vue'
import { accessoryStandardPriceState } from '../composables/accessoryPricing.js'

const props = defineProps({
  items: { type: Array, required: true },
  options: { type: Array, default: () => [] },
  loading: Boolean,
  searchOptions: { type: Function, required: true },
  money: { type: Function, required: true },
  money4: { type: Function, required: true },
})

const emit = defineEmits(['add', 'select', 'change', 'remove'])

const optionKey = option => `${option.product_id}:${option.sku_id}`
const identityValue = row => row.product_id && row.sku_id ? optionKey(row) : null
const currentSnapshot = row => ({
  product_id: row.product_id,
  sku_id: row.sku_id,
  accessory_name: row.product_name,
  accessory_model: row.model,
  accessory_color: row.color,
  standard_price: row.standard_price,
  customer_price: row.customer_price,
})
const rowOptions = row => {
  if (!row.product_id || !row.sku_id || props.options.some(option => optionKey(option) === optionKey(row))) return props.options
  return [currentSnapshot(row), ...props.options]
}
const handleSelect = (row, key) => {
  const option = rowOptions(row).find(item => optionKey(item) === key)
  if (option) emit('select', row, option)
}
</script>

<style scoped>
.accessory-detail-section { margin-top: 18px; }
.line-header { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 12px; }
.line-header span { margin-left: 10px; color: var(--text-secondary); font-size: 13px; }
.line-table-wrap { overflow-x: auto; border: 1px solid var(--border-color); border-radius: var(--card-radius); }
.line-table { width: 100%; }
.price-cell { display: flex; align-items: center; gap: 6px; }
.price-cell :deep(.el-input-number) { min-width: 0; flex: 1; }
.accessory-line-table :deep(.el-input-number) { width: 100%; }
.price-cell.is-manual :deep(.el-input__wrapper) { background: var(--color-warning-bg); }
.std-price, .customer-price-reference { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.customer-price-reference { min-width: 36px; font-size: 11px; }
.accessory-identity { margin-top: 3px; color: var(--text-secondary); font-size: 11px; }
.line-discount-input :deep(input) { color: var(--color-danger); font-variant-numeric: tabular-nums; }
</style>
