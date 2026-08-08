<template>
  <div class="sales-page">
    <header class="page-heading">
      <div>
        <h1>获客模型</h1>
        <p>定义“什么样的公司值得开发”。搜索任务会冻结当前模型快照，后续修改不会改变历史判断。</p>
      </div>
      <GlassButton
        v-permission="'sales_automation:admin'"
        variant="primary"
        left-icon="Check"
        :loading="saving"
        @click="save"
      >保存模型</GlassButton>
    </header>

    <section v-loading="loading" class="surface-card profile-card">
      <el-form :model="form" label-position="top" :disabled="!canWrite">
        <h2 class="section-heading">我们是谁</h2>
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="公司名称" required>
              <el-input v-model="form.company_name" maxlength="255" placeholder="例如：Leshine Hair" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="公司官网">
              <el-input v-model="form.company_website" maxlength="512" placeholder="https://example.com" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="产品能力">
              <TagInput v-model="form.products" placeholder="输入产品后回车，例如 human hair wigs" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="竞争优势">
              <TagInput v-model="form.advantages" placeholder="输入优势后回车，例如 small MOQ" />
            </el-form-item>
          </el-col>
        </el-row>

        <h2 class="section-heading target-heading">要找谁</h2>
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="目标国家/地区">
              <TagInput v-model="form.target_countries" placeholder="例如 United States" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="目标行业/客户类型">
              <TagInput v-model="form.target_industries" placeholder="例如 wig retailer" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="目标联系人角色">
              <TagInput v-model="form.target_roles" placeholder="例如 owner、buyer" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="排除条件">
              <TagInput v-model="form.exclusions" placeholder="例如 synthetic hair only" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="默认开发语言" class="language-field">
          <el-select v-model="form.default_language">
            <el-option label="English" value="en" />
            <el-option label="Español" value="es" />
            <el-option label="Français" value="fr" />
            <el-option label="Português" value="pt" />
          </el-select>
        </el-form-item>
      </el-form>
      <p v-if="!canWrite" class="read-only-hint">当前账号为只读权限，需要智能获客管理权限才能保存。</p>
    </section>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { ElOption, ElSelect } from 'element-plus'
import GlassButton from '@/components/GlassButton.vue'
import { getAcquisitionProfile, saveAcquisitionProfile } from '@/api/salesAutomation'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'

const TagInput = defineComponent({
  name: 'SalesTagInput',
  props: { modelValue: { type: Array, default: () => [] }, placeholder: { type: String, default: '' } },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h(ElSelect, {
      modelValue: props.modelValue,
      'onUpdate:modelValue': value => emit('update:modelValue', value),
      multiple: true,
      filterable: true,
      allowCreate: true,
      defaultFirstOption: true,
      placeholder: props.placeholder,
      style: 'width: 100%',
    }, () => props.modelValue.map(item => h(ElOption, { key: item, label: item, value: item })))
  },
})

const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('sales_automation:admin'))
const loading = ref(false)
const saving = ref(false)
const emptyForm = () => ({
  company_name: '', company_website: '', products: [], advantages: [],
  target_countries: [], target_industries: [], target_roles: [], exclusions: [], default_language: 'en',
})
const form = reactive(emptyForm())

async function load() {
  loading.value = true
  try {
    const res = await getAcquisitionProfile()
    if (res.data) Object.assign(form, emptyForm(), res.data)
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!form.company_name.trim()) {
    msgError('请填写公司名称')
    return
  }
  saving.value = true
  try {
    const res = await saveAcquisitionProfile(form)
    Object.assign(form, emptyForm(), res.data)
    msgSuccess('保存')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
@import './salesAutomation.css';
.profile-card { max-width: 1040px; }
.target-heading { margin-top: 8px; padding-top: 18px; border-top: 1px solid var(--border-color); }
.language-field { max-width: 280px; }
.read-only-hint { margin: 4px 0 0; color: var(--text-muted); font-size: 12px; }
</style>
