<template>
  <el-dialog
    :model-value="modelValue"
    :title="draft.id ? '编辑产品模板' : '新建产品模板'"
    width="min(960px, 94vw)"
    destroy-on-close
    @open="resetDraft"
    @closed="handleClosed"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="editor-scroll">
      <section class="form-section metadata-section">
        <h3>客户可见信息</h3>
        <div class="form-grid">
          <label>产品名称<el-input v-model="draft.name" maxlength="200" /></label>
          <label>产品分类<el-input v-model="draft.category" maxlength="100" /></label>
          <label class="wide">产品说明<el-input v-model="draft.description" type="textarea" :rows="2" /></label>
          <label>排序<el-input-number v-model="draft.sort" :min="0" :max="9999" /></label>
        </div>
      </section>

      <section v-permission="'customer_image:admin'" class="form-section prompt-section">
        <div class="section-heading">
          <div><h3>内部提示词</h3><p>仅模板管理员可见，不会返回给客户。</p></div>
        </div>
        <label>固定提示词<el-input v-model="draft.fixed_prompt" type="textarea" :rows="3" /></label>
        <label>输出约束<el-input v-model="draft.output_prompt" type="textarea" :rows="3" /></label>
      </section>

      <section class="form-section">
        <div class="section-heading">
          <div><h3>产品素材</h3><p>发布前必须各有一张封面图和参考图。</p></div>
          <span v-if="!draft.id" class="save-hint">请先保存模板，再上传素材</span>
        </div>
        <div class="asset-grid">
          <article class="asset-card">
            <div class="asset-preview">
              <img v-if="coverAsset && urls[coverAsset.id]" :src="urls[coverAsset.id]" alt="产品封面">
              <span v-else>产品封面待上传</span>
            </div>
            <strong>产品封面</strong>
            <div class="asset-actions">
              <label class="file-action" :class="{ disabled: !draft.id }">
                {{ coverAsset ? '替换封面' : '上传封面' }}
                <input type="file" accept="image/jpeg,image/png,image/webp" :disabled="!draft.id" @change="uploadAsset('cover', $event, 0)">
              </label>
              <GlassButton variant="outline" :disabled="!draft.id" @click="openLibrary('cover', 0)">从图库选择</GlassButton>
            </div>
          </article>
        </div>
        <div class="reference-heading">
          <div><strong>生成参考图</strong><p>可添加多张，顺序会作为生成参考顺序。</p></div>
          <div class="asset-actions">
            <label class="file-action" :class="{ disabled: !draft.id }">
              添加本地图
              <input type="file" accept="image/jpeg,image/png,image/webp" :disabled="!draft.id" @change="appendReference($event)">
            </label>
            <GlassButton variant="outline" :disabled="!draft.id" @click="openLibrary('reference', null, true)">从图库添加</GlassButton>
          </div>
        </div>
        <div v-if="referenceAssets.length" class="reference-grid">
          <article v-for="(asset, index) in referenceAssets" :key="asset.id" class="asset-card">
            <div class="asset-preview">
              <img v-if="urls[asset.id]" :src="urls[asset.id]" :alt="`参考图 ${index + 1}`">
            </div>
            <strong>参考图 {{ index + 1 }}</strong>
            <div class="asset-actions">
              <label class="file-action">
                本地替换
                <input type="file" accept="image/jpeg,image/png,image/webp" @change="uploadAsset('reference', $event, asset.position)">
              </label>
              <GlassButton variant="outline" @click="openLibrary('reference', asset.position)">图库替换</GlassButton>
              <GlassButton variant="link" :disabled="index === 0" :aria-label="`上移参考图 ${index + 1}`" @click="moveReference(index, -1)">上移</GlassButton>
              <GlassButton variant="link" :disabled="index === referenceAssets.length - 1" :aria-label="`下移参考图 ${index + 1}`" @click="moveReference(index, 1)">下移</GlassButton>
              <GlassButton variant="link" link-tone="danger" :aria-label="`删除参考图 ${index + 1}`" @click="removeReference(asset)">删除</GlassButton>
            </div>
          </article>
        </div>
        <div v-else class="empty-options">尚未添加生成参考图。</div>
      </section>

      <section class="form-section">
        <div class="section-heading">
          <div><h3>客户参数</h3><p>从上到下决定客户页面的展示顺序，默认值会自动填入。</p></div>
          <el-dropdown trigger="click" @command="addOption">
            <GlassButton variant="outline" left-icon="Plus">添加参数</GlassButton>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="single_choice">单选</el-dropdown-item>
                <el-dropdown-item command="color">颜色</el-dropdown-item>
                <el-dropdown-item command="boolean">是否</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <div v-if="!draft.options.length" class="empty-options">没有参数时，客户将直接使用固定提示词生成。</div>
        <article v-for="(option, optionIndex) in draft.options" :key="optionIndex" class="option-card">
          <div class="option-head">
            <strong>参数 {{ optionIndex + 1 }} · {{ CONTROL_LABELS[option.control_type] }}</strong>
            <div>
              <GlassButton variant="link" :disabled="optionIndex === 0" @click="move(draft.options, optionIndex, -1)">上移</GlassButton>
              <GlassButton variant="link" :disabled="optionIndex === draft.options.length - 1" @click="move(draft.options, optionIndex, 1)">下移</GlassButton>
              <GlassButton variant="link" link-tone="danger" @click="draft.options.splice(optionIndex, 1)">删除</GlassButton>
            </div>
          </div>
          <div class="form-grid option-fields">
            <label>参数键<el-input v-model="option.key" placeholder="如 view_angle" /></label>
            <label>客户看到的名称<el-input v-model="option.label" placeholder="如 展示角度" /></label>
            <label>默认值
              <el-select v-model="option.default_value" clearable>
                <el-option v-for="value in activeValues(option)" :key="value.value" :label="value.label" :value="value.value" />
              </el-select>
            </label>
            <label class="switch-label">客户必选<el-switch v-model="option.required" /></label>
          </div>

          <div class="value-list">
            <div v-for="(value, valueIndex) in option.values" :key="valueIndex" class="value-row">
              <input v-if="option.control_type === 'color'" v-model="value.color_hex" type="color" aria-label="颜色值">
              <el-input v-model="value.value" :disabled="option.control_type === 'boolean'" placeholder="提交值" />
              <el-input v-model="value.label" placeholder="客户标签" />
              <el-input v-model="value.prompt_fragment" placeholder="内部提示词片段" />
              <el-input v-if="option.control_type === 'color'" v-model="value.pantone_code" placeholder="Pantone（选填）" />
              <el-switch v-model="value.is_active" inline-prompt active-text="启" inactive-text="停" />
              <GlassButton variant="link" :disabled="valueIndex === 0" :aria-label="`上移选项值 ${valueIndex + 1}`" @click="move(option.values, valueIndex, -1)">↑</GlassButton>
              <GlassButton variant="link" :disabled="valueIndex === option.values.length - 1" :aria-label="`下移选项值 ${valueIndex + 1}`" @click="move(option.values, valueIndex, 1)">↓</GlassButton>
              <GlassButton v-if="option.control_type !== 'boolean'" variant="link" link-tone="danger" @click="option.values.splice(valueIndex, 1)">删</GlassButton>
            </div>
          </div>
          <GlassButton v-if="option.control_type !== 'boolean'" variant="outline" left-icon="Plus" @click="addValue(option)">添加选项值</GlassButton>
        </article>
      </section>
    </div>

    <template #footer>
      <GlassButton variant="ghost" @click="emit('update:modelValue', false)">关闭</GlassButton>
      <GlassButton v-permission="'customer_image:admin'" variant="primary" :loading="saving" @click="save">保存模板</GlassButton>
    </template>

    <el-dialog v-model="libraryVisible" title="从内部图库复制" width="min(760px, 90vw)" append-to-body @closed="closeLibrary">
      <div v-loading="libraryLoading" class="library-grid">
        <button v-for="asset in libraryAssets" :key="asset.id" type="button" class="library-item" @click="copyFromLibrary(asset)">
          <img v-if="libraryUrls[asset.id]" :src="libraryUrls[asset.id]" :alt="asset.title || '图库图片'">
          <span>{{ asset.title || `素材 #${asset.id}` }}</span>
        </button>
        <el-empty v-if="!libraryLoading && !libraryAssets.length" description="图库暂无可复制图片" />
      </div>
    </el-dialog>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/customerImage'
import {
  createEmptyOption,
  createEmptyOptionValue,
  createEmptyProductDraft,
  createAssetBlobController,
  moveReferenceIds,
  validateProductDraft,
} from './composables/useCustomerImageAdmin'

const props = defineProps({
  modelValue: Boolean,
  product: { type: Object, default: null },
  adminState: { type: Object, required: true },
})
const emit = defineEmits(['update:modelValue', 'saved'])
const CONTROL_LABELS = { single_choice: '单选', color: '颜色', boolean: '是否' }
const draft = ref(createEmptyProductDraft())
const assets = ref([])
const libraryAssets = ref([])
const libraryVisible = ref(false)
const libraryLoading = ref(false)
const targetRole = ref('cover')
const targetPosition = ref(0)
const targetAppend = ref(false)
const saving = ref(false)
let assetEpoch = 0
let libraryEpoch = 0

const assetBlobs = createAssetBlobController({
  fetchBlob: (asset, config) => api.getProductAssetBlob(asset.productId, asset.id, config),
})
const libraryBlobs = createAssetBlobController({
  fetchBlob: (asset, config) => api.getLibraryAssetBlob(asset.id, { thumbnail: true, ...config }),
})
const urls = assetBlobs.urls
const libraryUrls = libraryBlobs.urls

const coverAsset = computed(() => assets.value.find(asset => asset.role === 'cover'))
const referenceAssets = computed(() => assets.value
  .filter(asset => asset.role === 'reference')
  .sort((left, right) => left.position - right.position || left.id - right.id))
const activeValues = option => option.values.filter(value => value.is_active !== false)

async function loadAssets() {
  const epoch = ++assetEpoch
  assetBlobs.invalidate()
  if (!draft.value.id) { assets.value = []; return }
  const productId = draft.value.id
  const response = await api.listProductAssets(productId)
  if (epoch !== assetEpoch) return
  assets.value = response.data || []
  await assetBlobs.load(assets.value.map(asset => ({ ...asset, productId })))
}

async function resetDraft() {
  draft.value = props.product ? JSON.parse(JSON.stringify(props.product)) : createEmptyProductDraft()
  await loadAssets()
}

function addOption(type) { draft.value.options.push(createEmptyOption(type, draft.value.options.length)) }
function addValue(option) { option.values.push(createEmptyOptionValue(option.values.length)) }
function move(items, index, offset) {
  const target = index + offset
  if (target < 0 || target >= items.length) return
  ;[items[index], items[target]] = [items[target], items[index]]
}

async function save() {
  const error = validateProductDraft(draft.value)
  if (error) { ElMessage.warning(error); return }
  saving.value = true
  try {
    const saved = await props.adminState.saveProduct(draft.value)
    draft.value = JSON.parse(JSON.stringify(saved))
    await loadAssets()
    emit('saved', saved)
    ElMessage.success('模板已保存')
  } catch (error) {
    if (!error?.response) ElMessage.warning(error.message)
  } finally { saving.value = false }
}

async function uploadAsset(role, event, position) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !draft.value.id) return
  try {
    await api.uploadProductAsset(draft.value.id, role, position, file)
    await loadAssets()
    await props.adminState.loadProducts()
    ElMessage.success('素材已替换')
  } catch { /* shared interceptor provides request feedback */ }
}

async function appendReference(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !draft.value.id) return
  try {
    await api.appendProductReference(draft.value.id, file)
    await loadAssets()
    await props.adminState.loadProducts()
    ElMessage.success('参考图已添加')
  } catch { /* shared interceptor provides request feedback */ }
}

async function openLibrary(role, position, append = false) {
  targetRole.value = role
  targetPosition.value = position
  targetAppend.value = append
  libraryVisible.value = true
  libraryLoading.value = true
  const epoch = ++libraryEpoch
  libraryBlobs.invalidate()
  try {
    const response = await api.listLibraryAssets()
    if (epoch !== libraryEpoch) return
    libraryAssets.value = response.data?.items || []
    await libraryBlobs.load(libraryAssets.value)
  } finally {
    if (epoch === libraryEpoch) libraryLoading.value = false
  }
}

async function copyFromLibrary(asset) {
  try {
    if (targetAppend.value) {
      await api.appendProductReferenceFromLibrary(draft.value.id, asset.id)
    } else {
      await api.copyProductAssetFromLibrary(draft.value.id, {
        source_asset_id: asset.id, role: targetRole.value, position: targetPosition.value,
      })
    }
    libraryVisible.value = false
    closeLibrary()
    await loadAssets()
    await props.adminState.loadProducts()
    ElMessage.success('已复制到产品模板')
  } catch { /* shared interceptor provides request feedback */ }
}

async function moveReference(index, offset) {
  const assetIds = moveReferenceIds(referenceAssets.value, index, offset)
  if (assetIds[index] === referenceAssets.value[index]?.id) return
  try {
    await api.reorderProductReferences(draft.value.id, assetIds)
    await loadAssets()
    await props.adminState.loadProducts()
  } catch { /* shared interceptor provides request feedback */ }
}

async function removeReference(asset) {
  try {
    await ElMessageBox.confirm('删除后历史生成仍保留该参考图，是否继续？', '删除参考图', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
    await api.retireProductReference(draft.value.id, asset.id)
    await loadAssets()
    await props.adminState.loadProducts()
    ElMessage.success('参考图已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close' && !error?.response) throw error
  }
}

function closeLibrary() {
  libraryEpoch += 1
  libraryBlobs.invalidate()
  libraryAssets.value = []
}

function handleClosed() {
  assetEpoch += 1
  assetBlobs.invalidate()
  closeLibrary()
  libraryAssets.value = []
  emit('update:modelValue', false)
}

onBeforeUnmount(() => {
  assetEpoch += 1
  libraryEpoch += 1
  assetBlobs.dispose()
  libraryBlobs.dispose()
})
</script>

<style scoped>
.editor-scroll { display: grid; gap: 16px; max-height: min(68vh, 720px); overflow: auto; padding: 2px 8px 12px 2px; }
.form-section { display: grid; gap: 14px; padding: 18px; border: 1px solid var(--el-border-color-lighter); border-radius: 14px; }
.form-section h3, .form-section p { margin: 0; }
.form-section p, .save-hint { color: var(--el-text-color-secondary); font-size: 13px; }
.prompt-section { background: var(--el-fill-color-lighter); }
.section-heading, .option-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
label { display: grid; gap: 7px; color: var(--el-text-color-regular); font-size: 13px; font-weight: 600; }
.wide { grid-column: 1 / -1; }
.asset-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.reference-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.reference-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
.asset-card { display: grid; gap: 10px; padding: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 12px; }
.asset-preview { display: grid; place-items: center; min-height: 150px; overflow: hidden; border-radius: 9px; background: var(--el-fill-color-light); color: var(--el-text-color-secondary); }
.asset-preview img { width: 100%; height: 180px; object-fit: contain; }
.asset-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.file-action { display: grid; place-items: center; min-height: 44px; padding: 0 16px; border: 1px solid var(--el-border-color); border-radius: 10px; cursor: pointer; }
.file-action input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.file-action.disabled { cursor: not-allowed; opacity: .5; }
.empty-options { padding: 18px; border-radius: 10px; background: var(--el-fill-color-light); color: var(--el-text-color-secondary); text-align: center; }
.option-card { display: grid; gap: 14px; padding: 15px; border: 1px solid var(--el-border-color); border-radius: 12px; }
.switch-label { align-content: end; grid-template-columns: 1fr auto; align-items: center; min-height: 44px; }
.value-list { display: grid; gap: 8px; }
.value-row { display: grid; grid-template-columns: 42px minmax(90px, .7fr) minmax(100px, .8fr) minmax(160px, 1.5fr) minmax(80px, .5fr) auto auto auto auto; align-items: center; gap: 7px; }
.value-row > input[type='color'] { width: 38px; height: 38px; padding: 2px; border: 1px solid var(--el-border-color); border-radius: 8px; }
.library-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; max-height: 55vh; overflow: auto; }
.library-item { display: grid; gap: 7px; min-height: 150px; padding: 8px; border: 1px solid var(--el-border-color-lighter); border-radius: 11px; background: var(--el-bg-color); color: var(--el-text-color-primary); cursor: pointer; transition: transform 180ms ease-out, border-color 180ms ease-out; }
.library-item img { width: 100%; height: 110px; object-fit: cover; border-radius: 7px; }
:deep(.glass-button:not(.glass-button--link)), .library-item { min-height: 44px; }
@media (hover: hover) and (pointer: fine) { .library-item:hover { transform: translateY(-2px); border-color: var(--el-color-primary); } }
@media (max-width: 760px) { .form-grid, .asset-grid { grid-template-columns: 1fr; } .value-row { grid-template-columns: 38px 1fr 1fr; } .value-row > * { min-width: 0; } }
@media (prefers-reduced-motion: reduce) { .library-item { transition-duration: .01ms; } }
</style>
