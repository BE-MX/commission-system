<template>
  <el-dialog v-model="visible" title="跟进设置" width="480px" append-to-body>
    <el-form v-if="form" label-position="top">
      <el-form-item label="发货后几天提醒收货回访">
        <el-input-number v-model="form.receipt_delay_days" :min="1" :max="30" />
      </el-form-item>
      <el-form-item label="紧急异常推送给（钉钉）">
        <el-select v-model="form.urgent_receiver_user_ids" multiple filterable remote :remote-method="searchUsers" class="cfg-full">
          <el-option v-for="u in userOptions" :key="u.id" :value="u.id" :label="u.real_name" />
        </el-select>
      </el-form-item>
      <el-form-item label="客户跟进频率（天，超期在时间线标黄）">
        <div class="cfg-freq">
          <label v-for="level in Object.keys(form.frequency_days)" :key="level">
            <span>{{ level }}</span>
            <el-input-number v-model="form.frequency_days[level]" :min="1" :max="365" />
          </label>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <GlassButton @click="visible = false">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" @click="save">保存</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError, msgSuccessText } from '@/utils/feedback'

const visible = ref(false)
const saving = ref(false)
const form = ref(null)
const userOptions = ref([])

async function searchUsers(q) {
  try {
    const found = await followupApi.users(q)
    const known = new Map(userOptions.value.map(u => [u.id, u]))
    found.forEach(u => known.set(u.id, u))
    userOptions.value = [...known.values()]
  } catch (e) { msgError(apiError(e, '人员加载失败'), e) }
}

async function open() {
  visible.value = true
  try {
    form.value = await followupApi.config()
    await searchUsers('')
    // 已配置但不在首屏搜索结果里的接收人，先用编号占位，避免下拉显示成裸数字
    const ids = new Set(userOptions.value.map(u => u.id))
    form.value.urgent_receiver_user_ids.filter(id => !ids.has(id))
      .forEach(id => userOptions.value.push({ id, real_name: `用户 ${id}` }))
  } catch (e) {
    visible.value = false
    msgError(apiError(e, '配置加载失败'), e)
  }
}

async function save() {
  saving.value = true
  try {
    const { receipt_delay_days, urgent_receiver_user_ids, frequency_days } = form.value
    await followupApi.saveConfig({ receipt_delay_days, urgent_receiver_user_ids, frequency_days })
    msgSuccessText('跟进设置已保存')
    visible.value = false
  } catch (e) { msgError(apiError(e, '保存失败'), e) } finally { saving.value = false }
}

defineExpose({ open })
</script>

<style scoped>
.cfg-full { width: 100%; }
.cfg-freq { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 16px; }
.cfg-freq label { display: flex; align-items: center; gap: 8px; }
</style>
