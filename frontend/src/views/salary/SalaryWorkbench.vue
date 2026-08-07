<!--
  工资批次工作台（M2-f）。一个月的工资从考勤到锁定都在这一页。

  版面顺序是有意的：**异常清单在最上面，动作按钮在最下面。**
  反过来（先给「下一步」再列异常）等于邀请 HR 在没看异常的情况下往下走，
  而异常清单正是「该不该往下走」的唯一依据。
-->
<template>
  <div class="salary-page" v-loading="loading">
    <div class="salary-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 批次头：月份 / 状态 / 关键基数。基数放在最显眼处是因为 due_days
         是所有缺勤扣款的分母，错了整批都错，而它错的时候看不出来 -->
    <div class="salary-panel head" v-if="period">
      <div class="head-main">
        <GlassButton variant="ghost" left-icon="ArrowLeft" @click="$router.push('/salary/periods')">
          批次列表
        </GlassButton>
        <h2>{{ period.year_month }} 工资批次</h2>
        <el-tag :type="STATUS_TAG[period.status] || 'info'" effect="plain">
          {{ period.status_label }}
        </el-tag>
        <el-tag v-if="period.unlocked_at" type="danger" effect="plain">
          解锁过，前次导出已作废
        </el-tag>
      </div>

      <div class="head-facts">
        <div class="fact">
          <span class="fact-label">工作日数</span>
          <span class="fact-value">
            {{ period.workday_count ?? '未设置' }}
            <el-tag v-if="period.workday_needs_review" size="small" type="warning" effect="plain">
              待复核
            </el-tag>
            <el-button v-if="writable" v-permission="'salary:write'" link type="primary"
                       @click="openWorkdayEdit">改</el-button>
          </span>
          <!-- 自动值只按周一~五数，没扣法定节假日也没加调休。这个数是月中
               入离职人员缺勤扣款的分母，2 月批次要是照抄 20 天，全员算错 -->
          <span class="fact-hint">{{ period.workday_source_label || '—' }}</span>
        </div>
        <div class="fact">
          <span class="fact-label">自然日</span>
          <span class="fact-value">{{ period.natural_days }}</span>
          <span class="fact-hint">满月应出按规则参数取，不等于自然日</span>
        </div>
        <div class="fact">
          <span class="fact-label">发薪名单</span>
          <span class="fact-value">{{ anomalies?.payroll_headcount ?? '—' }} 人</span>
          <span class="fact-hint">在职且计发薪的人数</span>
        </div>
      </div>
    </div>

    <!-- 异常清单。ready_to_calculate 由后端算，前端不自己数 blocking_count -->
    <div class="salary-panel section" v-if="anomalies">
      <div class="section-head">
        <h3>异常清单</h3>
        <el-tag v-if="anomalies.ready_to_calculate" type="success" effect="dark">
          可以计算
        </el-tag>
        <el-tag v-else type="danger" effect="dark">
          还有 {{ anomalies.blocking_count }} 项必须处理
        </el-tag>
        <span class="section-hint" v-if="anomalies.info_count">
          另有 {{ anomalies.info_count }} 项提示，核对无误可忽略
        </span>
      </div>

      <div v-if="!anomalies.items?.length" class="empty-hint">
        没有异常。考勤、社保、公积金都齐了，可以往下走。
      </div>
      <template v-else>
        <div class="kind-chips">
          <el-tag v-for="k in anomalies.by_kind" :key="k.kind"
                  :type="k.severity === 'blocking' ? 'danger' : 'info'"
                  effect="plain" class="kind-chip"
                  @click="kindFilter = kindFilter === k.kind ? '' : k.kind">
            {{ k.kind_label }} {{ k.count }}
          </el-tag>
          <el-button v-if="kindFilter" link type="primary" @click="kindFilter = ''">
            显示全部
          </el-button>
        </div>
        <el-table :data="filteredAnomalies" border class="list-table" max-height="380">
          <el-table-column label="严重度" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="dark"
                      :type="row.severity === 'blocking' ? 'danger' : 'info'">
                {{ row.severity === 'blocking' ? '必须处理' : '提示' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="kind_label" label="类型" width="140" />
          <el-table-column prop="message" label="问题" min-width="260" show-overflow-tooltip />
          <!-- 每条异常都带 action：只报告问题不给下一步，等于把活推回给用户 -->
          <el-table-column prop="action" label="怎么处理" min-width="280" show-overflow-tooltip />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <!-- 记录级异常的处理场所在明细表（action 文案也这么写），其余去考勤页 -->
              <el-button v-if="row.employee_id" link type="primary"
                         @click="jumpToAnomaly(row)">
                {{ RECORD_LEVEL_KINDS.includes(row.kind) ? '去明细表' : '去考勤页' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>

    <!-- 考勤 / 导入 / 时间线 / 工资明细 -->
    <div class="salary-panel section">
      <el-tabs v-model="activeTab">
        <!-- 明细放最前：算完薪之后 HR 的活儿都在这张表上 -->
        <el-tab-pane label="工资明细" name="records">
          <div class="tab-toolbar">
            <el-input v-model="recordsKeyword" placeholder="按姓名/工号搜索" clearable
                      style="width: 200px" @change="fetchRecords()" />
            <span v-if="records.truncated" class="section-hint">
              结果过多只显示了前一部分，请用搜索缩小范围
            </span>
            <span class="grow" />
            <GlassButton v-if="canCalculate" v-permission="'salary:write'" variant="primary"
                         left-icon="Cpu" :loading="calculating" @click="doCalculate">
              计算工资
            </GlassButton>
          </div>
          <SalaryRecordsGrid :records="records" :loading="recordsLoading"
                             :status="period?.status || ''" :editable="recordsEditable"
                             :save-manual="saveManual" />
        </el-tab-pane>

        <el-tab-pane label="考勤" name="attendance">
          <div class="tab-toolbar">
            <el-input v-model="attendanceKeyword" placeholder="按姓名搜索" clearable
                      style="width: 200px" @change="fetchAttendance" />
            <el-checkbox v-model="attendanceOnlyPending" @change="fetchAttendance">
              只看请假小时没录的
            </el-checkbox>
            <span class="grow" />
            <span class="section-hint" v-if="attendance.pending_manual_count">
              {{ attendance.pending_manual_count }} 人的事假/病假还没录
            </span>
            <GlassButton v-if="writable" v-permission="'salary:write'" variant="primary"
                         left-icon="Refresh" :loading="syncing" @click="doSync">
              从钉钉同步
            </GlassButton>
          </div>

          <!-- 钉钉给不了这五列（那几列没有 column id），所以事假/病假只能人工录。
               这不是暂时状态，是接口的硬约束，得在界面上说明白 -->
          <el-alert v-if="lastSync?.missing_leave_columns?.length" type="warning"
                    :closable="false" class="tab-alert">
            钉钉接口取不到这几列：{{ lastSync.missing_leave_columns.join('、') }}。
            事假与病假小时只能在下表里人工录入——留空会被当成「还没录」，
            那一行的实出天数和全勤都算不出来。
          </el-alert>

          <el-table :data="attendance.items" border class="list-table" max-height="460">
            <el-table-column prop="emp_no" label="工号" width="80" />
            <el-table-column prop="name" label="姓名" width="90" />
            <el-table-column label="应出" width="80" align="right">
              <template #default="{ row }">
                <!-- 钉值优先于规则推导（后端引擎同样优先取它），星号 + tooltip 标明 -->
                <el-tooltip v-if="row.due_days_manual !== null && row.due_days_manual !== undefined"
                            content="手动钉值，引擎优先采用" placement="top">
                  <span>{{ money(row.due_days_manual) }}*</span>
                </el-tooltip>
                <template v-else>{{ money(row.due_days) }}</template>
              </template>
            </el-table-column>
            <el-table-column label="实出" width="80" align="right">
              <template #default="{ row }">
                <span v-if="row.actual_days !== null">{{ money(row.actual_days) }}</span>
                <el-tooltip v-else content="请假小时没录，算不出实出天数">
                  <span class="warn">待录入</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="事假(h)" width="86" align="right">
              <template #default="{ row }">{{ hours(row.personal_leave_hours) }}</template>
            </el-table-column>
            <el-table-column label="病假(h)" width="86" align="right">
              <template #default="{ row }">{{ hours(row.sick_leave_hours) }}</template>
            </el-table-column>
            <el-table-column label="年假" width="70" align="right">
              <template #default="{ row }">{{ money(row.annual_leave_days) }}</template>
            </el-table-column>
            <el-table-column label="迟到" prop="late_count" width="60" align="right" />
            <el-table-column label="早退" prop="early_leave_count" width="60" align="right" />
            <el-table-column label="漏卡" prop="miss_punch_count" width="60" align="right" />
            <el-table-column label="旷工" width="70" align="right">
              <template #default="{ row }">{{ money(row.absent_count) }}</template>
            </el-table-column>
            <el-table-column label="全勤" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="row.full_attendance ? 'success' : 'info'" effect="plain">
                  {{ row.full_attendance ? '是' : '否' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <el-button v-if="writable" v-permission="'salary:write'" link type="primary"
                           @click="openEditAttendance(row)">录入</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div class="empty-hint">还没有考勤数据。点「从钉钉同步」开始。</div>
            </template>
          </el-table>

          <!-- 没绑钉钉的人考勤永远是空的，必须逐个点名。放在表下面而不是塞进
               告警数组：这批人不处理，M3 会把他们当全勤发钱 -->
          <el-alert v-if="attendance.unbound?.length" type="error" :closable="false"
                    class="tab-alert">
            {{ attendance.unbound.length }} 人没绑钉钉 userid，考勤永远拉不到：
            {{ attendance.unbound.map(u => u.name).join('、') }}。
            请到员工档案补绑定后重新同步，确实不打卡的人直接手工录入。
          </el-alert>
        </el-tab-pane>

        <el-tab-pane label="社保 / 公积金" name="imports">
          <div class="import-grid">
            <div v-for="kind in IMPORT_KINDS" :key="kind.value" class="import-card">
              <div class="import-head">
                <h4>{{ kind.label }}</h4>
                <!-- show-list=false：导入结果由下面的统计块渲染，不需要文件名列表。
                     uploadFn 直接把 File 交给 doImport，成功与否由它自己弹窗说明 -->
                <AppUpload v-if="writable" :upload-fn="f => runImport(kind.value, f)"
                           accept=".xls,.xlsx" :show-list="false" :max-size-mb="20"
                           button-text="导入 Excel">
                  <GlassButton v-permission="'salary:write'" variant="ghost"
                               left-icon="Upload" :loading="importing === kind.value">
                    导入 Excel
                  </GlassButton>
                </AppUpload>
              </div>
              <div v-if="imports[kind.value]?.total" class="import-stats">
                <div><span>行数</span><b>{{ imports[kind.value].total }}</b></div>
                <div><span>已匹配</span><b>{{ imports[kind.value].match_counts?.matched ?? 0 }}</b></div>
                <div :class="{ bad: imports[kind.value].match_counts?.unmatched }">
                  <span>未匹配</span><b>{{ imports[kind.value].match_counts?.unmatched ?? 0 }}</b>
                </div>
                <div :class="{ bad: imports[kind.value].match_counts?.duplicate }">
                  <span>身份证撞号</span><b>{{ imports[kind.value].match_counts?.duplicate ?? 0 }}</b>
                </div>
                <div>
                  <span>进工资表合计</span>
                  <b>{{ money(imports[kind.value].personal_total_matched) }}</b>
                </div>
                <!-- 全量合计是拿来跟 Excel 合计行核的：两个数一致才说明文件读全了，
                     而它跟上面那个的差额就是「没匹配上档案的人的社保没扣」 -->
                <div>
                  <span>源表全量合计</span>
                  <b>{{ money(imports[kind.value].personal_total_all) }}</b>
                </div>
              </div>
              <div v-else class="empty-hint small">还没导入。</div>
            </div>
          </div>
          <el-alert type="info" :closable="false" class="tab-alert">
            导入后请拿「源表全量合计」跟 Excel 的合计行核一次。
            只核已匹配的合计对不出「文件没问题但有 8 个人没匹配上档案」这种情况，
            而没匹配上就等于这几个人的社保没扣。
          </el-alert>
        </el-tab-pane>

        <el-tab-pane label="操作记录" name="events">
          <el-timeline v-if="events.length" class="events">
            <el-timeline-item v-for="e in events" :key="e.id"
                              :timestamp="e.created_at?.slice(0, 19).replace('T', ' ')"
                              placement="top">
              <div class="event-line">
                <b>{{ e.event_label || e.event_type }}</b>
                <span v-if="e.from_status_label || e.to_status_label" class="muted">
                  {{ e.from_status_label || '—' }} → {{ e.to_status_label || '—' }}
                </span>
                <span v-if="e.operator_name" class="muted">{{ e.operator_name }}</span>
              </div>
              <div v-if="e.reason" class="event-reason">原因：{{ e.reason }}</div>
            </el-timeline-item>
          </el-timeline>
          <div v-else class="empty-hint">还没有操作记录。</div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 动作区放最后：往下走之前先看过上面的异常清单 -->
    <div class="salary-panel section actions" v-if="period">
      <div class="actions-main">
        <template v-for="step in period.next_steps" :key="step.status">
          <GlassButton
            :variant="step.endpoint === 'confirm' ? 'primary' : 'ghost'"
            :loading="stepping === step.status"
            @click="doStep(step)"
          >{{ step.label }}</GlassButton>
        </template>
        <GlassButton v-if="period.status === 'confirmed'" v-permission="'salary:admin'"
                     variant="ghost" left-icon="Unlock" @click="unlockVisible = true">
          解锁批次
        </GlassButton>
        <span v-if="!period.next_steps?.length && period.status !== 'confirmed'" class="muted">
          当前状态没有可执行的下一步。
        </span>
      </div>
      <div class="actions-hint" v-if="anomalies && !anomalies.ready_to_calculate">
        还有必须处理的异常。带着它们往下走，算出来的工资是错的——
        而少扣的钱不会有人来投诉。
      </div>
    </div>

    <!-- 工作日数 -->
    <el-dialog v-model="workdayEditing" title="修改工作日数" width="420px">
      <el-form label-width="100px">
        <el-form-item label="工作日数">
          <el-input-number v-model="workdayDraft" :min="1" :max="31"
                           controls-position="right" style="width: 100%" />
        </el-form-item>
      </el-form>
      <div class="hint">
        这个数是<b>月中入离职人员</b>缺勤扣款的分母。自动值只按周一~五数，
        没扣法定节假日、也没加回调休上班的周末，遇到春节国庆月份必须手工改。
      </div>
      <template #footer>
        <GlassButton variant="ghost" @click="workdayEditing = false">取消</GlassButton>
        <GlassButton variant="primary" @click="saveWorkday">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 人工录入考勤。口径说明跟着输入框一起放在组件里 -->
    <AttendanceEntryDialog
      :row="editRow" :draft="editDraft" :saving="editSaving"
      @save="saveAttendance" @close="editRow = null"
    />

    <!-- 解锁 -->
    <el-dialog v-model="unlockVisible" title="解锁批次" width="480px">
      <el-alert type="warning" :closable="false" class="tab-alert">
        解锁后<b>前次导出的工资表作废</b>，重新导出会打作废水印。
        财务手上那份旧表和新表长得一样，所以原因必须写清楚，供事后对账。
      </el-alert>
      <el-form label-width="80px">
        <el-form-item label="原因" required>
          <el-input v-model="unlockReason" type="textarea" :rows="3"
                    placeholder="例：3 月社保基数导错，需重算 12 人" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="unlockVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="unlocking" @click="doUnlock">
          确认解锁
        </GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import AppUpload from '@/components/AppUpload.vue'
import { money } from '@/api/salary'
import AttendanceEntryDialog from './components/AttendanceEntryDialog.vue'
import SalaryRecordsGrid from './components/SalaryRecordsGrid.vue'
import { RECORD_LEVEL_KINDS, useSalaryWorkbench } from './composables/useSalaryWorkbench'
import { useSalaryRecords } from './composables/useSalaryRecords'

const STATUS_TAG = {
  draft: 'info',
  attendance_synced: '',
  imported: '',
  calculated: 'warning',
  reviewing: 'warning',
  confirmed: 'success',
}

const IMPORT_KINDS = [
  { value: 'insurance', label: '社保' },
  { value: 'fund', label: '公积金' },
]

// 小时数单独一个格式化：请假小时的 null 是「还没录」，0 是「没请假」。
// 两者都渲染成 0 的话，异常清单里那条「请假小时未录」在表上看不出对应哪一行。
function hours(v) {
  if (v === null || v === undefined || v === '') return '待录入'
  return money(v)
}

const {
  periodId, loading, period, writable, activeTab, refreshAll,
  anomalies, events, kindFilter, filteredAnomalies, jumpToAnomaly,
  workdayEditing, workdayDraft, openWorkdayEdit, saveWorkday,
  attendance, attendanceKeyword, attendanceOnlyPending, fetchAttendance,
  syncing, lastSync, doSync,
  editRow, editDraft, editSaving, openEditAttendance, saveAttendance,
  imports, importing, doImport,
  stepping, doStep,
  unlockVisible, unlockReason, unlocking, doUnlock,
} = useSalaryWorkbench()

// 工资明细（M3-f）：计算按钮 + 22 列明细表。逻辑全在 composable / 表格组件里，
// 这里只做装配，本文件行数有 500 的硬上限
const {
  records, recordsKeyword, recordsLoading, fetchRecords,
  canCalculate, calculating, doCalculate,
  recordsEditable, saveManual,
} = useSalaryRecords({ periodId, period, activeTab, refreshAll })

// AppUpload 会把 uploadFn 的返回值展开进 modelValue，而导入没有落盘产物、
// 整个响应体展开进去毫无意义。这里吞掉返回值——show-list=false，那份列表不渲染，
// 导入结果由 doImport 自己弹窗 + 下面的统计块负责。
async function runImport(kind, file) {
  await doImport(kind, file)
  return {}
}
</script>

<style scoped>
.salary-page { position: relative; }
.salary-aurora { inset: -24px -28px; }
.salary-page > .salary-panel { position: relative; z-index: 1; }

.salary-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  padding: 16px;
}
.section { margin-top: 16px; }

.head-main { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.head-main h2 { margin: 0; font-size: 20px; }

.head-facts { display: flex; gap: 32px; margin-top: 14px; flex-wrap: wrap; }
.fact { display: flex; flex-direction: column; gap: 2px; }
.fact-label { font-size: 12px; color: var(--el-text-color-secondary); }
.fact-value { font-size: 18px; display: flex; align-items: center; gap: 6px; }
.fact-hint { font-size: 12px; color: var(--el-text-color-placeholder); }

.section-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.section-head h3 { margin: 0; font-size: 16px; }
.section-hint { font-size: 12px; color: var(--el-text-color-secondary); }

.kind-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.kind-chip { cursor: pointer; }

.tab-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.grow { flex: 1; }
.tab-alert { margin-top: 12px; }

.import-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.import-card {
  border: 1px solid var(--dash-glass-border);
  border-radius: 10px;
  padding: 14px;
}
.import-head { display: flex; align-items: center; justify-content: space-between; }
.import-head h4 { margin: 0; font-size: 15px; }
.import-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 12px; }
.import-stats div { display: flex; justify-content: space-between; font-size: 13px; }
.import-stats span { color: var(--el-text-color-secondary); }
.import-stats .bad b { color: var(--el-color-danger); }

.actions { display: flex; flex-direction: column; gap: 8px; }
.actions-main { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.actions-hint { font-size: 12px; color: var(--el-color-danger); }

.events { padding-left: 4px; }
.event-line { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.event-reason { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }

.muted { color: var(--el-text-color-placeholder); font-size: 13px; }
.warn { color: var(--el-color-warning); }
.hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.7; }
.empty-hint { padding: 24px 12px; color: var(--el-text-color-secondary); line-height: 1.8; }
.empty-hint.small { padding: 12px 0; }

.salary-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}
</style>
