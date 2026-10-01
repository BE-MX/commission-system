<template><section class="timeline"><h3>客户往来时间线</h3><el-alert v-if="error" title="时间线加载失败，请刷新重试。" type="error" :closable="false" /><GlassButton variant="secondary" :loading="loading" @click="fetchList">刷新时间线</GlassButton><el-timeline v-loading="loading"><el-timeline-item v-for="event in list" :key="event.event_id" :timestamp="event.occurred_at ? formatBeijingDateTime(event.occurred_at) : '时间未提供'"><strong>{{ event.title || event.event_type }}</strong><p>{{ event.summary || '无补充摘要' }}</p></el-timeline-item></el-timeline><el-empty v-if="!loading && !error && !list.length" description="暂无可见时间线记录" :image-size="48" /><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20,50,100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" /></section></template>
<script setup>
import { ref } from 'vue'
import { listCustomerTimeline } from '@/api/customerHub'
import { useListPage } from '@/composables/useListPage'
import { formatBeijingDateTime } from '@/utils/datetime'
const props=defineProps({customerId:{type:Number,required:true}}),error=ref(null)
const {loading,list,total,page,pageSize,fetchList,handlePageChange,handleSizeChange}=useListPage(async params=>{error.value=null;try{return (await listCustomerTimeline(props.customerId,params)).data}catch(e){error.value=e;return{items:[],total:0}}})
</script>
<style scoped>.timeline{padding:14px;border:1px solid var(--border-color);border-radius:var(--card-radius)}h3{font-size:14px;margin:0 0 12px}.el-timeline{padding-top:16px}.el-pagination{overflow-x:auto}p{color:var(--text-secondary);line-height:1.6}</style>
