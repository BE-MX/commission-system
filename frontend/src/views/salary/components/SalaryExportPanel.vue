<!--
  工资批次的导出面板（M4）：工资表双 sheet / 银行代发盘 / 导出历史与作废。

  页面上最重要的一句话是「这份文件能不能拿去发钱」：
  - 未锁定 → 工资表只给预览稿（文件里自带不得作为发放依据的标记），代发盘不给；
  - 解锁过 → 解锁前的导出全部作废，历史里标红，提醒回收旧文件。
  能不能导、哪一步卡住由后端 /exports 判定，前端不自己数状态。
-->
<template>
  <div class="export-panel" v-loading="loading">
    <el-alert v-if="loadError" type="error" :closable="false" class="block">
      {{ loadError }}
      <el-button link type="primary" @click="load">重试</el-button>
    </el-alert>

    <template v-if="overview">
      <el-alert v-if="overview.locked" type="success" :closable="false" class="block">
        批次已锁定。导出内容取锁定那一刻的档案快照，之后改档案不影响这份文件。
      </el-alert>
      <el-alert v-else type="warning" :closable="false" class="block">
        批次未锁定：工资表只能导出预览稿（文件标题与页眉都带「不得作为发放依据」），
        银行代发盘锁定后才能生成。
      </el-alert>
      <el-alert v-if="overview.voided_count" type="error" :closable="false" class="block">
        批次解锁过，之前导出的 {{ overview.voided_count }} 份文件已作废（见下方导出记录）。
        请回收旧文件，以锁定后重新导出的版本为准——工资表底部、代发盘文件名里都带导出编号，可回这里核对。
      </el-alert>

      <div class="export-grid">
        <div class="export-card">
          <div class="card-head">
            <h4>工资表</h4>
            <span class="muted">汇总表 + 明细表两张 sheet，格式同手工工资表</span>
          </div>
          <el-checkbox v-if="overview.can_plain_card" v-model="plainCard">
            银行卡号输出完整号码（默认脱敏，只显示前 4 后 4 位）
          </el-checkbox>
          <div class="card-actions">
            <GlassButton :variant="overview.locked ? 'primary' : 'ghost'" left-icon="Download"
                         :disabled="!overview.workbook.available || Boolean(busy)"
                         :loading="busy === 'workbook'" @click="downloadWorkbook">
              {{ overview.workbook.preview ? '导出预览稿' : '导出工资表' }}
            </GlassButton>
            <span v-if="overview.workbook.reason" class="muted">{{ overview.workbook.reason }}</span>
          </div>
          <div v-if="overview.workbook.missing_card_names.length" class="bank-issue">
            {{ overview.workbook.missing_card_names.join('、') }} 没有银行卡号，
            表里会标「无卡号」——先到员工档案补上{{ overview.locked ? '，再解锁、重新锁定后导出' : '' }}
          </div>
        </div>

        <div class="export-card" v-permission="'salary:admin'">
          <div class="card-head">
            <h4>银行代发盘</h4>
            <span class="muted">姓名 / 卡号 / 金额（扣除个税实发），默认按参保主体拆盘</span>
          </div>
          <div v-if="!overview.bank.available" class="muted">{{ overview.bank.reason }}</div>
          <template v-else>
            <div v-for="g in overview.bank.groups" :key="g.entity" class="bank-row">
              <div class="bank-main">
                <b>{{ g.entity }}</b>
                <span class="muted">{{ g.count }} 人 · {{ money(g.total_amount) }} 元</span>
                <GlassButton variant="ghost" left-icon="Download" class="bank-btn"
                             :disabled="Boolean(g.issues.length) || !g.count || Boolean(busy)"
                             :loading="busy === `bank:${g.entity}`" @click="downloadBank(g.entity)">
                  导出这一盘
                </GlassButton>
              </div>
              <div v-for="(i, idx) in g.issues" :key="idx" class="bank-issue">
                {{ i.name }}：{{ i.problem }}——处理后才能导出这一盘
              </div>
              <div v-if="g.zero_names.length" class="muted small">
                实发为 0、不进盘：{{ g.zero_names.join('、') }}
              </div>
            </div>
            <div class="card-actions">
              <el-button link type="primary" :disabled="hasBankIssues || Boolean(busy)"
                         :loading="busy === 'bank:'" @click="downloadBank('')">
                不拆盘，合并导出一个文件
              </el-button>
            </div>
            <div class="muted small">
              CSV 直接上传网银即可。不要用 Excel 打开后另存——19 位卡号会被改成科学计数，末几位变 0。
            </div>
          </template>
        </div>
      </div>

      <h4 class="history-title">导出记录</h4>
      <el-table :data="overview.history" border class="list-table" max-height="360" v-sticky-scrollbar>
        <el-table-column prop="export_no" label="编号" min-width="64" align="right">
          <template #default="{ row }">第 {{ row.export_no }} 次</template>
        </el-table-column>
        <el-table-column label="文件" min-width="140">
          <template #default="{ row }">
            {{ row.kind_label }}<span v-if="row.entity" class="muted"> · {{ row.entity }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }">
            <StatusBadge size="small" effect="plain" :type="STATUS_TYPES[row.status]">
              {{ row.status_label }}
            </StatusBadge>
          </template>
        </el-table-column>
        <el-table-column label="卡号" min-width="80">
          <template #default="{ row }">{{ row.plain_card ? '完整' : '脱敏' }}</template>
        </el-table-column>
        <el-table-column prop="record_count" label="人数" min-width="64" align="right" />
        <el-table-column label="金额" min-width="110" align="right">
          <template #default="{ row }">{{ money(row.total_amount) }}</template>
        </el-table-column>
        <el-table-column prop="operator_name" label="操作人" min-width="90" />
        <el-table-column label="导出时间" min-width="150">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="作废原因" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.status === 'voided'">{{ fmt(row.voided_at) }} 解锁：{{ row.void_reason || '未记录' }}</span>
          </template>
        </el-table-column>
        <template #empty><div class="muted">还没有导出过。</div></template>
      </el-table>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { blobErrorMessage, exportBank, exportWorkbook, getExportOverview, money } from '@/api/salary'
import { downloadBlob } from '@/utils/download'
import { msgError, msgSuccessText } from '@/utils/feedback'

const props = defineProps({
  periodId: { type: [Number, String], required: true },
  // 状态版本一变（锁定 / 解锁 / 计算）就重拉：作废判定与可导项都跟着它走
  statusVersion: { type: Number, default: 0 },
})

const STATUS_TYPES = { valid: 'success', voided: 'danger', preview: 'info' }

const overview = ref(null)
const loading = ref(false)
const loadError = ref('')
const plainCard = ref(false)
const busy = ref('')

const hasBankIssues = computed(() =>
  (overview.value?.bank?.groups || []).some(g => g.issues.length))

function fmt(v) {
  return v ? v.slice(0, 19).replace('T', ' ') : ''
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    overview.value = (await getExportOverview(props.periodId, { suppressToast: true })).data
  } catch (error) {
    loadError.value = error?.response?.data?.detail || '导出信息加载失败'
  } finally {
    loading.value = false
  }
}

// 每次导出后重拉：新记录进历史，导出编号与作废状态以后端为准
async function run(key, request, fallbackName) {
  busy.value = key
  try {
    downloadBlob(await request(), fallbackName)
    msgSuccessText('已生成，浏览器开始下载')
    await load()
  } catch (error) {
    msgError(await blobErrorMessage(error))
  } finally {
    busy.value = ''
  }
}

function downloadWorkbook() {
  return run('workbook', () => exportWorkbook(props.periodId, { plainCard: plainCard.value }),
    '工资表.xlsx')
}

function downloadBank(entity) {
  return run(`bank:${entity}`, () => exportBank(props.periodId, entity), '银行代发.csv')
}

watch(() => [props.periodId, props.statusVersion], load, { immediate: true })
</script>

<style scoped>
.block { margin-bottom: 12px; }
.export-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.export-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-head { display: flex; flex-direction: column; gap: 2px; }
.card-head h4 { margin: 0; font-size: 15px; }
.card-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.bank-row { display: flex; flex-direction: column; gap: 4px; padding: 6px 0; border-bottom: 1px dashed var(--el-border-color-lighter); }
.bank-main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.bank-btn { margin-left: auto; }
.bank-issue { font-size: 12px; color: var(--el-color-danger); }
.history-title { margin: 20px 0 10px; font-size: 15px; }
.muted { color: var(--el-text-color-secondary); font-size: 13px; }
.small { font-size: 12px; }
</style>
