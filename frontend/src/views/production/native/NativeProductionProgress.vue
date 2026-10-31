<template>
  <el-dialog :model-value="modelValue" title="工序进度" width="640px" :show-close="!pending" :close-on-click-modal="!pending" :close-on-press-escape="!pending" @update:model-value="$emit('update:modelValue', $event)">
    <ListPageStatus :error="progress.errorMessage.value" :loading="progress.loading.value" :has-data="progress.hasData.value" :paged="false" @retry="progress.load(item.id)" />
    <template v-if="progress.data.value">
      <p>{{ progress.data.value.route_name }} · 已完成 {{ progress.data.value.completed_steps }} / {{ progress.data.value.total_steps }} 道工序</p>
      <el-table :data="progress.data.value.steps" border class="list-table" v-sticky-scrollbar><el-table-column prop="step_order" label="顺序" min-width="65"/><el-table-column prop="process_name" label="工序" min-width="120"/><el-table-column label="完成情况" min-width="150"><template #default="{ row }">{{ row.status === 1 ? `${row.completed_by_user_name || '已完成'} · ${formatBeijingDateTime(row.completed_at)}` : '待完成' }}</template></el-table-column><el-table-column label="操作" min-width="110" class-name="table-action-column"><template #default="{ row }"><GlassButton v-if="row.status === 0" v-permission="'production:write'" variant="link" left-icon="Check" :loading="pending" @click="report(row)">登记本工序</GlassButton></template></el-table-column></el-table>
      <p>只允许已绑定本工序的当前登录用户报工。全部工序完成后，仍须仓库验收入库。</p>
    </template>
    <el-alert v-if="failure" :title="failure" type="error" :closable="false" show-icon />
  </el-dialog>
</template>
<script setup>
import { ref, watch } from 'vue'
import { getProgress } from '@/api/production'
import { productionClient } from '@/api/clients'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { formatBeijingDateTime } from '@/utils/datetime'
import { errorMessage } from '@/utils/errors'
import { msgSuccess } from '@/utils/feedback'
const props = defineProps({ modelValue: Boolean, item: Object }), emit = defineEmits(['update:modelValue', 'changed'])
const progress = useAsyncResource(async (id, { signal }) => getProgress(id, { signal, suppressToast: true }))
const pending = ref(false), failure = ref('')
watch(() => props.modelValue, visible => { if (visible) { failure.value = ''; progress.load(props.item.id, { clear: true }) } })
async function report(step) {
  if (pending.value) return
  const itemId = props.item.id
  pending.value = true; failure.value = ''
  try {
    const { data } = await productionClient.post('/local/report', { item_id: itemId, progress_id: step.id }, { suppressToast: true })
    if (!data.success) throw new Error(data.message)
    msgSuccess('登记工序'); if (props.modelValue && props.item.id === itemId) await progress.load(itemId); emit('changed')
  } catch (error) { failure.value = errorMessage(error) } finally { pending.value = false }
}
</script>
