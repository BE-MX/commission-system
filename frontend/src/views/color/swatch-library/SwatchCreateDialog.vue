<template>
  <el-dialog
    :model-value="modelValue" title="新建色板" width="480" append-to-body destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)" @open="reset"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="cd-form">
      <el-form-item label="所属库">
        <el-radio-group v-model="form.library_scope">
          <el-radio-button value="private">私库</el-radio-button>
          <el-radio-button value="public" :disabled="!canPublic">公库</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="form.library_scope === 'private'" label="绑定客户" prop="customer_id">
        <el-select v-model="form.customer_id" filterable placeholder="选择客户" class="w-full">
          <el-option v-for="c in customers" :key="c.customer_id" :label="c.display_name" :value="c.customer_id" />
        </el-select>
      </el-form-item>
      <div class="cd-two">
        <el-form-item label="色号" prop="color_code">
          <el-input v-model="form.color_code" maxlength="30" placeholder="#1C、#8/60" @input="autoBase" />
        </el-form-item>
        <el-form-item label="尺寸" prop="size_value">
          <div class="cd-size">
            <el-input-number v-model="form.size_value" class="cd-size-input" :min="0.5" :max="9999" :step="0.5" :precision="1" controls-position="right" />
            <el-select v-model="form.size_unit" class="cd-unit">
              <el-option label="inch" value="inch" />
              <el-option label="cm" value="cm" />
            </el-select>
          </div>
        </el-form-item>
      </div>
      <div class="cd-quick">
        <button v-for="n in QUICK" :key="n" type="button" :class="{ on: form.size_value === n }" @click="form.size_value = n">{{ n }}″</button>
      </div>
      <el-form-item label="名称">
        <el-input v-model="form.display_name" maxlength="100" placeholder="Ash Brown" />
      </el-form-item>
      <div class="cd-two">
        <el-form-item label="对比基准（公库色板）">
          <el-select v-model="form.base_swatch_id" clearable filterable placeholder="不设置" class="w-full" :loading="baseLoading">
            <el-option
              v-for="b in baseOptions" :key="b.id"
              :label="`${b.color_code} · ${b.size_value}${b.size_unit === 'inch' ? '″' : ' cm'}${b.stats.count ? '' : '（未测量）'}`"
              :value="b.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="允许色差 ΔE00" prop="tolerance_de">
          <el-input-number v-model="form.tolerance_de" :min="0.1" :max="20" :step="0.1" :precision="2" controls-position="right" />
        </el-form-item>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button :loading="saving" @click="submit(false)">创建</el-button>
      <el-button type="primary" :loading="saving" @click="submit(true)">创建并测量</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { createLibrarySwatch, getLibrarySwatches } from '@/api/colorLibrary'
import { msgError, msgSuccess } from '@/utils/feedback'
import { normalizeCode } from './swatchFormat.js'

const props = defineProps({
  modelValue: Boolean,
  scope: { type: String, default: 'private' },
  customers: { type: Array, default: () => [] },
  customerId: { type: Number, default: null },
  canPublic: Boolean,
})
const emit = defineEmits(['update:modelValue', 'created'])

const QUICK = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30]
const formRef = ref()
const saving = ref(false)
const baseOptions = ref([])
const baseLoading = ref(false)
const form = reactive({})

const rules = {
  customer_id: [{ required: true, message: '私库色板必须绑定客户', trigger: 'change' }],
  color_code: [{ required: true, whitespace: true, message: '请填写色号', trigger: 'blur' }],
  size_value: [{ required: true, message: '请填写尺寸', trigger: 'change' }],
  tolerance_de: [{ required: true, message: '请填写允许色差', trigger: 'change' }],
}

async function loadBases() {
  baseLoading.value = true
  try {
    const res = await getLibrarySwatches({ scope: 'public', page_size: 200 })
    baseOptions.value = res.data?.items || []
  } catch (err) {
    baseOptions.value = []
    console.warn('[swatch-library] load base options failed', err)
  } finally {
    baseLoading.value = false
  }
}

function reset() {
  Object.assign(form, {
    library_scope: props.scope === 'public' && props.canPublic ? 'public' : 'private',
    customer_id: props.customerId,
    color_code: '',
    size_value: 18,
    size_unit: 'inch',
    display_name: '',
    base_swatch_id: null,
    tolerance_de: 1.5,
  })
  formRef.value?.clearValidate()
  loadBases()
}

function autoBase() {
  if (form.base_swatch_id) return
  const key = normalizeCode(form.color_code)
  const hit = baseOptions.value.find((b) => normalizeCode(b.color_code) === key)
  if (hit) form.base_swatch_id = hit.id
}

async function submit(measure) {
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = { ...form, color_code: form.color_code.trim() }
    if (payload.library_scope === 'public') payload.customer_id = null
    const res = await createLibrarySwatch(payload)
    msgSuccess('创建色板')
    emit('update:modelValue', false)
    emit('created', { swatch: res.data, measure })
  } catch (err) {
    msgError(err?.response?.data?.detail || '创建失败', err)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.cd-two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.cd-size { display: flex; gap: 6px; width: 100%; }
.cd-size-input { flex: 1; min-width: 0; }
.cd-unit { width: 84px; }
.cd-quick { display: flex; flex-wrap: wrap; gap: 6px; margin: -4px 0 14px; }
.cd-quick button {
  height: 26px; padding: 0 10px; border-radius: 6px; border: 1px solid var(--border-color); background: var(--card-bg);
  font: 600 12px var(--font-display); color: var(--text-secondary); cursor: pointer;
  transition: border-color 160ms ease, color 160ms ease, transform 120ms ease-out;
}
.cd-quick button:active { transform: scale(0.96); }
.cd-quick button.on { border-color: var(--color-primary); color: var(--button-primary-text); background: var(--color-primary-light); }
.w-full { width: 100%; }
@media (max-width: 560px) { .cd-two { grid-template-columns: 1fr; } }
</style>
