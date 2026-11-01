<template>
  <el-dialog :model-value="visible" title="人工核对出库同步" width="480px" append-to-body
    :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy"
    @update:model-value="$emit('update:visible', $event)" @open="reset">
    <p class="review-target">出库单：{{ row?.outbound_no || row?.outbound_record_id }}</p>
    <el-form ref="formRef" label-position="top" :model="form" :rules="rules" @submit.prevent>
      <el-form-item label="处理方式" prop="resolution">
        <el-radio-group v-model="form.resolution" class="review-options">
          <el-radio value="confirm_not_created">确认未生成</el-radio>
          <el-radio value="bind_existing">绑定已存在的小满出库单</el-radio>
        </el-radio-group>
        <p class="review-hint">{{ hint }}</p>
      </el-form-item>
      <el-form-item label="核对依据" prop="reason">
        <el-input v-model="form.reason" type="textarea" :rows="3" maxlength="300" show-word-limit
          placeholder="写明你在小满看到的结果，例如：已在小满出库单页面核对，本次同步未改动明细" />
      </el-form-item>
    </el-form>
    <template #footer>
      <GlassButton :disabled="busy" @click="$emit('update:visible', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="busy" @click="submit">确认提交</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'

import GlassButton from '@/components/GlassButton.vue'

defineProps({ visible: Boolean, busy: Boolean, row: Object })
const emit = defineEmits(['update:visible', 'submit'])

const formRef = ref(null)
const form = reactive({ resolution: 'confirm_not_created', reason: '' })
const rules = {
  resolution: [{ required: true, message: '请选择处理方式', trigger: 'change' }],
  reason: [{ validator: (_, value, callback) => {
    const text = String(value || '').trim()
    callback(text.length < 8 ? new Error('请填写至少 8 个字的核对依据') : undefined)
  }, trigger: 'blur' }],
}
const hint = computed(() => form.resolution === 'confirm_not_created'
  ? '小满出库单没有被本次同步改动时选择。提交后释放订单锁，再重新预览并同步。'
  : '小满出库单已按本次同步改好时选择。系统会读取小满原单核对，一致才完成。')

function reset() {
  form.resolution = 'confirm_not_created'
  form.reason = ''
  formRef.value?.clearValidate()
}

async function submit() {
  if (!await formRef.value?.validate().catch(() => false)) return
  emit('submit', { resolution: form.resolution, reason: form.reason.trim() })
}
</script>

<style scoped>
.review-target { margin: 0 0 12px; color: var(--text-secondary); }
.review-options { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.review-hint { margin: 4px 0 0; color: var(--text-secondary); font-size: 13px; line-height: 1.5; }
</style>
