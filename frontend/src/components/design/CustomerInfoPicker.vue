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
      placeholder="输入客户名称或ID搜索"
      style="width: 100%"
      @change="select"
    >
      <el-option
        v-for="item in options"
        :key="item.id"
        :label="`${item.name} · ${item.country || '未知国家'} · ID ${item.id}`"
        :value="normalizeCustomerId(item.id)"
      />
    </el-select>
    <div class="field-hint">客户来自 OKKI customer_info，提交后按客户ID归档素材</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { searchMediaCustomers } from '@/api/customerMedia'
import { normalizeCustomerId } from '@/views/design/appointmentContract'

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
