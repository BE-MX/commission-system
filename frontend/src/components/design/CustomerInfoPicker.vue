<template>
  <div class="customer-picker">
    <el-select
      v-model="customerId"
      filterable
      remote
      reserve-keyword
      clearable
      :remote-method="search"
      :loading="loading"
      placeholder="输入客户名称或联系人名称搜索"
      style="width: 100%"
      @change="select"
    >
      <el-option
        v-for="item in options"
        :key="item.id"
        :label="formatCustomerOptionLabel(item)"
        :value="normalizeCustomerId(item.id)"
      />
    </el-select>
    <div class="field-hint">客户来自 OKKI，提交后将关联到所选客户</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { searchMediaCustomers } from '@/api/customerMedia'
import { formatCustomerOptionLabel, normalizeCustomerId } from '@/views/design/appointmentContract'

const customerId = defineModel({ type: String, default: '' })
const emit = defineEmits(['select'])
const options = ref([])
const loading = ref(false)
let timer

function search(keyword) {
  window.clearTimeout(timer)
  if (!keyword?.trim()) { options.value = []; return }
  timer = window.setTimeout(async () => {
    loading.value = true
    try { options.value = (await searchMediaCustomers(keyword.trim())).data || [] }
    finally { loading.value = false }
  }, 250)
}

function select(id) {
  const normalizedId = normalizeCustomerId(id)
  emit('select', options.value.find(item => normalizeCustomerId(item.id) === normalizedId) || null)
}
</script>
