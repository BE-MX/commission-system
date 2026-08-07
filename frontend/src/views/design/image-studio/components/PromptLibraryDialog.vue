<template>
  <el-dialog
    :model-value="visible"
    title="提示词库"
    width="680px"
    append-to-body
    class="prompt-library-dialog"
    @update:model-value="emit('update:visible', $event)"
    @open="onOpen"
  >
    <div v-loading="loading" class="tpl-body">
      <div v-if="categories.length" class="tpl-categories">
        <button
          v-for="item in categories"
          :key="item.key"
          type="button"
          class="category-chip"
          :class="{ 'is-active': item.key === category }"
          @click="category = item.key"
        >{{ item.label }}</button>
      </div>

      <div class="tpl-main">
        <div class="tpl-list" role="listbox" aria-label="模板列表">
          <button
            v-for="tpl in filteredTemplates"
            :key="tpl.id"
            type="button"
            class="tpl-item"
            :class="{ 'is-active': selected?.id === tpl.id }"
            role="option"
            :aria-selected="selected?.id === tpl.id"
            @click="select(tpl)"
          >
            <strong>{{ tpl.name }}</strong>
            <p>{{ tpl.content }}</p>
          </button>
          <p v-if="!loading && !filteredTemplates.length" class="tpl-empty">该类型暂无模板</p>
        </div>

        <div v-if="selected" class="tpl-side">
          <div v-for="option in selected.options" :key="option.key" class="param-group">
            <span class="param-label">{{ option.label }}</span>
            <div class="param-choices">
              <button
                v-for="choice in option.choices"
                :key="choice"
                type="button"
                class="choice-chip"
                :class="{ 'is-active': selections[option.key] === choice }"
                @click="chooseParam(option.key, choice)"
              >{{ choice }}</button>
              <button
                v-if="isColorParam(option)"
                type="button"
                class="choice-chip swatch-entry"
                :class="{ 'is-active': pantoneOpen === option.key }"
                title="打开潘通色卡库"
                @click="togglePantone(option.key)"
              >
                <el-icon><Brush /></el-icon>潘通色卡
              </button>
              <button
                v-if="pantonePicks[option.key]"
                type="button"
                class="choice-chip swatch-pick"
                :title="`${pantonePicks[option.key].code} ${pantonePicks[option.key].name || ''}`"
                @click="togglePantone(option.key)"
              >
                <span class="swatch-dot" :style="{ background: pantonePicks[option.key].hex }" />
                {{ pantonePicks[option.key].hex }}
              </button>
            </div>
            <div v-if="isColorParam(option) && pantoneOpen === option.key" class="pantone-panel">
              <el-input
                v-model="pantoneQuery"
                size="small"
                placeholder="搜索色号 / 名称 / HEX"
                clearable
              />
              <div class="pantone-grid">
                <button
                  v-for="color in visiblePantone"
                  :key="color.code"
                  type="button"
                  class="pantone-swatch"
                  :class="{ 'is-active': pantonePicks[option.key]?.code === color.code }"
                  :title="`${color.code} ${color.name || ''}`"
                  @click="pickPantone(option.key, color)"
                >
                  <span class="pantone-color" :style="{ background: color.hex }" />
                  <span class="pantone-code">{{ color.code }}</span>
                  <span class="pantone-hex">{{ color.hex }}</span>
                </button>
              </div>
              <p class="pantone-meta">{{ pantoneQuery ? `匹配 ${pantoneTotal} 条` : `共 ${pantoneTotal} 条` }}<template v-if="pantoneCapped">，仅显示前 {{ visiblePantone.length }} 条，输入关键词缩小范围</template></p>
            </div>
          </div>
          <div class="tpl-preview">
            <span class="param-label">生成内容预览</span>
            <p :class="{ 'is-incomplete': missing.length }">{{ composed }}</p>
            <p v-if="missing.length" class="preview-warning">还有 {{ missing.length }} 项参数未选择</p>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <GlassButton v-permission="'design_image:admin'" variant="outline" size="sm" @click="managerOpen = true">
        <template #left-icon><el-icon><Setting /></el-icon></template>
        管理模板
      </GlassButton>
      <GlassButton v-permission="'design_image:admin'" variant="outline" size="sm" :loading="seeding" @click="seed">
        导入预置模板
      </GlassButton>
      <GlassButton variant="ghost" @click="close">取消</GlassButton>
      <GlassButton variant="primary" :disabled="!selected || missing.length > 0" @click="apply">
        填入输入框
      </GlassButton>
    </template>
  </el-dialog>
  <PromptTemplateManagerDialog v-model:visible="managerOpen" @changed="fetchTemplates" />
</template>

<script setup>
import { computed, ref } from 'vue'
import { Brush, Setting } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { listPantoneColors, listPromptTemplates, seedPromptTemplates } from '@/api/designImage'
import { msgError, msgSuccess } from '@/utils/feedback'
import { composePrompt, isColorParam, missingPromptParams } from '../state'
import PromptTemplateManagerDialog from './PromptTemplateManagerDialog.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
})
const emit = defineEmits(['update:visible', 'apply'])

const CATEGORY_LABELS = {
  product: '产品图',
  scene: '场景图',
  poster: '海报',
  detail: '细节图',
  restyle: '换款改图',
}

const templates = ref([])
const loading = ref(false)
const seeding = ref(false)
const managerOpen = ref(false)
const category = ref('')
const selected = ref(null)
const selections = ref({})

/* 潘通色卡：模块级缓存一次拉全量，面板内前端过滤（2310 条，上限渲染防爆） */
const pantoneColors = ref([])
const pantoneLoaded = ref(false)
const pantonePicks = ref({})
const pantoneOpen = ref(null)
const pantoneQuery = ref('')
const PANTONE_RENDER_CAP = 240

const filteredPantone = computed(() => {
  const query = pantoneQuery.value.trim().toLowerCase()
  if (!query) return pantoneColors.value
  return pantoneColors.value.filter(color => (
    color.code.toLowerCase().includes(query)
    || (color.name ?? '').toLowerCase().includes(query)
    || color.hex.toLowerCase().includes(query)
  ))
})
const visiblePantone = computed(() => filteredPantone.value.slice(0, PANTONE_RENDER_CAP))
const pantoneTotal = computed(() => filteredPantone.value.length)
const pantoneCapped = computed(() => filteredPantone.value.length > PANTONE_RENDER_CAP)

async function ensurePantone() {
  if (pantoneLoaded.value) return
  try {
    const response = await listPantoneColors()
    pantoneColors.value = response?.data?.items ?? []
    pantoneLoaded.value = true
  } catch {
    msgError('潘通色库读取失败，请稍后重试')
  }
}

function chooseParam(key, choice) {
  selections.value = { ...selections.value, [key]: choice }
  const rest = { ...pantonePicks.value }
  delete rest[key]
  pantonePicks.value = rest
}

function togglePantone(key) {
  pantoneOpen.value = pantoneOpen.value === key ? null : key
  if (pantoneOpen.value) {
    pantoneQuery.value = ''
    void ensurePantone()
  }
}

function pickPantone(key, color) {
  pantonePicks.value = { ...pantonePicks.value, [key]: color }
  selections.value = { ...selections.value, [key]: color.hex }
  pantoneOpen.value = null
}

const categories = computed(() => {
  const seen = new Map()
  for (const tpl of templates.value) {
    if (!seen.has(tpl.category)) {
      seen.set(tpl.category, { key: tpl.category, label: CATEGORY_LABELS[tpl.category] || tpl.category })
    }
  }
  return [...seen.values()]
})
const filteredTemplates = computed(() => (
  templates.value.filter(tpl => !category.value || tpl.category === category.value)
))
const composed = computed(() => composePrompt(selected.value, selections.value))
const missing = computed(() => missingPromptParams(selected.value, selections.value))

function select(tpl) {
  selected.value = tpl
  selections.value = {}
  pantonePicks.value = {}
  pantoneOpen.value = null
  pantoneQuery.value = ''
}

async function fetchTemplates() {
  loading.value = true
  try {
    const response = await listPromptTemplates()
    templates.value = response?.data?.items ?? []
    if (!category.value || !categories.value.some(item => item.key === category.value)) {
      category.value = categories.value[0]?.key ?? ''
    }
  } catch {
    msgError('提示词库读取失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function seed() {
  seeding.value = true
  try {
    const response = await seedPromptTemplates()
    const result = response?.data ?? {}
    msgSuccess(`预置模板已导入（新增 ${result.created ?? 0} 条）`)
    await fetchTemplates()
  } catch {
    msgError('导入失败，请稍后重试')
  } finally {
    seeding.value = false
  }
}

function onOpen() {
  if (!templates.value.length) void fetchTemplates()
}

function close() {
  emit('update:visible', false)
}

function apply() {
  if (!selected.value || missing.value.length) return
  emit('apply', composed.value)
  close()
}
</script>

<style scoped>
.tpl-body { min-height: 320px; }
.tpl-categories { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.category-chip {
  padding: 6px 14px; border: 1px solid var(--border-color); border-radius: 999px;
  background: var(--toolbar-bg); color: var(--text-secondary); cursor: pointer; font-size: 12px;
  transition: border-color 160ms cubic-bezier(0.23, 1, 0.32, 1), color 160ms cubic-bezier(0.23, 1, 0.32, 1),
    background-color 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.category-chip.is-active { border-color: var(--color-primary); background: var(--color-primary-light); color: var(--color-gold-muted); font-weight: 600; }

.tpl-main { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; }
.tpl-list { display: flex; max-height: 340px; min-height: 200px; flex-direction: column; gap: 8px; overflow-y: auto; padding-right: 2px; }
.tpl-item {
  padding: 10px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-lg, 12px);
  background: var(--card-bg); cursor: pointer; text-align: left;
  transition: border-color 160ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.tpl-item strong { display: block; margin-bottom: 4px; color: var(--text-primary); font-size: 13px; }
.tpl-item p {
  display: -webkit-box; margin: 0; overflow: hidden; color: var(--text-muted); font-size: 12px;
  line-height: 1.6; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
}
.tpl-item.is-active { border-color: var(--color-primary); box-shadow: 0 0 0 3px var(--color-primary-glow); }
.tpl-empty { margin: 40px 0; color: var(--text-muted); font-size: 12px; text-align: center; }

.tpl-side {
  display: flex; max-height: 340px; flex-direction: column; gap: 12px; overflow-y: auto;
  padding: 12px; border: 1px solid var(--border-color); border-radius: var(--radius-lg, 12px); background: var(--toolbar-bg);
}
.param-label { display: block; margin-bottom: 6px; color: var(--text-muted); font-size: 11px; font-weight: 600; }
.param-choices { display: flex; flex-wrap: wrap; gap: 6px; }
.choice-chip {
  padding: 5px 12px; border: 1px solid var(--border-color); border-radius: 999px;
  background: var(--card-bg); color: var(--text-secondary); cursor: pointer; font-size: 12px;
  transition: border-color 160ms cubic-bezier(0.23, 1, 0.32, 1), color 160ms cubic-bezier(0.23, 1, 0.32, 1),
    background-color 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.choice-chip.is-active { border-color: var(--color-primary); background: var(--color-primary-light); color: var(--color-gold-muted); font-weight: 600; }
.tpl-preview { margin-top: auto; padding-top: 10px; border-top: 1px dashed var(--border-color); }
.tpl-preview > p { margin: 0; color: var(--text-primary); font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
.tpl-preview > p.is-incomplete { color: var(--text-muted); }
.preview-warning { margin: 6px 0 0; color: var(--color-warning-text); font-size: 11px; }

/* 潘通色卡 */
.swatch-entry { display: inline-flex; align-items: center; gap: 4px; }
.swatch-pick { display: inline-flex; align-items: center; gap: 6px; border-color: var(--color-primary); background: var(--color-primary-light); font-variant-numeric: tabular-nums; }
.swatch-dot { width: 14px; height: 14px; border: 1px solid rgba(26, 24, 22, 0.16); border-radius: 50%; }
.pantone-panel {
  margin-top: 8px; padding: 10px; border: 1px solid var(--border-color);
  border-radius: var(--radius-lg, 12px); background: var(--card-bg);
}
.pantone-grid {
  display: grid; max-height: 260px; margin-top: 8px; overflow-y: auto;
  grid-template-columns: repeat(auto-fill, minmax(86px, 1fr)); gap: 6px;
}
.pantone-swatch {
  overflow: hidden; padding: 0 0 5px; border: 1px solid var(--border-color); border-radius: 8px;
  background: var(--toolbar-bg); cursor: pointer; text-align: center;
  transition: border-color 160ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.pantone-color { display: block; height: 34px; }
.pantone-code { display: block; margin-top: 4px; overflow: hidden; padding: 0 4px; color: var(--text-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.pantone-hex { display: block; color: var(--text-muted); font-size: 10px; font-variant-numeric: tabular-nums; }
.pantone-swatch.is-active { border-color: var(--color-primary); box-shadow: 0 0 0 3px var(--color-primary-glow); }
.pantone-meta { margin: 6px 0 0; color: var(--text-muted); font-size: 11px; }

@media (hover: hover) and (pointer: fine) {
  .category-chip:hover, .choice-chip:hover { border-color: var(--color-primary); color: var(--color-gold-muted); }
  .tpl-item:hover { border-color: var(--border-hover); box-shadow: var(--card-shadow-hover); }
  .pantone-swatch:hover { border-color: var(--color-primary); }
}
@media (max-width: 640px) {
  .tpl-main { grid-template-columns: minmax(0, 1fr); }
  .tpl-list { max-height: 220px; }
}
@media (prefers-reduced-motion: reduce) {
  .category-chip, .choice-chip, .tpl-item, .pantone-swatch { transition: none; }
}
</style>
