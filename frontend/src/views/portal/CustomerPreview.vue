<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
const route = useRoute(), auth = useAuthStore()
const data = ref(null), error = ref(''), loading = ref(false), page = ref(1), pageSize = ref(20)
let generation = 0, controller
const rows = computed(() => (data.value?.items || []).slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
function clear() { generation++; controller?.abort(); data.value = null; error.value = ''; loading.value = false; page.value = 1 }
async function load() {
  clear(); const current = generation; controller = new AbortController(); loading.value = true
  try {
    const result = await portalAdminApi.customerPreview(route.params.accessId, controller.signal)
    if (current !== generation) return
    if (result.preview !== true || result.access_id !== route.params.accessId || !Array.isArray(result.items)) throw new Error('预览响应不完整，请重新读取。')
    data.value = result
  } catch (e) { if (current === generation) error.value = e?.response?.data?.message || e.message || '预览暂不可用。' }
  finally { if (current === generation) loading.value = false }
}
watch(() => route.params.accessId, load, { immediate: true })
watch(() => [auth.accessToken, auth.user], clear, { flush: 'sync' })
onBeforeUnmount(clear)
</script>
<template>
  <section class="customer-preview">
    <header><div><h1>Preview · 客户目录预览</h1><p>查看当前已发布的客户型号、颜色与货号展示。此页不建立客户登录态。</p></div><GlassButton :disabled="loading" @click="load">重新读取预览</GlassButton></header>
    <el-alert title="只读展示预览：没有下单或 PI 下载操作；价格、库存与图片请在实际客户站按当前权限读取。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="data"><p>已发布映射 v{{ data.mapping_version }} · 目录 v{{ data.catalog_version }} · 共 {{ data.items.length }} 个规格</p><el-alert v-if="data.access_status !== 'enabled'" title="该客户访问尚未启用；以下配置预览不代表客户当前可以登录。" type="warning" :closable="false" /></template>
    <el-table v-loading="loading" :data="rows" border class="list-table" v-sticky-scrollbar><template #empty><el-empty :image-size="72" description="暂无可预览的已发布授权商品" /></template>
      <el-table-column prop="model_name" label="客户型号" min-width="180" /><el-table-column prop="color_name" label="客户颜色" min-width="130" /><el-table-column prop="customer_sku" label="客户货号" min-width="160" /><el-table-column prop="length" label="长度" min-width="90" /><el-table-column prop="weight" label="重量" min-width="90" /><el-table-column prop="unit" label="单位" min-width="90" />
    </el-table>
    <el-pagination v-if="data" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="data.items.length" layout="total, sizes, prev, pager, next" @size-change="page = 1" />
  </section>
</template>
<style scoped>
header { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; justify-content: space-between; margin-bottom: 20px; } h1 { font-size: 24px; } p { color: var(--text-secondary); overflow-wrap: anywhere; } .el-alert { margin-bottom: 16px; } .el-pagination { overflow-x: auto; margin-top: 16px; }
</style>
