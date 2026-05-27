<template>
  <div class="palette-page">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="filters.color_family" placeholder="色族" clearable>
        <el-option v-for="f in filterOptions.color_families" :key="f" :label="familyLabel(f)" :value="f" />
      </el-select>
      <el-select v-model="filters.source" placeholder="来源" clearable>
        <el-option v-for="s in filterOptions.sources" :key="s" :label="sourceLabel(s)" :value="s" />
      </el-select>
      <el-select v-model="filters.luminance_level" placeholder="明度" clearable>
        <el-option v-for="l in filterOptions.luminance_levels" :key="l" :label="l" :value="l" />
      </el-select>
      <el-input v-model="filters.keyword" placeholder="搜索色号/名称..." clearable style="width: 200px;" />
      <el-button type="primary" @click="loadData">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button v-if="canWrite" type="success" @click="openCreate">+ 新增色号</el-button>
    </div>

    <!-- 色块网格 -->
    <div v-loading="loading" class="palette-grid">
      <ColorBlock
        v-for="item in paletteList"
        :key="item.id"
        :code="item.industry_code"
        :name="item.display_name"
        :hex="item.hex_code"
        @click="openDetail(item)"
      />
    </div>

    <!-- 空状态 -->
    <el-empty v-if="!loading && !paletteList.length" description="暂无色号数据" />

    <!-- 分页 -->
    <el-pagination
      v-if="total > 0"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @change="loadData"
    />

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="formVisible" :title="formTitle" width="500px" destroy-on-close>
      <el-form ref="formRef" :model="formData" :rules="formRules" label-width="100px">
        <el-form-item label="标准色号" prop="industry_code">
          <el-input v-model="formData.industry_code" placeholder="如 #1, #613" />
        </el-form-item>
        <el-form-item label="展示名称" prop="display_name">
          <el-input v-model="formData.display_name" placeholder="中文名称" />
        </el-form-item>
        <el-form-item label="英文名称">
          <el-input v-model="formData.display_name_en" placeholder="英文名称（可选）" />
        </el-form-item>
        <el-form-item label="HEX 色值" prop="hex_code">
          <el-input v-model="formData.hex_code" placeholder="#6B5A52">
            <template #append>
              <el-color-picker v-model="formData.hex_code" show-alpha="false" />
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="色族" prop="color_family">
          <el-select v-model="formData.color_family" placeholder="选择色族">
            <el-option label="黑色系" value="black" />
            <el-option label="棕色系" value="brown" />
            <el-option label="金色系" value="blonde" />
            <el-option label="红色系" value="red" />
            <el-option label="银色系" value="silver" />
            <el-option label="vibrant" value="vibrant" />
          </el-select>
        </el-form-item>
        <el-form-item label="冷暖调">
          <el-radio-group v-model="formData.undertone">
            <el-radio-button label="warm">暖调</el-radio-button>
            <el-radio-button label="cool">冷调</el-radio-button>
            <el-radio-button label="neutral">中性</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="明度级别">
          <el-select v-model="formData.luminance_level" placeholder="选择明度" clearable>
            <el-option label="低" value="low" />
            <el-option label="中低" value="medium-low" />
            <el-option label="中" value="medium" />
            <el-option label="中高" value="medium-high" />
            <el-option label="高" value="high" />
            <el-option label="很高" value="very-high" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="formData.source" placeholder="选择来源">
            <el-option label="行业通用" value="industry" />
            <el-option label="Bellami" value="bellami" />
            <el-option label="Luxy" value="luxy" />
            <el-option label="Great Lengths" value="great_lengths" />
            <el-option label="莱莎" value="leshine" />
            <el-option label="Organic Hair" value="organic_hair" />
          </el-select>
        </el-form-item>
        <el-form-item label="莱莎库存">
          <el-switch v-model="formData.is_leshine_stock" />
        </el-form-item>
        <el-form-item label="高峰季节">
          <el-checkbox-group v-model="formData.peak_season_arr">
            <el-checkbox label="spring">春</el-checkbox>
            <el-checkbox label="summer">夏</el-checkbox>
            <el-checkbox label="autumn">秋</el-checkbox>
            <el-checkbox label="winter">冬</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 详情弹窗 -->
    <ColorDetailModal
      v-model="detailVisible"
      :title="detailData.display_name || '色号详情'"
      :hex="detailData.hex_code"
      :rgb="[detailData.rgb_r, detailData.rgb_g, detailData.rgb_b]"
      :lab="detailData.lab ? [detailData.lab_l, detailData.lab_a, detailData.lab_b_val] : []"
      :hsl="detailData.hsl_h ? [detailData.hsl_h, detailData.hsl_s, detailData.hsl_l] : []"
      :undertone="detailData.undertone"
      :color-family="detailData.color_family"
      :luminance-level="detailData.luminance_level"
      :is-leshine-stock="!!detailData.is_leshine_stock"
      :peak-season="detailData.peak_season"
      :pantone-tcx="detailData.pantone_tcx"
      :pantone-delta-e="detailData.pantone_delta_e"
      :can-edit="canWrite"
      :can-delete="canAdmin"
      @edit="openEdit(detailData)"
      @delete="confirmDelete(detailData)"
      @generate-swatch="generateSwatch(detailData)"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  createColor,
  deleteColor,
  getColorFilterOptions,
  getColors,
  updateColor,
  generateSwatch as apiGenerateSwatch,
} from '@/api/color'
import { useTableSort } from '@/composables/useTableSort'
import ColorBlock from './components/ColorBlock.vue'
import ColorDetailModal from './components/ColorDetailModal.vue'

const authStore = useAuthStore()
const orderSort = useTableSort()
const canWrite = computed(() => authStore.hasPermission('color:write'))
const canAdmin = computed(() => authStore.hasPermission('color:admin'))

// 列表状态
const loading = ref(false)
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const paletteList = ref([])
const filterOptions = reactive({ color_families: [], sources: [], luminance_levels: [] })

const filters = reactive({
  color_family: '',
  source: '',
  luminance_level: '',
  keyword: '',
})

// 表单状态
const formVisible = ref(false)
const formTitle = ref('新增色号')
const formRef = ref(null)
const submitting = ref(false)
const editingId = ref(null)

const formData = reactive({
  industry_code: '',
  display_name: '',
  display_name_en: '',
  hex_code: '#6B5A52',
  color_family: 'brown',
  undertone: 'warm',
  luminance_level: '',
  source: 'industry',
  is_leshine_stock: false,
  peak_season_arr: [],
})

const formRules = {
  industry_code: [{ required: true, message: '请输入标准色号', trigger: 'blur' }],
  display_name: [{ required: true, message: '请输入展示名称', trigger: 'blur' }],
  hex_code: [
    { required: true, message: '请输入 HEX 色值', trigger: 'blur' },
    { pattern: /^#[0-9A-Fa-f]{6}$/, message: 'HEX 格式错误', trigger: 'blur' },
  ],
  color_family: [{ required: true, message: '请选择色族', trigger: 'change' }],
}

// 详情弹窗
const detailVisible = ref(false)
const detailData = ref({})

onMounted(() => {
  loadFilterOptions()
  loadData()
})

async function loadFilterOptions() {
  try {
    const res = await getColorFilterOptions()
    if (res.data?.code === 200) {
      Object.assign(filterOptions, res.data.data)
    }
  } catch {
    // ignore
  }
}

async function loadData() {
  loading.value = true
  try {
    const res = await getColors({
      page: page.value,
      page_size: pageSize.value,
      ...filters,
      ...orderSort.sortParams.value,
    })
    if (res.data?.code === 200) {
      paletteList.value = res.data.data.items || []
      total.value = res.data.data.total || 0
    }
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.color_family = ''
  filters.source = ''
  filters.luminance_level = ''
  filters.keyword = ''
  page.value = 1
  orderSort.reset()
  loadData()
}

function openCreate() {
  editingId.value = null
  formTitle.value = '新增色号'
  Object.assign(formData, {
    industry_code: '',
    display_name: '',
    display_name_en: '',
    hex_code: '#6B5A52',
    color_family: 'brown',
    undertone: 'warm',
    luminance_level: '',
    source: 'industry',
    is_leshine_stock: false,
    peak_season_arr: [],
  })
  formVisible.value = true
}

function openEdit(item) {
  detailVisible.value = false
  editingId.value = item.id
  formTitle.value = '编辑色号'
  Object.assign(formData, {
    industry_code: item.industry_code,
    display_name: item.display_name,
    display_name_en: item.display_name_en || '',
    hex_code: item.hex_code,
    color_family: item.color_family,
    undertone: item.undertone || 'warm',
    luminance_level: item.luminance_level || '',
    source: item.source,
    is_leshine_stock: !!item.is_leshine_stock,
    peak_season_arr: item.peak_season ? item.peak_season.split(',') : [],
  })
  formVisible.value = true
}

async function submitForm() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload = {
      ...formData,
      is_leshine_stock: formData.is_leshine_stock ? 1 : 0,
      peak_season: formData.peak_season_arr.join(','),
    }
    if (editingId.value) {
      await updateColor(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await createColor(payload)
      ElMessage.success('创建成功')
    }
    formVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '操作失败')
  } finally {
    submitting.value = false
  }
}

function openDetail(item) {
  detailData.value = item
  detailVisible.value = true
}

async function confirmDelete(item) {
  try {
    await ElMessageBox.confirm(`确定删除色号 ${item.industry_code} 吗？`, '确认删除', { type: 'warning' })
    await deleteColor(item.id)
    ElMessage.success('删除成功')
    detailVisible.value = false
    loadData()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.message || '删除失败')
    }
  }
}

async function generateSwatch(item) {
  try {
    const res = await apiGenerateSwatch({ color_id: item.id, style: 'swatch_card' })
    if (res.data?.code === 201) {
      ElMessage.success(`生成任务已创建 (ID: ${res.data.data.task_id})`)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '创建失败')
  }
}

function familyLabel(f) {
  const map = { black: '黑色系', brown: '棕色系', blonde: '金色系', red: '红色系', silver: '银色系', vibrant: 'vibrant' }
  return map[f] || f
}

function sourceLabel(s) {
  const map = { industry: '行业通用', bellami: 'Bellami', luxy: 'Luxy', great_lengths: 'Great Lengths', leshine: '莱莎', organic_hair: 'Organic Hair' }
  return map[s] || s
}
</script>

<style scoped>
.palette-page {
  padding: 20px;
}
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  align-items: center;
}
.palette-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
</style>
