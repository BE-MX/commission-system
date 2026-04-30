<template>
  <div class="date-period-picker">
    <el-date-picker
      v-model="localStartDate"
      type="date"
      placeholder="开始日期"
      value-format="YYYY-MM-DD"
      :disabled-date="disabledDate"
      :disabled="disabled"
      style="width: 150px"
      @change="onStartDateChange"
    />
    <el-select
      v-model="localStartPeriod"
      :disabled="disabled"
      style="width: 80px; margin-left: 4px"
      @change="emitChange"
    >
      <el-option label="上午" value="am" />
      <el-option label="下午" value="pm" />
    </el-select>

    <span class="range-sep">至</span>

    <el-date-picker
      v-model="localEndDate"
      type="date"
      placeholder="结束日期"
      value-format="YYYY-MM-DD"
      :disabled-date="disabledDate"
      :disabled="disabled"
      style="width: 150px"
      @change="onEndDateChange"
    />
    <el-select
      v-model="localEndPeriod"
      :disabled="disabled"
      style="width: 80px; margin-left: 4px"
      @change="emitChange"
    >
      <el-option label="上午" value="am" />
      <el-option label="下午" value="pm" />
    </el-select>

    <span v-if="hasError" class="period-error">同一天内开始时段不能晚于结束时段</span>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  startDate: { type: String, default: '' },
  startPeriod: { type: String, default: 'am' },
  endDate: { type: String, default: '' },
  endPeriod: { type: String, default: 'pm' },
  disabledDate: { type: Function, default: () => false },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:startDate',
  'update:startPeriod',
  'update:endDate',
  'update:endPeriod',
  'change',
])

const localStartDate = ref(props.startDate)
const localStartPeriod = ref(props.startPeriod || 'am')
const localEndDate = ref(props.endDate)
const localEndPeriod = ref(props.endPeriod || 'pm')

watch(() => props.startDate, v => { localStartDate.value = v })
watch(() => props.startPeriod, v => { localStartPeriod.value = v || 'am' })
watch(() => props.endDate, v => { localEndDate.value = v })
watch(() => props.endPeriod, v => { localEndPeriod.value = v || 'pm' })

const hasError = computed(() => {
  if (!localStartDate.value || !localEndDate.value) return false
  if (localStartDate.value !== localEndDate.value) return false
  return localStartPeriod.value === 'pm' && localEndPeriod.value === 'am'
})

function onStartDateChange() {
  if (localStartDate.value && !localEndDate.value) {
    localEndDate.value = localStartDate.value
  }
  emitChange()
}

function onEndDateChange() {
  emitChange()
}

function emitChange() {
  emit('update:startDate', localStartDate.value)
  emit('update:startPeriod', localStartPeriod.value)
  emit('update:endDate', localEndDate.value)
  emit('update:endPeriod', localEndPeriod.value)
  emit('change', {
    startDate: localStartDate.value,
    startPeriod: localStartPeriod.value,
    endDate: localEndDate.value,
    endPeriod: localEndPeriod.value,
  })
}
</script>

<style scoped>
.date-period-picker {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 0;
}
.range-sep {
  margin: 0 8px;
  color: var(--text-muted);
  font-size: 13px;
}
.period-error {
  display: block;
  width: 100%;
  color: var(--color-danger);
  font-size: 12px;
  margin-top: 4px;
}
</style>
