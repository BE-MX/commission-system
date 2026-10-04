<template>
  <DetailDrawer
    :model-value="modelValue" :title="`额度管理 · ${storeName || ''}`" :width="760"
    @update:model-value="v => $emit('update:modelValue', v)"
  >
    <ListPageStatus :error="quotaResource.errorMessage.value" :loading="quotaLoading" :has-data="quotaResource.hasData.value" @retry="fetchQuota" />
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
      <el-form label-position="top" inline @submit.prevent>
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
    <ListPageStatus v-if="recordsState.hasData.value" :error="recordsState.errorMessage.value" :loading="recordsLoading" :has-data="true" :data-page="recordsState.dataPage.value" @retry="fetchRecords" />
    <el-table :data="records" v-loading="recordsLoading" size="small" border style="width: 100%" class="list-table" v-sticky-scrollbar>
      <template #empty><ListPageStatus :error="recordsState.errorMessage.value" :loading="recordsLoading" @retry="fetchRecords"><el-empty description="暂无变动记录" :image-size="96" /></ListPageStatus></template>
      <el-table-column prop="created_at" label="时间" min-width="150" show-overflow-tooltip />
      <el-table-column label="类型" min-width="100">
        <template #default="{ row }">
          <StatusBadge size="small" :type="row.type === 'recharge' ? 'success' : 'warning'">
            {{ row.type === 'recharge' ? '充值' : '消耗' }}
          </StatusBadge>
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
    <el-pagination :page-sizes="[20, 50, 100]"
      v-model:current-page="page" v-model:page-size="pageSize" :total="total"
      layout="total, sizes, prev, pager, next" class="pager"
      @current-change="handlePageChange" @size-change="handleSizeChange"
    />
  </DetailDrawer>
</template>

<script setup>
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { watchListResourceScope } from '@/composables/useListResourceScope'

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

const quotaResource = useAsyncResource(async (id, { signal }) => id ? (await getStoreQuota(id, { signal, suppressToast: true })).data : null)
const quota = quotaResource.data, quotaLoading = quotaResource.loading
const recordsState = useListPage(async ({ storeId, page, page_size }, { signal }) => storeId ? (await listQuotaRecords(storeId, { offset: (page - 1) * page_size, limit: page_size }, { signal, suppressToast: true })).data : { items: [], total: 0 },
  { searchForm: { storeId: null }, immediate: false })
const { list: records, loading: recordsLoading, total, page, pageSize, handlePageChange, handleSizeChange } = recordsState
watchListResourceScope(recordsState, ['storeId'])

const rechargeForm = reactive({ amount: 100, remark: '' })
const recharging = ref(false)

function fetchQuota() { return quotaResource.load(props.modelValue ? props.storeId : null) }
function fetchRecords() { return recordsState.fetchList() }

async function handleRecharge() {
  if (!rechargeForm.amount || rechargeForm.amount < 1) {
    msgError('充值张数必须大于 0')
    return
  }
  if (recharging.value) return
  const storeId = props.storeId
  recharging.value = true
  try {
    await rechargeQuota(storeId, {
      amount: rechargeForm.amount,
      remark: rechargeForm.remark || null,
    })
    msgSuccess('充值')
    emit('changed')
    if (props.modelValue && props.storeId === storeId) {
      rechargeForm.remark = ''
      await Promise.all([fetchQuota(), recordsState.refreshCreate()])
    }
  } catch { /* 拦截器已提示 */ } finally {
    recharging.value = false
  }
}

// 每次打开（或换门店）重置分页并重新拉取；destroy-on-close 由 DetailDrawer 保证内容不残留
watch(() => [props.modelValue, props.storeId], ([visible, id]) => {
  recordsState.searchForm.storeId = visible ? id : null
  recordsState.handleSearch()
  quotaResource.load(visible ? id : null, { clear: true })
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
