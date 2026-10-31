<template>
  <div ref="panelRef" class="table-card">
    <FilterBar class="toolbar" :loading="resource.loading.value" @search="search" @reset="reset">
      <el-select v-model="filters.warehouse_id" clearable filterable placeholder="全部仓库" class="filter-w-md">
        <el-option v-for="w in warehouses.data.value" :key="w.id" :value="w.id" :label="w.name" />
      </el-select>
      <SkuPicker v-model="filters.sku_id" :active-only="false" class="filter-w-lg" />
    </FilterBar>
    <ListPageStatus
      :error="warehouses.errorMessage.value"
      :has-data="warehouses.hasData.value"
      @retry="warehouses.load()"
    />
    <div class="action-bar">
      <span>每次显示 20 条{{ mode === 'balances' ? '库存余额' : '流水' }}</span>
      <TableTools
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="columns"
        :fullscreen="isFullscreen"
        :loading="resource.loading.value"
        @refresh="load(offset)"
        @fullscreen="toggleFullscreen"
      />
    </div>
    <ListPageStatus
      :error="resource.errorMessage.value"
      :loading="resource.loading.value"
      :has-data="resource.hasData.value"
      :data-page="offset / 20 + 1"
      @retry="load(attemptedOffset)"
    />
    <el-table
      :data="resource.data.value"
      v-loading="resource.loading.value"
      border
      class="list-table"
      :class="densityClass"
      :max-height="isFullscreen ? undefined : 640"
     v-sticky-scrollbar>
      <el-table-column
        v-for="c in columns.filter(c => visibleKeys.includes(c.key))"
        :key="c.key"
        :prop="c.key"
        :label="c.label"
        min-width="125"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <StatusBadge v-if="c.key === 'quality'" :type="qualityLabels[row.quality]?.type || 'info'">
            {{ qualityLabels[row.quality]?.label || row.quality }}
          </StatusBadge>
          <span v-else-if="c.key === 'kind'">{{ kindLabels[row.kind] || row.kind }}</span>
          <span v-else-if="c.key === 'created_at'">{{ formatBeijingDateTime(row.created_at) }}</span>
          <span v-else>{{ row[c.key] ?? '—' }}</span>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty v-if="!resource.error.value" description="当前条件下没有记录" :image-size="96" />
      </template>
    </el-table>
    <div class="pager">
      <GlassButton
        :disabled="offset === 0 || resource.loading.value"
        left-icon="ArrowLeft"
        @click="load(offset - 20)"
      >
        上一批
      </GlassButton>
      <span>第 {{ offset / 20 + 1 }} 批</span>
      <GlassButton
        :disabled="resource.data.value.length < 20 || resource.loading.value"
        right-icon="ArrowRight"
        @click="load(offset + 20)"
      >
        下一批
      </GlassButton>
    </div>
  </div>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'
import { getBalances, getLedger, getWarehouses } from '@/api/inventory'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import SkuPicker from './components/SkuPicker.vue'
import { qualityLabels, kindLabels } from './labels'
import { formatBeijingDateTime } from '@/utils/datetime'
const props = defineProps({ mode: { type: String, required: true } })
const filters = reactive({ warehouse_id: null, sku_id: null }), applied = ref({}), offset = ref(0)
const warehouses = useAsyncResource(async (_, { signal }) => (await getWarehouses({ signal, suppressToast: true })).data, { initialData: [] })
const resource = useAsyncResource(async (params, { signal }) => (await (props.mode === 'balances' ? getBalances : getLedger)(params, { signal, suppressToast: true })).data, { initialData: [] })
const columns = [{ key: 'warehouse_name', label: '仓库' }, { key: 'product_name', label: '产品' }, { key: 'sku_code', label: 'SKU 编码' }, { key: 'quality', label: '质量状态' }, ...(props.mode === 'balances' ? [{ key: 'on_hand', label: '在手数量' }, { key: 'reserved', label: '预占数量' }, { key: 'available', label: '可售数量' }] : [{ key: 'document_id', label: '单据号' }, { key: 'kind', label: '业务类型' }, { key: 'on_hand_delta', label: '在手变动' }, { key: 'reserved_delta', label: '预占变动' }, { key: 'on_hand_after', label: '变动后在手' }, { key: 'reserved_after', label: '变动后预占' }, { key: 'reason', label: '原因' }, { key: 'created_at', label: '发生时间' }])]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView(`inventory-${props.mode}`, columns)
const attemptedOffset = ref(0)
async function load(next = 0) { attemptedOffset.value = next; if (await resource.load({ ...applied.value, offset: next, limit: 20 })) offset.value = next }
function search() { applied.value = { warehouse_id: filters.warehouse_id || undefined, sku_id: filters.sku_id || undefined }; resource.clear(); offset.value = 0; return load() }
function reset() { filters.warehouse_id = null; filters.sku_id = null; return search() }
onMounted(() => { warehouses.load(); load() })
</script>
