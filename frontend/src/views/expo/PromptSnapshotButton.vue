<template>
  <div>
    <span class="version-label">{{ result.prompt_version ? `${result.prompt_version.name} · 修订 ${result.prompt_version.revision}` : '历史图片' }}</span>
    <GlassButton v-permission="'expo:admin'" variant="link" @click="open">查看提示词</GlassButton>
    <DetailDrawer v-model="visible" title="生成时的提示词快照" width="min(720px, 100vw)" :loading="loading">
      <template v-if="snapshot"><p>{{ snapshot.version_name }} · 修订 {{ snapshot.revision }}</p><pre class="snapshot">{{ snapshot.text }}</pre></template>
      <div v-else-if="error" role="alert">{{ error }} <GlassButton variant="link" @click="open">重试</GlassButton></div>
      <el-empty v-else-if="!loading" description="此历史任务未保存提示词快照" />
    </DetailDrawer>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { getPromptSnapshot } from '@/api/expo'
const props = defineProps({ result: { type: Object, required: true } })
const visible = ref(false), loading = ref(false), snapshot = ref(null), error = ref('')
async function open() {
  visible.value = true; loading.value = true; snapshot.value = null; error.value = ''
  try { snapshot.value = (await getPromptSnapshot(props.result.id)).data }
  catch { error.value = '提示词加载失败，请重试' }
  finally { loading.value = false }
}
</script>
<style scoped>
.version-label { color: var(--el-text-color-secondary); font-size: 12px; }
.snapshot { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
</style>
