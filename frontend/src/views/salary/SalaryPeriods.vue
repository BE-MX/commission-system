<!--
  工资批次列表（M2-f）。只负责「看哪些月在跑 / 进哪个月」，
  所有动作都在工作台里做——列表页给动作按钮，HR 会在没看异常清单的情况下点下一步。
-->
<template>
  <div class="salary-page">
    <div class="salary-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="6">
        <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 100%" @change="fetchList">
          <el-option v-for="s in PERIOD_STATUS_ORDER" :key="s" :label="STATUS_TEXT[s]" :value="s" />
        </el-select>
      </el-col>
      <el-col :span="18" class="toolbar-right">
        <GlassButton variant="ghost" left-icon="RefreshLeft" @click="fetchList">刷新</GlassButton>
        <GlassButton v-permission="'salary:write'" variant="primary" left-icon="Plus" @click="openCreate">新建批次</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card salary-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="year_month" label="月份" min-width="100" />
        <el-table-column label="状态" min-width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_TAG[row.status] || 'info'" effect="plain">
              {{ row.status_label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="工作日数" min-width="130" align="right">
          <template #default="{ row }">
            {{ row.workday_count ?? '-' }}
            <!-- 自动推算只按周一~五数，没扣法定节假日也没加调休。
                 2 月批次的 20 天要是被当成应出基准用，全员缺勤扣款都是错的 -->
            <el-tag v-if="row.workday_needs_review" size="small" type="warning" effect="plain">待复核</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="自然日" prop="natural_days" min-width="80" align="right" />
        <el-table-column label="锁定" min-width="150">
          <template #default="{ row }">
            <span v-if="row.confirmed_at">{{ row.confirmed_at.slice(0, 16).replace('T', ' ') }}</span>
            <span v-else class="muted">-</span>
            <!-- 解锁过 = 前次导出已作废（决策 A4），列表就要能看出来，
                 不然财务手上那份旧表看起来跟有效表一模一样 -->
            <el-tag v-if="row.unlocked_at" size="small" type="danger" effect="plain">解锁过</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openPeriod(row)">进入工作台</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-hint">
            还没有任何工资批次。<br>
            一个批次 = 一个月的工资，从建批次开始，依次同步考勤、导入社保公积金、计算、复核、锁定。
          </div>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="新建工资批次" width="480px">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="月份" prop="year_month">
          <el-input v-model="form.year_month" placeholder="YYYY-MM，如 2026-03" />
        </el-form-item>
        <el-form-item label="工作日数">
          <el-input-number v-model="form.workday_count" :min="1" :max="31" controls-position="right" style="width: 100%" />
          <div class="hint">
            留空则自动推算（只按周一~五数，<b>不含法定节假日与调休</b>），
            推算出来的值会标「待复核」，进工作台后可改。
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="dialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submit">创建并进入</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { PERIOD_STATUS_ORDER } from '@/api/salary'
import { useSalaryPeriods } from './composables/useSalaryPeriods'

// 筛选下拉的文案。列表行里一律用接口回的 status_label，这份只服务于「还没有数据
// 时也要能选状态」的下拉——不能靠行数据现推。
const STATUS_TEXT = {
  draft: '草稿',
  attendance_synced: '考勤已同步',
  imported: '社保已导入',
  calculated: '已计算',
  reviewing: '复核中',
  confirmed: '已锁定',
}

const STATUS_TAG = {
  draft: 'info',
  attendance_synced: '',
  imported: '',
  calculated: 'warning',
  reviewing: 'warning',
  confirmed: 'success',
}

const {
  loading, list, statusFilter, fetchList,
  dialogVisible, saving, formRef, form, formRules, openCreate, submit,
  openPeriod,
} = useSalaryPeriods()
</script>

<style scoped>
.salary-page { position: relative; }
.salary-aurora { inset: -24px -28px; }
.salary-page .toolbar,
.salary-page .salary-panel { position: relative; z-index: 1; }

.toolbar { margin-bottom: 16px; }
.toolbar-right { display: flex; gap: 8px; justify-content: flex-end; }

.salary-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.salary-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.muted { color: var(--el-text-color-placeholder); }
.hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-top: 4px; }
.empty-hint { padding: 32px 16px; color: var(--el-text-color-secondary); line-height: 1.8; }
</style>
