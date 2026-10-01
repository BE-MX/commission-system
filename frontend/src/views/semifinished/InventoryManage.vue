<template>
  <div class="sf-page">
    <header class="sf-header"><div><h2>半成品库存</h2><p>实存、占用、可用和在制分口径展示；每次变化都有可追溯流水。</p></div></header>
    <section ref="panelRef" class="table-card">
      <div class="toolbar">
        <el-input v-model="keyword" clearable placeholder="搜索编码、尺寸或颜色" class="filter-w-lg" @keyup.enter="search" />
        <GlassButton variant="primary" :left-icon="Search" @click="search">查询</GlassButton>
        <GlassButton :left-icon="RefreshLeft" @click="reset">重置</GlassButton>
      </div>

      <!-- 操作行：本页无页级主操作，仅 TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="load"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <el-table v-loading="loading" :data="rows" border class="list-table sf-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <template #empty>
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column v-if="visibleKeys.includes('material')" label="半成品" min-width="190"><template #default="{ row }"><div class="sf-material"><strong>{{ row.size }}/{{ row.color_code }}</strong><small>{{ row.material_code }}</small></div></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('on-hand')" label="实存(g)" min-width="120" align="right"><template #default="{ row }">{{ grams(row.on_hand_grams) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('reserved')" label="占用(g)" min-width="120" align="right"><template #default="{ row }">{{ grams(row.reserved_grams) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('available')" label="可用(g)" min-width="120" align="right"><template #default="{ row }"><strong>{{ grams(row.available_grams) }}</strong></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('in-progress')" label="在制(g)" min-width="120" align="right"><template #default="{ row }">{{ grams(row.in_progress_grams) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('safety-stock')" label="安全库存(g)" min-width="130" align="right"><template #default="{ row }">{{ grams(row.safety_stock_grams) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('stock-status')" label="库存状态" min-width="100"><template #default="{ row }"><el-tag :type="stockType(row.stock_status)" effect="plain">{{ stockText(row.stock_status) }}</el-tag></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('updated-at')" label="更新时间" min-width="170" prop="updated_at" />
        <el-table-column class-name="table-action-column" label="操作" min-width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openLedger(row)">流水</el-button><el-button v-permission="'semifinished:admin'" link type="warning" @click="openAdjust(row)">调整</el-button></template></el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @size-change="handleSizeChange"
        @current-change="load"
      />
    </section>

    <el-drawer v-model="ledgerVisible" :title="`${currentMaterial?.size}/${currentMaterial?.color_code} 库存流水`" size="760px">
      <el-table :data="ledgerRows" border class="list-table">
        <el-table-column prop="created_at" label="时间" min-width="165" />
        <el-table-column label="类型" min-width="110"><template #default="{ row }">{{ movementText(row.movement_type) }}</template></el-table-column>
        <el-table-column label="数量(g)" min-width="110" align="right"><template #default="{ row }"><span :class="Number(row.quantity_grams) < 0 ? 'sf-danger' : 'sf-success'">{{ signed(row.quantity_grams) }}</span></template></el-table-column>
        <el-table-column label="实存后" min-width="110" align="right"><template #default="{ row }">{{ grams(row.on_hand_after) }}</template></el-table-column>
        <el-table-column label="占用后" min-width="110" align="right"><template #default="{ row }">{{ grams(row.reserved_after) }}</template></el-table-column>
        <el-table-column prop="business_type" label="业务来源" min-width="140" />
        <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-drawer>

    <el-dialog v-model="adjustVisible" title="库存调整" width="460px">
      <p>{{ currentMaterial?.size }}/{{ currentMaterial?.color_code }}，当前实存 {{ grams(currentMaterial?.on_hand_grams) }}g</p>
      <el-form label-width="90px"><el-form-item label="调整数量"><el-input-number v-model="adjustForm.quantity_grams" :precision="3" /> g</el-form-item><el-form-item label="调整原因" required><el-input v-model="adjustForm.remark" type="textarea" :rows="2" maxlength="500" /></el-form-item></el-form>
      <template #footer><el-button @click="adjustVisible=false">取消</el-button><el-button type="primary" :loading="adjustSubmitting" @click="submitAdjust">确认调整</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshLeft, Search } from '@element-plus/icons-vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { adjustSemifinishedInventory, getInventoryLedger, getSemifinishedInventory } from '@/api/semifinished'

const rows = ref([]); const loading = ref(false); const keyword = ref(''); const pagination = reactive({ page: 1, page_size: 20, total: 0 })
const ledgerVisible = ref(false); const ledgerRows = ref([]); const currentMaterial = ref(null)
const adjustVisible = ref(false); const adjustForm = reactive({ quantity_grams: 0, remark: '' })
const adjustSubmitting = ref(false)
const adjustIdempotencyKey = ref('')
const hasActiveFilters = computed(() => Boolean(keyword.value))
const grams = value => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 })
const signed = value => `${Number(value) > 0 ? '+' : ''}${grams(value)}`
const stockText = value => ({ shortage: '短缺', warning: '预警', sufficient: '充足' }[value] || value)
const stockType = value => ({ shortage: 'danger', warning: 'warning', sufficient: 'success' }[value] || 'info')
const movementText = value => ({ inbound: '入库', outbound: '出库', reserve: '预占', release: '释放', adjust: '调整', reversal: '冲销' }[value] || value)

// 列显隐面板数据源（TableTools；渲染保持静态模板列，v-if 按 key 控制）
const columnDefs = [
  { key: 'material', label: '半成品' },
  { key: 'on-hand', label: '实存(g)' },
  { key: 'reserved', label: '占用(g)' },
  { key: 'available', label: '可用(g)' },
  { key: 'in-progress', label: '在制(g)' },
  { key: 'safety-stock', label: '安全库存(g)' },
  { key: 'stock-status', label: '库存状态' },
  { key: 'updated-at', label: '更新时间' },
]
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('semifinished-inventory', columnDefs)

async function load() { loading.value = true; try { const data = await getSemifinishedInventory({ page: pagination.page, page_size: pagination.page_size, keyword: keyword.value || undefined }); rows.value = data.items || []; pagination.total = data.total || 0 } finally { loading.value = false } }
function search() { pagination.page = 1; load() }
function reset() { keyword.value = ''; search() }
function handleSizeChange() { pagination.page = 1; load() }
async function openLedger(row) { currentMaterial.value = row; const data = await getInventoryLedger(row.material_id, { page: 1, page_size: 100 }); ledgerRows.value = data.items || []; ledgerVisible.value = true }
function openAdjust(row) { currentMaterial.value = row; Object.assign(adjustForm, { quantity_grams: 0, remark: '' }); adjustIdempotencyKey.value = crypto.randomUUID(); adjustVisible.value = true }
async function submitAdjust() { if (!Number(adjustForm.quantity_grams)) return ElMessage.warning('调整数量不能为0'); if (!adjustForm.remark.trim()) return ElMessage.warning('请填写调整原因'); adjustSubmitting.value = true; try { await adjustSemifinishedInventory(currentMaterial.value.material_id, { ...adjustForm, idempotency_key: adjustIdempotencyKey.value }); ElMessage.success('库存调整成功'); adjustVisible.value = false; load() } finally { adjustSubmitting.value = false } }
load()
</script>

<style scoped src="./semifinished.css"></style>
