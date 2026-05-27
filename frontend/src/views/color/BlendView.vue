<template>
  <div class="blend-page">
    <div class="filter-bar">
      <el-select v-model="filters.blend_type" placeholder="混合类型" clearable>
        <el-option label="钢琴色 (Piano)" value="piano" />
        <el-option label="渐变 (Ombre)" value="ombre" />
        <el-option label="画染 (Balayage)" value="balayage" />
        <el-option label="发根深色 (Rooted)" value="rooted" />
        <el-option label="三色混编" value="tri-blend" />
        <el-option label="多色混编" value="multi-blend" />
      </el-select>
      <el-select v-model="filters.source" placeholder="来源" clearable>
        <el-option v-for="s in filterOptions.sources" :key="s" :label="sourceLabel(s)" :value="s" />
      </el-select>
      <el-input v-model="filters.keyword" placeholder="搜索编码/名称..." clearable style="width: 200px;" />
      <el-button type="primary" @click="loadData">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button v-if="canWrite" type="success" @click="openCreate">+ 新增混合色</el-button>
    </div>

    <el-table v-loading="loading" :data="blendList" style="width: 100%;" @sort-change="orderSort.onSortChange">
      <el-table-column label="综合色" width="80">
        <template #default="{ row }">
          <div class="blend-preview" :style="{ backgroundColor: row.computed_hex }"></div>
        </template>
      </el-table-column>
      <el-table-column prop="blend_code" label="编码" width="120" sortable="custom" />
      <el-table-column prop="display_name" label="名称" sortable="custom" />
      <el-table-column prop="blend_type" label="类型" width="120" sortable="custom">
        <template #default="{ row }">
          <el-tag size="small">{{ blendTypeLabel(row.blend_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="成分" min-width="200">
        <template #default="{ row }">
          <div class="component-tags">
            <el-tag
              v-for="c in row.components"
              :key="c.id"
              size="small"
              :style="{ borderColor: c.palette?.hex_code }"
            >
              {{ c.palette?.industry_code }} {{ Math.round((c.weight || 0) * 100) }}%
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="120">
        <template #default="{ row }">
          {{ sourceLabel(row.source) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button v-if="canWrite" size="small" type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canAdmin" size="small" type="danger" @click="confirmDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

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
    <el-dialog v-model="formVisible" :title="formTitle" width="700px" destroy-on-close>
      <el-form ref="formRef" :model="formData" :rules="formRules" label-width="100px">
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
        <div class="components-section">
          <div v-for="(comp, idx) in formData.components" :key="idx" class="component-row">
            <el-select v-model="comp.palette_id" placeholder="选择基础色" style="width: 200px;" filterable>
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
            <el-button type="danger" size="small" circle @click="removeComponent(idx)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button type="primary" plain @click="addComponent">+ 添加成分</el-button>
          <div class="weight-summary">
            权重总和: <el-tag :type="weightTotalValid ? 'success' : 'danger'">{{ weightTotal.toFixed(2) }}</el-tag>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!weightTotalValid" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="混合色详情" width="600px" destroy-on-close>
      <div v-if="detailData" class="blend-detail">
        <div class="detail-header">
          <div class="big-preview" :style="{ backgroundColor: detailData.computed_hex }"></div>
          <div class="detail-info">
            <h3>{{ detailData.display_name }}</h3>
            <p>{{ detailData.blend_code }}</p>
            <el-tag>{{ blendTypeLabel(detailData.blend_type) }}</el-tag>
            <el-tag type="info">{{ sourceLabel(detailData.source) }}</el-tag>
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
          <el-table :data="detailData.components" size="small">
            <el-table-column label="色块" width="60">
              <template #default="{ row }">
                <div class="mini-color" :style="{ backgroundColor: row.palette?.hex_code }"></div>
              </template>
            </el-table-column>
            <el-table-column prop="palette.industry_code" label="色号" width="80" />
            <el-table-column prop="palette.display_name" label="名称" />
            <el-table-column prop="position" label="位置" width="80">
              <template #default="{ row }">{{ positionLabel(row.position) }}</template>
            </el-table-column>
            <el-table-column prop="weight" label="权重" width="80">
              <template #default="{ row }">{{ Math.round((row.weight || 0) * 100) }}%</template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  createBlend,
  deleteBlend,
  getBlendFilterOptions,
  getBlends,
  getColors,
  updateBlend,
} from '@/api/color'
import { useTableSort } from '@/composables/useTableSort'
import GradientBar from './components/GradientBar.vue'

const authStore = useAuthStore()
const orderSort = useTableSort()
const canWrite = computed(() => authStore.hasPermission('color:write'))
const canAdmin = computed(() => authStore.hasPermission('color:admin'))

const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const blendList = ref([])
const filterOptions = reactive({ blend_types: [], sources: [] })
const paletteOptions = ref([])

const filters = reactive({ blend_type: '', source: '', keyword: '' })

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
  loadData()
})

async function loadFilterOptions() {
  try {
    const res = await getBlendFilterOptions()
    if (res.data?.code === 200) Object.assign(filterOptions, res.data.data)
  } catch { /* ignore */ }
}

async function loadPaletteOptions() {
  try {
    const res = await getColors({ page_size: 1000 })
    if (res.data?.code === 200) {
      paletteOptions.value = res.data.data.items || []
    }
  } catch { /* ignore */ }
}

async function loadData() {
  loading.value = true
  try {
    const res = await getBlends({
      page: page.value,
      page_size: pageSize.value,
      ...filters,
      ...orderSort.sortParams.value,
    })
    if (res.data?.code === 200) {
      blendList.value = res.data.data.items || []
      total.value = res.data.data.total || 0
    }
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  Object.keys(filters).forEach(k => filters[k] = '')
  page.value = 1
  orderSort.reset()
  loadData()
}

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
    ElMessage.error('成分权重总和必须等于1')
    return
  }
  if (formData.components.length < 2) {
    ElMessage.error('混合色至少需要2个成分')
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
      ElMessage.success('更新成功')
    } else {
      await createBlend(payload)
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

function openDetail(row) {
  detailData.value = row
  detailVisible.value = true
}

async function confirmDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除混合色 ${row.blend_code} 吗？`, '确认删除', { type: 'warning' })
    await deleteBlend(row.id)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.message || '删除失败')
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

<style scoped>
.blend-page { padding: 20px; }
.filter-bar { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }
.blend-preview { width: 40px; height: 40px; border-radius: 6px; border: 1px solid var(--el-border-color-lighter); }
.component-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.components-section { padding: 0 12px; }
.component-row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.weight-summary { margin-top: 12px; text-align: right; }
.option-color { display: inline-block; width: 14px; height: 14px; border-radius: 3px; margin-right: 8px; vertical-align: middle; border: 1px solid var(--el-border-color-lighter); }
.blend-detail { padding: 8px; }
.detail-header { display: flex; gap: 16px; margin-bottom: 20px; }
.big-preview { width: 100px; height: 100px; border-radius: 10px; border: 1px solid var(--el-border-color-lighter); flex-shrink: 0; }
.detail-info h3 { margin: 0 0 8px; font-size: 18px; }
.detail-info p { margin: 0 0 8px; color: var(--el-text-color-secondary); font-family: monospace; }
.blend-bar-section { margin-bottom: 20px; }
.section-title { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.blend-bar-wrapper { height: 40px; border-radius: 8px; overflow: hidden; border: 1px solid var(--el-border-color-lighter); }
.mini-color { width: 20px; height: 20px; border-radius: 4px; border: 1px solid var(--el-border-color-lighter); }
</style>
