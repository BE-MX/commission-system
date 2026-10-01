<!--
  薪资规则配置（M1）：职级薪级表 / 计算参数 / 部门映射。
  这三张表是 M3 计算引擎的口径来源，改一个数字就会改变全员工资，
  所以每处都标注了用途，且改口径的正确做法是新建生效日版本而非原地覆盖。
-->
<template>
  <div class="salary-page">
    <div class="salary-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-tabs v-model="activeTab" class="rules-tabs">
      <!-- 职级薪级表 -->
      <el-tab-pane label="职级薪级表" name="grades">
        <div ref="gradePanelRef" class="table-card salary-panel">
          <div class="toolbar">
            <el-select v-model="schemeFilter" placeholder="全部赛道" clearable class="filter-w-sm">
              <el-option v-for="s in schemeOptions" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
            <GlassButton variant="secondary" left-icon="RefreshLeft" @click="schemeFilter = ''">重置</GlassButton>
          </div>
          <div class="action-bar">
            <GlassButton v-permission="'salary:write'" variant="primary" left-icon="Plus" @click="openGrade(null)">新增职级行</GlassButton>
            <TableTools v-model:visible-keys="gradeVisibleKeys" v-model:density="gradeDensity" :columns="gradeColumnDefs" :fullscreen="gradeIsFullscreen" @refresh="fetchAll" @fullscreen="toggleGradeFullscreen" />
          </div>
          <el-table :data="filteredGrades" v-loading="loading" border class="list-table" :class="gradeDensityClass" :max-height="gradeIsFullscreen ? undefined : 640">
            <el-table-column v-if="gradeVisibleKeys.includes('scheme')" label="赛道" min-width="130">
              <template #default="{ row }">{{ schemeLabels[row.scheme] || row.scheme }}</template>
            </el-table-column>
            <el-table-column v-if="gradeVisibleKeys.includes('grade')" prop="grade_code" label="职级" min-width="80" sortable />
            <el-table-column v-if="gradeVisibleKeys.includes('salary')" label="底薪 / 标准工资" min-width="130" align="right">
              <template #default="{ row }">{{ money(salaryOf(row)) }}</template>
            </el-table-column>
            <el-table-column v-if="gradeVisibleKeys.includes('target')" prop="perf_target_monthly" label="月业绩目标($)" min-width="130" align="right" sortable />
            <el-table-column v-if="gradeVisibleKeys.includes('perf')" prop="perf_full" label="绩效满额" min-width="100" align="right" />
            <el-table-column v-if="gradeVisibleKeys.includes('new-sign')" prop="new_sign_min" label="新签下限(单)" min-width="110" align="right" />
            <el-table-column v-if="gradeVisibleKeys.includes('rate')" label="团队提成率" min-width="100" align="right">
              <template #default="{ row }">{{ row.team_rate !== null && row.team_rate !== undefined ? `${(row.team_rate * 100).toFixed(2)}%` : '-' }}</template>
            </el-table-column>
            <el-table-column v-if="gradeVisibleKeys.includes('effective')" prop="effective_from" label="生效日" min-width="110" sortable />
            <el-table-column v-if="gradeVisibleKeys.includes('expires')" label="失效日" min-width="110">
              <template #default="{ row }">
                <span v-if="row.effective_to">{{ row.effective_to }}</span>
                <el-tag v-else size="small" type="success" effect="plain">现行</el-tag>
              </template>
            </el-table-column>
            <el-table-column class-name="table-action-column" label="操作" min-width="100" fixed="right">
              <template #default="{ row }">
                <GlassButton v-permission="'salary:write'" variant="link" left-icon="Edit" @click="openGrade(row)">编辑</GlassButton>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- 计算参数 -->
      <el-tab-pane label="计算参数" name="params">
        <div ref="paramPanelRef" class="table-card salary-panel">
          <div class="action-bar">
            <TableTools v-model:visible-keys="paramVisibleKeys" v-model:density="paramDensity" :columns="paramColumnDefs" :fullscreen="paramIsFullscreen" @refresh="fetchAll" @fullscreen="toggleParamFullscreen" />
          </div>
          <el-table :data="params" v-loading="loading" border class="list-table" :class="paramDensityClass" :max-height="paramIsFullscreen ? undefined : 640">
            <el-table-column v-if="paramVisibleKeys.includes('key')" prop="param_key" label="参数键" min-width="200" show-overflow-tooltip />
            <el-table-column v-if="paramVisibleKeys.includes('value')" label="参数值" min-width="160">
              <template #default="{ row }">
                <el-input v-if="editingParamId === row.id" v-model="paramDraft.param_value" size="small" />
                <strong v-else>{{ row.param_value }}</strong>
              </template>
            </el-table-column>
            <el-table-column v-if="paramVisibleKeys.includes('type')" prop="value_type" label="类型" min-width="80" />
            <el-table-column v-if="paramVisibleKeys.includes('category')" prop="category" label="分类" min-width="100" />
            <el-table-column v-if="paramVisibleKeys.includes('description')" label="用途说明" min-width="280" show-overflow-tooltip>
              <template #default="{ row }">
                <el-input v-if="editingParamId === row.id" v-model="paramDraft.description" size="small" />
                <span v-else>{{ row.description || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column v-if="paramVisibleKeys.includes('effective')" prop="effective_from" label="生效日" min-width="110" />
            <el-table-column class-name="table-action-column" label="操作" min-width="150" fixed="right">
              <template #default="{ row }">
                <template v-if="editingParamId === row.id">
                  <GlassButton variant="link" left-icon="Check" @click="saveParam(row)">保存</GlassButton>
                  <GlassButton variant="link" left-icon="Close" @click="cancelEditParam">取消</GlassButton>
                </template>
                <GlassButton v-else v-permission="'salary:write'" variant="link" left-icon="Edit" @click="startEditParam(row)">修改</GlassButton>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <el-alert
          class="tip" type="warning" :closable="false" show-icon
          title="full_month_days（31）与 mid_month_weight_base（30）是两个不同用途的参数，不是笔误"
          description="前者是满月员工的应出天数基准（出勤折算用），后者是月中调薪/转正时底薪按天加权的基数（只用于底薪加权）。口径以表内「说明」列为准。改任何一个都会改变全员实发，改前请先在测试期次复算比对。"
        />
      </el-tab-pane>

      <!-- 部门映射 -->
      <el-tab-pane label="部门映射" name="depts">
        <div ref="deptPanelRef" class="table-card salary-panel">
          <div class="action-bar">
            <GlassButton v-permission="'salary:write'" variant="primary" left-icon="Plus" @click="openDept(null)">新增映射</GlassButton>
            <TableTools v-model:visible-keys="deptVisibleKeys" v-model:density="deptDensity" :columns="deptColumnDefs" :fullscreen="deptIsFullscreen" @refresh="fetchAll" @fullscreen="toggleDeptFullscreen" />
          </div>
          <el-table :data="deptMappings" v-loading="loading" border class="list-table" :class="deptDensityClass" :max-height="deptIsFullscreen ? undefined : 640">
            <el-table-column v-if="deptVisibleKeys.includes('detail')" prop="dept_detail" label="明细部门" min-width="160" sortable />
            <el-table-column v-if="deptVisibleKeys.includes('group')" label="汇总大部门" min-width="160">
              <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.dept_group }}</el-tag></template>
            </el-table-column>
            <el-table-column v-if="deptVisibleKeys.includes('sort')" prop="sort_order" label="排序" min-width="80" sortable />
            <el-table-column class-name="table-action-column" label="操作" min-width="100" fixed="right">
              <template #default="{ row }">
                <GlassButton v-permission="'salary:write'" variant="link" left-icon="Edit" @click="openDept(row)">编辑</GlassButton>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <el-alert
          class="tip" type="info" :closable="false" show-icon
          title="个别管理岗不随部门走"
          description="例如跟单1部多数人归后综部，但业务总监归业务部。这类例外在员工档案里填「大部门覆盖」，不要为一个人再拆一个明细部门。"
        />
      </el-tab-pane>
    </el-tabs>

    <!-- 职级行编辑 -->
    <el-dialog v-model="gradeDialog" title="职级薪级行" width="620px">
      <el-form ref="gradeFormRef" :model="gradeForm" :rules="gradeRules" label-width="120px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="赛道" prop="scheme">
              <el-select v-model="gradeForm.scheme" style="width: 100%">
                <el-option v-for="s in schemeOptions" :key="s.value" :label="s.label" :value="s.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="职级编码" prop="grade_code"><el-input v-model="gradeForm.grade_code" placeholder="如 P1 / M2 / F3" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="底薪">
              <el-input-number v-model="gradeForm.base_salary" :min="0" :precision="2" controls-position="right" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="标准工资">
              <el-input-number v-model="gradeForm.std_salary" :min="0" :precision="2" controls-position="right" style="width: 100%" />
              <div class="hint">管理岗填这栏，其余赛道填底薪</div>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="月业绩目标($)">
              <el-input-number v-model="gradeForm.perf_target_monthly" :min="0" :precision="2" controls-position="right" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="绩效满额">
              <el-input-number v-model="gradeForm.perf_full" :min="0" :precision="2" controls-position="right" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="新签下限(单)">
              <el-input-number v-model="gradeForm.new_sign_min" :min="0" controls-position="right" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="团队提成率">
              <el-input-number v-model="gradeForm.team_rate" :min="0" :max="1" :precision="4" :step="0.001" controls-position="right" style="width: 100%" />
              <div class="hint">小数，0.001 = 0.1%</div>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="生效日" prop="effective_from">
              <el-date-picker v-model="gradeForm.effective_from" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="失效日">
              <el-date-picker v-model="gradeForm.effective_to" type="date" value-format="YYYY-MM-DD" style="width: 100%" placeholder="留空 = 现行" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-alert
          type="info" :closable="false"
          title="改口径请新建生效日版本：同一 (赛道, 职级, 生效日) 会被覆盖，历史期次按当时口径复算才追得回来。"
        />
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="gradeDialog = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="gradeSaving" @click="submitGrade">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 部门映射编辑 -->
    <el-dialog v-model="deptDialog" title="部门映射" width="460px">
      <el-form ref="deptFormRef" :model="deptForm" :rules="deptRules" label-width="110px">
        <el-form-item label="明细部门" prop="dept_detail"><el-input v-model="deptForm.dept_detail" /></el-form-item>
        <el-form-item label="汇总大部门" prop="dept_group"><el-input v-model="deptForm.dept_group" placeholder="如 业务部 / 后综部" /></el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="deptForm.sort_order" :min="0" :max="9999" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="deptDialog = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="deptSaving" @click="submitDept">保存</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { money } from '@/api/salary'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { useSalaryRules } from './composables/useSalaryRules'

const gradeColumnDefs = [
  { key: 'scheme', label: '赛道' }, { key: 'grade', label: '职级' },
  { key: 'salary', label: '底薪 / 标准工资' }, { key: 'target', label: '月业绩目标($)' },
  { key: 'perf', label: '绩效满额' }, { key: 'new-sign', label: '新签下限(单)' },
  { key: 'rate', label: '团队提成率' }, { key: 'effective', label: '生效日' },
  { key: 'expires', label: '失效日' },
]
const paramColumnDefs = [
  { key: 'key', label: '参数键' }, { key: 'value', label: '参数值' },
  { key: 'type', label: '类型' }, { key: 'category', label: '分类' },
  { key: 'description', label: '用途说明' }, { key: 'effective', label: '生效日' },
]
const deptColumnDefs = [
  { key: 'detail', label: '明细部门' }, { key: 'group', label: '汇总大部门' },
  { key: 'sort', label: '排序' },
]
const {
  density: gradeDensity, densityClass: gradeDensityClass, visibleKeys: gradeVisibleKeys,
  panelRef: gradePanelRef, isFullscreen: gradeIsFullscreen, toggleFullscreen: toggleGradeFullscreen,
} = useTableView('salary-rules-grades', gradeColumnDefs)
const {
  density: paramDensity, densityClass: paramDensityClass, visibleKeys: paramVisibleKeys,
  panelRef: paramPanelRef, isFullscreen: paramIsFullscreen, toggleFullscreen: toggleParamFullscreen,
} = useTableView('salary-rules-params', paramColumnDefs)
const {
  density: deptDensity, densityClass: deptDensityClass, visibleKeys: deptVisibleKeys,
  panelRef: deptPanelRef, isFullscreen: deptIsFullscreen, toggleFullscreen: toggleDeptFullscreen,
} = useTableView('salary-rules-depts', deptColumnDefs)

const {
  activeTab, loading, fetchAll,
  params, deptMappings,
  schemeFilter, filteredGrades, salaryOf, schemeOptions, schemeLabels,
  gradeDialog, gradeSaving, gradeFormRef, gradeForm, gradeRules, openGrade, submitGrade,
  editingParamId, paramDraft, startEditParam, cancelEditParam, saveParam,
  deptDialog, deptSaving, deptFormRef, deptForm, deptRules, openDept, submitDept,
} = useSalaryRules()
</script>

<style scoped>
.salary-page { position: relative; }
.salary-aurora { inset: -24px -28px; }
.salary-page .rules-tabs { position: relative; z-index: 1; }


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

.tip { margin-top: 16px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.4; margin-top: 2px; }
</style>
