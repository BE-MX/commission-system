<template>
  <section class="invoice-hair-table">
    <div class="line-header">
      <div class="line-title">
        <span class="step">2</span><strong>产品明细</strong>
        <span v-if="isProduction" class="line-hint">生产单：关键词下拉可选可输，已有属性直接选，没有就按输入沉淀新产品。</span>
        <span v-else class="line-hint">四个关键词选择完整后自动匹配唯一 Product_name。</span>
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
        <el-button link type="primary" @click="collapseSpecs = !collapseSpecs">
          <el-icon><component :is="collapseSpecs ? ArrowDown : ArrowUp" /></el-icon>
          {{ collapseSpecs ? '展开规格列' : '收起规格列' }}
        </el-button>
        <el-button link type="primary" @click="showOptionalCols = !showOptionalCols">
          <el-icon><component :is="showOptionalCols ? ArrowUp : ArrowDown" /></el-icon>
          {{ showOptionalCols ? '收起选填列' : '展开选填列' }}
        </el-button>
        <!-- 勾选后才出现批量删除：平时不占位，也不用先选再找按钮 -->
        <template v-if="selectedCount">
          <span class="selection-hint">已选 {{ selectedCount }} 行</span>
          <el-button link type="danger" @click="removeSelected">
            <el-icon><Delete /></el-icon>
            删除所选
          </el-button>
          <el-button link @click="clearSelection">取消选择</el-button>
        </template>
        <el-button :disabled="!items.length" @click="clearAll"><el-icon><Delete /></el-icon>清空明细</el-button>
        <el-button :disabled="!items.length" @click="$emit('copy')"><el-icon><DocumentCopy /></el-icon>复制一行</el-button>
        <el-button @click="$emit('add-blank')"><el-icon><Plus /></el-icon>添加空行</el-button>
      </div>
    </div>
    <div class="stock-toolbar">
      <el-checkbox v-model="onlyShortage">仅显示库存不足的产品</el-checkbox>
      <span class="line-hint">自由可用已扣除待出库保留；浅红行表示本单待出库数量仍缺货</span>
      <el-button v-if="invoiceId" link type="primary" :loading="inventoryLoading" @click="refreshInventory">刷新库存与出库进度</el-button>
      <span v-if="inventoryLoading" class="line-hint" role="status">正在核对库存与出库进度</span>
      <el-text v-else-if="inventoryError" type="warning" role="status">库存核对失败，请刷新重试</el-text>
      <el-text v-else-if="unknownCount" type="warning" role="status">{{ unknownCount }} 行待核对，未计入库存不足筛选</el-text>
    </div>
    <div class="line-table-wrap">
      <el-table ref="lineTable" :data="pagedItems" :row-class-name="({ row }) => stockStatus(row).shortage ? 'stock-shortage-row' : ''" @sort-change="sortLines" @select="onSelect" @select-all="onSelectAll" border class="list-table line-table" max-height="560" v-sticky-scrollbar>
        <template #empty>
          <ListPageStatus :loading="onlyShortage && inventoryLoading" :error="onlyShortage ? inventoryError : ''" @retry="refreshInventory">
            <el-empty :image-size="96" :description="onlyShortage ? '暂无已确认库存不足的产品' : '暂无产品明细'" />
          </ListPageStatus>
        </template>
        <el-table-column type="selection" min-width="42" fixed />
        <el-table-column label="#" type="index" :index="indexBase" min-width="48" fixed />
        <el-table-column v-if="isProduction" label="Product" min-width="190" prop="product_display" sortable="custom">
          <template #default="{ row }">
            <el-select v-model="row.product_display" filterable allow-create default-first-option placeholder="系列描述，可输入" @change="onCustomFieldChange(row)">
              <el-option v-for="value in entryOptions.displays" :key="value" :label="value" :value="value" />
            </el-select>
            <el-text v-if="row.stock_warning" type="warning">{{ row.stock_warning }}</el-text>
          </template>
        </el-table-column>
        <el-table-column v-if="(showOptionalCols || !isProduction) && !collapseSpecs" label="Model" min-width="120" prop="model" sortable="custom">
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
        <el-table-column v-if="!collapseSpecs" label="Color" min-width="120" prop="color" sortable="custom">
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
        <el-table-column v-if="!collapseSpecs" label="Length" min-width="95" prop="length" sortable="custom">
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
        <el-table-column v-if="!collapseSpecs" label="Net Weight" min-width="105" prop="net_weight_grams" sortable="custom">
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
        <el-table-column v-if="isProduction" label="半成品库存" min-width="240" prop="semifinished_summary" sortable="custom">
          <template #default="{ row }">
            <div class="semifinished-cell">
              <el-checkbox v-model="row.semifinished_enabled" :disabled="row.semifinished_loading" @change="enabled => onSemifinishedToggle(row, enabled)">自动使用</el-checkbox>
              <template v-if="row.semifinished_enabled">
                <div v-for="item in row.semifinished_plan" :key="item.material_id" class="semifinished-line">
                  <span>{{ item.size && item.color_code ? `${item.size}/${item.color_code}` : `物料 #${item.material_id}` }}</span>
                  <el-input-number class="line-number-input" v-model="item.quantity_grams" :min="0.001" :precision="3" :controls="false" />
                  <small>g · 可用 {{ item.available_grams == null ? '--' : Number(item.available_grams).toLocaleString() }}g</small>
                </div>
                <el-button link type="primary" :loading="row.semifinished_loading" @click="loadSemifinished(row)">重新计算</el-button>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="!isProduction" :label="collapseSpecs ? 'Product_name' : '匹配'" :width="collapseSpecs ? undefined : 150" :min-width="collapseSpecs ? 230 : undefined" prop="product_name" sortable="custom">
          <template #default="{ row }">
            <!-- 规格列可见时 Product_name 只是重复，单元格给状态、名称悬停看；
                 规格列收起后它是唯一能区分行的信息，必须完整显示 -->
            <el-tooltip :disabled="collapseSpecs || !row.product_name" :content="row.product_name || ''" placement="top">
              <div :class="['product-cell', row.product_name ? 'is-matched' : 'is-pending']">
                <StatusBadge v-if="row.matching" size="small" type="info" effect="plain">匹配中</StatusBadge>
                <span v-else-if="collapseSpecs" class="product-name">{{ row.product_name || '待匹配' }}</span>
                <template v-else>
                  <span aria-hidden="true">{{ row.product_name ? '已匹配' : '待匹配' }}</span>
                  <span class="sr-only">{{ row.product_name || '待匹配' }}</span>
                </template>
              </div>
            </el-tooltip>
            <el-text v-if="row.stock_warning" type="warning">{{ row.stock_warning }}</el-text>
          </template>
        </el-table-column>
        <el-table-column label="自由可用" min-width="110">
          <template #default="{ row }">
            <span class="stock-count">{{ stockStatus(row).available ?? '待核对' }}</span>
            <el-text v-if="stockStatus(row).shortage" type="danger" size="small">库存不足</el-text>
          </template>
        </el-table-column>
        <el-table-column v-if="showOptionalCols" label="Curl" min-width="110" prop="curl" sortable="custom">
          <template #default="{ row }">
            <el-select v-model="row.curl" clearable placeholder="可选">
              <el-option v-for="value in CURL_OPTIONS" :key="value" :label="value" :value="value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="标准价" min-width="110" align="right" prop="standard_price" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.standard_price != null" class="std-price">
              {{ money(row.standard_price) }}
              <el-tooltip v-if="row.color_type_source === 'inferred'" content="该色号未登记色型映射，价格按命名规则推断的色型取得，请人工核对">
                <StatusBadge size="small" type="warning" effect="plain">色型推断</StatusBadge>
              </el-tooltip>
            </span>
            <StatusBadge v-else size="small" type="warning" effect="plain">无标准价</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="showDiscountCol" label="折扣" min-width="100" prop="discount_amount" sortable="custom">
          <template #default="{ row }"><el-input-number v-model="row.discount_amount" :precision="2" :controls="false" class="line-discount-input line-number-input" @change="onLineDiscountChange(row)" /></template>
        </el-table-column>
        <el-table-column label="客户价" min-width="130" align="right" prop="price_per_piece" sortable="custom" :fixed="pinColumns ? 'right' : false">
          <template #default="{ row }">
            <!-- 手改只用底色提示，整格留给数字；标准价与被两位显示藏住的小数位在悬停里对照 -->
            <el-tooltip :disabled="!priceHint(row)" :content="priceHint(row)" placement="top">
              <div :class="['price-cell', row.price_source === 'manual' ? 'is-manual' : '']">
                <!-- blur 也要提交：重输同样的两位值时 EP 不触发 change，行合计会停在旧值 -->
                <el-input-number class="line-price-input" v-model="row.price_per_piece" :min="0" :precision="2" :controls="false" :aria-label="row.price_source === 'manual' ? '客户价（已手改）' : '客户价'" @change="onPriceInput(row)" @blur="onPriceInput(row)" />
              </div>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="Quantity" min-width="96" prop="quantity" sortable="custom" :fixed="pinColumns ? 'right' : false">
          <template #default="{ row }">
            <el-input-number class="line-number-input" v-model="row.quantity" :ref="input => { if (row === quantityErrorRow) quantityInput = input }" :class="{ 'quantity-error': row === quantityErrorRow }" :min="1" :precision="0" :controls="false" @change="onQuantityChange(row)" />
            <el-text v-if="row === quantityErrorRow" type="danger" size="small">请填写正整数数量</el-text>
          </template>
        </el-table-column>
        <el-table-column label="TotalPrice" min-width="110" align="right" prop="total_price" sortable="custom" :fixed="pinColumns ? 'right' : false">
          <template #default="{ row }">{{ money(row.total_price) }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="56" fixed="right">
          <template #default="{ row }"><el-button link type="danger" aria-label="删除产品" @click="$emit('remove', row)"><el-icon><Delete /></el-icon></el-button></template>
        </el-table-column>
      </el-table>
    </div>
    <!-- 明细可能几十上百行：窗内分页，行号跨页连续；新增/导入后跳到末页 -->
    <div v-if="filteredItems.length" class="line-pagination">
      <el-pagination class="pager"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="filteredItems.length"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        small
        background
      />
    </div>
  </section>
</template>

<script setup>import { msgWarning } from '@/utils/feedback'
import { computed, nextTick, ref, watch } from 'vue'
import { confirmDanger, isFeedbackCancelled } from '@/utils/feedback'
import { sortTableRows } from '@/utils/tableSort'
import { useLineSelection } from '../composables/useLineSelection.js'
import { hiddenPricePrecision } from '../composables/invoiceSettlement.js'
import { useInvoiceStockShortage } from '../composables/useInvoiceStockShortage.js'
import { getInvoiceEditorInventory } from '@/api/invoice'

import { ArrowDown, ArrowUp, Delete, DocumentCopy, Plus } from '@element-plus/icons-vue'
import { CURL_OPTIONS } from '../composables/useInvoiceEditor'
import { quoteSemifinished } from '@/api/semifinished'

const props = defineProps({
  items: { type: Array, required: true },
  invoiceId: { type: Number, default: null },
  active: { type: Boolean, default: true },
  quantityErrorRow: { type: Object, default: null },
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
  // 旧版 640px 抽屉放不下右侧固定列（会挤掉全部可滚动空间），由调用方关掉
  pinColumns: { type: Boolean, default: true },
})
const emit = defineEmits(['paste', 'copy', 'add-blank', 'remove', 'remove-many'])
const { onlyShortage, stockStatus, filteredItems, unknownCount,
  loading: inventoryLoading, error: inventoryError, refreshInventory } = useInvoiceStockShortage(props, getInvoiceEditorInventory)
const showOptionalCols = ref(false)
function priceHint(row) {
  const parts = []
  const precise = hiddenPricePrecision(row.price_per_piece)
  if (precise) parts.push(`按 ${precise} 计价`)
  if (row.price_source === 'manual') parts.push(`已手改，标准价 ${row.standard_price == null ? '—' : preciseMoney(row.standard_price)}`)
  return parts.join(' · ')
}
const preciseMoney = value => hiddenPricePrecision(value) || props.money(value)
// 折扣大多数单不填：并入选填列；但只要有行填了折扣就常驻，避免金额对不上却看不到原因
const showDiscountCol = computed(() => showOptionalCols.value
  || props.items.some(row => Number(row.discount_amount || 0) !== 0))
const collapseSpecs = ref(false)

// 窗内分页：几十上百行时表格窗口高度固定；行号跨页连续
const page = ref(1)
const pageSize = ref(20)
const sortField = ref('')
const sortOrder = ref('')
function sortLines({ prop, order }) { sortField.value = prop; sortOrder.value = order; page.value = 1 }
const sortedItems = computed(() => sortTableRows(filteredItems.value, sortField.value, sortOrder.value, row => sortField.value === 'semifinished_summary'
  ? (row.semifinished_plan || []).map(item => `${item.size}/${item.color_code} ${item.quantity_grams}`).join(' / ')
  : row[sortField.value]))
const pagedItems = computed(() => sortedItems.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const indexBase = computed(() => (page.value - 1) * pageSize.value + 1)
const lineTable = ref(null)
const itemsRef = computed(() => props.items)
const { selectedCount, onSelect, onSelectAll, clearSelection, takeSelected } =
  useLineSelection(lineTable, itemsRef, pagedItems)

async function removeSelected() {
  try {
    await confirmDanger('删除', `所选 ${selectedCount.value} 行产品明细`, '删除后可重新添加，但本行录入内容会丢失。')
  } catch (error) {
    if (isFeedbackCancelled(error)) return
    throw error
  }
  emit('remove-many', takeSelected())
}

async function clearAll() {
  try {
    await confirmDanger('清空', `全部 ${props.items.length} 行产品明细`, '清空后可重新添加或从 Excel 粘贴，但已录入内容会丢失。')
  } catch (error) {
    if (isFeedbackCancelled(error)) return
    throw error
  }
  clearSelection()
  emit('remove-many', [...props.items])
}
const quantityInput = ref(null)
watch(() => props.quantityErrorRow, async row => {
  const index = props.items.indexOf(row)
  if (index < 0) return
  onlyShortage.value = false
  // Return to entry order so typing a quantity cannot move this row to another page.
  lineTable.value?.clearSort()
  sortField.value = ''
  sortOrder.value = ''
  page.value = Math.floor(index / pageSize.value) + 1
  await nextTick()
  quantityInput.value?.focus()
})
watch(() => props.items.length, (now, before) => {
  // Adding/importing must reveal new rows even when their stock is not known yet.
  if (now > before) onlyShortage.value = false
  const pages = Math.max(1, Math.ceil(now / pageSize.value))
  if (!before) page.value = 1 // 编辑单初次装载：从第一页开始审阅
  else if (now > before) page.value = pages // 添加空行/复制/Excel 粘贴：跟到末页
  else if (page.value > pages) page.value = pages // 删除行后收敛页码
})
watch(onlyShortage, () => { page.value = 1; clearSelection() }, { flush: 'sync' })
watch([filteredItems, pageSize], () => {
  page.value = Math.min(page.value, Math.max(1, Math.ceil(filteredItems.value.length / pageSize.value)))
  // Hidden rows must not remain selected for a later bulk deletion.
  if (onlyShortage.value) clearSelection()
})

async function loadSemifinished(row) {
  if (!row.product_id) {
    row.semifinished_enabled = false
    row.semifinished_plan = []
    msgWarning('该产品尚未绑定 OKKI 产品，不能自动使用半成品')
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
    msgWarning(error?.response?.data?.detail || error.message || '半成品计划计算失败')
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
.line-header-actions { flex-wrap: wrap; justify-content: flex-end; }
.stock-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; margin-bottom: 10px; }
.stock-toolbar .line-hint { color: var(--text-secondary); font-size: 12px; }
.line-table :deep(.stock-shortage-row) { --el-table-tr-bg-color: var(--tag-danger-bg); --el-table-row-hover-bg-color: var(--tag-danger-bg); }
.line-table :deep(.stock-shortage-row > td.el-table__cell),
.line-table :deep(.stock-shortage-row:hover > td.el-table__cell) { background: var(--tag-danger-bg) !important; }
.selection-hint { color: var(--text-secondary); font-size: 13px; font-variant-numeric: tabular-nums; }
.line-table-wrap { overflow-x: auto; border: 1px solid var(--border-color); border-radius: var(--card-radius); }
.line-pagination { display: flex; justify-content: flex-end; margin-top: 10px; }
.line-table { width: 100%; }
.product-cell { min-height: 28px; flex-wrap: wrap; row-gap: 2px; }
.product-name { overflow-wrap: anywhere; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.stock-count { font-size: 11px; color: var(--text-secondary); border: 1px solid var(--border-color); border-radius: 6px; padding: 1px 7px; background: var(--table-header-bg); white-space: nowrap; }
.product-cell.is-pending { color: var(--text-muted); }
.std-price { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.price-cell.is-manual :deep(.el-input__wrapper) { background: var(--color-warning-bg); }
.price-cell { width: 100%; }
.line-price-input { width: 100%; }
.line-number-input { width: 100%; }
.price-cell :deep(input) { text-align: right; font-variant-numeric: tabular-nums; }
.line-discount-input :deep(input) { color: var(--color-danger); font-variant-numeric: tabular-nums; }
.quantity-error { outline: 1px solid var(--color-danger); }
.semifinished-cell { display: flex; flex-direction: column; gap: 6px; }
.semifinished-line { display: grid; grid-template-columns: minmax(85px, 1fr) 90px 14px; align-items: center; gap: 6px; font-size: 12px; }
.semifinished-line small { color: var(--text-muted); }
</style>
