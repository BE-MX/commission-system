<!--
  单人考勤人工录入（M2-f）。

  拆成独立组件不只是为了给工作台减行数：这个对话框是**事假/病假小时的唯一入口**
  （钉钉那五列没有 column id，接口根本取不到），口径说明必须跟输入框待在一起。
  说明散到别处，HR 就会把「没请假」填成留空，那一行的实出天数和全勤都算不出来。

  v-model 收的是草稿对象，父组件负责逐字段比对后只提交改动过的字段——
  整行 spread 会把未编辑的 null 变成显式清空，把刚录的病假抹掉。
-->
<template>
  <el-dialog :model-value="!!row" :title="`录入考勤 — ${row?.name || ''}`" width="520px"
             @update:model-value="v => !v && emit('close')">
    <el-form label-width="110px">
      <el-form-item label="事假(小时)">
        <el-input-number v-model="draft.personal_leave_hours" :min="0" :precision="2"
                         controls-position="right" style="width: 100%" />
      </el-form-item>
      <el-form-item label="病假(小时)">
        <el-input-number v-model="draft.sick_leave_hours" :min="0" :precision="2"
                         controls-position="right" style="width: 100%" />
      </el-form-item>
      <el-form-item label="年假(天)">
        <el-input-number v-model="draft.annual_leave_days" :min="0" :precision="2"
                         controls-position="right" style="width: 100%" />
      </el-form-item>
      <el-form-item label="年假余额(天)">
        <el-input-number v-model="draft.annual_leave_remain" :min="0" :precision="2"
                         controls-position="right" style="width: 100%" />
      </el-form-item>

      <el-divider content-position="left">
        <span class="divider-text">以下钉钉能取到，权限没开通时才需手填</span>
      </el-divider>

      <el-form-item label="迟到(次)">
        <el-input-number v-model="draft.late_count" :min="0"
                         controls-position="right" style="width: 100%" />
      </el-form-item>
      <el-form-item label="早退(次)">
        <el-input-number v-model="draft.early_leave_count" :min="0"
                         controls-position="right" style="width: 100%" />
      </el-form-item>
      <el-form-item label="漏打卡(次)">
        <el-input-number v-model="draft.miss_punch_count" :min="0"
                         controls-position="right" style="width: 100%" />
      </el-form-item>
      <el-form-item label="旷工(天)">
        <el-input-number v-model="draft.absent_count" :min="0" :precision="2"
                         controls-position="right" style="width: 100%" />
      </el-form-item>

      <el-divider content-position="left">
        <span class="divider-text">特殊口径，平时别动</span>
      </el-divider>

      <!-- 应出钉值是这个对话框里唯一跟「请假小时」无关的字段：规则复原不了的
           应出天数（月中入职 21.75 那种）只能靠人钉，引擎拿不到这个数 -->
      <el-form-item label="应出天数钉值">
        <el-input-number v-model="draft.due_days_manual" :min="0.01" :max="31" :precision="2"
                         controls-position="right" style="width: 100%"
                         placeholder="留空 = 按规则推导" />
        <div class="field-hint">
          规则复原不了才钉（如李晓雨 3 月 21.75 天）；平时留空，清空保存即恢复按规则推导。
        </div>
      </el-form-item>
    </el-form>

    <div class="hint">
      <b>没请假就填 0，不要留空。</b>留空的含义是「还没录」——那一行的实出天数和全勤
      都算不出来，会一直挂在异常清单里挡住计算。<br>
      事假破全勤；病假超上限破全勤；<b>年假不破全勤</b>。改完立刻重判，不用再点别的按钮。
    </div>

    <template #footer>
      <GlassButton variant="ghost" @click="emit('close')">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" @click="emit('save')">保存</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
defineProps({
  row: { type: Object, default: null },
  draft: { type: Object, required: true },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['save', 'close'])
</script>

<style scoped>
.hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.7; }
.field-hint { font-size: 12px; color: var(--el-text-color-placeholder); line-height: 1.5; margin-top: 4px; }
.divider-text { font-size: 12px; color: var(--el-text-color-placeholder); }
</style>
