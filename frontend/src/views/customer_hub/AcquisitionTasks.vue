<template>
  <div class="workflow">
    <div class="actions"><el-button v-permission="'sales_automation:admin'" :loading="profileLoading" @click="openProfile">配置获客模型</el-button><el-button v-any-permission="['sales_automation:write','sales_automation:admin']" type="primary" @click="jobDialog = true">创建获客任务</el-button></div>
    <el-alert v-if="profileLoadError" type="error" title="获客模型加载失败，未打开编辑器，避免覆盖现有配置。" :closable="false" show-icon><template #default><el-button link type="primary" @click="openProfile">重试</el-button></template></el-alert>
    <el-alert v-else-if="workflowError" type="error" title="操作失败，请检查字段或权限后重试。" :closable="false" show-icon />
    <CustomerHubWorkspace :key="refreshKey" kind="acquisition" />
    <el-dialog v-model="jobDialog" title="创建获客任务" width="520"><el-form label-position="top"><el-form-item label="任务名称"><el-input v-model="job.name" /></el-form-item><el-form-item label="目标数量"><el-input-number v-model="job.target_count" :min="1" :max="500" /></el-form-item><el-form-item label="国家（逗号分隔）"><el-input v-model="job.countries" /></el-form-item></el-form><template #footer><el-button @click="jobDialog = false">取消</el-button><el-button type="primary" :loading="workflowLoading" @click="submitJob">创建</el-button></template></el-dialog>
    <el-dialog v-model="profileDialog" title="配置获客模型" width="700"><el-form label-position="top" class="profile-form"><el-form-item label="公司名称"><el-input v-model="form.company_name" /></el-form-item><el-form-item label="公司网站"><el-input v-model="form.company_website" /></el-form-item><ListField v-model="form.products" label="产品" /><ListField v-model="form.competitive_advantages" label="竞争优势" /><ListField v-model="form.target_countries" label="目标国家" /><ListField v-model="form.target_industries" label="目标行业" /><ListField v-model="form.target_roles" label="目标角色" /><ListField v-model="form.exclusions" label="排除条件" /><el-form-item label="默认触达语言"><el-input v-model="form.default_outreach_language" /></el-form-item><el-form-item label="策略版本"><el-input v-model="form.policy_version" /></el-form-item><el-form-item label="策略 JSON" class="span-two"><el-input v-model="form.policyText" type="textarea" :rows="6" /></el-form-item></el-form><template #footer><el-button @click="profileDialog = false">取消</el-button><el-button v-permission="'sales_automation:admin'" type="primary" :loading="workflowLoading" @click="submitProfile">保存</el-button></template></el-dialog>
  </div>
</template>
<script setup>
import { computed, defineComponent, h, reactive, ref } from 'vue'
import { ElFormItem, ElInput } from 'element-plus'
import { msgError, msgSuccess } from '@/utils/feedback'
import CustomerHubWorkspace from './CustomerHubWorkspace.vue'
import { useAcquisitionWorkflows } from './composables/useCustomerHub'
import { buildAcquisitionProfilePayload, shouldOpenProfileEditor } from './customerHubController'
const { workflowLoading, workflowError, loadProfile, saveProfile, createJob } = useAcquisitionWorkflows()
const refreshKey = ref(0), jobDialog = ref(false), profileDialog = ref(false), profileLoading = ref(false), profileLoadError = ref(false)
const job = reactive({ name: '', target_count: 20, countries: '' })
const form = reactive({ company_name: '', company_website: '', products: [], competitive_advantages: [], target_countries: [], target_industries: [], target_roles: [], exclusions: [], default_outreach_language: 'en', policy_version: '', policyText: '{}' })
const split = value => value.split(',').map(item => item.trim()).filter(Boolean)
async function openProfile() { profileLoading.value = true; profileLoadError.value = false; const result = await loadProfile(); profileLoading.value = false; if (!shouldOpenProfileEditor(result)) { profileLoadError.value = true; return } const p = result.data || {}; Object.assign(form, { company_name: p.company_name || '', company_website: p.company_website || '', products: p.products || [], competitive_advantages: p.advantages || [], target_countries: p.target_countries || [], target_industries: p.target_industries || [], target_roles: p.target_roles || [], exclusions: p.exclusions || [], default_outreach_language: p.default_language || 'en', policy_version: p.policy_version || '', policyText: JSON.stringify(p.policy_json || {}, null, 2) }); profileDialog.value = true }
async function submitJob() { if (await createJob({ name: job.name, target_count: job.target_count, adapter: 'agent', criteria_json: { countries: split(job.countries) } })) { jobDialog.value = false; refreshKey.value++; msgSuccess('创建获客任务') } }
async function submitProfile() { let policy_json; try { policy_json = JSON.parse(form.policyText) } catch { msgError('策略 JSON 格式错误'); return } if (await saveProfile(buildAcquisitionProfilePayload({ ...form, policy_json }))) { profileDialog.value = false; msgSuccess('保存获客模型') } }
const ListField = defineComponent({ props: { modelValue: Array, label: String }, emits: ['update:modelValue'], setup(props, { emit }) { const text = computed({ get: () => (props.modelValue || []).join(', '), set: value => emit('update:modelValue', split(value)) }); return () => h(ElFormItem, { label: props.label }, () => h(ElInput, { modelValue: text.value, 'onUpdate:modelValue': value => { text.value = value } })) } })
</script>
<style scoped>
.workflow { display: grid; gap: 12px; }.actions { display: flex; justify-content: flex-end; gap: 8px; }.profile-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }.span-two { grid-column: 1 / -1; }@media (max-width: 700px) { .profile-form { grid-template-columns: 1fr; }.span-two { grid-column: auto; } }
</style>
