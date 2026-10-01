<template>
  <section class="directory">
    <div class="segments"><button v-for="(label,key) in tiers" :key="key" type="button" :class="{selected:searchForm.tier===key}" :aria-pressed="searchForm.tier===key" @click="selectTier(key)"><span>{{ label }}</span><strong>{{ segmentSummary?.[key] ?? '—' }}</strong></button></div>
    <p class="hint">公司统一分层 · {{ policyVersion || '策略版本未提供' }}。分层与事项优先级分开计算，承诺期限优先。</p>
    <section class="table-card lg-card is-static">
      <div class="toolbar"><el-input v-model="searchForm.keyword" clearable aria-label="搜索客户" placeholder="搜索客户名称或编号" @keyup.enter="handleSearch" @clear="handleSearch" /><el-select v-model="searchForm.customer_scope" aria-label="客户归属范围" @change="handleSearch"><el-option label="我主负责" value="primary" /><el-option label="我协作" value="collaborator" /><el-option label="授权可见" value="authorized" /></el-select><el-select v-model="searchForm.sort" aria-label="客户排序" @change="handleSearch"><el-option label="经营价值" value="value" /><el-option label="最近订单" value="order" /><el-option label="最近互动" value="contact" /><el-option label="档案完整度" value="profile" /><el-option label="最近更新" value="updated" /></el-select><el-select v-model="searchForm.focus" clearable aria-label="经营重点" placeholder="全部经营重点" @change="handleSearch"><el-option label="承诺与风险" value="commitments" /><el-option label="当前需求" value="needs" /><el-option label="复购窗口" value="reorder" /></el-select><GlassButton variant="secondary" :loading="loading" @click="handleSearch">刷新</GlassButton><GlassButton v-if="searchForm.tier" variant="ghost" @click="selectTier('')">全部分层</GlassButton></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-table v-loading="loading" :data="list" row-key="customer_id" border class="list-table">
        <el-table-column label="客户" min-width="210"><template #default="{row}"><button class="customer-link" type="button" @click="$emit('open-customer',row.customer_id)"><strong>{{ row.display_name || row.canonical_company_name || `客户 #${row.customer_id}` }}</strong><span>{{ row.customer_code || '编号未提供' }}</span></button></template></el-table-column>
        <el-table-column label="统一分层 / 依据" min-width="230"><template #default="{row}"><el-tag size="small">{{ tiers[row.tier] || '待核验' }}</el-tag><p>{{ row.tier_reason || '分层依据未提供' }}</p><span class="hint">{{ row.tier_policy_version || '策略版本未提供' }}</span></template></el-table-column>
        <el-table-column label="商业订单" min-width="150"><template #default="{row}"><strong>{{ row.order_count ?? '—' }} 单</strong><p>{{ row.order_amount_usd == null ? 'USD汇总未提供' : `USD ${Number(row.order_amount_usd).toLocaleString('en-US')}` }}</p><span class="hint">最近 {{ date(row.last_order_at) }}</span></template></el-table-column>
        <el-table-column label="经营上下文" min-width="220"><template #default="{row}"><p>{{ row.primary_product_families?.join('、') || '产品来源未提供' }}</p><p>最近互动 {{ date(row.last_interaction_at) }}</p><span class="hint">数据截至 {{ date(row.data_as_of) }}</span></template></el-table-column>
        <el-table-column label="档案" min-width="120"><template #default="{row}">{{ identityLabel(row.identity_status) }}<p>完整度 {{ row.profile_completeness ?? '—' }}%</p></template></el-table-column>
        <el-table-column label="操作" min-width="118" max-width="160" class-name="table-action-column" fixed="right"><template #default="{row}"><GlassButton variant="link" @click="$emit('open-customer',row.customer_id)">客户作战卡</GlassButton></template></el-table-column>
      </el-table><el-empty v-if="!loading && !error && !list.length" description="当前筛选下没有可见客户" :image-size="72" />
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </section>
    <p class="hint">来源同步：{{ sourceWatermarks?.length ? sourceWatermarks.map(row=>`${row.source} · ${row.status} · ${date(row.synced_through)}`).join('；') : '暂无可靠同步水位' }}</p>
  </section>
</template>
<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useListPage } from '@/composables/useListPage'
import { listCustomers } from '@/api/customerHub'
import { formatBeijingDateTime } from '@/utils/datetime'
import { identityLabel } from './operationsPresentation'
import { errorMessage } from './workbenchV2Controller'
defineEmits(['open-customer'])
const tiers={reorder:'复购窗口',active:'活跃客户',new:'新客培育',wake:'需唤醒',sleep:'沉睡客户',unknown:'待核验'}
const route=useRoute(),router=useRouter()
const segmentSummary=ref(null),policyVersion=ref(null),sourceWatermarks=ref([]),error=ref('')
let latest=0,lastResult={items:[],total:0}
const {loading,list,total,page,pageSize,searchForm,fetchList,handleSearch,handlePageChange,handleSizeChange}=useListPage(async params=>{const request=++latest;error.value='';router.replace({query:{...route.query,mode:'customers',...Object.fromEntries(Object.entries(params).map(([key,value])=>[`c_${key}`,String(value)]))}});try{const clean=Object.fromEntries(Object.entries(params).filter(([,value])=>value!=='' && value!=null));const response=await listCustomers(clean);if(request===latest){segmentSummary.value=response.data.segment_summary;policyVersion.value=response.data.policy_version;sourceWatermarks.value=response.data.source_watermarks;lastResult=response.data}return response.data}catch(e){if(request===latest){error.value=`${errorMessage(e)} 当前保留上次结果，可能已过期。`;segmentSummary.value=null}return lastResult}},{pageSize:[20,50,100].includes(Number(route.query.c_page_size))?Number(route.query.c_page_size):20,searchForm:{keyword:String(route.query.c_keyword||''),customer_scope:['primary','collaborator','authorized'].includes(route.query.c_customer_scope)?route.query.c_customer_scope:'primary',tier:tiers[route.query.c_tier]?route.query.c_tier:'',sort:['value','order','contact','profile','updated'].includes(route.query.c_sort)?route.query.c_sort:'value',focus:['commitments','needs','reorder'].includes(route.query.c_focus)?route.query.c_focus:''}})
page.value=Math.max(1,Number(route.query.c_page)||1)
const date=value=>value?formatBeijingDateTime(value,{seconds:false}):'未提供'
function selectTier(tier){searchForm.tier=tier;handleSearch()}
defineExpose({refresh:fetchList})
</script>
<style scoped>.directory{display:grid;gap:14px}.segments{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}.segments button{font:inherit;padding:14px;display:grid;gap:8px;text-align:left;border:1px solid var(--border-color);border-radius:var(--card-radius);background:var(--card-bg);color:var(--text-secondary);cursor:pointer}.segments strong{font-size:22px;color:var(--text-primary);font-variant-numeric:tabular-nums}.segments .selected{border-color:var(--color-primary)}.hint{color:var(--text-muted);font-size:12px;line-height:1.6;margin:0}.table-card{padding:0;overflow:hidden}.toolbar{display:flex;flex-wrap:wrap;gap:8px;padding:12px;background:var(--toolbar-bg)}.toolbar :deep(.el-input){flex:1;min-width:200px}.toolbar :deep(.el-select){width:160px}.customer-link{display:grid;gap:6px;border:0;background:transparent;color:var(--text-primary);font:inherit;text-align:left;cursor:pointer}.customer-link strong{color:var(--color-primary)}.customer-link span{color:var(--text-muted);font-size:12px}p{margin:6px 0;line-height:1.6}.el-pagination{padding:12px;justify-content:flex-end;overflow-x:auto}button:focus-visible{outline:2px solid var(--color-primary);outline-offset:3px}@media(max-width:850px){.segments{grid-template-columns:repeat(3,1fr)}}@media(max-width:500px){.segments{grid-template-columns:repeat(2,1fr)}.toolbar :deep(.el-select){flex:1;min-width:140px}}</style>
