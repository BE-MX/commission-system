<template>
  <section class="invoice-hair-table">
    <div class="line-header">
      <div>
        <strong>产品明细</strong>
        <span v-if="isProduction">生产单：关键词下拉可选可输，已有属性直接选，没有就按输入沉淀新产品。</span>
        <span v-else>四个关键词选择完整后自动匹配唯一 Product_name。</span>
      </div>
      <div class="line-header-actions">
        <el-tooltip :disabled="canPasteImport" :content="pasteImportDisabledReason">
          <span>
            <el-button v-permission="'invoice:write'" :disabled="!canPasteImport" @click="$emit('paste')">
              <el-icon><DocumentCopy /></el-icon>
              从 Excel 粘贴
            </el-button>
          </span>
        </el-tooltip>
        <el-button link type="primary" @click="showOptionalCols = !showOptionalCols">
          <el-icon><component :is="showOptionalCols ? ArrowUp : ArrowDown" /></el-icon>
          {{ showOptionalCols ? '收起选填列' : '展开选填列' }}
        </el-button>
        <el-button @click="$emit('add')"><el-icon><Plus /></el-icon>添加明细</el-button>
      </div>
    </div>
    <div class="line-table-wrap">
      <el-table :data="items" border class="list-table line-table">
        <el-table-column label="#" type="index" min-width="48" max-width="60" fixed />
        <el-table-column v-if="isProduction" label="Product" min-width="190" max-width="260">
          <template #default="{ row }">
            <el-select v-model="row.product_display" filterable allow-create default-first-option placeholder="系列描述，可输入" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.displays" :key="value" :label="value" :value="value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column v-if="showOptionalCols || !isProduction" label="Model" min-width="120" max-width="180">
          <template #default="{ row }">
            <el-select v-if="isProduction" v-model="row.model" filterable allow-create clearable default-first-option placeholder="可选" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.models" :key="value" :label="value" :value="value" />
            </el-select>
            <el-select v-else v-model="row.model" filterable placeholder="Model" @visible-change="visible => visible && loadLineOptions(row)" @change="onLineFilterChange(row)">
              <el-option v-for="value in row.options.models" :key="value" :label="value" :value="value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="Color" min-width="120" max-width="170">
          <template #default="{ row }">
            <el-select v-if="isProduction" v-model="row.color" filterable allow-create default-first-option placeholder="Color" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.colors" :key="value" :label="value" :value="value" />
            </el-select>
            <el-select v-else v-model="row.color" filterable placeholder="Color" @visible-change="visible => visible && loadLineOptions(row)" @change="onLineFilterChange(row)">
              <el-option v-for="value in row.options.colors" :key="value" :label="value" :value="value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="Length" min-width="95" max-width="130">
          <template #default="{ row }">
            <el-select v-if="isProduction" v-model="row.length" filterable allow-create default-first-option placeholder="Length" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.sizes" :key="value" :label="value" :value="value" />
            </el-select>
            <el-select v-else v-model="row.length" filterable placeholder="Length" @visible-change="visible => visible && loadLineOptions(row)" @change="onLineFilterChange(row)">
              <el-option v-for="value in row.options.sizes" :key="value" :label="value" :value="value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="Net Weight" min-width="105" max-width="150">
          <template #default="{ row }">
            <el-select v-if="isProduction" v-model="row.net_weight_grams" filterable allow-create default-first-option placeholder="Unit" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.units" :key="value" :label="value" :value="value" />
            </el-select>
            <el-select v-else v-model="row.net_weight_grams" filterable placeholder="Unit" @visible-change="visible => visible && loadLineOptions(row)" @change="onLineFilterChange(row)">
              <el-option v-for="value in row.options.units" :key="value" :label="value" :value="value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column v-if="!isProduction" label="Product_name" min-width="230" max-width="360" show-overflow-tooltip>
          <template #default="{ row }">
            <div :class="['product-cell', row.product_name ? 'is-matched' : 'is-pending']">
              <span>{{ row.product_name || '待匹配' }}</span>
              <el-tag v-if="row.sku_id" size="small" effect="plain">SKU {{ row.sku_id }}</el-tag>
              <el-tag v-else-if="row.matching" size="small" type="info" effect="plain">匹配中</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="showOptionalCols" label="Curl" min-width="110" max-width="150">
          <template #default="{ row }">
            <el-select v-model="row.curl" clearable placeholder="可选">
              <el-option v-for="value in CURL_OPTIONS" :key="value" :label="value" :value="value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="标准价" min-width="95" max-width="140" align="right">
          <template #default="{ row }">
            <span v-if="row.standard_price != null" class="std-price">
              {{ money4(row.standard_price) }}
              <el-tooltip v-if="row.color_type_source === 'inferred'" content="该色号未登记色型映射，价格按命名规则推断的色型取得，请人工核对">
                <el-tag size="small" type="warning" effect="plain">色型推断</el-tag>
              </el-tooltip>
            </span>
            <el-tag v-else size="small" type="warning" effect="plain">无标准价</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="客户价" min-width="140" max-width="180">
          <template #default="{ row }">
            <div :class="['price-cell', row.price_source === 'manual' ? 'is-manual' : '']">
              <el-input-number v-model="row.price_per_piece" :min="0.01" :precision="4" :controls="false" @change="onPriceInput(row)" />
              <el-tag v-if="row.price_source === 'manual'" size="small" type="warning" effect="plain">手改</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Quantity" min-width="100" max-width="140">
          <template #default="{ row }"><el-input-number v-model="row.quantity" :min="1" :precision="0" :controls="false" @change="updateLineTotal(row)" /></template>
        </el-table-column>
        <el-table-column label="折扣" min-width="110" max-width="150">
          <template #default="{ row }"><el-input-number v-model="row.discount_amount" :precision="2" :controls="false" class="line-discount-input" @change="onLineDiscountChange(row)" /></template>
        </el-table-column>
        <el-table-column label="TotalPrice" min-width="100" max-width="150" align="right">
          <template #default="{ row }">{{ money(row.total_price) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="64" max-width="80" fixed="right">
          <template #default="{ row }"><el-button link type="danger" aria-label="删除产品" @click="$emit('remove', row)"><el-icon><Delete /></el-icon></el-button></template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { ArrowDown, ArrowUp, Delete, DocumentCopy, Plus } from '@element-plus/icons-vue'
import { CURL_OPTIONS } from '../composables/useInvoiceEditor'

defineProps({
  items: { type: Array, required: true },
  isProduction: Boolean,
  entryOptions: { type: Object, required: true },
  canPasteImport: Boolean,
  pasteImportDisabledReason: { type: String, default: '' },
  loadLineOptions: { type: Function, required: true },
  onLineFilterChange: { type: Function, required: true },
  onCustomFieldChange: { type: Function, required: true },
  onPriceInput: { type: Function, required: true },
  onLineDiscountChange: { type: Function, required: true },
  updateLineTotal: { type: Function, required: true },
  money: { type: Function, required: true },
  money4: { type: Function, required: true },
})
defineEmits(['paste', 'add', 'remove'])
const showOptionalCols = ref(false)
</script>

<style scoped>
.line-header { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 12px; }
.line-header span { margin-left: 10px; color: var(--text-secondary); font-size: 13px; }
.line-header-actions, .price-cell, .product-cell { display: flex; align-items: center; gap: 8px; }
.line-table-wrap { overflow-x: auto; border: 1px solid var(--border-color); border-radius: var(--card-radius); }
.line-table { width: 100%; }
.product-cell { min-height: 28px; }
.product-cell.is-pending { color: var(--text-muted); }
.std-price { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.price-cell.is-manual :deep(.el-input__wrapper) { background: var(--color-warning-bg); }
.line-discount-input :deep(input) { color: var(--color-danger); font-variant-numeric: tabular-nums; }
</style>
