<template>
  <el-form :model="modelValue" label-width="100px">
    <!-- 基本信息 -->
    <div class="form-section">
      <h4>基本信息</h4>
      <el-form-item label="标题" required>
        <el-input v-model="modelValue.title" placeholder="一句话概括案例" maxlength="100" show-word-limit />
      </el-form-item>
      <el-form-item label="客户名称">
        <el-input v-model="modelValue.customer_name" placeholder="可选" />
      </el-form-item>
      <el-form-item label="客户国家">
        <el-input v-model="modelValue.customer_country" placeholder="如: 美国、英国" />
      </el-form-item>
      <el-form-item label="客户类型">
        <el-select v-model="modelValue.customer_type" placeholder="选择客户类型" style="width: 100%">
          <el-option v-for="t in CUSTOMER_TYPES" :key="t" :label="t" :value="t" />
        </el-select>
      </el-form-item>
      <el-form-item label="沟通渠道">
        <el-select v-model="modelValue.communication_channel" placeholder="选择沟通渠道" style="width: 100%">
          <el-option v-for="c in CHANNELS" :key="c" :label="c" :value="c" />
        </el-select>
      </el-form-item>
      <el-form-item label="沟通时段">
        <el-input v-model="modelValue.communication_period" placeholder="如: 2026-05-01 至 2026-05-03" />
      </el-form-item>
      <el-form-item label="总回合数">
        <el-input-number v-model="modelValue.total_rounds" :min="1" :max="100" placeholder="整数" />
      </el-form-item>
      <el-form-item label="最终结果">
        <el-select v-model="modelValue.final_result" placeholder="选择结果" style="width: 100%">
          <el-option v-for="r in RESULTS" :key="r" :label="r" :value="r" />
        </el-select>
      </el-form-item>
      <el-form-item label="背调状态">
        <el-select v-model="modelValue.background_check_status" placeholder="选择背调状态" style="width: 100%">
          <el-option v-for="s in BG_STATUSES" :key="s" :label="s" :value="s" />
        </el-select>
      </el-form-item>
    </div>

    <!-- 场景与过程 -->
    <div class="form-section">
      <h4>场景与过程</h4>
      <el-form-item label="场景背景" required>
        <el-input v-model="modelValue.scenario" type="textarea" :rows="3" placeholder="客户背景 / 遇到的问题" maxlength="1000" show-word-limit />
      </el-form-item>
      <el-form-item label="做了什么" required>
        <el-input v-model="modelValue.what_was_done" type="textarea" :rows="4" placeholder="详细执行过程" maxlength="3000" show-word-limit />
      </el-form-item>
      <el-form-item label="结果" required>
        <el-input v-model="modelValue.result" type="textarea" :rows="2" placeholder="最终达成什么结果" maxlength="1000" show-word-limit />
      </el-form-item>
    </div>

    <!-- 标签与分享 -->
    <div class="form-section">
      <h4>标签与分享</h4>
      <el-form-item label="标签">
        <el-checkbox-group v-model="modelValue.tags">
          <el-checkbox v-for="t in TAGS" :key="t" :value="t" :label="t" />
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="分享人">
        <el-input v-model="modelValue.share_person" placeholder="留空将使用当前用户" />
      </el-form-item>
      <el-form-item label="分享日期">
        <el-date-picker v-model="modelValue.share_date" type="date" value-format="YYYY-MM-DD" placeholder="默认今日" style="width: 100%" />
      </el-form-item>
    </div>
  </el-form>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  isEdit: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const TAGS = ['开发跟进', '谈判技巧', '定制流程', '物流处理', '纠纷解决', '竞品应对']
const CUSTOMER_TYPES = ['沙龙', '品牌', '电商', '批发', '影视', '其他']
const CHANNELS = ['WhatsApp', '阿里TM', 'Email', 'Instagram', '其他']
const RESULTS = ['成交', '未成交', '谈判中', '流失']
const BG_STATUSES = ['有wiki记录', '无历史背调']

const modelValue = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})
</script>

<style scoped>
.form-section { margin-bottom: 20px; }
.form-section h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
  margin: 0 0 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-color, #f0ece5);
}
</style>
