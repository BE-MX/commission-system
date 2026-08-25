<template>
  <div class="sf-page">
    <header class="sf-header">
      <div><h2>半成品订单</h2><p>订单以 g 为单位；实际完成或收货时录入增量，自动形成库存入库流水。</p></div>
      <el-button v-permission="'semifinished:write'" type="primary" @click="openCreate">新建半成品订单</el-button>
    </header>
    <section class="sf-card">
      <div class="sf-toolbar">
        <el-input v-model="filters.keyword" clearable placeholder="搜索订单号或批次号" style="width: 260px" @keyup.enter="search" />
        <el-select v-model="filters.status" clearable placeholder="订单状态" style="width: 150px" @change="search">
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-button type="primary" @click="search">查询</el-button><el-button @click="reset">重置</el-button>
      </div>
      <el-table v-loading="loading" :data="rows" border class="list-table sf-table">
        <el-table-column prop="order_no" label="订单号" min-width="155" />
        <el-table-column prop="batch_no" label="批次号" min-width="130" show-overflow-tooltip />
        <el-table-column label="来源" min-width="120"><template #default="{ row }"><el-tag effect="plain">{{ row.source_type === 'production_sync' ? '产成品联动' : '手工创建' }}</el-tag></template></el-table-column>
        <el-table-column label="状态" min-width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="item_count" label="明细" min-width="80" align="right" />
        <el-table-column label="下单(g)" min-width="120" align="right"><template #default="{ row }">{{ grams(row.order_qty_grams) }}</template></el-table-column>
        <el-table-column label="已入库(g)" min-width="120" align="right"><template #default="{ row }">{{ grams(row.received_qty_grams) }}</template></el-table-column>
        <el-table-column prop="expected_delivery_date" label="预计交期" min-width="120" />
        <el-table-column prop="created_at" label="创建时间" min-width="165" />
        <el-table-column label="操作" min-width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button v-if="['submitted','partial'].includes(row.status)" v-permission="'semifinished:write'" link type="danger" @click="terminate(row)">终止</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="sf-pagination"><el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :total="pagination.total" :page-sizes="[20,50,100]" layout="total,sizes,prev,pager,next" @change="load" /></div>
    </section>

    <el-dialog v-model="createVisible" title="新建半成品订单" width="700px">
      <el-form label-width="90px">
        <el-form-item label="批次号"><el-input v-model="createForm.batch_no" maxlength="64" /></el-form-item>
        <el-form-item label="预计交期"><el-date-picker v-model="createForm.expected_delivery_date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="是否加急"><el-switch v-model="createForm.is_urgent" /></el-form-item>
        <el-form-item label="订单明细">
          <div class="sf-component-list">
            <div v-for="(item, index) in createForm.items" :key="index" class="sf-component-row">
              <el-select v-model="item.material_id" filterable placeholder="选择半成品"><el-option v-for="material in materialOptions" :key="material.id" :label="`${material.size}/${material.color_code} (${material.material_code})`" :value="material.id" /></el-select>
              <el-input-number v-model="item.quantity_grams" :min="0.001" :precision="3" /><el-button link type="danger" @click="createForm.items.splice(index, 1)">删除</el-button>
            </div>
            <el-button @click="createForm.items.push({ material_id: null, quantity_grams: 100 })">添加明细</el-button>
          </div>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="createForm.remark" type="textarea" :rows="2" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" @click="submitCreate">提交</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" title="半成品订单详情" size="760px">
      <div v-if="detail">
        <div class="sf-summary">
          <div class="sf-summary-item"><span>订单号</span><strong style="font-size: 16px">{{ detail.order_no }}</strong></div>
          <div class="sf-summary-item"><span>状态</span><strong style="font-size: 16px">{{ statusText(detail.status) }}</strong></div>
          <div class="sf-summary-item"><span>批次号</span><strong style="font-size: 16px">{{ detail.batch_no || '—' }}</strong></div>
          <div class="sf-summary-item"><span>来源</span><strong style="font-size: 16px">{{ detail.source_type }}</strong></div>
        </div>
        <el-table :data="detail.items" border class="list-table">
          <el-table-column label="半成品" min-width="180"><template #default="{ row }"><div class="sf-material"><strong>{{ row.size }}/{{ row.color_code }}</strong><small>{{ row.material_code }}</small></div></template></el-table-column>
          <el-table-column label="下单(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.order_qty_grams) }}</template></el-table-column>
          <el-table-column label="已入库(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.received_qty_grams) }}</template></el-table-column>
          <el-table-column label="剩余(g)" min-width="110" align="right"><template #default="{ row }">{{ grams(row.remaining_qty_grams) }}</template></el-table-column>
          <el-table-column label="操作" min-width="100"><template #default="{ row }"><el-button v-if="Number(row.remaining_qty_grams) > 0 && ['submitted','partial'].includes(detail.status)" v-permission="'semifinished:write'" link type="primary" @click="openReceive(row)">入库</el-button></template></el-table-column>
        </el-table>
      </div>
    </el-drawer>

    <el-dialog v-model="receiveVisible" title="录入半成品入库" width="460px">
      <p>{{ receivingItem?.size }}/{{ receivingItem?.color_code }}，剩余 {{ grams(receivingItem?.remaining_qty_grams) }}g</p>
      <el-form label-width="90px"><el-form-item label="本次入库"><el-input-number v-model="receiveForm.quantity_grams" :min="0.001" :max="Number(receivingItem?.remaining_qty_grams || 0)" :precision="3" /> g</el-form-item><el-form-item label="备注"><el-input v-model="receiveForm.remark" maxlength="500" /></el-form-item></el-form>
      <template #footer><el-button @click="receiveVisible = false">取消</el-button><el-button type="primary" @click="submitReceive">确认入库</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createSemifinishedOrder, getMaterials, getSemifinishedOrder, getSemifinishedOrders, receiveSemifinishedItem, terminateSemifinishedOrder } from '@/api/semifinished'

const statusOptions = [{ value: 'submitted', label: '已提交' }, { value: 'partial', label: '部分入库' }, { value: 'completed', label: '已完成' }, { value: 'terminated', label: '已终止' }]
const filters = reactive({ keyword: '', status: '' })
const pagination = reactive({ page: 1, page_size: 20, total: 0 })
const rows = ref([]); const loading = ref(false)
const createVisible = ref(false); const materialOptions = ref([])
const createForm = reactive({ batch_no: '', expected_delivery_date: null, is_urgent: false, remark: '', items: [] })
const detailVisible = ref(false); const detail = ref(null)
const receiveVisible = ref(false); const receivingItem = ref(null); const receiveForm = reactive({ quantity_grams: 0, remark: '' })
const grams = value => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 })
const statusText = value => statusOptions.find(item => item.value === value)?.label || value
const statusType = value => ({ submitted: 'primary', partial: 'warning', completed: 'success', terminated: 'info' }[value] || 'info')

async function load() { loading.value = true; try { const data = await getSemifinishedOrders({ ...filters, page: pagination.page, page_size: pagination.page_size }); rows.value = data.items || []; pagination.total = data.total || 0 } finally { loading.value = false } }
function search() { pagination.page = 1; load() }
function reset() { filters.keyword = ''; filters.status = ''; search() }
async function openCreate() { const data = await getMaterials({ page: 1, page_size: 100 }); materialOptions.value = data.items || []; Object.assign(createForm, { batch_no: '', expected_delivery_date: null, is_urgent: false, remark: '', items: [{ material_id: null, quantity_grams: 100 }] }); createVisible.value = true }
async function submitCreate() { if (!createForm.items.length || createForm.items.some(item => !item.material_id || Number(item.quantity_grams) <= 0)) return ElMessage.warning('请完整填写订单明细'); await createSemifinishedOrder({ ...createForm }); ElMessage.success('订单已创建'); createVisible.value = false; load() }
async function openDetail(row) { detail.value = await getSemifinishedOrder(row.id); detailVisible.value = true }
async function terminate(row) { await ElMessageBox.confirm(`确认终止订单 ${row.order_no}？已有入库不会撤销。`, '终止订单'); await terminateSemifinishedOrder(row.id); ElMessage.success('订单已终止'); load(); if (detail.value?.id === row.id) detail.value = await getSemifinishedOrder(row.id) }
function openReceive(row) { receivingItem.value = row; receiveForm.quantity_grams = Number(row.remaining_qty_grams); receiveForm.remark = ''; receiveVisible.value = true }
async function submitReceive() { await receiveSemifinishedItem(receivingItem.value.id, { quantity_grams: receiveForm.quantity_grams, idempotency_key: crypto.randomUUID(), remark: receiveForm.remark || null }); ElMessage.success('入库成功'); receiveVisible.value = false; detail.value = await getSemifinishedOrder(detail.value.id); load() }
load()
</script>

<style scoped src="./semifinished.css"></style>
