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
        <el-row :gutter="16" class="toolbar">
          <el-col :span="6">
            <el-select v-model="schemeFilter" placeholder="全部赛道" clearable style="width: 100%">
              <el-option v-for="s in schemeOptions" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
          </el-col>
          <el-col :span="18" class="toolbar-right">
            <GlassButton v-permission="'salary:write'" variant="primary" left-icon="Plus" @click="openGrade(null)">新增职级行</GlassButton>
          </el-col>
        </el-row>

        <div class="table-card salary-panel">
          <el-table :data="filteredGrades" v-loading="loading" border class="list-table" style="width: 100%">
            <el-table-column label="赛道" min-width="130">
              <template #default="{ row }">{{ schemeLabels[row.scheme] || row.scheme }}</template>
            </el-table-column>
            <el-table-column prop="grade_code" label="职级" min-width="80" sortable />
            <el-table-column label="底薪 / 标准工资" min-width="130" align="right">
              <template #default="{ row }">{{ money(salaryOf(row)) }}</template>
            </el-table-column>
            <el-table-column prop="perf_target_monthly" label="月业绩目标($)" min-width="130" align="right" sortable />
            <el-table-column prop="perf_full" label="绩效满额" min-width="100" align="right" />
            <el-table-column prop="new_sign_min" label="新签下限(单)" min-width="110" align="right" />
            <el-table-column label="团队提成率" min-width="100" align="right">
              <template #default="{ row }">{{ row.team_rate !== null && row.team_rate !== undefined ? `${(row.team_rate * 100).toFixed(2)}%` : '-' }}</template>
            </el-table-column>
            <el-table-column prop="effective_from" label="生效日" min-width="110" sortable />
            <el-table-column label="失效日" min-width="110">
              <template #default="{ row }">
                <span v-if="row.effective_to">{{ row.effective_to }}</span>
                <el-tag v-else size="small" type="success" effect="plain">现行</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="100" fixed="right">
              <template #default="{ row }">
                <GlassButton v-permission="'salary:write'" variant="link" left-icon="Edit" @click="openGrade(row)">编辑</GlassButton>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- 计算参数 -->
      <el-tab-pane label="计算参数" name="params">
        <div class="table-card salary-panel">
          <el-table :data="params" v-loading="loading" border class="list-table" style="width: 100%">
            <el-table-column prop="param_key" label="参数键" min-width="200" show-overflow-tooltip />
            <el-table-column label="参数值" min-width="160">
              <template #default="{ row }">
                <el-input v-if="editingParamId === row.id" v-model="paramDraft.param_value" size="small" />
                <strong v-else>{{ row.param_value }}</strong>
              </template>
            </el-table-column>
            <el-table-column prop="value_type" label="类型" min-width="80" />
            <el-table-column prop="category" label="分类" min-width="100" />
            <el-table-column label="用途说明" min-width="280" show-overflow-tooltip>
              <template #default="{ row }">
                <el-input v-if="editingParamId === row.id" v-model="paramDraft.description" size="small" />
                <span v-else>{{ row.description || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="effective_from" label="生效日" min-width="110" />
            <el-table-column label="操作" min-width="150" fixed="right">
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
        <el-row :gutter="16" class="toolbar">
          <el-col :span="24" class="toolbar-right">
            <GlassButton v-permission="'salary:write'" variant="primary" left-icon="Plus" @click="openDept(null)">新增映射</GlassButton>
          </el-col>
        </el-row>
        <div class="table-card salary-panel">
          <el-table :data="deptMappings" v-loading="loading" border class="list-table" style="width: 100%">
            <el-table-column prop="dept_detail" label="明细部门" min-width="160" sortable />
            <el-table-column label="汇总大部门" min-width="160">
              <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.dept_group }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="sort_order" label="排序" min-width="80" sortable />
            <el-table-column label="操作" min-width="100" fixed="right">
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
import { useSalaryRules } from './composables/useSalaryRules'

const {
  activeTab, loading,
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

.salary-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.salary-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.salary-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

.tip { margin-top: 16px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.4; margin-top: 2px; }
</style>
