<template>
  <el-link type="primary" class="customer-sync-link" @click="open">
    搜索不到客户？点击这里同步最新客户信息
  </el-link>
  <el-dialog v-model="visible" title="从 OKKI 同步客户信息" width="480px" append-to-body>
    <div class="customer-sync-tip">
      客户资料来自 OKKI 定期同步，新客户或负责人变更可能有延迟。输入 OKKI 中的客户公司名称，立即拉取该客户最新资料。
    </div>
    <el-input
      v-model="companyName"
      maxlength="256"
      clearable
      placeholder="客户公司名称（Company Name）"
      @keyup.enter="submit"
    />
    <el-alert
      v-if="result"
      class="customer-sync-result"
      type="success"
      :closable="false"
      show-icon
    >
      <template #title>{{ result.message }}</template>
      <div class="customer-sync-detail">客户：{{ result.company_name }}（ID {{ result.company_id }}）</div>
      <div v-if="result.country_name" class="customer-sync-detail">国家/地区：{{ result.country_name }}</div>
      <div class="customer-sync-detail">
        负责人：{{ result.owner_names?.length ? result.owner_names.join('、') : '公海（暂无负责人）' }}
      </div>
    </el-alert>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button v-if="result" type="primary" :loading="applying" @click="apply">选用该客户</el-button>
      <el-button v-else type="primary" :loading="loading" @click="submit">同步</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useInvoiceCustomerSync } from '../composables/useInvoiceCustomerSync'

// onSelect(syncResult) → bool：由编辑器按当前私海筛选尝试选中，返回是否选用成功
const props = defineProps({
  onSelect: { type: Function, required: true },
})

const { visible, companyName, loading, result, open, submit } = useInvoiceCustomerSync()
const applying = ref(false)

async function apply() {
  if (!result.value) return
  applying.value = true
  try {
    if (await props.onSelect(result.value)) visible.value = false
  } finally {
    applying.value = false
  }
}
</script>

<style scoped>
.customer-sync-link {
  margin-top: 4px;
  font-size: 12px;
}

.customer-sync-tip {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.customer-sync-result {
  margin-top: 14px;
}

.customer-sync-detail {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.6;
}
</style>
