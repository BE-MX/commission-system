<template>
  <div class="price-config-page">
    <div class="page-header">
      <div>
        <h2>价格与产品配置</h2>
        <p>标准参考价矩阵、色型映射、客户价格规则与生产单沉淀产品管理。</p>
      </div>
    </div>
    <section class="table-card">
      <el-tabs v-model="activeTab">
        <!-- ── 标准价格表 ── -->
        <el-tab-pane label="标准价格表" name="std">
          <el-tabs v-model="activePriceKind">
            <el-tab-pane label="头发价格" name="hair">
          <div class="tab-toolbar">
            <el-select v-model="stdFilter" clearable filterable placeholder="按系列筛选" style="width: 320px" @change="loadStdPrices">
              <el-option v-for="s in stdSeriesOptions" :key="s" :label="s" :value="s" />
            </el-select>
            <el-button v-permission="'invoice:admin'" type="primary" @click="openStdDialog()">
              <el-icon><Plus /></el-icon>
              新增价格
            </el-button>
            <el-upload v-permission="'invoice:admin'" :show-file-list="false" accept=".xlsx" :http-request="handleImport">
              <el-button>
                <el-icon><Upload /></el-icon>
                导入价格表 Excel
              </el-button>
            </el-upload>
          </div>
          <el-table v-loading="stdLoading" :data="stdPrices" border class="list-table">
            <el-table-column prop="series_grade" label="系列 + 工艺档" min-width="280" show-overflow-tooltip />
            <el-table-column prop="length" label="长度" min-width="80" />
            <el-table-column prop="weight_unit" label="克重" min-width="80" />
            <el-table-column label="色型" min-width="110">
              <template #default="{ row }">
                <el-tag effect="plain">{{ colorTypeText(row.color_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="标准价" min-width="120" align="right">
              <template #default="{ row }">{{ row.currency }} {{ Number(row.price).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="更新时间" min-width="170" show-overflow-tooltip />
            <el-table-column label="操作" min-width="140" fixed="right">
              <template #default="{ row }">
                <el-button v-permission="'invoice:admin'" link type="primary" @click="openStdDialog(row)">
                  <el-icon><Edit /></el-icon>
                  编辑
                </el-button>
                <el-button v-permission="'invoice:admin'" link type="danger" @click="removeStd(row)">
                  <el-icon><Delete /></el-icon>
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
            </el-tab-pane>
            <el-tab-pane label="配件价格" name="accessory" lazy>
              <AccessoryPriceConfig />
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>
        <!-- ── 色型映射 ── -->
        <el-tab-pane label="色型映射" name="colors">
          <div class="tab-toolbar">
            <span class="hint">未登记的色号会按命名规则自动推断色型，推断不了则该行显示"无标准价"。</span>
            <el-button v-permission="'invoice:admin'" type="primary" @click="colorDialog.visible = true">
              <el-icon><Plus /></el-icon>
              新增映射
            </el-button>
          </div>
          <el-table v-loading="colorLoading" :data="colorTypes" border class="list-table">
            <el-table-column prop="color_code" label="色号" min-width="160" />
            <el-table-column label="色型" min-width="140">
              <template #default="{ row }">
                <el-tag effect="plain">{{ colorTypeText(row.color_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="100" fixed="right">
              <template #default="{ row }">
                <el-button v-permission="'invoice:admin'" link type="danger" @click="removeColor(row)">
                  <el-icon><Delete /></el-icon>
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <!-- ── 客户价格规则 ── -->
        <el-tab-pane label="客户价格规则" name="rules">
          <div class="tab-toolbar">
            <el-input v-model="ruleKeyword" clearable placeholder="搜索客户" style="width: 240px" @keyup.enter="loadRules" />
            <el-button @click="loadRules">
              <el-icon><Search /></el-icon>
              筛选
            </el-button>
            <el-button v-permission="'invoice:admin'" type="primary" @click="openRuleDialog()">
              <el-icon><Plus /></el-icon>
              新增规则
            </el-button>
          </div>
          <el-table v-loading="ruleLoading" :data="rules" border class="list-table">
            <el-table-column prop="customer_name" label="客户" min-width="220" show-overflow-tooltip />
            <el-table-column prop="customer_id" label="客户 ID" min-width="140" show-overflow-tooltip />
            <el-table-column label="调价方式" min-width="200">
              <template #default="{ row }">
                {{ ruleText(row) }}
              </template>
            </el-table-column>
            <el-table-column label="启用" min-width="80">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'" effect="plain">{{ row.enabled ? '启用' : '停用' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
            <el-table-column label="操作" min-width="140" fixed="right">
              <template #default="{ row }">
                <el-button v-permission="'invoice:admin'" link type="primary" @click="openRuleDialog(row)">
                  <el-icon><Edit /></el-icon>
                  编辑
                </el-button>
                <el-button v-permission="'invoice:admin'" link type="danger" @click="removeRule(row)">
                  <el-icon><Delete /></el-icon>
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <!-- ── 自定义产品 ── -->
        <el-tab-pane label="生产单沉淀产品" name="custom">
          <div class="tab-toolbar">
            <el-input v-model="customKeyword" clearable placeholder="搜索产品名/型号" style="width: 260px" @keyup.enter="loadCustom" />
            <el-button @click="loadCustom">
              <el-icon><Search /></el-icon>
              筛选
            </el-button>
            <el-button v-permission="'invoice:admin'" @click="runReconcile">
              <el-icon><Refresh /></el-icon>
              与 OKKI 产品库对账回填
            </el-button>
          </div>
          <el-table v-loading="customLoading" :data="customProducts" border class="list-table">
            <el-table-column prop="product_name" label="产品名" min-width="300" show-overflow-tooltip />
            <el-table-column prop="model" label="Model" min-width="140" show-overflow-tooltip />
            <el-table-column prop="color" label="Color" min-width="110" />
            <el-table-column prop="size" label="Length" min-width="90" />
            <el-table-column prop="unit" label="Unit" min-width="90" />
            <el-table-column prop="use_count" label="使用次数" min-width="90" align="right" />
            <el-table-column label="OKKI 关联" min-width="150">
              <template #default="{ row }">
                <el-tag v-if="row.okki_product_id" type="success" effect="plain">已关联 {{ row.okki_product_id }}</el-tag>
                <el-tag v-else type="info" effect="plain">待 OKKI 建品</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </section>
    <!-- 标准价编辑 -->
    <el-dialog v-model="stdDialog.visible" :title="stdDialog.form.id ? '编辑标准价' : '新增标准价'" width="520px">
      <el-form :model="stdDialog.form" label-width="110px">
        <el-form-item label="系列+工艺档" required>
          <el-select v-model="stdDialog.form.series_grade" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="s in stdSeriesOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="长度" required>
          <el-input v-model="stdDialog.form.length" maxlength="16" placeholder="如 16" />
        </el-form-item>
        <el-form-item label="克重" required>
          <el-input v-model="stdDialog.form.weight_unit" maxlength="16" placeholder="如 20g" />
        </el-form-item>
        <el-form-item label="色型" required>
          <el-select v-model="stdDialog.form.color_type" style="width: 100%">
            <el-option v-for="(label, key) in COLOR_TYPE_TEXT" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="标准价" required>
          <el-input-number v-model="stdDialog.form.price" :min="0" :precision="2" controls-position="right" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="stdDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveStd">保存</el-button>
      </template>
    </el-dialog>
    <!-- 色型映射新增 -->
    <el-dialog v-model="colorDialog.visible" title="新增色型映射" width="420px">
      <el-form :model="colorDialog.form" label-width="90px">
        <el-form-item label="色号" required>
          <el-input v-model="colorDialog.form.color_code" maxlength="32" placeholder="如 #P8/24 或 Cookies Cream" />
        </el-form-item>
        <el-form-item label="色型" required>
          <el-select v-model="colorDialog.form.color_type" style="width: 100%">
            <el-option v-for="(label, key) in COLOR_TYPE_TEXT" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="colorDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveColor">保存</el-button>
      </template>
    </el-dialog>
    <!-- 客户规则编辑 -->
    <el-dialog v-model="ruleDialog.visible" :title="ruleDialog.form.id ? '编辑客户价格规则' : '新增客户价格规则'" width="520px">
      <el-form :model="ruleDialog.form" label-width="110px">
        <el-form-item label="客户" required>
          <el-select
            v-model="ruleDialog.customer"
            value-key="company_id"
            filterable
            remote
            :remote-method="searchRuleCustomers"
            :loading="ruleCustomerLoading"
            :disabled="!!ruleDialog.form.id"
            placeholder="输入客户名称/ID 搜索"
            style="width: 100%"
            @change="onRuleCustomerChange"
          >
            <el-option
              v-for="c in ruleCustomerOptions"
              :key="c.company_id"
              :label="customerLabel(c)"
              :value="c"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="调价方式" required>
          <el-radio-group v-model="ruleDialog.form.adjust_type">
            <el-radio value="fixed">固定加减额</el-radio>
            <el-radio value="percent">上浮/下调百分比</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="ruleDialog.form.adjust_type === 'percent' ? '百分比 (%)' : '加减额'" required>
          <el-input-number v-model="ruleDialog.form.adjust_value" :precision="2" controls-position="right" style="width: 100%" />
          <div class="dialog-hint">正数为上调，负数为下调。例：-5 表示在标准价基础上{{ ruleDialog.form.adjust_type === 'percent' ? '下调 5%' : '减 5' }}。</div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="ruleDialog.form.enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="ruleDialog.form.remark" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Edit, Plus, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import { customerLabel } from './composables/useInvoiceEditor'
import AccessoryPriceConfig from './components/AccessoryPriceConfig.vue'
import {
  deleteColorType,
  deleteCustomerRule,
  deleteStdPrice,
  importPriceWorkbook,
  listColorTypes,
  listCustomProducts,
  listCustomerRules,
  listStdPrices,
  reconcileCustomProducts,
  searchInvoiceCustomers,
  upsertColorType,
  upsertCustomerRule,
  upsertStdPrice,
} from '@/api/invoice'

const COLOR_TYPE_TEXT = { solid: '纯色 Solid', piano: '钢琴色 Piano', ombre: '渐变 Ombre', balayage: '巴拉雅奇 Balayage' }

const activeTab = ref('std')
const activePriceKind = ref('hair')

// 标准价
const stdLoading = ref(false)
const stdPrices = ref([])
const stdFilter = ref('')
const stdDialog = reactive({ visible: false, form: emptyStd() })
const stdSeriesOptions = computed(() => [...new Set(stdPrices.value.map(r => r.series_grade))])

// 色型
const colorLoading = ref(false)
const colorTypes = ref([])
const colorDialog = reactive({ visible: false, form: { color_code: '', color_type: 'solid' } })

// 客户规则
const ruleLoading = ref(false)
const rules = ref([])
const ruleKeyword = ref('')
const ruleCustomerLoading = ref(false)
const ruleCustomerOptions = ref([])
const ruleDialog = reactive({ visible: false, customer: null, form: emptyRule() })

// 自定义产品
const customLoading = ref(false)
const customProducts = ref([])
const customKeyword = ref('')

onMounted(() => {
  loadStdPrices()
  loadColorTypes()
  loadRules()
  loadCustom()
})

function emptyStd() {
  return { id: null, series_grade: '', length: '', weight_unit: '', color_type: 'solid', price: null, currency: 'USD' }
}

function emptyRule() {
  return { id: null, customer_id: '', customer_name: '', adjust_type: 'fixed', adjust_value: 0, enabled: true, remark: '' }
}

function colorTypeText(key) {
  return COLOR_TYPE_TEXT[key] || key
}

function ruleText(row) {
  const sign = Number(row.adjust_value) >= 0 ? '+' : ''
  return row.adjust_type === 'percent'
    ? `标准价 ${sign}${Number(row.adjust_value)}%`
    : `标准价 ${sign}${Number(row.adjust_value)}（固定额）`
}

// ── 标准价 ──────────────────────────────────────────

async function loadStdPrices() {
  stdLoading.value = true
  try {
    const res = await listStdPrices(stdFilter.value ? { series_grade: stdFilter.value } : {})
    stdPrices.value = res.items || []
  } finally {
    stdLoading.value = false
  }
}

function openStdDialog(row) {
  stdDialog.form = row
    ? { ...row, price: Number(row.price) }
    : emptyStd()
  stdDialog.visible = true
}

async function saveStd() {
  const f = stdDialog.form
  if (!f.series_grade || !f.length || !f.weight_unit || f.price == null) {
    ElMessage.warning('系列、长度、克重、价格均必填')
    return
  }
  await upsertStdPrice(f)
  stdDialog.visible = false
  msgSuccess('保存')
  loadStdPrices()
}

async function removeStd(row) {
  await confirmDanger('删除', `${row.series_grade} ${row.length}/${row.weight_unit} 的标准价`)
  await deleteStdPrice(row.id)
  msgSuccess('删除')
  loadStdPrices()
}

async function handleImport({ file }) {
  const formData = new FormData()
  formData.append('file', file)
  const result = await importPriceWorkbook(formData)
  ElMessage.success(`导入完成：标准价格 ${result.prices_imported} 格，已按两位小数四舍五入${result.skipped?.length ? `，跳过 ${result.skipped.length} 行` : ''}`)
  loadStdPrices()
  loadColorTypes()
}

// ── 色型 ────────────────────────────────────────────

async function loadColorTypes() {
  colorLoading.value = true
  try {
    const res = await listColorTypes()
    colorTypes.value = res.items || []
  } finally {
    colorLoading.value = false
  }
}

async function saveColor() {
  if (!colorDialog.form.color_code) {
    ElMessage.warning('请输入色号')
    return
  }
  await upsertColorType(colorDialog.form)
  colorDialog.visible = false
  colorDialog.form = { color_code: '', color_type: 'solid' }
  msgSuccess('保存')
  loadColorTypes()
}

async function removeColor(row) {
  await confirmDanger('删除', `色号 ${row.color_code} 的映射`)
  await deleteColorType(row.id)
  msgSuccess('删除')
  loadColorTypes()
}

// ── 客户规则 ────────────────────────────────────────

async function loadRules() {
  ruleLoading.value = true
  try {
    const res = await listCustomerRules(ruleKeyword.value ? { keyword: ruleKeyword.value } : {})
    rules.value = res.items || []
  } finally {
    ruleLoading.value = false
  }
}

async function searchRuleCustomers(keyword) {
  ruleCustomerLoading.value = true
  try {
    const res = await searchInvoiceCustomers({ keyword })
    ruleCustomerOptions.value = res.items || []
  } finally {
    ruleCustomerLoading.value = false
  }
}

function onRuleCustomerChange(customer) {
  ruleDialog.form.customer_id = customer?.company_id == null ? '' : String(customer.company_id)
  ruleDialog.form.customer_name = customer?.company_name || ''
}

function openRuleDialog(row) {
  ruleDialog.form = row
    ? { ...row, adjust_value: Number(row.adjust_value), enabled: !!row.enabled }
    : emptyRule()
  ruleDialog.customer = row ? { company_id: row.customer_id, company_name: row.customer_name } : null
  ruleDialog.visible = true
  searchRuleCustomers('')
}

async function saveRule() {
  const f = ruleDialog.form
  if (!f.customer_id) {
    ElMessage.warning('请选择客户')
    return
  }
  await upsertCustomerRule(f)
  ruleDialog.visible = false
  msgSuccess('保存')
  loadRules()
}

async function removeRule(row) {
  await confirmDanger('删除', `${row.customer_name || row.customer_id} 的价格规则`)
  await deleteCustomerRule(row.id)
  msgSuccess('删除')
  loadRules()
}

// ── 自定义产品 ──────────────────────────────────────

async function loadCustom() {
  customLoading.value = true
  try {
    const res = await listCustomProducts(customKeyword.value ? { keyword: customKeyword.value } : {})
    customProducts.value = res.items || []
  } finally {
    customLoading.value = false
  }
}

async function runReconcile() {
  const result = await reconcileCustomProducts()
  ElMessage.success(`对账完成：检查 ${result.checked} 条，回填 ${result.linked} 条`)
  loadCustom()
}
</script>

<style scoped src="./invoice-price-config.css"></style>
