<template>
  <el-dialog class="customer-hub-dialog" v-model="visible" append-to-body title="新建维护计划" width="640px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-form label-position="top" :disabled="saving">
      <el-form-item label="计划类型"><el-select v-model="planType"><el-option v-for="type in MAINTENANCE_PLAN_TYPES" :key="type" :value="type" :label="MAINTENANCE_PLAN_TYPE_LABELS[type]" /></el-select></el-form-item>
      <el-form-item label="计划名称"><el-input v-model="form.title" placeholder="要在什么时候、依据什么推进客户" /></el-form-item>
      <template v-if="planType==='manual'">
        <el-form-item label="计划时间（北京时间）"><el-date-picker v-model="form.scheduled_at" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" /></el-form-item>
        <el-form-item label="联系目的"><el-input v-model="form.purpose" /></el-form-item>
        <el-form-item label="渠道"><ChannelSelect v-model="form.channel" /></el-form-item>
      </template>
      <template v-else-if="planType==='birthday'">
        <SourceStatus :error="sourcesError" :loading="sourcesLoading" @refresh="loadSources" />
        <el-form-item label="已核验联系人"><el-select v-model="form.contact_id" :loading="sourcesLoading" placeholder="选择有确证生日依据的联系人" @change="selectContact"><el-option v-for="contact in sources?.contacts || []" :key="contact.contact_id" :value="contact.contact_id" :label="`${contact.name || '姓名未提供'}${contact.selectable ? '' : ` · ${contact.unavailable_reason || '生日待核验'}`}`" :disabled="!contact.selectable" /></el-select></el-form-item>
        <div class="date-pair"><el-form-item label="生日月"><el-input-number v-model="form.month" :min="1" :max="12" /></el-form-item><el-form-item label="生日日期"><el-input-number v-model="form.day" :min="1" :max="31" /></el-form-item></div>
        <el-form-item v-if="form.month===2 && form.day===29" label="非闰年如何安排（需明确选择）"><el-radio-group v-model="form.leap_day_policy"><el-radio value="skip">当年跳过</el-radio><el-radio value="feb28">2 月 28 日</el-radio><el-radio value="mar1">3 月 1 日</el-radio></el-radio-group></el-form-item>
        <el-form-item label="客户当地联系时间（可选提示）"><el-time-picker v-model="form.local_contact_time" value-format="HH:mm:ss" /></el-form-item>
        <p class="hint">生日来源选自这个联系人的确证事实。若日期有误，先修订原始生日事实；年份未知不猜年龄。</p>
      </template>
      <template v-else-if="planType==='holiday'">
        <el-form-item label="节日名称 / 编码"><el-input v-model="form.holiday_code" /></el-form-item>
        <el-form-item label="适用地区"><el-input v-model="form.calendar_region" /></el-form-item>
        <el-form-item label="本次日期"><el-date-picker v-model="form.occurrence_local_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="客户当地联系时间（可选提示）"><el-time-picker v-model="form.local_contact_time" value-format="HH:mm:ss" /></el-form-item>
        <el-checkbox v-model="form.applicability_confirmed">已依据客户信息确认适用</el-checkbox>
      </template>
      <template v-else-if="planType==='campaign'">
        <el-alert v-if="campaignError" :title="campaignError" type="error" :closable="false" />
        <el-form-item label="已发布且正在生效的活动"><el-select v-model="form.campaign_id" :loading="campaignLoading" @change="selectCampaign"><el-option v-for="campaign in campaigns" :key="campaign.id" :value="campaign.id" :label="`${campaign.title} · ${campaign.status==='active'?'生效中':'当前不可用'}`" :disabled="campaign.status!=='active'" /></el-select></el-form-item>
        <p v-if="selectedCampaign" class="hint">有效期 {{ date(selectedCampaign.effective_from) }} — {{ date(selectedCampaign.effective_to) }} · 活动版本 {{ selectedCampaign.campaign_version }}</p>
        <GlassButton variant="secondary" :loading="previewLoading" :disabled="!selectedCampaign || selectedCampaign.status!=='active'" @click="checkCampaign">核验本客户是否适用</GlassButton>
        <p v-if="campaignPreview" class="hint">{{ campaignEligible ? '当前客户符合活动受众条件' : campaignExclusion }} · 预览有效至 {{ date(campaignPreview.expires_at) }}</p>
        <p class="hint">活动来源、版本和适用性由系统核验；保存时服务端再次检查。</p>
      </template>
      <template v-else-if="planType==='shipping'">
        <SourceStatus :error="sourcesError" :loading="sourcesLoading" @refresh="loadSources" />
        <el-form-item label="真实物流事件"><el-select v-model="form.shipment_event_id" :loading="sourcesLoading" @change="selectShippingEvent"><el-option v-for="event in sources?.shipment_events || []" :key="event.shipment_event_id" :value="event.shipment_event_id" :label="`${event.title || event.trigger_event_type} · ${date(event.occurred_at)}${event.selectable ? '' : ` · ${event.unavailable_reason || '不可用'}`}`" :disabled="!event.selectable" /></el-select></el-form-item>
        <el-form-item label="已确认的物流订单关联"><el-select v-model="form.shipment_order_link_ids" multiple placeholder="选定事件后自动匹配，可确认本次涉及订单"><el-option v-for="link in eligibleShippingLinks" :key="link.id" :value="link.id" :label="`${link.order_no || `订单 #${link.order_id}`} · ${link.tracking_no || `运单 #${link.shipment_id}`}`" :disabled="!link.selectable || link.state!=='active'" /></el-select></el-form-item>
        <p class="hint">仅使用明确的订单与运单关联；姓名或电话相似不会自动绑定。事件来源失效时不能继续保存。</p>
        <el-form-item label="联系渠道"><ChannelSelect v-model="form.contact_channel" /></el-form-item>
      </template>
      <template v-else-if="planType==='sample'">
        <el-form-item label="关联样品事项"><el-select v-model="form.sample_case_id"><el-option v-for="sample in samples" :key="sample.id" :value="sample.id" :label="`样品订单 #${sample.sample_order_id} · ${SAMPLE_STAGE_LABELS[sample.stage]}`" /></el-select></el-form-item>
        <el-form-item label="计划目标"><el-radio-group v-model="samplePurpose"><el-radio value="test">安排测试</el-radio><el-radio value="feedback">收集反馈</el-radio></el-radio-group></el-form-item>
        <el-form-item v-if="samplePurpose==='test'" label="计划测试日期"><el-date-picker v-model="form.test_planned_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item v-else label="反馈期限（北京时间）"><el-date-picker v-model="form.feedback_due_at" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" /></el-form-item>
      </template>
      <template v-if="planType!=='campaign'"><p v-if="planType==='shipping'" class="hint">事件关联依据 {{ form.evidence_refs.length }} 条，保存原始来源版本。</p><EvidencePicker v-else v-model="form.evidence_refs" :customer-id="customerId" references kind="fact" /></template>
    </el-form>
    <template #footer><GlassButton variant="secondary" :disabled="saving" :loading="sourcesLoading || campaignLoading" @click="refreshSources">刷新可选来源（保留输入）</GlassButton><GlassButton v-permission="'customer_pcw:write'" variant="primary" :loading="saving" :disabled="sourcesLoading || previewLoading || (planType==='campaign' && !campaignEligible) || (['birthday','shipping'].includes(planType) && !sources)" @click="save">保存计划</GlassButton></template>
  </el-dialog>
</template>
<script setup>
import { computed, defineComponent, h, reactive, ref, watch } from 'vue'
import { ElOption, ElSelect } from 'element-plus'
import { createMaintenancePlan, getMaintenancePlanSources, listCampaigns, previewCampaign } from '@/api/customerHub'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { MAINTENANCE_PLAN_TYPES, MAINTENANCE_PLAN_TYPE_LABELS, SAMPLE_STAGE_LABELS } from '../customerWorkspaceController'
import { birthdayFormFromContact, buildSourcedPlanPayload, shippingFormFromEvent } from '../maintenancePlanController'
import { createSubmissionIdentity, errorMessage } from '../workbenchV2Controller'
import { channelLabels } from '../operationsPresentation'
import EvidencePicker from '../EvidencePicker.vue'
const props=defineProps({customerId:{type:Number,required:true},samples:{type:Array,default:()=>[]}}),emit=defineEmits(['saved'])
const visible=ref(false),saving=ref(false),error=ref(''),planType=ref('manual'),samplePurpose=ref('test')
const defaults=()=>({title:'',scheduled_at:'',purpose:'',channel:'whatsapp',contact_id:null,month:null,day:null,local_contact_time:null,leap_day_policy:'skip',holiday_code:'',calendar_region:'',occurrence_local_date:'',applicability_confirmed:false,campaign_id:null,shipment_event_id:null,shipment_order_link_ids:[],contact_channel:'whatsapp',sample_case_id:null,test_planned_date:'',feedback_due_at:'',evidence_refs:[]})
const form=reactive(defaults())
const sources=ref(null),sourcesLoading=ref(false),sourcesError=ref(''),campaigns=ref([]),campaignLoading=ref(false),campaignError=ref(''),campaignPreview=ref(null),previewLoading=ref(false),identity=createSubmissionIdentity('plan')
const selectedCampaign=computed(()=>campaigns.value.find(row=>row.id===form.campaign_id)),selectedEvent=computed(()=>sources.value?.shipment_events?.find(row=>row.shipment_event_id===form.shipment_event_id))
const eligibleShippingLinks=computed(()=>sources.value?.shipment_links?.filter(row=>selectedEvent.value?.shipment_order_link_ids?.includes(row.id)) || [])
const campaignEligible=computed(()=>campaignPreview.value?.eligible?.some(row=>row.customer_id===props.customerId)===true)
const campaignExclusion=computed(()=>campaignPreview.value?.excluded?.find(row=>row.customer_id===props.customerId)?.reasons?.join('、') || '当前客户不符合活动受众条件')
const date=value=>value?formatBeijingDateTime(value,{seconds:false}):'未提供'
let sourceRequest=0,campaignRequest=0,previewRequest=0
async function loadSources(){const request=++sourceRequest;sourcesLoading.value=true;sourcesError.value='';try{const response=await getMaintenancePlanSources(props.customerId);if(request===sourceRequest)sources.value=response.data}catch(e){if(request===sourceRequest){sources.value=null;sourcesError.value=errorMessage(e)}}finally{if(request===sourceRequest)sourcesLoading.value=false}}
async function loadCampaigns(){const request=++campaignRequest;campaignLoading.value=true;campaignError.value='';try{const response=await listCampaigns({});if(request===campaignRequest)campaigns.value=response.data?.items||[]}catch(e){if(request===campaignRequest){campaigns.value=[];campaignError.value=errorMessage(e)}}finally{if(request===campaignRequest)campaignLoading.value=false}}
async function refreshSources(){await Promise.allSettled([loadSources(),loadCampaigns()]);campaignPreview.value=null}
function open(){identity.reset();error.value='';visible.value=true;refreshSources()}
function selectContact(id){const row=sources.value?.contacts?.find(contact=>contact.contact_id===id);if(row)Object.assign(form,birthdayFormFromContact(row))}
function selectShippingEvent(id){const row=sources.value?.shipment_events?.find(event=>event.shipment_event_id===id);if(row)Object.assign(form,shippingFormFromEvent(row))}
function selectCampaign(){++previewRequest;campaignPreview.value=null;previewLoading.value=false;campaignError.value=''}
async function checkCampaign(){const campaign=selectedCampaign.value;if(!campaign)return;const request=++previewRequest;previewLoading.value=true;campaignError.value='';try{const response=await previewCampaign(campaign.id);if(request===previewRequest)campaignPreview.value={...response.data,campaign_id:campaign.id,campaign_version:campaign.campaign_version}}catch(e){if(request===previewRequest){campaignPreview.value=null;campaignError.value=errorMessage(e)}}finally{if(request===previewRequest)previewLoading.value=false}}
async function save(){if(saving.value)return;error.value='';try{const input={...form,...(planType.value==='sample'?samplePurpose.value==='test'?{feedback_due_at:null,purpose:'test'}:{test_planned_date:null,purpose:'feedback'}:{})};const payload=buildSourcedPlanPayload(planType.value,input,sources.value,{customerId:props.customerId,campaigns:campaigns.value,campaignPreview:campaignPreview.value,samples:props.samples});saving.value=true;await createMaintenancePlan(props.customerId,payload,identity.forPayload(payload));msgSuccess('维护计划已保存');visible.value=false;Object.assign(form,defaults());campaignPreview.value=null;emit('saved')}catch(e){error.value=errorMessage(e)}finally{saving.value=false}}
watch(planType,()=>{form.evidence_refs=[];error.value='';if(planType.value==='birthday' && form.contact_id)selectContact(form.contact_id);if(planType.value==='shipping' && form.shipment_event_id)selectShippingEvent(form.shipment_event_id)})
const ChannelSelect=defineComponent({props:{modelValue:String},emits:['update:modelValue'],setup(componentProps,{emit:send}){return()=>h(ElSelect,{modelValue:componentProps.modelValue,'onUpdate:modelValue':value=>send('update:modelValue',value)},()=>Object.entries(channelLabels).map(([value,label])=>h(ElOption,{value,label})))}})
const SourceStatus=defineComponent({props:{error:String,loading:Boolean},emits:['refresh'],setup(componentProps,{emit:send}){return()=>h('div',{class:'source-status'},[componentProps.error?h('p',{class:'source-error'},componentProps.error):null,h('button',{type:'button',disabled:componentProps.loading,onClick:()=>send('refresh')},componentProps.loading?'加载真实来源…':'刷新联系人与物流来源')])}})
defineExpose({open})
</script>
<style scoped>.date-pair{display:flex;gap:16px;flex-wrap:wrap}.hint{color:var(--text-muted);font-size:12px;line-height:1.6}.el-select,.el-date-editor{max-width:100%}.channel-select{width:100%;padding:9px;border:1px solid var(--border-color);border-radius:var(--input-radius,8px);background:var(--card-bg);color:var(--text-primary)}:deep(.source-status){margin-bottom:12px}:deep(.source-error){color:var(--color-danger-text)}:deep(.source-status button){font:inherit;padding:8px 12px;border:1px solid var(--border-color);border-radius:8px;background:var(--card-bg);color:var(--text-primary);cursor:pointer}</style>
