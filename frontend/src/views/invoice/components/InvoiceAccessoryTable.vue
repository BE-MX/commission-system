<template>
  <section class="accessory-detail-section">
    <div class="line-header">
      <div class="line-title">
        <span class="step">3</span><strong>配件明细</strong>
        <span class="line-hint">Hair ExtensionsTools Fee · 仅可选择已配置标准价的真实 OKKI SKU</span>
      </div>
      <div class="line-header-actions">
        <!-- 勾选后才出现批量删除：平时不占位，也不用先选再找按钮 -->
        <template v-if="selectedCount">
          <span class="selection-hint">已选 {{ selectedCount }} 行</span>
          <el-button link type="danger" @click="removeSelected">
            <el-icon><Delete /></el-icon>
            删除所选
          </el-button>
          <el-button link @click="clearSelection">取消选择</el-button>
        </template>
        <el-button link type="primary" @click="showOptionalCols = !showOptionalCols">
          <el-icon><component :is="showOptionalCols ? ArrowUp : ArrowDown" /></el-icon>
          {{ showOptionalCols ? '收起折扣列' : '展开折扣列' }}
        </el-button>
        <el-button :disabled="!items.length" @click="clearAll">
          <el-icon><Delete /></el-icon>
          清空配件
        </el-button>
        <el-button @click="$emit('add')">
          <el-icon><Plus /></el-icon>
          添加配件
        </el-button>
      </div>
    </div>
    <div class="line-table-wrap accessory-line-table-wrap">
      <el-table ref="lineTable" :data="pagedItems" @sort-change="sortLines" @select="onSelect" @select-all="onSelectAll" border class="list-table line-table accessory-line-table" max-height="560" v-sticky-scrollbar>
        <el-table-column type="selection" width="42" fixed :selectable="() => true" />
        <el-table-column label="#" type="index" :index="indexBase" width="48" fixed />
        <el-table-column label="Name" min-width="190" prop="product_name" sortable="custom">
          <template #default="{ row }">
            <!-- 不要加 @visible-change 预取：EP 2.13 起该事件绑内部 dropdownMenuVisible
                 （随 loading/option 挂载数翻转），配合请求会形成无限刷新环；
                 展开时 EP 自动调 remote-method('')，预取本就冗余 -->
            <el-select
              :model-value="identityValue(row)"
              filterable
              remote
              reserve-keyword
              :remote-method="searchOptions"
              :loading="loading"
              placeholder="搜索已配置配件"
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
        <el-table-column label="Model" min-width="130" prop="model" sortable="custom">
          <template #default="{ row }"><el-input :model-value="row.model" readonly /></template>
        </el-table-column>
        <el-table-column label="Color" min-width="130" prop="color" sortable="custom">
          <template #default="{ row }"><el-input :model-value="row.color" readonly /></template>
        </el-table-column>
        <el-table-column label="标准价" width="110" align="right" prop="standard_price" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.standard_price != null" class="std-price">{{ money(row.standard_price) }}</span>
            <StatusBadge v-else-if="accessoryStandardPriceState(row) === 'invalid'" size="small" type="warning" effect="plain">需重新配置</StatusBadge>
            <span v-else class="std-price">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showDiscountCol" label="折扣" width="100" prop="discount_amount" sortable="custom">
          <template #default="{ row }">
            <el-input-number v-model="row.discount_amount" :precision="2" :controls="false" class="line-discount-input" @change="$emit('change', row)" />
          </template>
        </el-table-column>
        <el-table-column label="客户价" width="130" align="right" prop="price_per_piece" sortable="custom" fixed="right">
          <template #default="{ row }">
            <!-- 输入框占满整格；客户参考价移到下方小字，手改只用底色提示 -->
            <div :class="['price-cell', row.price_source === 'manual' ? 'is-manual' : '']">
              <el-input-number
                v-model="row.price_per_piece"
                :aria-label="row.price_source === 'manual' ? '成交价（已手改）' : '成交价'"
                :min="0"
                :precision="2"
                :controls="false"
                :disabled="row.standard_price == null"
                @change="$emit('change', row)"
              />
              <span class="customer-price-reference" :title="row.customer_price == null ? '选择客户后解析客户价' : `客户价 ${money(row.customer_price)}`">
                {{ row.customer_price == null ? '客户价 —' : `客户价 ${money(row.customer_price)}` }}{{ row.price_source === 'manual' ? ' · 已手改' : '' }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Quantity" width="96" prop="quantity" sortable="custom" fixed="right">
          <template #default="{ row }">
            <el-input-number v-model="row.quantity" :ref="input => { if (row === quantityErrorRow) quantityInput = input }" :class="{ 'quantity-error': row === quantityErrorRow }" :min="1" :precision="0" :controls="false" @change="$emit('change', row)" />
            <el-text v-if="row === quantityErrorRow" type="danger" size="small">请填写正整数数量</el-text>
          </template>
        </el-table-column>
        <el-table-column label="TotalPrice" width="110" align="right" prop="total_price" sortable="custom" fixed="right">
          <template #default="{ row }">{{ money(row.total_price) }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" width="56" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" aria-label="删除配件" @click="$emit('remove', row)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <!-- 配件也可能几十行：与产品明细同款窗内分页，行号跨页连续 -->
    <div v-if="items.length" class="line-pagination">
      <el-pagination class="pager"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="items.length"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        small
        background
      />
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { confirmDanger, isFeedbackCancelled } from '@/utils/feedback'
import { sortTableRows } from '@/utils/tableSort'
import { ArrowDown, ArrowUp, Delete, Plus } from '@element-plus/icons-vue'
import { accessoryStandardPriceState } from '../composables/accessoryPricing.js'
import { useLineSelection } from '../composables/useLineSelection.js'

const props = defineProps({
  items: { type: Array, required: true },
  quantityErrorRow: { type: Object, default: null },
  options: { type: Array, default: () => [] },
  loading: Boolean,
  searchOptions: { type: Function, required: true },
  money: { type: Function, required: true },
})

const emit = defineEmits(['add', 'select', 'change', 'remove', 'remove-many'])

// 窗内分页：与产品明细同款；新增行后跳到末页
const page = ref(1)
const pageSize = ref(20)
const sortField = ref('')
const sortOrder = ref('')
function sortLines({ prop, order }) { sortField.value = prop; sortOrder.value = order; page.value = 1 }
const sortedItems = computed(() => sortTableRows(props.items, sortField.value, sortOrder.value, row => sortField.value === 'semifinished_summary'
  ? (row.semifinished_plan || []).map(item => `${item.size}/${item.color_code} ${item.quantity_grams}`).join(' / ')
  : row[sortField.value]))
const pagedItems = computed(() => sortedItems.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const indexBase = computed(() => (page.value - 1) * pageSize.value + 1)
const lineTable = ref(null)
// 折扣大多数单不填：没有行填折扣时隐藏，填过就常驻
const showOptionalCols = ref(false)
const showDiscountCol = computed(() => showOptionalCols.value
  || props.items.some(row => Number(row.discount_amount || 0) !== 0))
const itemsRef = computed(() => props.items)
const { selectedCount, onSelect, onSelectAll, clearSelection, takeSelected } =
  useLineSelection(lineTable, itemsRef, pagedItems)

async function removeSelected() {
  const count = selectedCount.value
  try {
    await confirmDanger('删除', `所选 ${count} 行配件`, '删除后可重新添加，但本行录入内容会丢失。')
  } catch (error) {
    if (isFeedbackCancelled(error)) return
    throw error
  }
  emit('remove-many', takeSelected())
}

async function clearAll() {
  try {
    await confirmDanger('清空', `全部 ${props.items.length} 行配件`, '清空后可重新添加，但已录入内容会丢失。')
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
  // Return to entry order so typing a quantity cannot move this row to another page.
  lineTable.value?.clearSort()
  sortField.value = ''
  sortOrder.value = ''
  page.value = Math.floor(index / pageSize.value) + 1
  await nextTick()
  quantityInput.value?.focus()
})
watch(() => props.items.length, (now, before) => {
  const pages = Math.max(1, Math.ceil(now / pageSize.value))
  if (!before) page.value = 1
  else if (now > before) page.value = pages
  else if (page.value > pages) page.value = pages
})

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
/* 卡片间距由父级 .pane-main 的 gap 提供，不再自带顶距 */
.accessory-detail-section { margin-top: 0; }
.line-header { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 12px; }
.line-title { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.line-title .line-hint { color: var(--text-secondary); font-size: 13px; }
.step { display: inline-flex; width: 20px; height: 20px; flex: none; align-items: center; justify-content: center; border-radius: 6px; background: var(--color-primary); color: #fff; font-size: 12px; font-weight: 700; }
.line-table-wrap { overflow-x: auto; border: 1px solid var(--border-color); border-radius: var(--card-radius); }
.line-pagination { display: flex; justify-content: flex-end; margin-top: 10px; }
.line-header-actions { display: flex; align-items: center; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.selection-hint { color: var(--text-secondary); font-size: 13px; font-variant-numeric: tabular-nums; }
.line-table { width: 100%; }
.price-cell { display: flex; flex-direction: column; align-items: stretch; gap: 2px; }
.price-cell :deep(.el-input-number) { width: 100%; }
.price-cell :deep(input) { text-align: right; font-variant-numeric: tabular-nums; }
.accessory-line-table :deep(.el-input-number) { width: 100%; }
.quantity-error { outline: 1px solid var(--color-danger); }
.price-cell.is-manual :deep(.el-input__wrapper) { background: var(--color-warning-bg); }
.std-price, .customer-price-reference { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.customer-price-reference { font-size: 11px; line-height: 1.3; text-align: right; white-space: nowrap; }
.accessory-identity { margin-top: 3px; color: var(--text-secondary); font-size: 11px; }
.line-discount-input :deep(input) { color: var(--color-danger); font-variant-numeric: tabular-nums; }
</style>
