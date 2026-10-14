<template>
  <DetailDrawer :model-value="modelValue" :title="`库存详情 · ${row?.outbound_no || ''}`" width="960px"
    :loading="loading" @update:model-value="$emit('update:modelValue', $event)">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="details">
      <div class="inventory-heading">
        <div><strong>{{ details.record.customer_name }}</strong><p>目标仓库：{{ details.warehouse_name || details.warehouse_id || '待确认' }}</p></div>
        <div class="inventory-summary">
          <StatusBadge :type="details.shortage_count ? 'danger' : 'success'">缺货 {{ details.shortage_count }} 项</StatusBadge>
          <StatusBadge v-if="details.unknown_count" type="warning">待核对 {{ details.unknown_count }} 项</StatusBadge>
        </div>
      </div>
      <el-alert title="库存来自小满同步镜像，每项标明更新时间。缺口按目标仓库可用库存计算，实存中可能有占用；数量沿用原单单位。" type="info" :closable="false" show-icon />
      <p v-if="details.record.record_source === 'okki' || ['done', 'skipped', 'awaiting_sync'].includes(details.record.outbound_state)" class="inventory-note">已生成出库单或正在等待镜像同步：这里对照该单数量与当前库存。该单可能已占用或扣减库存，显示缺口不代表需要重复补货或重新出库。</p>
      <p v-else-if="['running', 'uncertain'].includes(details.record.outbound_state)" class="inventory-note">出库正在处理或结果待核对，可能已占用库存。此处缺口仅供核对，请先确认原任务结果。</p>
      <p v-else class="inventory-note">待出库任务：缺货和待核对项优先展示；库存满足后仍由原出库流程核对生成。</p>
      <div class="inventory-tools">
        <el-checkbox v-model="onlyIssues">只看缺货 / 待核对</el-checkbox>
        <small>查询时间：{{ formatBeijingDateTime(details.queried_at) }}</small>
      </div>
      <el-table :data="visibleItems" border class="list-table" v-sticky-scrollbar>
        <template #empty><el-empty :image-size="64" description="当前没有缺货或待核对项" /></template>
        <el-table-column type="expand">
          <template #default="{ row: item }">
            <div class="inventory-expand">
              <p>原单行号：{{ item.line_numbers.join('、') }} · SKU：{{ item.sku_id || '未映射' }}</p>
              <p v-if="item.line_numbers.length > 1">同一产品与 SKU 的多行数量已合计，库存只计算一次。</p>
              <el-table v-if="item.warehouses.length" :data="item.warehouses" size="small" border class="list-table" v-sticky-scrollbar>
                <el-table-column prop="warehouse_id" label="仓库 ID" min-width="160" />
                <el-table-column label="可用" min-width="100"><template #default="{ row: stock }">{{ amount(stock.available) }}</template></el-table-column>
                <el-table-column label="实存" min-width="100"><template #default="{ row: stock }">{{ amount(stock.real_count) }}</template></el-table-column>
                <el-table-column label="同步时间" min-width="165"><template #default="{ row: stock }">{{ formatBeijingDateTime(stock.synced_at) }}</template></el-table-column>
              </el-table>
              <p v-else>未找到对应库存镜像，请核对产品映射和库存同步。</p>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="产品 / SKU" min-width="250">
          <template #default="{ row: item }">
            <strong class="inventory-product">{{ item.product_name }}</strong>
            <small class="inventory-note">SKU {{ item.sku_id || '未映射' }} · {{ item.unit || '原单数量单位' }}</small>
            <div class="inventory-mobile">
              <StatusBadge :type="stateTypes[item.status]">{{ stateLabels[item.status] }}</StatusBadge>
              <p>需要 {{ amount(item.required) }} · 可用 {{ amount(item.available) }} · <strong :class="{ 'inventory-shortage': item.status === 'shortage' }">缺 {{ amount(item.shortage) }}</strong></p>
              <small class="inventory-note">{{ item.synced_at ? formatBeijingDateTime(item.synced_at) : '缺少库存或同步时间' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="本单数量" min-width="100" align="right"><template #default="{ row: item }">{{ amount(item.required) }}</template></el-table-column>
        <el-table-column label="可用库存" min-width="100" align="right"><template #default="{ row: item }">{{ amount(item.available) }}</template></el-table-column>
        <el-table-column label="实存" min-width="90" align="right"><template #default="{ row: item }">{{ amount(item.real_count) }}</template></el-table-column>
        <el-table-column label="不可用数量" min-width="110" align="right"><template #default="{ row: item }">{{ amount(item.unavailable_count) }}</template></el-table-column>
        <el-table-column label="缺口" min-width="90" align="right"><template #default="{ row: item }"><strong :class="{ 'inventory-shortage': item.status === 'shortage' }">{{ amount(item.shortage) }}</strong></template></el-table-column>
        <el-table-column label="状态 / 同步时间" min-width="175">
          <template #default="{ row: item }">
            <StatusBadge :type="stateTypes[item.status]">{{ stateLabels[item.status] }}</StatusBadge>
            <small class="inventory-note">{{ item.disabled ? '库存已停用 · ' : '' }}{{ item.synced_at ? formatBeijingDateTime(item.synced_at) : '缺少库存或同步时间' }}</small>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!details.items.length" description="未找到该单产品明细，请核对原单同步" :image-size="80" />
    </template>
    <template #footer><GlassButton left-icon="Refresh" :loading="loading" @click="load">刷新库存详情</GlassButton></template>
  </DetailDrawer>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { getOutboundInventory } from '@/api/shipping'
import { formatBeijingDateTime } from '@/utils/datetime'

const props = defineProps({ modelValue: Boolean, row: Object })
defineEmits(['update:modelValue'])
const loading = ref(false)
const details = ref(null)
const error = ref('')
const onlyIssues = ref(false)
const stateLabels = { shortage: '库存不足', sufficient: '可用数满足', unknown: '待核对' }
const stateTypes = { shortage: 'danger', sufficient: 'success', unknown: 'warning' }
const visibleItems = computed(() => (details.value?.items || []).filter(item => !onlyIssues.value || item.status !== 'sufficient'))
const amount = value => value == null ? '—' : value
let controller
let version = 0

async function load() {
  controller?.abort()
  const current = ++version
  if (!props.modelValue || !props.row?.outbound_record_id) return
  controller = new AbortController()
  loading.value = true
  error.value = ''
  details.value = null
  try {
    const response = await getOutboundInventory(props.row.outbound_record_id, { signal: controller.signal })
    if (current === version) details.value = response.data
  } catch (err) {
    if (current === version && !controller.signal.aborted) error.value = err.response?.data?.message || err.response?.data?.detail || '库存详情加载失败，请重试'
  } finally {
    if (current === version) loading.value = false
  }
}
watch(() => [props.modelValue, props.row?.outbound_record_id], () => {
  onlyIssues.value = false
  if (props.modelValue) load()
  else { ++version; controller?.abort(); details.value = null; loading.value = false }
}, { immediate: true })
onBeforeUnmount(() => { ++version; controller?.abort() })
</script>

<style scoped>
.inventory-heading, .inventory-tools { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.inventory-summary { display: flex; gap: 8px; flex-wrap: wrap; }
.inventory-tools { margin-top: 16px; }
.inventory-note { display: block; color: var(--text-secondary); font-size: 12px; margin: 8px 0; }
.inventory-product { overflow-wrap: anywhere; }
.inventory-shortage { color: var(--tag-danger-text); }
.inventory-expand { padding: 8px 16px; }
.inventory-mobile { display: none; }
@media (max-width: 600px) { .inventory-mobile { display: block; } }
</style>
