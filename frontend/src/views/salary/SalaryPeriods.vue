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

    <!-- 表格卡片：筛选区 + 操作行 + 表格（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card salary-panel">
      <FilterBar :loading="loading" :pending="pending" @search="search" @reset="resetFilters">
        <el-select v-model="statusFilter" placeholder="全部状态" clearable class="filter-w-sm">
          <el-option v-for="s in PERIOD_STATUS_ORDER" :key="s" :label="STATUS_TEXT[s]" :value="s" />
        </el-select>
        <template #summary><span>最多显示最近 60 个符合条件的批次。</span></template>
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-permission="'salary:write'" variant="primary" left-icon="Plus" @click="openCreate">新建批次</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="periodsResource.error.value && list.length" v-bind="resourceStatus(periodsResource)" @retry="fetchList" />
      <el-table :data="list" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" style="width: 100%">
        <template #empty>
          <ListPageStatus v-bind="resourceStatus(periodsResource)" @retry="fetchList">
          <el-empty :image-size="96" :description="appliedStatus ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="appliedStatus" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
          </ListPageStatus>
        </template>
        <el-table-column v-if="visibleKeys.includes('year-month')" prop="year_month" label="月份" min-width="100" />
        <el-table-column prop="status" v-if="visibleKeys.includes('status')" label="状态" min-width="140">
          <template #default="{ row }">
            <StatusBadge size="small" :value="row.status" :dictionary="SALARY_STATUS" :label="row.status_label" effect="plain" />
          </template>
        </el-table-column>
        <el-table-column prop="workday_count" v-if="visibleKeys.includes('workday-count')" label="工作日数" min-width="130" align="right">
          <template #default="{ row }">
            {{ row.workday_count ?? '-' }}
            <!-- 自动推算只按周一~五数，没扣法定节假日也没加调休。
                 2 月批次的 20 天要是被当成应出基准用，全员缺勤扣款都是错的 -->
            <StatusBadge v-if="row.workday_needs_review" size="small" type="warning" effect="plain">待复核</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('natural-days')" label="自然日" prop="natural_days" min-width="80" align="right" />
        <el-table-column prop="confirmed_at" v-if="visibleKeys.includes('locked')" label="锁定" min-width="150">
          <template #default="{ row }">
            <span v-if="row.confirmed_at">{{ row.confirmed_at.slice(0, 16).replace('T', ' ') }}</span>
            <span v-else class="muted">-</span>
            <!-- 解锁过 = 前次导出已作废（决策 A4），列表就要能看出来，
                 不然财务手上那份旧表看起来跟有效表一模一样 -->
            <StatusBadge v-if="row.unlocked_at" size="small" type="danger" effect="plain">解锁过</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('remark')" prop="remark" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column class-name="table-action-column" label="操作" min-width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openPeriod(row)"><el-icon><Right /></el-icon>进入工作台</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="新建工资批次" width="480px">
      <el-form label-position="top" ref="formRef" :model="form" :rules="formRules">
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
import { SALARY_STATUS, SALARY_STATUS_LABELS as STATUS_TEXT, SALARY_STATUS_TYPES as STATUS_TAG } from './salaryStatus.js'
import { PERIOD_STATUS_ORDER } from '@/api/salary'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { useSalaryPeriods } from './composables/useSalaryPeriods'

// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'year-month', label: '月份' },
  { key: 'status', label: '状态' },
  { key: 'workday-count', label: '工作日数' },
  { key: 'natural-days', label: '自然日' },
  { key: 'locked', label: '锁定' },
  { key: 'remark', label: '备注' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('salary-periods', columnDefs)

// 筛选下拉的文案。列表行里一律用接口回的 status_label，这份只服务于「还没有数据
// 时也要能选状态」的下拉——不能靠行数据现推。




const {
  loading, list, statusFilter, appliedStatus, pending, periodsResource, fetchList, search, resetFilters,
  dialogVisible, saving, formRef, form, formRules, openCreate, submit,
  openPeriod,
} = useSalaryPeriods()

const resourceStatus = resource => ({ error: resource.errorMessage.value, loading: resource.loading.value, hasData: resource.hasLoaded.value, paged: false })
</script>

<style scoped>
.salary-page { position: relative; }
.salary-aurora { inset: -24px -28px; }
.salary-page .salary-panel { position: relative; z-index: 1; }

/* 表格面板玻璃皮肤（scoped 覆盖全局 .table-card 白底）；筛选区/操作行/分页用全局规范类 */
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
</style>
