<template>
  <div class="wig-page">
    <el-row :gutter="16" class="toolbar">
      <el-col :span="8">
        <el-input v-model="keyword" placeholder="搜索型号 / 名称" clearable prefix-icon="Search" />
      </el-col>
      <el-col :span="16">
        <GlassButton variant="primary" left-icon="Plus" @click="openCreate">新建发型</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card">
      <el-table :data="filteredWigs" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column label="封面" min-width="70">
          <template #default="{ row }">
            <el-image v-if="row.cover_url" :src="row.cover_url" :preview-src-list="[row.cover_url]" preview-teleported fit="cover" class="cover-thumb" />
            <span v-else class="cover-empty">无</span>
          </template>
        </el-table-column>
        <el-table-column prop="model_no" label="型号" min-width="110" show-overflow-tooltip />
        <el-table-column prop="name" label="名称" min-width="130" show-overflow-tooltip />
        <el-table-column label="系列" min-width="90">
          <template #default="{ row }">
            <el-tag v-if="row.series === 'zhizhen'" size="small" class="tag-zhizhen">至臻</el-tag>
            <el-tag v-else size="small" effect="plain">经典</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="适配标签" min-width="220">
          <template #default="{ row }">
            <el-tag v-for="f in row.fit_tags?.face_shapes || []" :key="'f-' + f" size="small" effect="plain" class="fit-tag">{{ labelOf(FACE_SHAPES, f) }}</el-tag>
            <el-tag v-for="n in row.fit_tags?.needs || []" :key="'n-' + n" size="small" effect="plain" type="warning" class="fit-tag">{{ labelOf(NEEDS, n) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="销售定位" min-width="160">
          <template #default="{ row }">
            <el-tag v-for="p in row.fit_tags?.sell_positions || []" :key="'p-' + p" size="small" effect="plain" type="success" class="fit-tag">{{ p }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" min-width="80" sortable />
        <el-table-column label="启用" min-width="80">
          <template #default="{ row }">
            <el-switch :model-value="!!row.is_active" @change="(v) => toggleActive(row, v)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="140" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'expo:admin'" variant="link" left-icon="Edit" @click="openEdit(row)">编辑</GlassButton>
            <GlassButton v-permission="'expo:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawerVisible" :title="isEdit ? '编辑发型' : '新建发型'" :size="560" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
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
            <el-upload :show-file-list="false" :http-request="uploadAngle" accept="image/*">
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
        <el-form-item label="卖点"><el-input v-model="form.selling_points" type="textarea" :rows="2" placeholder="核心卖点，供话术引用" /></el-form-item>
        <el-form-item label="证据引用">
          <el-select v-model="form.evidence_refs" multiple filterable allow-create default-first-option placeholder="自由输入证据编号 / 来源" style="width: 100%" />
        </el-form-item>
        <el-form-item label="优先级"><el-input-number v-model="form.priority" :min="0" :max="999" style="width: 100%" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="drawerVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submit">保存</GlassButton>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getWigs, createWig, updateWig, deleteWig, uploadWigPhoto } from '@/api/expo'
import { confirmDanger, msgSuccess } from '@/utils/feedback'

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

const wigs = ref([])
const loading = ref(false)
const keyword = ref('')
const filteredWigs = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
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

function emptyForm() {
  return {
    model_no: '', name: '', series: 'classic', cover_path: '',
    wig_description: '', composite_prompt: '', selling_points: '',
    evidence_refs: [], priority: 0, is_active: true,
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

async function fetchWigs() {
  loading.value = true
  try {
    const res = await getWigs()
    wigs.value = res.data || []
  } finally {
    loading.value = false
  }
}

function toUpsert(src) {
  return {
    model_no: src.model_no, name: src.name, series: src.series,
    cover_path: src.cover_path || src.cover_url || '',
    angle_photos: src.angle_photos || [],
    wig_description: src.wig_description || '', composite_prompt: src.composite_prompt || '',
    fit_tags: src.fit_tags || {}, selling_points: src.selling_points || '',
    evidence_refs: src.evidence_refs || [], priority: src.priority || 0, is_active: !!src.is_active,
  }
}

function openCreate() {
  isEdit.value = false
  editId.value = null
  form.value = emptyForm()
  coverPreview.value = ''
  anglePhotos.value = []
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
}

async function uploadCover({ file }) {
  const res = await uploadWigPhoto(file)
  form.value.cover_path = res.data.path
  coverPreview.value = res.data.url
  ElMessage.success('封面上传成功')
}

async function uploadAngle({ file }) {
  const res = await uploadWigPhoto(file)
  anglePhotos.value.push({ path: res.data.path, url: res.data.url })
  ElMessage.success('图片上传成功')
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const body = { ...toUpsert(form.value), angle_photos: anglePhotos.value.map((p) => p.path) }
    if (isEdit.value) {
      await updateWig(editId.value, body)
      ElMessage.success('更新成功')
    } else {
      await createWig(body)
      ElMessage.success('创建成功')
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
    ElMessage.success(value ? '已启用' : '已停用')
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

<style scoped>
.toolbar { margin-bottom: 16px; }
.cover-thumb { width: 40px; height: 40px; border-radius: 6px; display: block; }
.cover-empty { color: var(--text-muted); font-size: 12px; }
.fit-tag { margin: 2px 4px 2px 0; }
.tag-zhizhen {
  background: var(--color-warning-bg);
  border-color: var(--color-gold-muted);
  color: var(--color-gold-muted, #b8860b);
}
.upload-slot {
  width: 88px; height: 88px; border: 1px dashed var(--border-color); border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-muted); font-size: 12px; cursor: pointer; background: var(--toolbar-bg);
}
.upload-slot:hover { border-color: var(--color-primary); color: var(--color-primary); }
.upload-preview { width: 88px; height: 88px; border-radius: 8px; display: block; }
.angle-list { display: flex; flex-wrap: wrap; gap: 8px; }
.angle-item { position: relative; }
.angle-remove {
  position: absolute; top: -6px; right: -6px; width: 18px; height: 18px; line-height: 16px;
  text-align: center; border-radius: 50%; background: var(--color-danger); color: #fff;
  font-size: 12px; cursor: pointer; z-index: 1;
}
</style>
