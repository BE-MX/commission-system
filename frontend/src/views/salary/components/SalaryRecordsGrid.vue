<!--
  工资明细表（M3-f）。22 列宽表，是算完薪之后的主战场。

  冻结列的取舍：序号/工号/姓名钉在左边；右边钉的是**最后三列结果列**
  （实发/个税/税后实发）而不只实发一列——el-table 的右冻结列按声明顺序
  从右缘排，只钉中间的实发会让它漂到个税后面去，列序反而乱了。

  手动 5 列的单元格契约不对称，靠 COLUMNS 里的标志位区分：
  - bonus/performance/other/subsidy 是 {auto, manual, final} 三元组，
    显示 final，编辑的是 manual（空 = 没覆盖，placeholder 亮出引擎值）；
  - 个税只有 income_tax_amount 一个扁平值（flat: true），拿不到 auto/manual
    拆分，只能编当前显示值，也没有覆盖底色可标；PUT 字段名 income_tax 与
    显示字段不同，靠 putField 桥接。
-->
<template>
  <el-table :data="records.items" border class="list-table records-grid" max-height="560"
            v-loading="loading" :row-class-name="rowClass"
            :show-summary="records.items.length > 0" :summary-method="summaryRow">
    <el-table-column v-for="col in COLUMNS" :key="col.prop" :prop="col.prop" :label="col.label"
                     :width="col.width" :fixed="col.fixed" :align="col.align"
                     :show-overflow-tooltip="col.tooltip">
      <template #default="{ row }">
        <template v-if="col.manual">
          <div v-if="isEditing(row, col.prop)" class="cell-editor">
            <el-input-number v-model="editDraft" :precision="2" :controls="false"
                             size="small" ref="editInput"
                             :min="col.flat ? 0 : -999999" :max="999999"
                             :placeholder="col.flat ? '留空=清除人工值' : `引擎 ${money(row[col.prop]?.auto)}`"
                             @keyup.enter="commitEdit(row, col)"
                             @keyup.esc="cancelEdit" />
            <el-button link type="primary" size="small" :loading="savingCell"
                       @click="commitEdit(row, col)"><el-icon><Check /></el-icon></el-button>
            <el-button link size="small" @click="cancelEdit"><el-icon><Close /></el-icon></el-button>
          </div>
          <el-tooltip v-else :disabled="!isOverridden(row, col.prop)"
                      :content="overrideTip(row, col.prop)" placement="top">
            <div class="cell-value"
                 :class="{ overridden: isOverridden(row, col.prop), readonly: !editable }"
                 @click="startEdit(row, col.prop)">
              {{ money(cellFinal(row, col)) }}
            </div>
          </el-tooltip>
        </template>
        <b v-else-if="col.bold">{{ money(row[col.prop]) }}</b>
        <template v-else>{{ col.money ? money(row[col.prop]) : row[col.prop] }}</template>
      </template>
    </el-table-column>

    <template #empty>
      <div class="empty-hint">
        {{ notCalculated
          ? '还没有工资明细。点右上角「计算工资」，算出全批明细后这里才有数。'
          : '没有符合条件的记录。' }}
      </div>
    </template>
  </el-table>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { Check, Close } from '@element-plus/icons-vue'
import { money } from '@/api/salary'

const props = defineProps({
  // { items, total, totals, truncated }——totals 是后端按当前查询算的合计，
  // 带搜索条件时合计跟着滤后结果走，不是全批的
  records: { type: Object, required: true },
  loading: { type: Boolean, default: false },
  status: { type: String, default: '' },          // 批次状态，决定空态文案
  editable: { type: Boolean, default: false },    // 已含 salary:write 权限判断
  // (row, putField, value|null) => Promise<bool>；null = 清除覆盖
  saveManual: { type: Function, required: true },
})

// 全列配置。manual=true 的是可手改列；列序与线下工资表一致（其他加减在减项
// 小计前、补贴在实发前）——对账时列错位比多滚动几次更致命。
// 减项三列 + 减项小计是负数（与 HR 表同构），直接照显。
const COLUMNS = [
  { prop: 'seq_no', label: '序号', width: 60, fixed: 'left', align: 'right' },
  { prop: 'emp_no', label: '工号', width: 80, fixed: 'left' },
  { prop: 'name', label: '姓名', width: 90, fixed: 'left' },
  { prop: 'dept_detail', label: '部门', width: 140, tooltip: true },
  { prop: 'position', label: '岗位', width: 110, tooltip: true },
  { prop: 'due_days', label: '应出', width: 75, align: 'right', money: true },
  { prop: 'actual_days', label: '实出', width: 75, align: 'right', money: true },
  { prop: 'base_salary', label: '底薪', width: 100, align: 'right', money: true },
  { prop: 'bonus', label: '奖金', width: 120, align: 'right', manual: true },
  { prop: 'performance', label: '绩效', width: 120, align: 'right', manual: true },
  { prop: 'seniority_pay', label: '工龄工资', width: 90, align: 'right', money: true },
  { prop: 'attendance_bonus', label: '全勤奖', width: 90, align: 'right', money: true },
  { prop: 'add_subtotal', label: '加项小计', width: 100, align: 'right', money: true },
  { prop: 'social_insurance', label: '社保', width: 100, align: 'right', money: true },
  { prop: 'housing_fund', label: '公积金', width: 100, align: 'right', money: true },
  { prop: 'absence_deduction', label: '缺勤扣款', width: 100, align: 'right', money: true },
  { prop: 'other', label: '其他加减', width: 120, align: 'right', manual: true },
  { prop: 'deduct_subtotal', label: '减项小计', width: 100, align: 'right', money: true },
  { prop: 'subsidy', label: '补贴', width: 120, align: 'right', manual: true },
  { prop: 'net_salary', label: '实发工资', width: 110, align: 'right', money: true, bold: true, fixed: 'right' },
  // 个税是扁平字段（flat），PUT 走 income_tax；输入框 min/max 与后端
  // RecordManualEdit 的边界一致（个税 ge=0，其余列允许负值=扣钱），别放宽
  { prop: 'income_tax_amount', label: '个税', width: 110, align: 'right', manual: true, flat: true, putField: 'income_tax', fixed: 'right' },
  { prop: 'net_after_tax', label: '税后实发', width: 110, align: 'right', money: true, bold: true, fixed: 'right' },
]

// 合计行只显示这五列，字段名与后端 totals 一一对应
const SUMMARY_PROPS = ['base_salary', 'add_subtotal', 'deduct_subtotal', 'net_salary', 'net_after_tax']

const notCalculated = computed(() => !['calculated', 'reviewing', 'confirmed'].includes(props.status))

// --- 行内编辑：全表同时只有一格在编辑，状态就一对 key + 草稿值 ---

const editing = ref(null)        // `${row.id}:${prop}`
const editDraft = ref(null)
const savingCell = ref(false)
const editInput = ref(null)      // v-for 模板里的 ref 是数组，但同时只开一个编辑器

function isEditing(row, prop) {
  return editing.value === `${row.id}:${prop}`
}

// 单元格取值兼容两种形态：三元组对象或扁平数字（个税）
function cellValue(cell) {
  return (cell !== null && typeof cell === 'object') ? (cell.manual ?? null) : (cell ?? null)
}

function cellFinal(row, col) {
  const cell = row[col.prop]
  return (cell !== null && typeof cell === 'object') ? cell.final : cell
}

function startEdit(row, prop) {
  if (!props.editable || savingCell.value) return
  editing.value = `${row.id}:${prop}`
  // 三元组列编的是 manual（null → 空框，placeholder 显示引擎值）；
  // 个税没有 manual 概念，只能拿当前显示值当初值
  editDraft.value = cellValue(row[prop])
  nextTick(() => editInput.value?.[0]?.focus?.())
}

function cancelEdit() {
  editing.value = null
}

async function commitEdit(row, col) {
  if (savingCell.value) return
  const before = cellValue(row[col.prop])
  const draft = editDraft.value ?? null
  // 没动过就直接关框，不发请求——否则每次点开再回车都白写一行、刷一次版本号
  if (String(before ?? '') === String(draft ?? '')) {
    editing.value = null
    return
  }
  savingCell.value = true
  try {
    await props.saveManual(row, col.putField || col.prop, draft === null ? null : Number(draft))
  } finally {
    // 成败都关框：成功行已原地替换；失败（409）行已被刷新，草稿是旧数，留着会误导
    savingCell.value = false
    editing.value = null
  }
}

// --- 覆盖高亮：manual 非空且与 auto 不等 → 底色 + tooltip ---
// 用 Number 比，后端 Decimal 过 JSON 可能是 3500 也可能是 '3500.00'

function isOverridden(row, prop) {
  const cell = row[prop]
  if (!cell || typeof cell !== 'object') return false
  if (cell.manual === null || cell.manual === undefined) return false
  return Number(cell.manual) !== Number(cell.auto)
}

function overrideTip(row, prop) {
  const cell = row[prop] || {}
  return `引擎值 ${money(cell.auto)}，人工值 ${money(cell.manual)}`
}

// calc_flags 含 negative_net 的行整行标红：实发为负意味着发钱变扣钱，
// 是算薪结果里最危险的一类，必须一眼能扫到
function rowClass({ row }) {
  return row.calc_flags?.includes('negative_net') ? 'row-negative' : ''
}

function summaryRow({ columns }) {
  return columns.map((col, i) => {
    if (i === 0) return '合计'
    return SUMMARY_PROPS.includes(col.property) ? money(props.records.totals?.[col.property]) : ''
  })
}
</script>

<style scoped>
.records-grid :deep(.row-negative) {
  --el-table-tr-bg-color: var(--el-color-danger-light-9);
  --el-table-row-hover-bg-color: var(--el-color-danger-light-8);
}

.cell-value { min-height: 24px; line-height: 24px; cursor: pointer; border-radius: 4px; }
.cell-value.readonly { cursor: default; }
/* 醒目但不刺眼：warning 底色 + 加粗，跟负数行的 danger 红拉开层级 */
.cell-value.overridden {
  background: var(--el-color-warning-light-7);
  font-weight: 600;
}

.cell-editor { display: flex; align-items: center; gap: 2px; }
.cell-editor :deep(.el-input-number) { flex: 1; min-width: 0; }
.cell-editor :deep(.el-input__inner) { text-align: right; }

.empty-hint { padding: 24px 12px; color: var(--el-text-color-secondary); line-height: 1.8; }
</style>
