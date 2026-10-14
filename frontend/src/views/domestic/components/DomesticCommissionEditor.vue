<template>
  <div class="commission-editor">
    <div v-for="(row, index) in modelValue" :key="index" class="commission-row">
      <el-select :model-value="row.user_id" filterable placeholder="选择提成业务员" :aria-label="`提成业务员 ${index + 1}`" @update:model-value="patch(index, { user_id: $event })">
        <el-option v-if="row.user_id && !owners.some(owner => owner.value === row.user_id)" :value="row.user_id" :label="row.user_name || '已停用业务员'" disabled />
        <el-option v-for="owner in owners" :key="owner.value" :label="owner.label" :value="owner.value" :disabled="modelValue.some((other, n) => n !== index && other.user_id === owner.value)" />
      </el-select>
      <el-input-number :model-value="Number(row.rate) * 100" :min="0.01" :max="100" :precision="2" :step="1" :aria-label="`提成率 ${index + 1}（百分比）`" @update:model-value="patch(index, { rate: $event == null ? '' : ($event / 100).toFixed(4) })" />
      <span>%</span>
      <GlassButton variant="link" link-tone="danger" :aria-label="`移除提成业务员 ${index + 1}`" @click="remove(index)">移除</GlassButton>
    </div>
    <GlassButton v-if="modelValue.length < 2" variant="link" left-icon="Plus" @click="add">添加业务员</GlassButton>
    <p class="commission-hint">{{ commissionSummary(namedRows) }}</p>
    <p class="commission-hint">调整仅影响之后新建的订单，已有订单保留原分配。</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { commissionSummary } from '../domesticCommission'

const props = defineProps({ modelValue: { type: Array, required: true }, owners: { type: Array, default: () => [] } })
const emit = defineEmits(['update:modelValue'])
const namedRows = computed(() => props.modelValue.map(row => ({ ...row,
  user_name: props.owners.find(owner => owner.value === row.user_id)?.label || row.user_name,
})))
function patch(index, change) { emit('update:modelValue', props.modelValue.map((row, n) => n === index ? { ...row, ...change } : row)) }
function remove(index) { emit('update:modelValue', props.modelValue.filter((_, n) => n !== index)) }
function add() { emit('update:modelValue', [...props.modelValue, { user_id: null, rate: props.modelValue.length ? '0.0100' : '0.0400' }]) }
</script>

<style scoped>
.commission-editor { width: 100%; }
.commission-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.commission-row .el-select { flex: 1; min-width: 150px; }
.commission-hint { margin: 4px 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
</style>
