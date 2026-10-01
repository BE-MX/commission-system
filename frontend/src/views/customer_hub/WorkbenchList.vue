<template>
  <section class="workbench" aria-label="客户事项">
    <div class="summary-grid">
      <button v-for="view in ITEM_VIEWS" :key="view.value" type="button" class="summary-card" :class="{selected:searchForm.view===view.value}" :aria-pressed="searchForm.view===view.value" @click="selectView(view.value)"><span>{{ view.label }}</span><strong>{{ loading || !summary ? '—' : view.count ? summary[view.count] : (summary.items_resolved + summary.items_cancelled) }}</strong></button>
      <div class="summary-card"><span>今日行动已完成</span><strong>{{ summary?.actions_done_today ?? '—' }}</strong><small>行动完成与事项解决分别记录</small></div>
    </div>
    <p class="hint">按事项计数，三视图互斥；已解决结果需复核时回到待我处理。所有业务时间均为北京时间。</p>
    <section v-if="capacity" class="capacity lg-card is-static"><strong>{{ capacity.business_date }} · 每日普通容量</strong><span>已承接 {{ capacity.admitted }} / {{ capacity.budget }} · 未承接 {{ capacity.queued }}</span><p class="hint">完成、终止和延后都不释放当日额度，也不自动补位。超额需明确主动再领一条及原因。</p></section>
    <div class="toolbar">
      <el-input v-if="!customerId" v-model="searchForm.keyword" clearable aria-label="搜索客户事项" placeholder="搜索客户或事项" @keyup.enter="handleSearch" @clear="handleSearch" />
      <el-select v-model="searchForm.customer_scope" aria-label="客户范围" @change="handleSearch"><el-option label="我主负责" value="primary" /><el-option label="我协作" value="collaborator" /><el-option label="授权可见" value="authorized" /></el-select>
      <el-select v-model="searchForm.action_scope" aria-label="行动执行范围" @change="handleSearch"><el-option label="需我行动" value="mine" /><el-option label="可见协作行动" value="visible" /></el-select>
      <el-select v-model="searchForm.focus" clearable aria-label="经营重点" placeholder="全部经营重点" @change="handleSearch"><el-option label="承诺与风险" value="commitments" /><el-option label="当前需求" value="needs" /><el-option label="复购窗口" value="reorder" /></el-select>
      <el-select v-if="searchForm.view==='ended'" v-model="searchForm.ended_state" clearable aria-label="结束结果" placeholder="全部结束结果" @change="handleSearch"><el-option label="已解决" value="resolved" /><el-option label="已终止" value="cancelled" /></el-select>
      <GlassButton variant="secondary" left-icon="Refresh" :loading="loading" @click="fetchList">刷新</GlassButton>
    </div>
    <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
    <p v-if="dataAsOf" class="hint">数据截至 {{ date(dataAsOf) }} · 策略 {{ policyVersion || '未提供' }}</p>
    <div v-loading="loading" class="action-list" :aria-busy="loading">
      <article v-for="row in list" :key="row.item_id" class="action-row">
        <div class="row-main"><button v-if="!customerId" v-permission="'customer:read'" class="customer-link" type="button" @click="$emit('open-customer',row.customer_id)">{{ row.customer_name }}</button><h3>{{ row.title }}</h3><p>{{ readableValue(row.goal_definition) || '目标定义未提供' }}</p><div class="meta"><el-tag size="small">{{ ITEM_STATE_LABELS[row.state] || row.state }}</el-tag><span>来源版本 {{ row.source_revision ?? '未提供' }}</span><span v-if="row.review_at">核验 {{ date(row.review_at) }}</span><span v-if="row.result_validity==='review_required'">解决证据失效 · 待复核</span><span v-if="row.state==='paused'">{{ row.pause_reason }} · 恢复：{{ row.resume_condition || '条件未提供' }}</span></div></div>
        <div class="row-action"><GlassButton variant="secondary" @click="itemDetail.open(row)">查看目标与进展</GlassButton><GlassButton v-if="row.can_admit" v-any-permission="['customer_pcw:write','customer_radar:write','customer:admin']" variant="primary" :disabled="loading || saving" @click="openAdmission(row)">{{ capacity && capacity.admitted >= capacity.budget ? '主动再领一条' : '领取到今日' }}</GlassButton><span v-else-if="row.daily_admitted" class="hint">已承接到今日</span></div>
      </article><el-empty v-if="!loading && !error && !list.length" description="当前范围没有事项，可调整筛选查看" :image-size="72" />
    </div>
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    <WorkItemDetail ref="itemDetail" @saved="saved" />
    <el-dialog class="customer-hub-dialog" v-model="admissionVisible" append-to-body title="领取到今日计划" width="480px"><p>{{ admissionItem?.title }}</p><el-alert v-if="admissionError" :title="admissionError" type="error" :closable="false" /><p v-if="allowExtra">当前普通额度已满。这次只增加一条额度，保留已领取集合。</p><el-input v-model="admissionReason" type="textarea" placeholder="本次主动承接原因" /><template #footer><GlassButton variant="secondary" :disabled="saving" @click="fetchList">刷新容量</GlassButton><GlassButton v-any-permission="['customer_pcw:write','customer_radar:write','customer:admin']" variant="primary" :loading="saving" :disabled="!capacity || (allowExtra && !admissionReason.trim())" @click="admit">{{ allowExtra ? '确认增加一条并领取' : '确认领取' }}</GlassButton></template></el-dialog>
  </section>
</template>
<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useListPage } from '@/composables/useListPage'
import { listWorkbenchItems, admitDailyPlanItem } from '@/api/customerHub'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { readableValue } from './operationsPresentation'
import { ITEM_VIEWS, ITEM_STATE_LABELS, createSubmissionIdentity, errorMessage } from './workbenchV2Controller'
import WorkItemDetail from './WorkItemDetail.vue'
const props=defineProps({customerId:{type:Number,default:null},initialItemId:{type:Number,default:null}}), emit=defineEmits(['open-customer','saved'])
const route=useRoute(),router=useRouter()
const summary=ref(null),capacity=ref(null),error=ref(''),dataAsOf=ref(null),policyVersion=ref(null),itemDetail=ref(null),saving=ref(false)
let latest=0,lastResult={items:[],total:0}
const {loading,list,total,page,pageSize,searchForm,fetchList,handleSearch,handlePageChange,handleSizeChange}=useListPage(async params=>{
 const request=++latest;error.value='';if(!props.customerId)router.replace({query:{...route.query,mode:'items',...Object.fromEntries(Object.entries(params).map(([key,value])=>[`w_${key}`,String(value)]))}});try{const clean=Object.fromEntries(Object.entries({...params,...(props.customerId?{customer_id:props.customerId}:{})}).filter(([,value])=>value!=='' && value!=null));const response=await listWorkbenchItems(clean);if(response.data?.count_unit!=='work_item')throw new Error('事项统计契约未就绪，请刷新后重试');if(request===latest){summary.value=response.data.summary;capacity.value=response.data.capacity;dataAsOf.value=response.data.data_as_of;policyVersion.value=response.data.policy_version;lastResult=response.data}return response.data}catch(e){if(request===latest){error.value=`${errorMessage(e)} 当前保留上次结果，可能已过期。`;summary.value=null;capacity.value=null}return lastResult}
},{pageSize:[20,50,100].includes(Number(route.query.w_page_size))?Number(route.query.w_page_size):20,searchForm:{keyword:props.customerId?'':String(route.query.w_keyword||''),customer_scope:props.customerId?'authorized':['primary','collaborator','authorized'].includes(route.query.w_customer_scope)?route.query.w_customer_scope:'primary',action_scope:props.customerId?'visible':route.query.w_action_scope==='visible'?'visible':'mine',view:['need_me','in_progress','ended'].includes(route.query.w_view)?route.query.w_view:'need_me',ended_state:['resolved','cancelled'].includes(route.query.w_ended_state)?route.query.w_ended_state:'',focus:['commitments','needs','reorder'].includes(route.query.w_focus)?route.query.w_focus:''}})
page.value=props.customerId?1:Math.max(1,Number(route.query.w_page)||1)
const date=value=>value?formatBeijingDateTime(value,{seconds:false}):'未提供'
const admissionVisible=ref(false),admissionItem=ref(null),admissionReason=ref(''),allowExtra=ref(false),admissionError=ref(''),identity=createSubmissionIdentity('admission')
function openAdmission(row){admissionItem.value=row;admissionReason.value='';allowExtra.value=Boolean(capacity.value && capacity.value.admitted>=capacity.value.budget);admissionError.value='';identity.reset();admissionVisible.value=true}
async function admit(){if(saving.value||!capacity.value)return;saving.value=true;admissionError.value='';const payload={item_id:admissionItem.value.item_id,expected_plan_version:capacity.value.version,allow_one_extra:allowExtra.value,reason:admissionReason.value.trim()};try{await admitDailyPlanItem(payload,identity.forPayload(payload));msgSuccess('已承接到今日，额度已登记');admissionVisible.value=false;await saved()}catch(e){admissionError.value=errorMessage(e)}finally{saving.value=false}}
function selectView(view){searchForm.view=ITEM_VIEWS.some(item=>item.value===view)?view:'need_me';handleSearch()}
async function saved(){await fetchList();emit('saved')}
watch(()=>props.customerId,()=>{lastResult={items:[],total:0};handleSearch()})
function openItem(id){itemDetail.value?.open({item_id:id})}
onMounted(()=>{if(props.initialItemId)openItem(props.initialItemId)})
defineExpose({refresh:fetchList,selectView,openItem})
</script>
<style scoped>
.workbench{display:grid;gap:14px;color:var(--text-primary)}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.summary-card{font:inherit;display:grid;gap:8px;text-align:left;padding:16px;border:1px solid var(--border-color);border-radius:var(--card-radius);background:var(--card-bg);color:var(--text-secondary)}button.summary-card{cursor:pointer}.summary-card strong{font-size:24px;font-variant-numeric:tabular-nums;color:var(--text-primary)}.summary-card.selected{border-color:var(--color-primary)}.summary-card small,.hint{font-size:12px;line-height:1.6;color:var(--text-muted);margin:0}.capacity{padding:14px;display:flex;gap:12px;flex-wrap:wrap}.capacity p{width:100%}.toolbar{display:flex;gap:8px;flex-wrap:wrap}.toolbar .el-input{flex:1;min-width:180px}.toolbar .el-select{width:160px}.action-list{border:1px solid var(--border-color);border-radius:var(--card-radius);background:var(--card-bg);min-height:100px}.action-row{display:flex;justify-content:space-between;gap:16px;padding:16px;border-bottom:1px solid var(--border-color)}.action-row:last-child{border:0}.row-main{min-width:0}.row-action{display:grid;gap:8px;align-content:center;justify-items:end}.customer-link{border:0;background:transparent;color:var(--color-primary);font:inherit;text-align:left;cursor:pointer}.row-main h3{font-size:15px;margin:8px 0}.row-main p{color:var(--text-secondary);overflow-wrap:anywhere}.meta{display:flex;gap:10px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--text-muted)}.el-pagination{overflow-x:auto}.summary-card:focus-visible,.customer-link:focus-visible{outline:2px solid var(--color-primary);outline-offset:3px}@media(max-width:768px){.summary-grid{grid-template-columns:repeat(2,1fr)}.action-row{flex-direction:column}.row-action{display:flex;justify-content:flex-end;flex-wrap:wrap}}
</style>
