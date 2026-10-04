<template>
  <div class="price-config-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="price-config-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <div>
        <h2>价格与产品配置</h2>
        <p>标准参考价矩阵、色型映射、客户价格规则与生产单沉淀产品管理。</p>
      </div>
    </div>
    <section class="price-tabs-panel">
      <el-tabs v-model="activeTab">
        <!-- ── 标准价格表 ── -->
        <el-tab-pane label="标准价格表" name="std">
          <el-tabs v-model="activePriceKind">
            <el-tab-pane label="头发价格" name="hair">
          <div ref="stdPanelRef" class="table-card price-table-panel">
          <FilterBar :loading="stdLoading" :pending="stdPending" @search="searchStd" @reset="resetStd">
            <el-select v-model="stdFilter" clearable filterable placeholder="按系列筛选" class="filter-w-md">
              <el-option v-for="s in stdSeriesOptions" :key="s" :label="s" :value="s" />
            </el-select>
          </FilterBar>
          <div class="action-bar">
            <GlassButton v-permission="'invoice:admin'" variant="primary" :left-icon="Plus" @click="openStdDialog()">新增价格</GlassButton>
            <el-upload v-permission="'invoice:admin'" :show-file-list="false" accept=".xlsx" :http-request="handleImport">
              <GlassButton variant="secondary" :left-icon="Upload">导入价格表 Excel</GlassButton>
            </el-upload>
            <TableTools v-model:visible-keys="stdVisibleKeys" v-model:density="stdDensity" :columns="stdColumnDefs" :fullscreen="stdIsFullscreen" :loading="stdLoading" @refresh="loadStdPrices" @fullscreen="toggleStdFullscreen" />
          </div>
          <ListPageStatus v-if="stdResource.error.value && stdPrices.length" v-bind="resourceStatus(stdResource)" @retry="loadStdPrices" />
          <el-table v-loading="stdLoading" :data="stdPrices" border class="list-table" :class="stdDensityClass" :max-height="stdIsFullscreen ? undefined : 640" v-sticky-scrollbar>
            <template #empty><ListPageStatus v-bind="resourceStatus(stdResource)" @retry="loadStdPrices"><el-empty description="暂无配置记录" /></ListPageStatus></template>
            <el-table-column v-if="stdVisibleKeys.includes('series')" prop="series_grade" label="系列 + 工艺档" min-width="280" show-overflow-tooltip />
            <el-table-column v-if="stdVisibleKeys.includes('length')" prop="length" label="长度" min-width="80" />
            <el-table-column v-if="stdVisibleKeys.includes('weight')" prop="weight_unit" label="克重" min-width="80" />
            <el-table-column prop="color_type" v-if="stdVisibleKeys.includes('color-type')" label="色型" min-width="190">
              <template #default="{ row }">
                <StatusBadge effect="plain">{{ colorTypeText(row.color_type) }}</StatusBadge>
              </template>
            </el-table-column>
            <el-table-column prop="price" v-if="stdVisibleKeys.includes('price')" label="标准价" min-width="120" align="right">
              <template #default="{ row }">{{ row.currency }} {{ formatMoney(row.price) }}</template>
            </el-table-column>
            <el-table-column v-if="stdVisibleKeys.includes('updated')" prop="updated_at" label="更新时间" min-width="170" show-overflow-tooltip />
            <el-table-column class-name="table-action-column" label="操作" min-width="140" fixed="right">
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
          </div>
            </el-tab-pane>
            <el-tab-pane label="配件价格" name="accessory" lazy>
              <AccessoryPriceConfig />
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>
        <!-- ── 色型映射 ── -->
        <el-tab-pane label="色型映射" name="colors">
          <div ref="colorPanelRef" class="table-card price-table-panel">
          <div class="toolbar">
            <span class="hint">未登记的色号会按命名规则自动推断色型，推断不了则该行显示"无标准价"。</span>
          </div>
          <div class="action-bar">
            <GlassButton v-permission="'invoice:admin'" variant="primary" :left-icon="Plus" @click="colorDialog.visible = true">新增映射</GlassButton>
            <TableTools v-model:visible-keys="colorVisibleKeys" v-model:density="colorDensity" :columns="colorColumnDefs" :fullscreen="colorIsFullscreen" :loading="colorLoading" @refresh="loadColorTypes" @fullscreen="toggleColorFullscreen" />
          </div>
          <ListPageStatus v-if="colorResource.error.value && colorTypes.length" v-bind="resourceStatus(colorResource)" @retry="loadColorTypes" />
          <el-table v-loading="colorLoading" :data="colorTypes" border class="list-table" :class="colorDensityClass" :max-height="colorIsFullscreen ? undefined : 640" v-sticky-scrollbar>
            <template #empty><ListPageStatus v-bind="resourceStatus(colorResource)" @retry="loadColorTypes"><el-empty description="暂无配置记录" /></ListPageStatus></template>
            <el-table-column v-if="colorVisibleKeys.includes('code')" prop="color_code" label="色号" min-width="160" />
            <el-table-column prop="color_type" v-if="colorVisibleKeys.includes('type')" label="色型" min-width="190">
              <template #default="{ row }">
                <StatusBadge effect="plain">{{ colorTypeText(row.color_type) }}</StatusBadge>
              </template>
            </el-table-column>
            <el-table-column class-name="table-action-column" label="操作" min-width="100" fixed="right">
              <template #default="{ row }">
                <el-button v-permission="'invoice:admin'" link type="danger" @click="removeColor(row)">
                  <el-icon><Delete /></el-icon>
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          </div>
        </el-tab-pane>
        <!-- ── 客户价格规则 ── -->
        <el-tab-pane label="客户价格规则" name="rules">
          <div ref="rulePanelRef" class="table-card price-table-panel">
          <FilterBar :loading="ruleLoading" :pending="rulePending" @search="searchRules" @reset="resetRuleFilter">
            <el-input v-model="ruleKeyword" clearable placeholder="搜索客户" class="filter-w-md" />
          </FilterBar>
          <div class="action-bar">
            <GlassButton v-permission="'invoice:admin'" variant="primary" :left-icon="Plus" @click="openRuleDialog()">新增规则</GlassButton>
            <TableTools v-model:visible-keys="ruleVisibleKeys" v-model:density="ruleDensity" :columns="ruleColumnDefs" :fullscreen="ruleIsFullscreen" :loading="ruleLoading" @refresh="loadRules" @fullscreen="toggleRuleFullscreen" />
          </div>
          <ListPageStatus v-if="ruleResource.error.value && rules.length" v-bind="resourceStatus(ruleResource)" @retry="loadRules" />
          <el-table v-loading="ruleLoading" :data="rules" border class="list-table" :class="ruleDensityClass" :max-height="ruleIsFullscreen ? undefined : 640" v-sticky-scrollbar>
            <template #empty><ListPageStatus v-bind="resourceStatus(ruleResource)" @retry="loadRules"><el-empty description="暂无配置记录" /></ListPageStatus></template>
            <el-table-column v-if="ruleVisibleKeys.includes('customer')" prop="customer_name" label="客户" min-width="220" show-overflow-tooltip />
            <el-table-column v-if="ruleVisibleKeys.includes('customer-id')" prop="customer_id" label="客户 ID" min-width="140" show-overflow-tooltip />
            <el-table-column :sort-by="row => (ruleText(row))" v-if="ruleVisibleKeys.includes('adjust')" label="调价方式" min-width="200">
              <template #default="{ row }">
                {{ ruleText(row) }}
              </template>
            </el-table-column>
            <el-table-column prop="enabled" v-if="ruleVisibleKeys.includes('enabled')" label="启用" min-width="100">
              <template #default="{ row }">
                <StatusBadge :value="row.enabled" :dictionary="ENABLED_STATUS" effect="plain" />
              </template>
            </el-table-column>
            <el-table-column v-if="ruleVisibleKeys.includes('remark')" prop="remark" label="备注" min-width="180" show-overflow-tooltip />
            <el-table-column class-name="table-action-column" label="操作" min-width="140" fixed="right">
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
          </div>
        </el-tab-pane>
        <!-- ── 自定义产品 ── -->
        <el-tab-pane label="生产单沉淀产品" name="custom">
          <div ref="customPanelRef" class="table-card price-table-panel">
          <FilterBar :loading="customLoading" :pending="customPending" @search="searchCustom" @reset="resetCustomFilter">
            <el-input v-model="customKeyword" clearable placeholder="搜索产品名/型号" class="filter-w-md" />
            <template #summary><span>最多显示最近 200 个符合条件的产品，请用搜索缩小范围。</span></template>
          </FilterBar>
          <div class="action-bar">
            <GlassButton v-permission="'invoice:admin'" variant="secondary" :left-icon="Refresh" @click="runReconcile">与 OKKI 产品库对账回填</GlassButton>
            <TableTools v-model:visible-keys="customVisibleKeys" v-model:density="customDensity" :columns="customColumnDefs" :fullscreen="customIsFullscreen" :loading="customLoading" @refresh="loadCustom" @fullscreen="toggleCustomFullscreen" />
          </div>
          <ListPageStatus v-if="customResource.error.value && customProducts.length" v-bind="resourceStatus(customResource)" @retry="loadCustom" />
          <el-table v-loading="customLoading" :data="customProducts" border class="list-table" :class="customDensityClass" :max-height="customIsFullscreen ? undefined : 640" v-sticky-scrollbar>
            <template #empty><ListPageStatus v-bind="resourceStatus(customResource)" @retry="loadCustom"><el-empty description="暂无配置记录" /></ListPageStatus></template>
            <el-table-column v-if="customVisibleKeys.includes('name')" prop="product_name" label="产品名" min-width="300" show-overflow-tooltip />
            <el-table-column v-if="customVisibleKeys.includes('model')" prop="model" label="Model" min-width="140" show-overflow-tooltip />
            <el-table-column v-if="customVisibleKeys.includes('color')" prop="color" label="Color" min-width="110" />
            <el-table-column v-if="customVisibleKeys.includes('size')" prop="size" label="Length" min-width="90" />
            <el-table-column v-if="customVisibleKeys.includes('unit')" prop="unit" label="Unit" min-width="90" />
            <el-table-column v-if="customVisibleKeys.includes('count')" prop="use_count" label="使用次数" min-width="90" align="right" />
            <el-table-column prop="okki_product_id" v-if="customVisibleKeys.includes('okki')" label="OKKI 关联" min-width="150">
              <template #default="{ row }">
                <StatusBadge v-if="row.okki_product_id" type="success" effect="plain">已关联 {{ row.okki_product_id }}</StatusBadge>
                <StatusBadge v-else type="info" effect="plain">待 OKKI 建品</StatusBadge>
              </template>
            </el-table-column>
          </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>
    <!-- 标准价编辑 -->
    <el-dialog v-model="stdDialog.visible" :title="stdDialog.form.id ? '编辑标准价' : '新增标准价'" width="640px">
      <el-form label-position="top" :model="stdDialog.form">
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
    <el-dialog v-model="colorDialog.visible" title="新增色型映射" width="480px">
      <el-form label-position="top" :model="colorDialog.form">
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
    <el-dialog v-model="ruleDialog.visible" :title="ruleDialog.form.id ? '编辑客户价格规则' : '新增客户价格规则'" width="640px">
      <el-form label-position="top" :model="ruleDialog.form">
        <ListPageStatus v-if="ruleCustomerResource.error.value" v-bind="resourceStatus(ruleCustomerResource)" @retry="ruleCustomerResource.load()" />
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
import { ENABLED_STATUS } from '@/utils/status'
import { formatMoney } from '../../utils/money.js'
import { msgWarning, msgSuccessText, msgSuccess, confirmDanger } from '@/utils/feedback'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { Delete, Edit, Plus, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { customerLabel } from './composables/useInvoiceEditor'
import AccessoryPriceConfig from './components/AccessoryPriceConfig.vue'
import { COLOR_TYPE_TEXT, stdColumnDefs, colorColumnDefs, ruleColumnDefs, customColumnDefs, emptyStd, emptyRule, colorTypeText, ruleText } from './invoicePricePresentation'
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

const activeTab = ref('std')
const activePriceKind = ref('hair')
const {
  density: stdDensity, densityClass: stdDensityClass, visibleKeys: stdVisibleKeys,
  panelRef: stdPanelRef, isFullscreen: stdIsFullscreen, toggleFullscreen: toggleStdFullscreen,
} = useTableView('invoice-standard-prices', stdColumnDefs)
const {
  density: colorDensity, densityClass: colorDensityClass, visibleKeys: colorVisibleKeys,
  panelRef: colorPanelRef, isFullscreen: colorIsFullscreen, toggleFullscreen: toggleColorFullscreen,
} = useTableView('invoice-color-types', colorColumnDefs)
const {
  density: ruleDensity, densityClass: ruleDensityClass, visibleKeys: ruleVisibleKeys,
  panelRef: rulePanelRef, isFullscreen: ruleIsFullscreen, toggleFullscreen: toggleRuleFullscreen,
} = useTableView('invoice-customer-rules', ruleColumnDefs)
const {
  density: customDensity, densityClass: customDensityClass, visibleKeys: customVisibleKeys,
  panelRef: customPanelRef, isFullscreen: customIsFullscreen, toggleFullscreen: toggleCustomFullscreen,
} = useTableView('invoice-custom-products', customColumnDefs)

const resourceStatus = resource => ({ error: resource.errorMessage.value, loading: resource.loading.value, hasData: resource.hasLoaded.value, paged: false })
const readConfig = signal => ({ signal, suppressToast: true })
const stdResource = useAsyncResource(async (_, { signal }) => (await listStdPrices({}, readConfig(signal))).items || [], { initialData: [] })
const stdLoading = stdResource.loading
const stdFilter = ref(''), appliedStdFilter = ref('')
const stdPrices = computed(() => appliedStdFilter.value ? stdResource.data.value.filter(row => row.series_grade === appliedStdFilter.value) : stdResource.data.value)
const stdDialog = reactive({ visible: false, form: emptyStd() })
const stdSeriesOptions = computed(() => [...new Set(stdResource.data.value.map(row => row.series_grade))])
const stdPending = computed(() => stdFilter.value !== appliedStdFilter.value)
function searchStd() { appliedStdFilter.value = stdFilter.value; return loadStdPrices() }
function resetStd() { stdFilter.value = ''; return searchStd() }

const colorResource = useAsyncResource(async (_, { signal }) => (await listColorTypes(readConfig(signal))).items || [], { initialData: [] })
const colorLoading = colorResource.loading, colorTypes = colorResource.data
const colorDialog = reactive({ visible: false, form: { color_code: '', color_type: 'solid' } })

const ruleResource = useAsyncResource(async (params, { signal }) => (await listCustomerRules(params, readConfig(signal))).items || [], { initialData: [] })
const ruleLoading = ruleResource.loading, rules = ruleResource.data
const ruleKeyword = ref(''), appliedRuleKeyword = ref('')
const rulePending = computed(() => ruleKeyword.value !== appliedRuleKeyword.value)
function searchRules() { appliedRuleKeyword.value = ruleKeyword.value; return loadRules() }
function resetRuleFilter() { ruleKeyword.value = ''; return searchRules() }
const ruleCustomerResource = useAsyncResource(async (params, { signal }) => (await searchInvoiceCustomers(params, readConfig(signal))).items || [], { initialData: [] })
const ruleCustomerLoading = ruleCustomerResource.loading, ruleCustomerOptions = ruleCustomerResource.data
const ruleDialog = reactive({ visible: false, customer: null, form: emptyRule() })
watch(() => ruleDialog.visible, visible => { if (!visible) ruleCustomerResource.clear() })

const customResource = useAsyncResource(async (params, { signal }) => (await listCustomProducts(params, readConfig(signal))).items || [], { initialData: [] })
const customLoading = customResource.loading, customProducts = customResource.data
const customKeyword = ref(''), appliedCustomKeyword = ref('')
const customPending = computed(() => customKeyword.value !== appliedCustomKeyword.value)
function searchCustom() { appliedCustomKeyword.value = customKeyword.value; return loadCustom() }
function resetCustomFilter() { customKeyword.value = ''; return searchCustom() }

onMounted(() => {
  loadStdPrices()
  loadColorTypes()
  loadRules()
  loadCustom()
})

// ── 标准价 ──────────────────────────────────────────

function loadStdPrices() { return stdResource.load() }

function openStdDialog(row) {
  stdDialog.form = row
    ? { ...row, price: Number(row.price) }
    : emptyStd()
  stdDialog.visible = true
}

async function saveStd() {
  const f = stdDialog.form
  if (!f.series_grade || !f.length || !f.weight_unit || f.price == null) {
    msgWarning('系列、长度、克重、价格均必填')
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
  msgSuccessText(`导入完成：标准价格 ${result.prices_imported} 格，已按两位小数四舍五入${result.skipped?.length ? `，跳过 ${result.skipped.length} 行` : ''}`)
  loadStdPrices()
  loadColorTypes()
}

// ── 色型 ────────────────────────────────────────────

function loadColorTypes() { return colorResource.load() }

async function saveColor() {
  if (!colorDialog.form.color_code) {
    msgWarning('请输入色号')
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

function loadRules() { return ruleResource.load(appliedRuleKeyword.value ? { keyword: appliedRuleKeyword.value } : {}) }

function searchRuleCustomers(keyword) { return ruleCustomerResource.load({ keyword }, { clear: true }) }

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
    msgWarning('请选择客户')
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

function loadCustom() { return customResource.load(appliedCustomKeyword.value ? { keyword: appliedCustomKeyword.value } : {}) }

async function runReconcile() {
  const result = await reconcileCustomProducts()
  msgSuccessText(`对账完成：检查 ${result.checked} 条，回填 ${result.linked} 条`)
  loadCustom()
}
</script>

<style scoped src="./invoice-price-config.css"></style>
