<template>
  <UiDrawer :model-value="modelValue" :title="material ? '编辑资料' : '新增资料条目'" eyebrow="MATERIAL" @update:model-value="emit('update:modelValue', $event)">
    <form class="mat-form" @submit.prevent="submit">
      <div class="form-item">
        <label class="field-label">名称 *（项目内唯一，即下载文件名前缀）</label>
        <input v-model.trim="form.name" class="input" type="text" placeholder="如：价格体系" required />
      </div>
      <div class="form-item">
        <label class="field-label">说明</label>
        <textarea v-model.trim="form.description" class="textarea" placeholder="这份资料是什么、给谁用"></textarea>
      </div>
      <div class="form-row">
        <div class="form-item">
          <label class="field-label">分类</label>
          <select v-model="form.category" class="select">
            <option v-for="c in CATEGORY_ORDER" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <div class="form-item">
          <label class="field-label">重要级</label>
          <select v-model="form.importance" class="select">
            <option value="required">必须</option>
            <option value="important">重要</option>
            <option value="optional">锦上添花</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-item">
          <label class="field-label">所属 Phase</label>
          <select v-model="form.phase" class="select">
            <option :value="null">不归属</option>
            <option v-for="p in [1, 2, 3, 4]" :key="p" :value="p">Phase {{ p }}</option>
          </select>
        </div>
        <div class="form-item">
          <label class="field-label">负责人</label>
          <select v-model="form.owner" class="select">
            <option value="">未指派</option>
            <option v-for="m in members" :key="m.username" :value="m.username">{{ m.display_name }}</option>
          </select>
        </div>
      </div>

      <div v-if="!material" class="form-item">
        <label class="field-label">交付类型</label>
        <div class="delivery-picker">
          <label v-for="(meta, t) in DELIVERY_TYPE" :key="t" class="delivery-option" :class="{ checked: form.delivery_type === t }">
            <input v-model="form.delivery_type" type="radio" :value="t" />
            <span class="delivery-name">{{ meta.label }}</span>
            <span class="delivery-desc">{{ deliveryHints[t] }}</span>
          </label>
        </div>
      </div>
      <div v-if="form.delivery_type === 'link'" class="form-item">
        <label class="field-label">外部链接 *（网盘 / 素材中台地址）</label>
        <input v-model.trim="form.external_url" class="input" type="url" placeholder="https://…" />
      </div>
      <div v-if="form.delivery_type === 'offline'" class="form-item">
        <label class="field-label">线下交付方式备注</label>
        <input v-model.trim="form.delivery_remark" class="input" type="text" placeholder="如：亮哥当面交接给顾问" />
        <p class="offline-hint">凭据类材料禁止上传原文，本站只跟踪状态与备注。</p>
      </div>
    </form>
    <template #footer>
      <button class="btn" type="button" @click="emit('update:modelValue', false)">取消</button>
      <button class="btn btn-primary" type="button" :disabled="busy || !canSubmit" @click="submit">
        <span v-if="busy" class="spinner"></span>{{ material ? '保存' : '新增' }}
      </button>
    </template>
  </UiDrawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import UiDrawer from './UiDrawer.vue'
import { CATEGORY_ORDER, DELIVERY_TYPE } from '../utils/labels.js'

const props = defineProps({
  modelValue: Boolean,
  material: { type: Object, default: null }, // null = 新增；否则编辑（交付类型不可改）
  members: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'save'])

const deliveryHints = {
  file: '直接上传文件，版本自动编号',
  offline: '凭据/账号类，禁传原文，只跟踪状态',
  link: '大体积媒体存网盘/素材中台',
}

const busy = ref(false)
const form = reactive({
  name: '',
  description: '',
  category: '其他',
  importance: 'important',
  phase: null,
  owner: '',
  delivery_type: 'file',
  external_url: '',
  delivery_remark: '',
})

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    const m = props.material
    Object.assign(form, {
      name: m?.name || '',
      description: m?.description || '',
      category: m?.category || '其他',
      importance: m?.importance || 'important',
      phase: m?.phase ?? null,
      owner: m?.owner || '',
      delivery_type: m?.delivery_type || 'file',
      external_url: m?.external_url || '',
      delivery_remark: m?.delivery_remark || '',
    })
  },
  { immediate: true }
)

const canSubmit = computed(() => {
  if (!form.name) return false
  if (form.delivery_type === 'link' && !form.external_url) return false
  return true
})

async function submit() {
  if (busy.value) return
  busy.value = true
  try {
    await emit('save', {
      name: form.name,
      description: form.description || null,
      category: form.category,
      importance: form.importance,
      phase: form.phase,
      owner: form.owner || null,
      delivery_type: form.delivery_type,
      external_url: form.external_url || null,
      delivery_remark: form.delivery_remark || null,
    })
    emit('update:modelValue', false)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.mat-form { display: flex; flex-direction: column; gap: 18px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.delivery-picker { display: flex; flex-direction: column; gap: 8px; }
.delivery-option {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 10px;
  align-items: center;
  border: 1px solid var(--hairline-strong);
  border-radius: var(--radius);
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.delivery-option input { accent-color: var(--cinnabar); grid-row: span 2; }
.delivery-option.checked { border-color: var(--ink); background: var(--paper-raised); }
.delivery-name { font-size: 13px; font-weight: 600; }
.delivery-desc { font-size: 12px; color: var(--ink-3); }
.offline-hint { margin-top: 8px; font-size: 12px; color: var(--cinnabar); }
</style>
