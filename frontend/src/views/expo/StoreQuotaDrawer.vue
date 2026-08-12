<template>
  <DetailDrawer
    :model-value="modelValue" :title="`额度管理 · ${storeName || ''}`" :width="680"
    @update:model-value="v => $emit('update:modelValue', v)"
  >
    <div v-loading="quotaLoading" class="quota-cards">
      <div class="quota-card">
        <div class="quota-num">{{ quota?.total_quota ?? '-' }}</div>
        <div class="quota-label">累计充值</div>
      </div>
      <div class="quota-card">
        <div class="quota-num">{{ quota?.used_quota ?? '-' }}</div>
        <div class="quota-label">已使用</div>
      </div>
      <div class="quota-card" :class="{ 'is-zero': quota && quota.remaining === 0 }">
        <div class="quota-num">{{ quota?.remaining ?? '-' }}</div>
        <div class="quota-label">剩余可用</div>
      </div>
    </div>

    <div v-permission="'expo_store:recharge'" class="recharge-card">
      <div class="block-title">充值</div>
      <el-form inline @submit.prevent>
        <el-form-item label="张数">
          <el-input-number v-model="rechargeForm.amount" :min="1" :max="100000" controls-position="right" style="width: 130px" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="rechargeForm.remark" maxlength="255" placeholder="如：8月展会充值" style="width: 200px" />
        </el-form-item>
        <el-form-item>
          <GlassButton variant="primary" :loading="recharging" @click="handleRecharge">确认充值</GlassButton>
        </el-form-item>
      </el-form>
    </div>

    <div class="block-title">变动记录</div>
    <el-table :data="records" v-loading="recordsLoading" size="small" border style="width: 100%" class="list-table">
      <el-table-column prop="created_at" label="时间" min-width="150" show-overflow-tooltip />
      <el-table-column label="类型" min-width="76">
        <template #default="{ row }">
          <el-tag size="small" :type="row.type === 'recharge' ? 'success' : 'warning'">
            {{ row.type === 'recharge' ? '充值' : '消耗' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="张数" min-width="80" align="right">
        <template #default="{ row }">
          <span :class="row.amount > 0 ? 'amt-plus' : 'amt-minus'">{{ row.amount > 0 ? '+' : '' }}{{ row.amount }}</span>
        </template>
      </el-table-column>
      <el-table-column label="变动前 → 后" min-width="110">
        <template #default="{ row }">{{ row.balance_before }} → {{ row.balance_after }}</template>
      </el-table-column>
      <el-table-column label="操作人" min-width="90" show-overflow-tooltip>
        <template #default="{ row }">{{ row.operator_name || `#${row.operator_user_id}` }}</template>
      </el-table-column>
      <el-table-column label="备注" min-width="110" show-overflow-tooltip>
        <template #default="{ row }">{{ row.remark || '-' }}</template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page" v-model:page-size="pageSize" :total="total"
      layout="total, prev, pager, next" class="pager"
      @current-change="fetchRecords"
    />
  </DetailDrawer>
</template>

<script setup>
/**
 * 门店额度抽屉：余额三卡 + 充值表单（expo_store:recharge）+ 变动流水。
 * 由 StoreManagement 以 storeId/storeName 驱动，打开时拉取快照与第一页流水。
 */
import { reactive, ref, watch } from 'vue'
import { getStoreQuota, rechargeQuota, listQuotaRecords } from '@/api/expo'
import { msgSuccess, msgError } from '@/utils/feedback'
import DetailDrawer from '@/components/DetailDrawer.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  storeId: { type: Number, default: null },
  storeName: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const quota = ref(null)
const quotaLoading = ref(false)
const records = ref([])
const recordsLoading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const rechargeForm = reactive({ amount: 100, remark: '' })
const recharging = ref(false)

async function fetchQuota() {
  quotaLoading.value = true
  try {
    const res = await getStoreQuota(props.storeId)
    quota.value = res.data
  } finally {
    quotaLoading.value = false
  }
}

async function fetchRecords() {
  recordsLoading.value = true
  try {
    const res = await listQuotaRecords(props.storeId, {
      offset: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    })
    const data = res.data || {}
    records.value = data.items || []
    total.value = data.total || 0
  } finally {
    recordsLoading.value = false
  }
}

async function handleRecharge() {
  if (!rechargeForm.amount || rechargeForm.amount < 1) {
    msgError('充值张数必须大于 0')
    return
  }
  recharging.value = true
  try {
    await rechargeQuota(props.storeId, {
      amount: rechargeForm.amount,
      remark: rechargeForm.remark || null,
    })
    msgSuccess('充值')
    rechargeForm.remark = ''
    await Promise.all([fetchQuota(), fetchRecords()])
    emit('changed')
  } catch { /* 拦截器已提示 */ } finally {
    recharging.value = false
  }
}

// 每次打开（或换门店）重置分页并重新拉取；destroy-on-close 由 DetailDrawer 保证内容不残留
watch(() => [props.modelValue, props.storeId], ([visible, id]) => {
  if (!visible || !id) return
  page.value = 1
  fetchQuota()
  fetchRecords()
}, { immediate: true })
</script>

<style scoped>
.quota-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px; }
.quota-card {
  background: var(--toolbar-bg); border: 1px solid var(--border-color);
  border-radius: var(--card-radius); padding: 14px 16px; text-align: center;
}
.quota-num { font-size: 24px; font-weight: 700; color: var(--text-primary); }
.quota-card.is-zero .quota-num { color: var(--color-danger-text, #c0392b); }
.quota-label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
.recharge-card {
  border: 1px dashed var(--border-color); border-radius: var(--card-radius);
  padding: 12px 16px 0; margin-bottom: 16px;
}
.block-title { font-weight: 600; color: var(--text-primary); margin-bottom: 10px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.amt-plus { color: var(--color-success-text, #1e8449); font-weight: 600; }
.amt-minus { color: var(--color-gold-muted, #b8860b); font-weight: 600; }
</style>
