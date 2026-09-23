<template>
  <section class="invoice-hair-table">
    <div class="line-header">
      <div class="line-title">
        <span class="step">2</span><strong>产品明细</strong>
        <span v-if="isProduction" class="line-hint">生产单：关键词下拉可选可输，已有属性直接选，没有就按输入沉淀新产品。</span>
        <span v-else class="line-hint">四个关键词选择完整后自动匹配唯一 Product_name。</span>
      </div>
      <div class="line-header-actions">
        <el-button link type="primary" @click="collapseSpecs = !collapseSpecs">
          <el-icon><component :is="collapseSpecs ? ArrowDown : ArrowUp" /></el-icon>
          {{ collapseSpecs ? '展开规格列' : '收起规格列' }}
        </el-button>
        <el-button link type="primary" @click="showOptionalCols = !showOptionalCols">
          <el-icon><component :is="showOptionalCols ? ArrowUp : ArrowDown" /></el-icon>
          {{ showOptionalCols ? '收起选填列' : '展开选填列' }}
        </el-button>
        <el-button :disabled="!items.length" @click="$emit('copy')"><el-icon><DocumentCopy /></el-icon>复制一行</el-button>
        <el-button @click="$emit('add-blank')"><el-icon><Plus /></el-icon>添加空行</el-button>
      </div>
    </div>
    <div class="line-table-wrap">
      <el-table :data="pagedItems" border class="list-table line-table" max-height="560">
        <el-table-column label="#" type="index" :index="indexBase" min-width="48" max-width="60" fixed />
        <el-table-column v-if="isProduction" label="Product" min-width="190" max-width="260">
          <template #default="{ row }">
            <el-select v-model="row.product_display" filterable allow-create default-first-option placeholder="系列描述，可输入" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.displays" :key="value" :label="value" :value="value" />
            </el-select>
            <el-text v-if="row.stock_warning" type="warning">{{ row.stock_warning }}</el-text>
          </template>
        </el-table-column>
        <el-table-column v-if="(showOptionalCols || !isProduction) && !collapseSpecs" label="Model" min-width="120" max-width="180">
          <template #default="{ row }">
            <el-select v-if="isProduction" v-model="row.model" filterable allow-create clearable default-first-option placeholder="可选" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.models" :key="value" :label="value" :value="value" />
            </el-select>
            <el-select v-else v-model="row.model" filterable placeholder="Model" @visible-change="visible => visible && loadLineOptions(row)" @change="onLineFilterChange(row)">
              <template v-for="group in lineOptionGroups(row.options, 'models')" :key="group.label">
                <el-option-group v-if="group.label" :label="group.label">
                  <el-option v-for="value in group.options" :key="value" :label="value" :value="value" />
                </el-option-group>
                <template v-else>
                  <el-option v-for="value in group.options" :key="value" :label="value" :value="value" />
                </template>
              </template>
            </el-select>
          </template>
        </el-table-column>
        <el-table-column v-if="!collapseSpecs" label="Color" min-width="120" max-width="170">
          <template #default="{ row }">
            <el-select v-if="isProduction" v-model="row.color" filterable allow-create default-first-option placeholder="Color" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.colors" :key="value" :label="value" :value="value" />
            </el-select>
            <el-select v-else v-model="row.color" filterable placeholder="Color" @visible-change="visible => visible && loadLineOptions(row)" @change="onLineFilterChange(row)">
              <template v-for="group in lineOptionGroups(row.options, 'colors')" :key="group.label">
                <el-option-group v-if="group.label" :label="group.label">
                  <el-option v-for="value in group.options" :key="value" :label="value" :value="value" />
                </el-option-group>
                <template v-else>
                  <el-option v-for="value in group.options" :key="value" :label="value" :value="value" />
                </template>
              </template>
            </el-select>
          </template>
        </el-table-column>
        <el-table-column v-if="!collapseSpecs" label="Length" min-width="95" max-width="130">
          <template #default="{ row }">
            <el-select v-if="isProduction" v-model="row.length" filterable allow-create default-first-option placeholder="Length" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.sizes" :key="value" :label="value" :value="value" />
            </el-select>
            <el-select v-else v-model="row.length" filterable placeholder="Length" @visible-change="visible => visible && loadLineOptions(row)" @change="onLineFilterChange(row)">
              <template v-for="group in lineOptionGroups(row.options, 'sizes')" :key="group.label">
                <el-option-group v-if="group.label" :label="group.label">
                  <el-option v-for="value in group.options" :key="value" :label="value" :value="value" />
                </el-option-group>
                <template v-else>
                  <el-option v-for="value in group.options" :key="value" :label="value" :value="value" />
                </template>
              </template>
            </el-select>
          </template>
        </el-table-column>
        <el-table-column v-if="!collapseSpecs" label="Net Weight" min-width="105" max-width="150">
          <template #default="{ row }">
            <el-select v-if="isProduction" v-model="row.net_weight_grams" filterable allow-create default-first-option placeholder="Unit" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.units" :key="value" :label="value" :value="value" />
            </el-select>
            <el-select v-else v-model="row.net_weight_grams" filterable placeholder="Unit" @visible-change="visible => visible && loadLineOptions(row)" @change="onLineFilterChange(row)">
              <template v-for="group in lineOptionGroups(row.options, 'units')" :key="group.label">
                <el-option-group v-if="group.label" :label="group.label">
                  <el-option v-for="value in group.options" :key="value" :label="value" :value="value" />
                </el-option-group>
                <template v-else>
                  <el-option v-for="value in group.options" :key="value" :label="value" :value="value" />
                </template>
              </template>
            </el-select>
          </template>
        </el-table-column>
        <el-table-column v-if="isProduction" label="半成品库存" min-width="240" max-width="320">
          <template #default="{ row }">
            <div class="semifinished-cell">
              <el-checkbox v-model="row.semifinished_enabled" :disabled="row.semifinished_loading" @change="enabled => onSemifinishedToggle(row, enabled)">自动使用</el-checkbox>
              <template v-if="row.semifinished_enabled">
                <div v-for="item in row.semifinished_plan" :key="item.material_id" class="semifinished-line">
                  <span>{{ item.size && item.color_code ? `${item.size}/${item.color_code}` : `物料 #${item.material_id}` }}</span>
                  <el-input-number v-model="item.quantity_grams" :min="0.001" :precision="3" :controls="false" />
                  <small>g · 可用 {{ item.available_grams == null ? '--' : Number(item.available_grams).toLocaleString() }}g</small>
                </div>
                <el-button link type="primary" :loading="row.semifinished_loading" @click="loadSemifinished(row)">重新计算</el-button>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="!isProduction" label="Product_name" min-width="230" max-width="360" show-overflow-tooltip>
          <template #default="{ row }">
            <div :class="['product-cell', row.product_name ? 'is-matched' : 'is-pending']">
              <span>{{ row.product_name || '待匹配' }}</span>
              <span v-if="row.sku_id" class="stock-count">库存 {{ row.available_stock == null ? '—' : Math.round(row.available_stock) }}</span>
              <el-tag v-else-if="row.matching" size="small" type="info" effect="plain">匹配中</el-tag>
            </div>
            <el-text v-if="row.stock_warning" type="warning">{{ row.stock_warning }}</el-text>
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
          <template #default="{ row }"><el-input-number v-model="row.quantity" :min="1" :precision="0" :controls="false" @change="onQuantityChange(row)" /></template>
        </el-table-column>
        <el-table-column label="折扣" min-width="110" max-width="150">
          <template #default="{ row }"><el-input-number v-model="row.discount_amount" :precision="2" :controls="false" class="line-discount-input" @change="onLineDiscountChange(row)" /></template>
        </el-table-column>
        <el-table-column label="TotalPrice" min-width="100" max-width="150" align="right">
          <template #default="{ row }">{{ money(row.total_price) }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="64" max-width="80" fixed="right">
          <template #default="{ row }"><el-button link type="danger" aria-label="删除产品" @click="$emit('remove', row)"><el-icon><Delete /></el-icon></el-button></template>
        </el-table-column>
      </el-table>
    </div>
    <!-- 明细可能几十上百行：窗内分页，行号跨页连续；新增/导入后跳到末页 -->
    <div v-if="items.length" class="line-pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="items.length"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        small
        background
      />
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp, Delete, DocumentCopy, Plus } from '@element-plus/icons-vue'
import { CURL_OPTIONS } from '../composables/useInvoiceEditor'
import { quoteSemifinished } from '@/api/semifinished'

const props = defineProps({
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
defineEmits(['paste', 'copy', 'add-blank', 'remove'])
const showOptionalCols = ref(false)
const collapseSpecs = ref(false)

// 窗内分页：几十上百行时表格窗口高度固定；行号跨页连续
const page = ref(1)
const pageSize = ref(10)
const pagedItems = computed(() => props.items.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const indexBase = computed(() => (page.value - 1) * pageSize.value + 1)
watch(() => props.items.length, (now, before) => {
  const pages = Math.max(1, Math.ceil(now / pageSize.value))
  if (!before) page.value = 1 // 编辑单初次装载：从第一页开始审阅
  else if (now > before) page.value = pages // 添加空行/复制/Excel 粘贴：跟到末页
  else if (page.value > pages) page.value = pages // 删除行后收敛页码
})

async function loadSemifinished(row) {
  if (!row.product_id) {
    row.semifinished_enabled = false
    row.semifinished_plan = []
    ElMessage.warning('该产品尚未绑定 OKKI 产品，不能自动使用半成品')
    return
  }
  row.semifinished_loading = true
  try {
    const quote = await quoteSemifinished({ product_id: row.product_id, finished_qty: Number(row.quantity || 1) })
    row.semifinished_plan = (quote.items || []).map(item => ({
      material_id: item.material_id,
      material_code: item.material_code,
      size: item.size,
      color_code: item.color_code,
      available_grams: Number(item.available_grams),
      quantity_grams: Number(item.suggested_qty_grams),
    }))
  } catch (error) {
    row.semifinished_enabled = false
    row.semifinished_plan = []
    ElMessage.warning(error?.response?.data?.detail || error.message || '半成品计划计算失败')
  } finally { row.semifinished_loading = false }
}

function onSemifinishedToggle(row, enabled) {
  if (enabled) loadSemifinished(row)
  else row.semifinished_plan = []
}

function onQuantityChange(row) {
  props.updateLineTotal(row)
  if (row.semifinished_enabled) loadSemifinished(row)
}

const OPTION_GROUP_LABELS = { models: '全部型号', colors: '全部颜色', sizes: '全部长度', units: '全部克重' }
// 级联候选（按行内其余维度过滤）置顶，全量差集垫底：整行复制后其余维度已满时，
// 全量组是换型号/换色的唯一出口。差集为空（无过滤态）时平铺不分组。
function lineOptionGroups(options, key) {
  const matched = options[key] || []
  const matchedSet = new Set(matched)
  const rest = (options[`all_${key}`] || []).filter(value => !matchedSet.has(value))
  if (!rest.length) return [{ label: '', options: matched }]
  return [
    { label: '匹配当前组合', options: matched },
    { label: OPTION_GROUP_LABELS[key], options: rest },
  ].filter(group => group.options.length)
}
</script>

<style scoped>
.line-header { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 12px; }
.line-title { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.line-title .line-hint { color: var(--text-secondary); font-size: 13px; }
.step { display: inline-flex; width: 20px; height: 20px; flex: none; align-items: center; justify-content: center; border-radius: 6px; background: var(--color-primary); color: #fff; font-size: 12px; font-weight: 700; }
.line-header-actions, .price-cell, .product-cell { display: flex; align-items: center; gap: 8px; }
.line-table-wrap { overflow-x: auto; border: 1px solid var(--border-color); border-radius: var(--card-radius); }
.line-pagination { display: flex; justify-content: flex-end; margin-top: 10px; }
.line-table { width: 100%; }
.product-cell { min-height: 28px; }
.stock-count { font-size: 11px; color: var(--text-secondary); border: 1px solid var(--border-color); border-radius: 6px; padding: 1px 7px; background: var(--table-header-bg); white-space: nowrap; }
.product-cell.is-pending { color: var(--text-muted); }
.std-price { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.price-cell.is-manual :deep(.el-input__wrapper) { background: var(--color-warning-bg); }
.line-discount-input :deep(input) { color: var(--color-danger); font-variant-numeric: tabular-nums; }
.semifinished-cell { display: flex; flex-direction: column; gap: 6px; }
.semifinished-line { display: grid; grid-template-columns: minmax(85px, 1fr) 90px 14px; align-items: center; gap: 6px; font-size: 12px; }
.semifinished-line small { color: var(--text-muted); }
</style>
