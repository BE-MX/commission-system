<template>
  <div class="outcome-grid">
    <el-form-item label="本次结果">
      <el-select v-model="form.result_code" clearable placeholder="可留空" class="full">
        <el-option v-for="result in results" :key="result" :label="result" :value="result" />
      </el-select>
    </el-form-item>
    <el-form-item label="事实来源">
      <el-select v-model="form.evidence_kind" clearable placeholder="可留空" class="full">
        <el-option label="客户明确说" value="customer" /><el-option label="我的判断" value="assessment" />
      </el-select>
    </el-form-item>
  </div>
  <el-form-item label="主要障碍">
    <el-select v-model="form.obstacles" multiple clearable collapse-tags collapse-tags-tooltip placeholder="可多选" class="full">
      <el-option v-for="obstacle in obstacles" :key="obstacle" :label="obstacle" :value="obstacle" />
    </el-select>
  </el-form-item>
  <template v-if="shareable">
    <el-form-item label="共享接手摘要">
      <el-input v-model="form.shared_summary" type="textarea" maxlength="500" placeholder="仅填可在协作范围内共享的要点" />
    </el-form-item>
    <el-form-item v-if="progress">
      <el-checkbox v-model="form.effective_progress">本次有有效推进</el-checkbox>
    </el-form-item>
  </template>
  <el-form-item v-if="stage" label="更新当前开发进度">
    <el-select v-model="form.development_stage" clearable placeholder="保留当前进度" class="full">
      <el-option v-for="(label, value) in DEVELOPMENT_STAGE" :key="value" :label="label" :value="value" />
    </el-select>
  </el-form-item>
</template>

<script setup>
import { computed } from 'vue'
import { DEVELOPMENT_STAGE } from '../customerOverview'

const props = defineProps({
  form: { type: Object, required: true }, shareable: Boolean, stage: Boolean, progress: Boolean, dicts: Object,
})
const results = computed(() => [...new Set([...(props.dicts?.domestic_followup_result || ['未接通', '未回复', '有效沟通', '已报价', '已寄样', '客户拒绝']), props.form.result_code].filter(Boolean))])
const obstacles = computed(() => [...new Set([...(props.dicts?.domestic_followup_obstacle || ['价格', '产品适配', '采购时机', '决策人', '已有供应商', '信任不足', '其他']), ...(props.form.obstacles || [])])])
</script>

<style scoped>
.outcome-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.full { width: 100%; }
</style>
