<template>
  <div class="booking-customer-tags">
    <CustomerTagBoard
      :dimensions="dimensions"
      :tags="customerTags"
      :disabled="!customerId || saving"
      @add="pickerVisible = true"
    />
    <CustomerMediaTagPicker
      v-model="pickerVisible"
      title="为客户添加标签"
      :dimensions="dimensions"
      :available-tags="customerTags"
      :context="{ customerId: customerId }"
      :saving="saving"
      hint="标签属于当前客户，之后创建预约也会自动显示。"
      @save="save"
      @created="onCreated"
      @renamed="onRenamed"
    />
  </div>
</template>

<script setup>import { msgWarning, msgSuccessText } from '@/utils/feedback'
import { onMounted, ref, watch } from 'vue'

import { addCustomerTags, getCustomerTagDimensions, getCustomerTags } from '@/api/customerMedia'
import CustomerTagBoard from './CustomerTagBoard.vue'
import CustomerMediaTagPicker from './CustomerMediaTagPicker.vue'

const props = defineProps({ customerId: { type: [String, Number], default: '' } })
const dimensions = ref([])
const customerTags = ref([])
const pickerVisible = ref(false)
const saving = ref(false)
let loadVersion = 0

onMounted(async () => {
  try { dimensions.value = (await getCustomerTagDimensions()).data || [] } catch { /* API interceptor reports errors */ }
})

watch(() => props.customerId, async customerId => {
  const version = ++loadVersion
  customerTags.value = []
  pickerVisible.value = false
  if (!customerId) return
  try {
    const response = await getCustomerTags(customerId)
    if (version === loadVersion) customerTags.value = response.data || []
  } catch { /* API interceptor reports errors */ }
}, { immediate: true })

async function save({ tags }) {
  if (!props.customerId || !tags.some(item => item.tag_value_ids.length)) {
    msgWarning('请先选择至少一个客户标签')
    return
  }
  const customerId = props.customerId
  saving.value = true
  try {
    const response = await addCustomerTags(customerId, tags)
    if (props.customerId === customerId) {
      customerTags.value = response.data || []
      pickerVisible.value = false
    }
    msgSuccessText('客户标签已保存')
  } finally { saving.value = false }
}

function onCreated({ dimension_id, value }) {
  if (!customerTags.value.some(tag => tag.tag_value_id === value.id)) {
    customerTags.value.push({ dimension_id, tag_value_id: value.id, value: value.value,
      dimension_label: dimensions.value.find(dim => dim.id === dimension_id)?.label || '' })
  }
}
function onRenamed({ id, value }) {
  customerTags.value = customerTags.value.map(tag => tag.tag_value_id === id ? { ...tag, value } : tag)
}
</script>

<style scoped>
.booking-customer-tags { margin: 0 0 24px; }
</style>
