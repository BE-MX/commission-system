<template>
  <div class="repair-page">
    <div class="page-head">
      <h2>回款日期修复</h2>
      <p class="sub">
        按工作表把系统里 <b>okki_receipts</b> 的回款日期纠正为正确值。匹配锚点：<b>客户名 + 订单总额USD → 唯一订单</b>。
        流程：上传 → 预览 → 逐条确认 → 写入。写入前不改任何数据，写入的每条都留有回滚记录。
      </p>
    </div>

    <el-card class="upload-card" shadow="never">
      <AppUpload
        v-model="files"
        :upload-fn="doPreview"
        accept=".xlsx"
        :limit="1"
        :max-size-mb="20"
        button-text="选择工作表（.xlsx）"
      />
      <span v-if="plan" class="src-hint">已解析：{{ plan.source_file }}</span>
    </el-card>

    <template v-if="plan">
      <div class="stat-row">
        <div class="stat" :class="{ active: true }">
          <div class="num">{{ plan.summary.total_rows }}</div><div class="label">工作表行数</div>
        </div>
        <div class="stat change">
          <div class="num">{{ plan.summary.will_change_receipts }}</div>
          <div class="label">待修改回款单（{{ plan.summary.will_change_orders }} 单）</div>
        </div>
        <div class="stat ok">
          <div class="num">{{ plan.summary.already_ok }}</div><div class="label">日期已正确</div>
        </div>
        <div class="stat miss">
          <div class="num">{{ plan.summary.unmatched }}</div><div class="label">无法匹配</div>
        </div>
      </div>

      <!-- 待修改 -->
      <el-card v-if="changeRows.length" class="block" shadow="never">
        <div class="block-head">
          <div>
            <span class="block-title">待修改（勾选后写入）</span>
            <span class="head-hint">多笔订单按回款单号顺序分配日期，请对照 Excel金额 / 回款单金额 核验后再写入（两者因手续费本就不等）</span>
          </div>
          <el-button
            v-permission="'invoice:admin'"
            type="primary"
            :disabled="!selected.length"
            @click="onApply"
          >确认修复选中 {{ selected.length }} 条</el-button>
        </div>
        <el-table
          ref="tableRef"
          :data="changeRows"
          size="small"
          row-key="cash_collection_id"
          @selection-change="selected = $event"
        >
          <el-table-column type="selection" width="44" :selectable="() => !applied" />
          <el-table-column prop="company" label="客户名" min-width="150" show-overflow-tooltip />
          <el-table-column prop="order_no" label="订单号" min-width="120" show-overflow-tooltip />
          <el-table-column label="订单总额" width="104" align="right">
            <template #default="{ row }">{{ fmt(row.order_total) }}</template>
          </el-table-column>
          <el-table-column label="Excel金额" width="104" align="right">
            <template #default="{ row }">{{ fmt(row.excel_amount) }}</template>
          </el-table-column>
          <el-table-column label="回款单金额" width="104" align="right">
            <template #default="{ row }">{{ fmt(row.receipt_amount) }}</template>
          </el-table-column>
          <el-table-column label="当前日期 → 目标日期" min-width="200">
            <template #default="{ row }">
              <span class="old">{{ row.old_date || '（空）' }}</span>
              <el-icon class="arrow"><Right /></el-icon>
              <span class="new">{{ row.new_date }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-alert
        v-else
        class="block"
        type="info"
        :closable="false"
        title="没有需要修改的回款单——匹配到的记录日期均已正确。"
      />

      <!-- 无法匹配 -->
      <el-card v-if="plan.unmatched.length" class="block" shadow="never">
        <div class="block-head">
          <span class="block-title">无法匹配（{{ plan.unmatched.length }} 条）</span>
          <el-button @click="onExportUnmatched">导出无法匹配 Excel</el-button>
        </div>
        <div class="reason-tags">
          <el-tag
            v-for="(cnt, code) in reasonCounts"
            :key="code"
            type="info"
            effect="plain"
          >{{ REASON_LABELS[code] || code }}：{{ cnt }}</el-tag>
        </div>
        <el-table :data="plan.unmatched" size="small" max-height="320">
          <el-table-column prop="company" label="客户名" min-width="150" show-overflow-tooltip />
          <el-table-column label="订单总额" width="110" align="right">
            <template #default="{ row }">{{ fmt(row.order_total) }}</template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="200" />
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Right } from '@element-plus/icons-vue'
import AppUpload from '@/components/AppUpload.vue'
import { msgSuccess, msgError } from '@/utils/feedback'
import { downloadBlob } from '@/utils/download'
import {
  previewReceiptRepair,
  applyReceiptRepair,
  exportReceiptRepairUnmatched,
} from '@/api/invoice'

const REASON_LABELS = {
  company_not_found: '客户名在回款表中不存在',
  no_order_amount_match: '该客户下无总额匹配的订单',
  multi_order_match: '匹配到多个订单，无法唯一确定',
  order_no_receipt: '订单存在但系统无回款记录',
  receipt_count_mismatch: '回款笔数与系统不一致',
  no_target_date: 'Excel 未提供有效回款日期',
}

const files = ref([])
const plan = ref(null)
const selected = ref([])
const applied = ref(false)
const tableRef = ref(null)

// AppUpload 注入的上传实现：这里不持久化文件，只做一次只读预览
async function doPreview(file) {
  const fd = new FormData()
  fd.append('file', file)
  const result = await previewReceiptRepair(fd)
  plan.value = result
  applied.value = false
  selected.value = []
  return { path: file.name, url: '' }
}

// 把 will_change 摊平成回款单级行，便于逐条勾选
const changeRows = computed(() => {
  if (!plan.value) return []
  const rows = []
  for (const w of plan.value.will_change) {
    for (const c of w.changes) {
      rows.push({
        company: w.company,
        order_no: w.order_no,
        order_total: w.order_total,
        cash_collection_id: c.cash_collection_id,
        excel_amount: c.excel_amount,
        receipt_amount: c.receipt_amount,
        old_date: c.old_date,
        new_date: c.new_date,
      })
    }
  }
  return rows
})

const reasonCounts = computed(() => {
  const m = {}
  for (const u of plan.value?.unmatched || []) m[u.reason_code] = (m[u.reason_code] || 0) + 1
  return m
})

function fmt(v) {
  return v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function onApply() {
  if (!selected.value.length) return
  const items = selected.value.map(r => ({ cash_collection_id: r.cash_collection_id, new_date: r.new_date }))
  try {
    const res = await applyReceiptRepair({ source_file: plan.value.source_file, items })
    if (res.failed) {
      // 有失败：不锁定，可再次点击重试；已成功的行重复 apply 会被幂等跳过
      msgError(`已修复 ${res.applied} 条，失败 ${res.failed} 条，可重试`)
    } else {
      applied.value = true
      msgSuccess(`已修复 ${res.applied} 条`)
    }
  } catch (e) {
    msgError('写入失败：' + (e?.message || e))
  }
}

async function onExportUnmatched() {
  try {
    const res = await exportReceiptRepairUnmatched({ unmatched: plan.value.unmatched })
    downloadBlob(res)
  } catch (e) {
    msgError('导出失败：' + (e?.message || e))
  }
}
</script>

<style scoped>
.repair-page { padding: 4px 2px; }
.page-head h2 { margin: 0 0 6px; color: var(--text-primary); }
.page-head .sub { margin: 0 0 16px; color: var(--text-secondary); font-size: 13px; line-height: 1.7; max-width: 900px; }
.upload-card { border-radius: var(--radius-lg); margin-bottom: 16px; }
.src-hint { margin-left: 12px; color: var(--text-secondary); font-size: 12px; }

.stat-row { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.stat {
  flex: 1; min-width: 140px; background: var(--card-bg); border: 1px solid var(--border-color);
  border-radius: var(--radius-lg); padding: 14px 16px; text-align: center;
}
.stat .num { font-size: 26px; font-weight: 700; color: var(--text-primary); line-height: 1.1; }
.stat .label { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
.stat.change { background: var(--color-primary-light); border-color: var(--color-primary); }
.stat.change .num { color: var(--color-primary); }
.stat.ok .num { color: var(--color-success-text); }
.stat.miss .num { color: var(--color-danger-text); }

.block { border-radius: var(--radius-lg); margin-bottom: 16px; }
.block-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.block-title { font-weight: 600; color: var(--text-primary); }
.head-hint { margin-left: 10px; font-size: 12px; color: var(--text-secondary); }
.reason-tags { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }

.old { color: var(--text-secondary); }
.arrow { margin: 0 8px; color: var(--color-primary); vertical-align: middle; }
.new { color: var(--color-success-text); font-weight: 600; }
</style>
