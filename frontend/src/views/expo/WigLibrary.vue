<template>
  <div class="wig-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="wig-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div ref="panelRef" class="table-card wig-panel">
      <FilterBar :pending="keyword.trim() !== appliedKeyword" @search="applySearch" @reset="resetFilters">
        <el-input v-model="keyword" placeholder="搜索型号 / 名称" clearable prefix-icon="Search" class="filter-w-lg" />
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton variant="primary" left-icon="Plus" @click="openCreate">新建发型</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchWigs"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus :error="listResource.errorMessage.value" :loading="loading" :has-data="wigs.length > 0" @retry="fetchWigs" />
      <el-table :data="filteredWigs" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" style="width: 100%" v-sticky-scrollbar>
        <template #empty>
          <el-empty v-if="!loading && !listResource.error.value" :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column :sortable="false" v-if="visibleKeys.includes('cover')" label="封面" min-width="70">
          <template #default="{ row }">
            <el-image v-if="row.cover_url" :src="row.thumb_url || row.cover_url" :preview-src-list="[row.cover_url]" preview-teleported fit="cover" class="cover-thumb" />
            <span v-else class="cover-empty">无</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('model-no')" prop="model_no" label="型号" min-width="110" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="名称" min-width="130" show-overflow-tooltip />
        <el-table-column prop="series" v-if="visibleKeys.includes('series')" label="系列" min-width="100">
          <template #default="{ row }">
            <StatusBadge v-if="row.series === 'zhizhen'" size="small" class="tag-zhizhen">至臻</StatusBadge>
            <StatusBadge v-else size="small" effect="plain">经典</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column :sort-by="row => [...(row.fit_tags?.face_shapes || []).map(value => labelOf(FACE_SHAPES, value)), ...(row.fit_tags?.needs || []).map(value => labelOf(NEEDS, value))].join('、')" v-if="visibleKeys.includes('fit-tags')" label="适配标签" min-width="220">
          <template #default="{ row }">
            <StatusBadge v-for="f in row.fit_tags?.face_shapes || []" :key="'f-' + f" size="small" effect="plain" class="fit-tag">{{ labelOf(FACE_SHAPES, f) }}</StatusBadge>
            <StatusBadge v-for="n in row.fit_tags?.needs || []" :key="'n-' + n" size="small" effect="plain" type="warning" class="fit-tag">{{ labelOf(NEEDS, n) }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column :sort-by="row => (row.fit_tags?.sell_positions || []).join('、')" v-if="visibleKeys.includes('sell-positions')" label="销售定位" min-width="160">
          <template #default="{ row }">
            <StatusBadge v-for="p in row.fit_tags?.sell_positions || []" :key="'p-' + p" size="small" effect="plain" type="success" class="fit-tag">{{ p }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('priority')" prop="priority" label="优先级" min-width="80" sortable />
        <el-table-column prop="must_recommend" v-if="visibleKeys.includes('must-recommend')" label="主推" min-width="100">
          <template #default="{ row }">
            <StatusBadge v-if="row.must_recommend" type="danger" effect="plain" size="small">主推</StatusBadge>
            <span v-else style="color: var(--text-muted)">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" v-if="visibleKeys.includes('is-active')" label="启用" min-width="80">
          <template #default="{ row }">
            <el-switch :model-value="!!row.is_active" @change="(v) => toggleActive(row, v)" />
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="140" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'expo:admin'" variant="link" left-icon="Edit" @click="openEdit(row)">编辑</GlassButton>
            <GlassButton v-permission="'expo:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <DetailDrawer v-model="drawerVisible" :title="isEdit ? '编辑发型' : '新建发型'" :width="560" destroy-on-close>
      <el-form label-position="top" ref="formRef" :model="form" :rules="rules">
        <el-form-item label="型号" prop="model_no"><el-input v-model="form.model_no" placeholder="如 LS-101" /></el-form-item>
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" placeholder="发型名称" /></el-form-item>
        <el-form-item label="系列" prop="series">
          <el-radio-group v-model="form.series">
            <el-radio-button value="classic">经典款</el-radio-button>
            <el-radio-button value="zhizhen">至臻款</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="封面图">
          <el-upload :show-file-list="false" :http-request="uploadCover" accept="image/*">
            <el-image v-if="coverPreview" :src="coverPreview" fit="cover" class="upload-preview" />
            <div v-else class="upload-slot">+ 上传封面</div>
          </el-upload>
        </el-form-item>
        <el-form-item label="多角度图">
          <div class="angle-list">
            <div v-for="(p, i) in anglePhotos" :key="p.path" class="angle-item">
              <el-image :src="p.url" fit="cover" class="upload-preview" />
              <span class="angle-remove" @click="anglePhotos.splice(i, 1)">×</span>
            </div>
            <el-upload multiple :show-file-list="false" :http-request="uploadAngle" accept="image/*">
              <div class="upload-slot">+ 添加</div>
            </el-upload>
          </div>
        </el-form-item>
        <el-form-item label="发型描述"><el-input v-model="form.wig_description" type="textarea" :rows="3" placeholder="发型外观描述（用于试戴生成）" /></el-form-item>
        <el-form-item label="合成提示词"><el-input v-model="form.composite_prompt" type="textarea" :rows="3" placeholder="AI 合成 composite prompt" /></el-form-item>
        <el-form-item label="性别">
          <el-select v-model="form.fit_tags.gender" style="width: 100%">
            <el-option v-for="o in GENDERS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="适配脸型">
          <el-select v-model="form.fit_tags.face_shapes" multiple style="width: 100%">
            <el-option v-for="o in FACE_SHAPES" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="肤色深浅">
          <el-select v-model="form.fit_tags.skin_depths" multiple style="width: 100%">
            <el-option v-for="o in SKIN_DEPTHS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="冷暖调">
          <el-select v-model="form.fit_tags.undertones" multiple style="width: 100%">
            <el-option v-for="o in UNDERTONES" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="适配年龄">
          <el-select v-model="form.fit_tags.age_ranges" multiple filterable allow-create default-first-option placeholder="自由输入，如 35-45" style="width: 100%">
            <el-option v-for="o in ['25-35', '35-45', '45-55', '55+']" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="适配需求">
          <el-select v-model="form.fit_tags.needs" multiple style="width: 100%">
            <el-option v-for="o in NEEDS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="风格">
          <el-select v-model="form.fit_tags.styles" multiple style="width: 100%">
            <el-option v-for="o in STYLES" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="长度">
          <el-select v-model="form.fit_tags.length" style="width: 100%">
            <el-option v-for="o in LENGTHS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="职业场景">
          <el-select v-model="form.fit_tags.occupations" multiple filterable allow-create default-first-option placeholder="适合的职业人群，可自由输入" style="width: 100%">
            <el-option v-for="o in OCCUPATIONS" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="生活场景">
          <el-select v-model="form.fit_tags.life_scenes" multiple filterable allow-create default-first-option placeholder="适合的生活场合，可自由输入" style="width: 100%">
            <el-option v-for="o in LIFE_SCENES" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="销售定位">
          <el-select v-model="form.fit_tags.sell_positions" multiple filterable allow-create default-first-option placeholder="主推方向，如 减龄短发款 / 显精神款" style="width: 100%">
            <el-option v-for="o in SELL_POSITIONS" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="不适合人群">
          <el-select v-model="form.fit_tags.not_suitable" multiple filterable allow-create default-first-option placeholder="销售避坑提示，如 脖子短 / 下颌宽" style="width: 100%">
            <el-option v-for="o in NOT_SUITABLE" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="卖点"><el-input v-model="form.selling_points" type="textarea" :rows="2" placeholder="核心卖点+吸引点，供话术引用" /></el-form-item>
        <el-form-item label="销售描述"><el-input v-model="form.sales_description" type="textarea" :rows="3" placeholder="发型特点解说+门店一句话解说，供线索话术引用（不进生图，与「发型描述」分开）" /></el-form-item>
        <el-form-item label="证据引用">
          <el-select v-model="form.evidence_refs" multiple filterable allow-create default-first-option placeholder="自由输入证据编号 / 来源" style="width: 100%" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" :max="999" style="width: 100%" />
          <span style="color: var(--text-muted); font-size: 12px">数字越大，同评级内推荐分越高、排更前（小幅折算，封顶）</span>
        </el-form-item>
        <el-form-item label="主推">
          <el-switch v-model="form.must_recommend" />
          <span style="margin-left: 8px; color: var(--text-muted); font-size: 12px">开启后置顶推荐列表最前（不论脸型，仍按性别过滤，多款主推之间按匹配分排序）；建议少量款设为主推，过多会挤占匹配推荐位</span>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.is_active" /></el-form-item>

        <!-- 发色×三角度参考图：仅编辑态（需已保存的发型 id）；客户端只显示已备图的发色 -->
        <template v-if="isEdit">
          <el-divider content-position="left">发色 × 三角度参考图</el-divider>
          <p class="cm-hint">
            为各发色上传三角度实拍图，合成时直接照搬（含颜色）。<b>上传后点最底部「保存」一并生效</b>；
            某发色不备图则客户端走「原色」（发型自身多角度图）。
          </p>
          <ListPageStatus :error="matrixResource.errorMessage.value" :loading="colorMatrixLoading" :has-data="colorMatrix.length > 0" @retry="matrixResource.load()" />
          <div v-loading="colorMatrixLoading" class="cm-list">
            <div v-for="c in colorMatrix" :key="c.hair_color_id" class="cm-row" :class="{ dirty: c.dirty }">
              <div class="cm-color">
                <img v-if="c.swatch_url" :src="c.thumb_url || c.swatch_url" class="cm-sw" alt="" />
                <i v-else class="cm-sw" :style="{ background: c.hex || '#ccc' }" />
                <div class="cm-meta"><b>{{ c.name }}</b><small>{{ c.code }}</small></div>
                <span v-if="c.dirty" class="cm-unsaved">未保存</span>
              </div>
              <div class="angle-list">
                <div v-for="(p, i) in c.photos" :key="p.path" class="angle-item">
                  <el-image :src="p.url" fit="cover" class="upload-preview" />
                  <span class="angle-remove" @click="removeColorPhoto(c, i)">×</span>
                </div>
                <el-upload
                  v-if="c.photos.length + (c.reserving || 0) < 3" multiple :show-file-list="false"
                  :http-request="(o) => uploadColorAngle(c, o)" accept="image/*"
                >
                  <div class="upload-slot">+ 添加</div>
                </el-upload>
              </div>
            </div>
            <div v-if="!colorMatrixLoading && !matrixResource.error.value && !colorMatrix.length" class="cm-empty">
              发色库暂无启用发色，请先到发色库添加发色
            </div>
          </div>
        </template>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="drawerVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submit">保存</GlassButton>
      </template>
    </DetailDrawer>
  </div>
</template>

<script setup>import { msgWarning, msgSuccessText, confirmDanger, msgSuccess } from '@/utils/feedback'
import { ref, computed, onMounted, watch } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'


import {
  getWigs, createWig, updateWig, deleteWig, uploadWigPhoto,
  getWigColorImages, saveWigColorImages, deleteWigColorImages,
} from '@/api/expo'
import TableTools from '@/components/TableTools.vue'
import { useWigLibraryTable } from './composables/useWigLibraryTable'

// 选项词汇对齐《发型推荐分析表》的业务语言；value 是 AI 分析枚举，不可改
const FACE_SHAPES = [
  { value: 'oval', label: '鹅蛋脸' }, { value: 'round', label: '圆脸' }, { value: 'square', label: '方脸' },
  { value: 'heart', label: '心形/瓜子脸' }, { value: 'long', label: '长脸' }, { value: 'diamond', label: '菱形脸' },
]
const SKIN_DEPTHS = [
  { value: 'fair', label: '冷白/白皙' }, { value: 'light', label: '白皙黄皮' }, { value: 'medium', label: '自然黄皮' }, { value: 'tan', label: '小麦/深肤' },
]
const UNDERTONES = [{ value: 'cool', label: '冷调' }, { value: 'warm', label: '暖调' }, { value: 'neutral', label: '中性' }]
const NEEDS = [{ value: 'volume', label: '发量丰盈' }, { value: 'gray_cover', label: '白发遮盖' }, { value: 'style_change', label: '造型变换' }]
// 与 kiosk 登记页 style_pref、AI 分析 temperament 枚举三处同步（改一处必须同步另两处）
const STYLES = ['知性优雅', '减龄轻盈', '自然日常', '端庄大气', '温柔清纯', '时尚轻熟']
const GENDERS = [{ value: 'female', label: '女款' }, { value: 'male', label: '男款' }]
const LENGTHS = [{ value: 'short', label: '短发' }, { value: 'bob', label: '波波头' }, { value: 'shoulder', label: '及肩' }, { value: 'long', label: '长发' }]
// 以下四个维度来自《发型推荐分析表》，仅供销售侧参考，不参与匹配打分
const OCCUPATIONS = [
  '职场白领', '管理层', '教师', '医生', '美业从业者', '销售顾问',
  '门店老板', '培训讲师', '主播', '设计师', '学生', '行政前台', '客服',
]
const LIFE_SCENES = [
  '日常通勤', '逛街', '聚会', '拍照', '旅行', '约会',
  '见家长', '家庭聚餐', '咖啡厅', '展会', '直播间', '上学',
]
const SELL_POSITIONS = [
  '减龄短发款', '显精神款', '时尚气质款', '温柔气质款', '自然百搭款', '初戴推荐款',
  '显脸小款', '职场女性推荐款', '妈妈减龄款', '气质提升款', '形象提升款', '高级色款',
]
const NOT_SUITABLE = [
  '追求长发飘逸感', '喜欢强烈网红风', '头围特别大', '完全不化妆气色偏暗',
  '大脸盘', '下颌宽', '脖子短', '肩膀厚', '气质偏传统保守', '脸特别长', '不喜欢蓬松纹理感',
]

function labelOf(options, value) {
  return options.find((o) => o.value === value)?.label || value
}

const listResource = useAsyncResource(async (_, { signal }) => (await getWigs(undefined, { signal, suppressToast: true })).data || [])
const wigs = computed(() => listResource.data.value || [])
const loading = listResource.loading
const keyword = ref('')
const appliedKeyword = ref('')
function applySearch() { appliedKeyword.value = keyword.value.trim(); return fetchWigs() }
const filteredWigs = computed(() => {
  const kw = appliedKeyword.value.toLowerCase()
  if (!kw) return wigs.value
  return wigs.value.filter((w) => (w.model_no || '').toLowerCase().includes(kw) || (w.name || '').toLowerCase().includes(kw))
})

const drawerVisible = ref(false)
const isEdit = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref()
const coverPreview = ref('')
const anglePhotos = ref([]) // [{path, url}]
// 发色矩阵：每项 {hair_color_id, code, name, hex, swatch_url, has_images, saving, photos:[{path,url}]}
const matrixResource = useAsyncResource(async (wigId, { signal }) => wigId ? ((await getWigColorImages(wigId, { signal, suppressToast: true })).data || []).map(c => ({
  hair_color_id: c.hair_color_id, code: c.code, name: c.name,
  hex: c.hex, swatch_url: c.swatch_url, has_images: c.has_images, dirty: false,
  photos: (c.angle_photos || []).map((p, i) => ({ path: p, url: (c.angle_urls || [])[i] || `/${p}` })),
})) : [])
const colorMatrix = computed({ get: () => matrixResource.data.value || [], set: value => { matrixResource.data.value = value } })
const colorMatrixLoading = matrixResource.loading
watch(drawerVisible, opened => { if (!opened) matrixResource.load(null, { clear: true }) })

function emptyForm() {
  return {
    model_no: '', name: '', series: 'classic', cover_path: '',
    wig_description: '', composite_prompt: '', selling_points: '', sales_description: '',
    evidence_refs: [], priority: 0, must_recommend: false, is_active: true,
    fit_tags: {
      gender: 'female', face_shapes: [], skin_depths: [], undertones: [], age_ranges: [], needs: [], styles: [], length: '',
      occupations: [], life_scenes: [], sell_positions: [], not_suitable: [],
    },
  }
}
const form = ref(emptyForm())
const rules = {
  model_no: [{ required: true, message: '请输入型号', trigger: 'blur' }],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  series: [{ required: true, message: '请选择系列', trigger: 'change' }],
}

const fetchWigs = () => listResource.load()

const {
  columnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen,
  hasActiveFilters, resetFilters,
} = useWigLibraryTable(keyword, applySearch, appliedKeyword)

function toUpsert(src) {
  return {
    model_no: src.model_no, name: src.name, series: src.series,
    cover_path: src.cover_path || src.cover_url || '',
    angle_photos: src.angle_photos || [],
    wig_description: src.wig_description || '', composite_prompt: src.composite_prompt || '',
    fit_tags: src.fit_tags || {}, selling_points: src.selling_points || '',
    sales_description: src.sales_description || '',
    evidence_refs: src.evidence_refs || [], priority: src.priority || 0,
    must_recommend: !!src.must_recommend, is_active: !!src.is_active,
  }
}

function openCreate() {
  isEdit.value = false
  editId.value = null
  form.value = emptyForm()
  coverPreview.value = ''
  anglePhotos.value = []
  matrixResource.load(null, { clear: true }) // 新建态无 wig id，发色矩阵在首次保存后再编辑
  drawerVisible.value = true
}

function openEdit(row) {
  isEdit.value = true
  editId.value = row.id
  const ft = row.fit_tags || {}
  form.value = {
    ...toUpsert(row),
    fit_tags: {
      gender: ft.gender || 'female', face_shapes: ft.face_shapes || [], skin_depths: ft.skin_depths || [],
      undertones: ft.undertones || [], age_ranges: ft.age_ranges || [], needs: ft.needs || [],
      styles: ft.styles || [], length: ft.length || '',
      occupations: ft.occupations || [], life_scenes: ft.life_scenes || [],
      sell_positions: ft.sell_positions || [], not_suitable: ft.not_suitable || [],
    },
  }
  coverPreview.value = row.cover_url || ''
  // path 用于保存（裸相对路径），url 用于预览（带前导 / 的可访问地址，来自后端 angle_urls）
  const urls = row.angle_urls || []
  anglePhotos.value = (row.angle_photos || []).map((p, i) => ({ path: p, url: urls[i] || `/${p}` }))
  drawerVisible.value = true
  loadColorMatrix(row.id)
}

const loadColorMatrix = wigId => matrixResource.load(wigId, { clear: true })

// 支持一次多选：多张文件的回调near-同步触发,await 前 photos.length 还没涨,
// 光靠它判上限会全部放行→超 3 张。用 reserving 同步占坑,保证并发上传也卡在三张
async function uploadColorAngle(item, { file }) {
  if (item.photos.length + (item.reserving || 0) >= 3) {
    if (!item._warnedFull) { msgWarning('每个发色最多三张，多余的已忽略'); item._warnedFull = true }
    return
  }
  item.reserving = (item.reserving || 0) + 1
  item._warnedFull = false
  try {
    const res = await uploadWigPhoto(file)
    item.photos.push({ path: res.data.path, url: res.data.url })
    item.dirty = true // 待底部「保存」一并落库
  } catch { /* 拦截器已提示 */ } finally {
    item.reserving -= 1
  }
}

// 移除某张（本地暂存，随底部「保存」提交）
function removeColorPhoto(item, i) {
  item.photos.splice(i, 1)
  item.dirty = true
}

// 底部「保存」时随发型一起落库：改动过的发色行——有图 upsert、清空且原有图则删
async function reconcileColorMatrix() {
  for (const c of colorMatrix.value) {
    if (!c.dirty) continue
    if (c.photos.length) {
      await saveWigColorImages(editId.value, c.hair_color_id, { angle_photos: c.photos.map((p) => p.path) })
      c.has_images = true
    } else if (c.has_images) {
      await deleteWigColorImages(editId.value, c.hair_color_id)
      c.has_images = false
    }
    c.dirty = false
  }
}

async function uploadCover({ file }) {
  const res = await uploadWigPhoto(file)
  form.value.cover_path = res.data.path
  coverPreview.value = res.data.url
  msgSuccessText('封面上传成功')
}

// 支持一次多选：el-upload 逐文件回调本函数，缩略图逐张出现即反馈，不再逐张弹 toast（多选会刷屏）
async function uploadAngle({ file }) {
  const res = await uploadWigPhoto(file)
  anglePhotos.value.push({ path: res.data.path, url: res.data.url })
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const body = { ...toUpsert(form.value), angle_photos: anglePhotos.value.map((p) => p.path) }
    if (isEdit.value) {
      await updateWig(editId.value, body)
      await reconcileColorMatrix() // 发色三角度图随本次「保存」一并落库（去掉了逐行保存按钮）
      msgSuccessText('更新成功')
    } else {
      await createWig(body)
      msgSuccessText('创建成功')
    }
    drawerVisible.value = false
    fetchWigs()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function toggleActive(row, value) {
  try {
    await updateWig(row.id, { ...toUpsert(row), is_active: value })
    row.is_active = value
    msgSuccessText(value ? '已启用' : '已停用')
  } catch { /* 拦截器已提示 */ }
}

async function handleDelete(row) {
  try {
    await confirmDanger('删除', `发型 ${row.model_no}`, '将物理删除该发型及其封面/多角度图。已产生试戴记录的发型无法删除，请改用「停用」。')
  } catch { return }
  try {
    await deleteWig(row.id)
    msgSuccess('删除')
    fetchWigs()
  } catch { /* 拦截器已提示（含 409 已被引用） */ }
}

onMounted(fetchWigs)
</script>

<style scoped src="./wig-library.css"></style>
