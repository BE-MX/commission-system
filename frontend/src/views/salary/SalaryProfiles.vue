<!--
  员工薪资档案（M1）。标记/样式照 system/DictManagement.vue，
  分页/搜索/排序编排照 expo/ExpoLeads.vue（宪法 14）。
  身份证与银行卡在列表与详情里只出脱敏串——明文永不过前端。
-->
<template>
  <div class="salary-page">
    <div class="salary-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 表格卡片：筛选区 + 操作行 + 表格 + 分页（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card salary-panel">
      <FilterBar  class="toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value" @search="handleSearch" @reset="handleReset"><el-input
          v-model="searchForm.keyword" placeholder="搜索姓名 / 工号 / 岗位" clearable
          prefix-icon="Search" class="filter-w-lg"
        />
<el-select v-model="searchForm.dept_detail" placeholder="明细部门" clearable class="filter-w-sm" >
          <el-option v-for="d in deptOptions" :key="d.id" :label="d.dept_detail" :value="d.dept_detail" />
        </el-select>
<el-select v-model="searchForm.status" placeholder="在职状态" clearable class="filter-w-sm" >
          <el-option label="在职" value="active" />
          <el-option label="离职" value="left" />
        </el-select>
</FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-permission="'salary:write'" variant="primary" left-icon="Plus" @click="openCreate">新增档案</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listPageState.hasData.value" :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="fetchList" />
<el-table
        :data="list" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" style="width: 100%"
        :default-sort="{ prop: sortField, order: sortOrder === 'desc' ? 'descending' : 'ascending' }"
        @sort-change="handleSortChange" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('emp-no')" prop="emp_no" label="工号" min-width="80" sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="姓名" min-width="90" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('dept-detail')" prop="dept_detail" label="明细部门" min-width="110" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('dept-group')" label="汇总大部门" min-width="110" prop="dept_group" sortable="custom">
          <template #default="{ row }">
            <StatusBadge v-if="row.dept_group" size="small" effect="plain">{{ row.dept_group }}</StatusBadge>
            <span v-else class="muted">未映射</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('position')" prop="position" label="岗位" min-width="110" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('grade')" label="职级" min-width="130" show-overflow-tooltip prop="grade_code" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.grade_code">{{ schemeLabels[row.grade_scheme] || row.grade_scheme }} · {{ row.grade_code }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('base-salary')" label="生效底薪" min-width="100" align="right" prop="base_salary_effective" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.base_salary_effective !== null && row.base_salary_effective !== undefined">
              <!-- 后端 Decimal 经 JSON 变 float，3500.00 会显示成 3500；工资域分位必须留住 -->
              {{ money(row.base_salary_effective) }}
              <StatusBadge v-if="row.base_salary_override !== null && row.base_salary_override !== undefined" size="small" type="warning" effect="plain">定薪</StatusBadge>
            </span>
            <!-- 底薪推不出来 = 算薪时会报异常，这里就要红着提醒 HR 去补 -->
            <StatusBadge v-else size="small" type="danger" effect="plain">待补</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('hire-date')" prop="hire_date" label="入职日期" min-width="110" sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('bank-card')" prop="bank_card_masked" sortable="custom" label="银行卡" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.bank_card_masked || '-' }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="150" prop="status" sortable="custom">
          <template #default="{ row }">
            <StatusBadge :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="plain">
              {{ row.status === 'active' ? '在职' : '离职' }}
            </StatusBadge>
            <StatusBadge v-if="!row.payroll_included" size="small" type="info" effect="plain">不参与工资表</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="100" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'salary:write'" variant="link" left-icon="Edit" @click="openEdit(row)">编辑</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑员工档案' : '新增员工档案'" width="760px" top="6vh">
      <el-form label-position="top" ref="formRef" :model="form" :rules="formRules">
        <el-divider content-position="left">基本信息</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="工号" prop="emp_no">
              <el-input v-model="form.emp_no" :disabled="isEdit" placeholder="3 与 003 会归一成同一个工号" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="姓名" prop="name"><el-input v-model="form.name" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="明细部门">
              <el-select v-model="form.dept_detail" filterable allow-create clearable placeholder="选择或输入" style="width: 100%">
                <el-option v-for="d in deptOptions" :key="d.id" :label="d.dept_detail" :value="d.dept_detail" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="岗位"><el-input v-model="form.position" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="大部门覆盖">
              <el-input v-model="form.dept_group_override" placeholder="留空按部门映射推导" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="在职状态">
              <el-select v-model="form.status" style="width: 100%">
                <el-option label="在职" value="active" />
                <el-option label="离职" value="left" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="入职日期" label-width="90px">
              <el-date-picker v-model="form.hire_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="转正日期" label-width="90px">
              <el-date-picker v-model="form.regular_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="离职日期" label-width="90px">
              <el-date-picker v-model="form.leave_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">薪资口径</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="职级赛道">
              <el-select v-model="form.grade_scheme" clearable style="width: 100%" @change="form.grade_code = ''">
                <el-option v-for="s in schemeOptions" :key="s.value" :label="s.label" :value="s.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="职级">
              <el-select v-model="form.grade_code" clearable :disabled="!gradeCodeOptions.length" style="width: 100%">
                <el-option v-for="g in gradeCodeOptions" :key="g.value" :label="g.label" :value="g.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="手动定薪">
              <el-input-number v-model="form.base_salary_override" :min="0" :precision="2" controls-position="right" style="width: 100%" />
              <div class="hint">填了就盖过职级表；空着按职级表取</div>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="试用期薪资">
              <el-input-number v-model="form.probation_salary" :min="0" :precision="2" controls-position="right" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="试用期说明"><el-input v-model="form.probation_note" placeholder="如：前 3 个月 80%" /></el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="保底工资" label-width="90px">
              <el-input-number v-model="form.guaranteed_salary" :min="0" :precision="2" controls-position="right" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="保底起" label-width="80px">
              <el-date-picker v-model="form.guaranteed_from" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="保底止" label-width="80px">
              <el-date-picker v-model="form.guaranteed_to" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">发放与参保</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="身份证">
              <el-input
                v-model="form.id_card" :disabled="clearIdCard"
                :placeholder="isEdit ? '留空表示不修改' : '入库即加密，页面不再回显'"
              />
              <!-- 没有这个开关，录错后只能覆盖成另一个值、永远清不掉 -->
              <el-checkbox v-if="isEdit" v-model="clearIdCard" class="pii-clear">清除已存的身份证</el-checkbox>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="银行卡">
              <el-input
                v-model="form.bank_card" :disabled="clearBankCard"
                :placeholder="isEdit ? '留空表示不修改' : '入库即加密，页面不再回显'"
              />
              <el-checkbox v-if="isEdit" v-model="clearBankCard" class="pii-clear">清除已存的银行卡</el-checkbox>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="开户行"><el-input v-model="form.bank_name" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="参保主体"><el-input v-model="form.insurance_entity" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="参与工资表">
              <el-switch v-model="form.payroll_included" :active-value="1" :inactive-value="0" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="参与公积金">
              <el-switch v-model="form.fund_included" :active-value="1" :inactive-value="0" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="手机号"><el-input v-model="form.mobile" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="钉钉 userid"><el-input v-model="form.dingtalk_userid" /></el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="dialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submit">保存</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { money } from '@/api/salary'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { useSalaryProfiles } from './composables/useSalaryProfiles'

// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'emp-no', label: '工号' },
  { key: 'name', label: '姓名' },
  { key: 'dept-detail', label: '明细部门' },
  { key: 'dept-group', label: '汇总大部门' },
  { key: 'position', label: '岗位' },
  { key: 'grade', label: '职级' },
  { key: 'base-salary', label: '生效底薪' },
  { key: 'hire-date', label: '入职日期' },
  { key: 'bank-card', label: '银行卡' },
  { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('salary-profiles', columnDefs)

const listPageState = useSalaryProfiles()
const {
  loading, list, total, page, pageSize, searchForm, fetchList,
  handleSearch, handleReset, handlePageChange, handleSizeChange,
  sortField, sortOrder, handleSortChange,
  deptOptions, gradeCodeOptions, schemeOptions, schemeLabels,
  clearIdCard, clearBankCard,
  dialogVisible, saving, isEdit, formRef, form, formRules,
  openCreate, openEdit, submit,
} = listPageState

const hasActiveFilters = computed(() => Boolean(searchForm.keyword || searchForm.dept_detail || searchForm.status))
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

.salary-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.salary-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.salary-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

.muted { color: var(--el-text-color-placeholder); }
/* 清除开关是破坏性操作，压在输入框下方、字号收小，不跟主输入抢注意力 */
.pii-clear { margin-top: 4px; font-size: 12px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.4; margin-top: 2px; }
</style>
