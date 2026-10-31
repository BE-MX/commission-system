<template>
  <section>
    <InvoiceRouteStatus :invoice="form" />
    <el-form-item v-if="!form.id" label="正式办理路线">
      <el-select v-model="form.transaction_route" aria-label="正式办理路线" :disabled="resource.loading.value || !!resource.error.value">
        <el-option value="legacy" label="小满流程" :disabled="resource.data.value?.capabilities?.legacy === false" />
        <el-option value="local" label="方舟独立" :disabled="resource.data.value?.capabilities?.local_new_orders !== true" />
      </el-select>
    </el-form-item>
    <GlassButton v-else-if="routeEditable(form)" v-permission="'commerce_transition:write'" :disabled="dirty" @click="openChange">调整草稿路线</GlassButton>
    <ListPageStatus :error="resource.errorMessage.value" :loading="resource.loading.value" :has-data="resource.hasData.value" :paged="false" @retry="load" />
    <el-dialog v-model="changeOpen" title="调整草稿办理路线" width="480px" append-to-body :close-on-click-modal="!command.pending.value" :show-close="!command.pending.value">
      <el-form label-position="top" :disabled="command.pending.value"><el-form-item label="正式路线"><el-select v-model="nextRoute"><el-option value="legacy" label="小满流程" :disabled="resource.data.value?.capabilities?.legacy !== true" /><el-option value="local" label="方舟独立" :disabled="resource.data.value?.capabilities?.local_new_orders !== true" /></el-select></el-form-item><el-form-item label="核验依据"><el-input v-model="evidence" type="textarea" maxlength="1000" /></el-form-item></el-form>
      <p>仅无经济事实的草稿可调整。保存后重新读取办理权与商品身份。</p>
      <el-alert v-if="command.failure.value" :title="command.failure.value" type="error" :closable="false" />
      <template #footer><GlassButton :disabled="command.pending.value" @click="changeOpen = false">返回</GlassButton><GlassButton v-permission="'commerce_transition:write'" variant="primary" :loading="command.pending.value" @click="change">保存路线</GlassButton></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { onDeactivated, ref, watch } from 'vue'
import { getTransitionStatus, setInvoiceRoute } from '@/api/commerceTransition'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { routeEditable } from './routeState'
import InvoiceRouteStatus from './InvoiceRouteStatus.vue'
const props = defineProps({ form: Object, dirty: Boolean })
const emit = defineEmits(['changed'])
const resource = useAsyncResource(async (_, { signal }) => (await getTransitionStatus({ signal, suppressToast: true })).data)
const changeOpen = ref(false), nextRoute = ref('legacy'), evidence = ref(''), command = useNativeCommand()
async function load() {
 const loaded = await resource.load()
 const recommended = resource.data.value?.capabilities?.default_route
 if (loaded && !props.form.id && ['legacy','local'].includes(recommended)) props.form.transaction_route = recommended
 return loaded
}
function openChange() { nextRoute.value = props.form.transaction_route; evidence.value = ''; command.reset(); changeOpen.value = true }
async function change() {
 const result = await command.run({ payload: () => { if (!evidence.value.trim()) throw new Error('请填写核验依据'); return { route: nextRoute.value, expected_authority_epoch: props.form.authority_epoch, evidence: { reference: evidence.value.trim() } } }, send: body => { const { request_key, ...payload } = body; return setInvoiceRoute(props.form.id, payload) } })
 if(result.ok) { changeOpen.value = false; emit('changed') }
}
watch(() => props.form.id, load, { immediate: true })
onDeactivated(() => { changeOpen.value = false; resource.cancel() })
</script>
