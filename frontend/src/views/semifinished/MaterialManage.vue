<template>
  <div class="sf-page">
    <header class="sf-header">
      <div><h2>半成品列表</h2><p>按尺寸与标准化颜色跨产品共享，自动解析结果需审核后才能参与自动库存。</p></div>
      <div class="sf-actions">
        <el-button v-permission="'semifinished:admin'" @click="previewSync">同步预览</el-button>
        <el-button v-permission="'semifinished:admin'" type="primary" @click="applySync">应用产品同步</el-button>
        <el-button v-permission="'semifinished:write'" type="success" :disabled="!selectedMaterials.length" @click="openOrder">生产下单</el-button>
      </div>
    </header>

    <section class="sf-card">
      <el-tabs v-model="activeTab" @tab-change="loadCurrent">
        <el-tab-pane label="半成品" name="materials" />
        <el-tab-pane label="产品关联审核" name="mappings" />
      </el-tabs>
      <div class="sf-toolbar">
        <el-input v-model="filters.keyword" clearable placeholder="搜索编码、尺寸、颜色或产品" style="width: 280px" @keyup.enter="search" />
        <el-checkbox v-model="filters.review_only" label="仅看待审核" @change="search" />
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>

      <el-table v-if="activeTab === 'materials'" v-loading="loading" :data="rows" border class="list-table sf-table" @selection-change="selectedMaterials = $event">
        <el-table-column type="selection" min-width="48" />
        <el-table-column label="半成品" min-width="180">
          <template #default="{ row }"><div class="sf-material"><strong>{{ row.size }}/{{ row.color_code }}</strong><small>{{ row.material_code }}</small></div></template>
        </el-table-column>
        <el-table-column prop="color_type" label="色型" min-width="100" />
        <el-table-column prop="product_count" label="关联产品" min-width="100" align="right" />
        <el-table-column label="实存(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.on_hand_grams) }}</template></el-table-column>
        <el-table-column label="占用(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.reserved_grams) }}</template></el-table-column>
        <el-table-column label="可用(g)" min-width="110" align="right"><template #default="{ row }"><strong>{{ grams(row.available_grams) }}</strong></template></el-table-column>
        <el-table-column label="状态" min-width="90"><template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template></el-table-column>
      </el-table>

      <el-table v-else v-loading="loading" :data="rows" border class="list-table sf-table">
        <el-table-column prop="product_name" label="产品" min-width="300" show-overflow-tooltip />
        <el-table-column prop="model" label="型号" min-width="170" show-overflow-tooltip />
        <el-table-column label="规格" min-width="170"><template #default="{ row }">{{ row.size }}/{{ row.color_expression }}/{{ grams(row.unit_grams) }}g</template></el-table-column>
        <el-table-column label="半成品组成" min-width="240"><template #default="{ row }"><el-tag v-for="item in row.components" :key="item.material_id" size="small" effect="plain" style="margin: 2px">{{ item.size }}/{{ item.color_code }} · {{ percent(item.ratio) }}</el-tag></template></el-table-column>
        <el-table-column label="审核" min-width="110"><template #default="{ row }"><el-tag :type="row.parse_status === 'confirmed' ? 'success' : 'warning'" effect="plain">{{ row.parse_status === 'confirmed' ? '已确认' : '待审核' }}</el-tag></template></el-table-column>
        <el-table-column label="说明" min-width="160" prop="parse_message" show-overflow-tooltip />
        <el-table-column label="操作" min-width="90" fixed="right"><template #default="{ row }"><el-button v-permission="'semifinished:write'" link type="primary" @click="editMapping(row)">配比</el-button></template></el-table-column>
      </el-table>
      <div class="sf-pagination"><el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :total="pagination.total" :page-sizes="[20, 50, 100]" layout="total,sizes,prev,pager,next" @change="loadCurrent" /></div>
    </section>

    <el-dialog v-model="previewVisible" title="产品解析预览" width="720px">
      <div v-if="preview" class="sf-summary">
        <div class="sf-summary-item"><span>符合产品</span><strong>{{ preview.eligible_products }}</strong></div>
        <div class="sf-summary-item"><span>预计半成品</span><strong>{{ preview.material_count }}</strong></div>
        <div class="sf-summary-item"><span>新增关联</span><strong>{{ preview.new_mappings }}</strong></div>
        <div class="sf-summary-item"><span>待审核</span><strong>{{ preview.needs_review }}</strong></div>
      </div>
      <el-table :data="preview?.examples || []" max-height="360" border class="list-table">
        <el-table-column prop="product_name" label="产品" min-width="280" show-overflow-tooltip />
        <el-table-column label="解析结果" min-width="230"><template #default="{ row }">{{ row.components.map(c => `${row.size}/${c}`).join('、') }}</template></el-table-column>
        <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip />
      </el-table>
    </el-dialog>

    <el-dialog v-model="mappingVisible" title="确认半成品配比" width="620px">
      <p class="sf-muted">{{ editingMapping?.product_name }}</p>
      <div class="sf-component-list">
        <div v-for="item in mappingComponents" :key="item.material_id" class="sf-component-row">
          <span>{{ item.size }}/{{ item.color_code }}</span>
          <el-input-number v-model="item.ratio" :min="0.000001" :max="1" :precision="6" :step="0.05" />
          <span>{{ percent(item.ratio) }}</span>
        </div>
      </div>
      <p :class="ratioValid ? 'sf-success' : 'sf-danger'">配比合计：{{ percent(ratioTotal) }}</p>
      <template #footer><el-button @click="mappingVisible = false">取消</el-button><el-button type="primary" :disabled="!ratioValid" @click="saveMapping">确认配比</el-button></template>
    </el-dialog>

    <el-dialog v-model="orderVisible" title="创建半成品订单" width="620px">
      <div class="sf-component-list">
        <div v-for="item in orderItems" :key="item.material_id" class="sf-component-row">
          <span>{{ item.label }}</span><el-input-number v-model="item.quantity_grams" :min="0.001" :precision="3" /><span>g</span>
        </div>
      </div>
      <el-input v-model="orderRemark" type="textarea" :rows="2" maxlength="500" placeholder="备注" style="margin-top: 14px" />
      <template #footer><el-button @click="orderVisible = false">取消</el-button><el-button type="primary" @click="submitOrder">提交订单</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { applyMaterialSync, createSemifinishedOrder, getMappings, getMaterials, previewMaterialSync, updateMapping } from '@/api/semifinished'

const activeTab = ref('materials')
const loading = ref(false)
const rows = ref([])
const selectedMaterials = ref([])
const filters = reactive({ keyword: '', review_only: false })
const pagination = reactive({ page: 1, page_size: 20, total: 0 })
const previewVisible = ref(false)
const preview = ref(null)
const mappingVisible = ref(false)
const editingMapping = ref(null)
const mappingComponents = ref([])
const orderVisible = ref(false)
const orderItems = ref([])
const orderRemark = ref('')

const ratioTotal = computed(() => mappingComponents.value.reduce((sum, item) => sum + Number(item.ratio || 0), 0))
const ratioValid = computed(() => Math.abs(ratioTotal.value - 1) < 0.000001)
const grams = value => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 })
const percent = value => `${(Number(value || 0) * 100).toFixed(2)}%`

async function loadCurrent() {
  loading.value = true
  try {
    const fn = activeTab.value === 'materials' ? getMaterials : getMappings
    const data = await fn({ page: pagination.page, page_size: pagination.page_size, keyword: filters.keyword || undefined, review_only: filters.review_only })
    rows.value = data.items || []
    pagination.total = data.total || 0
  } finally { loading.value = false }
}
function search() { pagination.page = 1; loadCurrent() }
function reset() { filters.keyword = ''; filters.review_only = false; search() }
async function previewSync() { preview.value = await previewMaterialSync(); previewVisible.value = true }
async function applySync() {
  await ElMessageBox.confirm('将按当前产品列表新增或更新自动解析结果，人工确认的配比不会被覆盖。', '应用产品同步')
  const result = await applyMaterialSync()
  ElMessage.success(`已同步 ${result.applied} 个产品，${result.needs_review} 个待审核`)
  loadCurrent()
}
function editMapping(row) { editingMapping.value = row; mappingComponents.value = row.components.map(item => ({ ...item, ratio: Number(item.ratio) })); mappingVisible.value = true }
async function saveMapping() {
  await updateMapping(editingMapping.value.id, { components: mappingComponents.value.map(item => ({ material_id: item.material_id, ratio: item.ratio })) })
  ElMessage.success('配比已确认'); mappingVisible.value = false; loadCurrent()
}
function openOrder() {
  orderItems.value = selectedMaterials.value.map(row => ({ material_id: row.id, label: `${row.size}/${row.color_code}`, quantity_grams: 100 }))
  orderRemark.value = ''; orderVisible.value = true
}
async function submitOrder() {
  await createSemifinishedOrder({ items: orderItems.value.map(item => ({ material_id: item.material_id, quantity_grams: item.quantity_grams })), remark: orderRemark.value || null })
  ElMessage.success('半成品订单已创建'); orderVisible.value = false
}

loadCurrent()
</script>

<style scoped src="./semifinished.css"></style>
