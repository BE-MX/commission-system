<template>
  <div class="blend-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="blend-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 混合色表格：筛选区 + 操作行 + 表格 + 分页同在卡片内（List Page Spec） -->
    <section ref="panelRef" class="table-card blend-panel">
      <FilterBar class="toolbar" :loading="loading" :pending="listPageState.hasPendingSearch.value" @search="handleSearch" @reset="resetFilters">
        <el-select v-model="filters.blend_type" placeholder="混合类型" clearable class="filter-w-sm">
          <el-option label="钢琴色 (Piano)" value="piano" />
          <el-option label="渐变 (Ombre)" value="ombre" />
          <el-option label="画染 (Balayage)" value="balayage" />
          <el-option label="发根深色 (Rooted)" value="rooted" />
          <el-option label="三色混编" value="tri-blend" />
          <el-option label="多色混编" value="multi-blend" />
        </el-select>
        <el-select v-model="filters.source" placeholder="来源" clearable class="filter-w-sm">
          <el-option v-for="s in filterOptions.sources" :key="s" :label="sourceLabel(s)" :value="s" />
        </el-select>
        <el-input v-model="filters.keyword" placeholder="搜索编码/名称..." clearable class="filter-w-md" />
      </FilterBar>
    <ListPageStatus v-if="filterResource.error.value" :paged="false" :error="filterResource.errorMessage.value" :loading="filterResource.loading.value" :has-data="filterResource.hasLoaded.value" @retry="loadFilterOptions" />

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-if="canWrite" variant="primary" :left-icon="Plus" @click="openCreate">新增混合色</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="loadData"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listPageState.hasData.value" :error="listPageState.errorMessage.value" :loading="loading" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="loadData" />
      <el-table v-loading="loading" :data="blendList" class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" @sort-change="handleSortChange" border>
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="loading" :has-data="false" @retry="loadData">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
      <el-table-column v-if="visibleKeys.includes('preview')" label="综合色" min-width="80">
        <template #default="{ row }">
          <div class="blend-preview" :style="{ backgroundColor: row.computed_hex }"></div>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('blend-code')" prop="blend_code" label="编码" min-width="120" sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('display-name')" prop="display_name" label="名称" sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('blend-type')" prop="blend_type" label="类型" min-width="120" sortable="custom">
        <template #default="{ row }">
          <StatusBadge size="small">{{ blendTypeLabel(row.blend_type) }}</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('components')" label="成分" min-width="200">
        <template #default="{ row }">
          <div class="component-tags">
            <StatusBadge
              v-for="c in row.components"
              :key="c.id"
              size="small"
              :style="{ borderColor: c.palette?.hex_code }"
            >
              {{ c.palette?.industry_code }} {{ Math.round((c.weight || 0) * 100) }}%
            </StatusBadge>
          </div>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('source')" prop="source" label="来源" min-width="120">
        <template #default="{ row }">
          {{ sourceLabel(row.source) }}
        </template>
      </el-table-column>
      <el-table-column class-name="table-action-column" label="操作" min-width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">
            <el-icon><View /></el-icon> 详情
          </el-button>
          <el-button v-if="canWrite" link type="primary" @click="openEdit(row)">
            <el-icon><Edit /></el-icon> 编辑
          </el-button>
          <el-button v-if="canAdmin" link type="danger" @click="confirmDelete(row)">
            <el-icon><Delete /></el-icon> 删除
          </el-button>
        </template>
      </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </section>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="formVisible" :title="formTitle" width="760px" destroy-on-close>
      <el-form label-position="top" ref="formRef" :model="formData" :rules="formRules">
        <el-form-item label="混合编码" prop="blend_code">
          <el-input v-model="formData.blend_code" placeholder="如 #8/60, #1C/18" />
        </el-form-item>
        <el-form-item label="展示名称" prop="display_name">
          <el-input v-model="formData.display_name" />
        </el-form-item>
        <el-form-item label="英文名称">
          <el-input v-model="formData.display_name_en" />
        </el-form-item>
        <el-form-item label="混合类型" prop="blend_type">
          <el-select v-model="formData.blend_type" placeholder="选择类型">
            <el-option label="钢琴色 (Piano)" value="piano" />
            <el-option label="渐变 (Ombre)" value="ombre" />
            <el-option label="画染 (Balayage)" value="balayage" />
            <el-option label="发根深色 (Rooted)" value="rooted" />
            <el-option label="三色混编" value="tri-blend" />
            <el-option label="多色混编" value="multi-blend" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源" prop="source">
          <el-select v-model="formData.source">
            <el-option label="Bellami" value="bellami" />
            <el-option label="Luxy" value="luxy" />
            <el-option label="Great Lengths" value="great_lengths" />
            <el-option label="莱莎" value="leshine" />
            <el-option label="Organic Hair" value="organic_hair" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="品牌命名">
          <el-input v-model="formData.brand_name" placeholder="如 Vanilla Latte（可选）" />
        </el-form-item>

        <!-- 成分配置 -->
        <el-divider>成分配置</el-divider>
        <ListPageStatus :paged="false" :error="paletteResource.errorMessage.value" :loading="paletteResource.loading.value" :has-data="paletteResource.hasData.value" @retry="loadPaletteOptions"><el-empty v-if="!paletteOptions.length" description="暂无可选基础色" :image-size="96" /></ListPageStatus>
        <div class="components-section">
          <div v-for="(comp, idx) in formData.components" :key="idx" class="component-row">
            <el-select v-model="comp.palette_id" :loading="paletteResource.loading.value" placeholder="选择基础色" style="width: 200px;" filterable>
              <el-option
                v-for="p in paletteOptions"
                :key="p.id"
                :label="`${p.industry_code} ${p.display_name}`"
                :value="p.id"
              >
                <span class="option-color" :style="{ backgroundColor: p.hex_code }"></span>
                <span>{{ p.industry_code }} {{ p.display_name }}</span>
              </el-option>
            </el-select>
            <el-select v-model="comp.position" placeholder="位置" style="width: 120px;">
              <el-option label="发根" value="root" />
              <el-option label="发中" value="mid" />
              <el-option label="发尾" value="end" />
              <el-option label="高光" value="highlight" />
              <el-option label="均匀" value="even" />
            </el-select>
            <el-input-number v-model="comp.weight" :min="0" :max="1" :step="0.05" :precision="2" style="width: 120px;" />
            <el-button type="danger" circle @click="removeComponent(idx)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button type="primary" plain @click="addComponent">+ 添加成分</el-button>
          <div class="weight-summary">
            权重总和: <StatusBadge :type="weightTotalValid ? 'success' : 'danger'">{{ weightTotal.toFixed(2) }}</StatusBadge>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!weightTotalValid" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 详情弹窗 -->
    <DetailDrawer v-model="detailVisible" title="混合色详情" width="640px" destroy-on-close>
      <div v-if="detailData" class="blend-detail">
        <div class="detail-header">
          <div class="big-preview" :style="{ backgroundColor: detailData.computed_hex }"></div>
          <div class="detail-info">
            <h3>{{ detailData.display_name }}</h3>
            <p>{{ detailData.blend_code }}</p>
            <StatusBadge>{{ blendTypeLabel(detailData.blend_type) }}</StatusBadge>
            <StatusBadge type="info">{{ sourceLabel(detailData.source) }}</StatusBadge>
          </div>
        </div>
        <div class="blend-bar-section">
          <p class="section-title">渐变色条</p>
          <div class="blend-bar-wrapper">
            <GradientBar :components="detailData.components" :blend-type="detailData.blend_type" />
          </div>
        </div>
        <div class="components-detail">
          <p class="section-title">成分明细</p>
          <el-table :data="detailData.components" size="small" border class="list-table">
            <el-table-column label="色块" min-width="60">
              <template #default="{ row }">
                <div class="mini-color" :style="{ backgroundColor: row.palette?.hex_code }"></div>
              </template>
            </el-table-column>
            <el-table-column prop="palette.industry_code" label="色号" min-width="80" />
            <el-table-column prop="palette.display_name" label="名称" />
            <el-table-column prop="position" label="位置" min-width="80">
              <template #default="{ row }">{{ positionLabel(row.position) }}</template>
            </el-table-column>
            <el-table-column prop="weight" label="权重" min-width="80">
              <template #default="{ row }">{{ Math.round((row.weight || 0) * 100) }}%</template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </DetailDrawer>
  </div>
</template>

<script setup>import { msgError, msgSuccessText, confirmAction } from '@/utils/feedback'
import { computed, onMounted, reactive, ref } from 'vue'

import { Delete, Edit, Plus, RefreshLeft, Search, View } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  createBlend,
  deleteBlend,
  getBlendFilterOptions,
  getBlends,
  getAllColorsForSelection,
  updateBlend,
} from '@/api/color'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useListPage } from '@/composables/useListPage'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import GradientBar from './components/GradientBar.vue'

const authStore = useAuthStore()
const orderSort = useTableSort()
function handleSortChange(event) { orderSort.onSortChange(event); return listPageState.handleSortChange({ sort_field: orderSort.sortField.value, sort_order: orderSort.sortOrder.value }) }
const canWrite = computed(() => authStore.hasPermission('color:write'))
const canAdmin = computed(() => authStore.hasPermission('color:admin'))

const listPageState = useListPage(async (params, { signal }) => (await getBlends(params, { signal, suppressToast: true })).data, { searchForm: { blend_type: '', source: '', keyword: '', sort_field: '', sort_order: '' } })
const { loading, page, pageSize, total, list: blendList, searchForm: filters, fetchList: loadData, handleSearch, handleReset: resetFilters, handlePageChange, handleSizeChange } = listPageState
const filterResource = useAsyncResource(async (_, { signal }) =>
  (await getBlendFilterOptions({ signal, suppressToast: true })).data, { initialData: { blend_types: [], sources: [] } })
const filterOptions = filterResource.data
const paletteResource = useAsyncResource(async (_, { signal }) => getAllColorsForSelection({ signal, suppressToast: true }), { initialData: [] })
const paletteOptions = paletteResource.data

const hasActiveFilters = computed(() => {
  const applied = listPageState.appliedSearchForm.value
  return Boolean(applied.blend_type || applied.source || applied.keyword)
})

// 列显隐元数据：TableTools 列设置面板的数据源（模板列保持静态，操作列不进配置）
const columnDefs = [
  { key: 'preview', label: '综合色' },
  { key: 'blend-code', label: '编码' },
  { key: 'display-name', label: '名称' },
  { key: 'blend-type', label: '类型' },
  { key: 'components', label: '成分' },
  { key: 'source', label: '来源' },
]
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('blend-view', columnDefs)

const formVisible = ref(false)
const formTitle = ref('新增混合色')
const formRef = ref(null)
const submitting = ref(false)
const editingId = ref(null)

const formData = reactive({
  blend_code: '',
  display_name: '',
  display_name_en: '',
  blend_type: 'piano',
  source: 'leshine',
  brand_name: '',
  components: [],
})

const formRules = {
  blend_code: [{ required: true, message: '请输入混合编码', trigger: 'blur' }],
  display_name: [{ required: true, message: '请输入展示名称', trigger: 'blur' }],
  blend_type: [{ required: true, message: '请选择混合类型', trigger: 'change' }],
  source: [{ required: true, message: '请选择来源', trigger: 'change' }],
}

const weightTotal = computed(() =>
  formData.components.reduce((sum, c) => sum + (c.weight || 0), 0)
)
const weightTotalValid = computed(() => Math.abs(weightTotal.value - 1.0) <= 0.02)

const detailVisible = ref(false)
const detailData = ref(null)

onMounted(() => {
  loadFilterOptions()
  loadPaletteOptions()
})

function loadFilterOptions() { return filterResource.load() }

function loadPaletteOptions() { return paletteResource.load() }





function addComponent() {
  formData.components.push({
    palette_id: null,
    position: 'even',
    weight: 0.5,
    sort_order: formData.components.length,
  })
}

function removeComponent(idx) {
  formData.components.splice(idx, 1)
}

function openCreate() {
  editingId.value = null
  formTitle.value = '新增混合色'
  Object.assign(formData, {
    blend_code: '',
    display_name: '',
    display_name_en: '',
    blend_type: 'piano',
    source: 'leshine',
    brand_name: '',
    components: [{ palette_id: null, position: 'even', weight: 0.5, sort_order: 0 }],
  })
  formVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  formTitle.value = '编辑混合色'
  Object.assign(formData, {
    blend_code: row.blend_code,
    display_name: row.display_name,
    display_name_en: row.display_name_en || '',
    blend_type: row.blend_type,
    source: row.source,
    brand_name: row.brand_name || '',
    components: row.components?.map((c, i) => ({
      palette_id: c.palette_id,
      position: c.position || 'even',
      weight: c.weight || 0.5,
      sort_order: c.sort_order || i,
    })) || [],
  })
  formVisible.value = true
}

async function submitForm() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (!weightTotalValid.value) {
    msgError('成分权重总和必须等于1')
    return
  }
  if (formData.components.length < 2) {
    msgError('混合色至少需要2个成分')
    return
  }

  submitting.value = true
  try {
    const payload = {
      ...formData,
      components: formData.components.map((c, i) => ({
        palette_id: c.palette_id,
        position: c.position,
        weight: c.weight,
        sort_order: i,
      })),
    }
    if (editingId.value) {
      await updateBlend(editingId.value, payload)
      msgSuccessText('更新成功')
    } else {
      await createBlend(payload)
      msgSuccessText('创建成功')
    }
    formVisible.value = false
    await (editingId.value ? listPageState.refreshUpdate() : listPageState.refreshCreate())
  } catch (e) {
    msgError(e.response?.data?.message || '操作失败', e)
  } finally {
    submitting.value = false
  }
}

function openDetail(row) {
  detailData.value = row
  detailVisible.value = true
}

async function confirmDelete(row) {
  try {
    await confirmAction(`确定删除混合色 ${row.blend_code} 吗？`, '确认删除', { type: 'warning' })
    await deleteBlend(row.id)
    msgSuccessText('删除成功')
    await listPageState.refreshRemove()
  } catch (e) {
    if (e !== 'cancel') msgError(e.response?.data?.message || '删除失败', e)
  }
}

function blendTypeLabel(t) {
  const map = { piano: '钢琴色', ombre: '渐变', balayage: '画染', rooted: '发根深色', 'tri-blend': '三色混编', 'multi-blend': '多色混编' }
  return map[t] || t
}

function sourceLabel(s) {
  const map = { bellami: 'Bellami', luxy: 'Luxy', great_lengths: 'Great Lengths', leshine: '莱莎', organic_hair: 'Organic Hair', custom: '自定义' }
  return map[s] || s
}

function positionLabel(p) {
  const map = { root: '发根', mid: '发中', end: '发尾', highlight: '高光', even: '均匀' }
  return map[p] || p
}
</script>

<style scoped src="./blend-view.css"></style>
