<template>
  <section class="table-card">
    <div class="toolbar">
      <el-input v-model="searchForm.keyword" clearable placeholder="方舟单号 / 工厂单据编号" class="filter-w-lg" @keyup.enter="handleSearch" />
      <el-date-picker v-model="searchForm.dates" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" />
      <el-select v-model="searchForm.status" clearable placeholder="单据状态" class="filter-w-sm">
        <el-option label="草稿" value="draft" /><el-option label="已作废" value="voided" />
      </el-select>
      <el-input v-model="searchForm.creator" clearable placeholder="创建人姓名" class="filter-w-sm" @keyup.enter="handleSearch" />
      <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
      <GlassButton left-icon="RefreshLeft" @click="handleReset()">重置</GlassButton>
    </div>
    <div class="action-bar">
      <GlassButton v-any-permission="['factory_inbound:write', 'factory_inbound:admin']" variant="primary" :icon="Camera"
        @click="router.push('/factory-inbound/scan')">拍新单</GlassButton>
      <GlassButton v-permission="'factory_inbound:admin'" :icon="Setting" @click="aliasesOpen = true">维护词表</GlassButton>
    </div>
    <ListPageStatus v-if="hasData" :error="errorMessage" :loading="loading" :has-data="hasData" @retry="fetchList" />
    <el-table :data="list" v-loading="loading" border class="list-table" max-height="640" v-sticky-scrollbar>
      <template #empty>
        <ListPageStatus :error="errorMessage" :loading="loading" @retry="fetchList">
          <el-empty :image-size="96" description="暂无工厂到货单" />
        </ListPageStatus>
      </template>
      <el-table-column prop="inbound_no" label="方舟单号" min-width="170" show-overflow-tooltip />
      <el-table-column label="工厂单据编号" min-width="125">
        <template #default="{ row }">{{ row.delivery_no || row.recognized_delivery_no || '待核对' }}</template>
      </el-table-column>
      <el-table-column label="工厂发货日" min-width="110">
        <template #default="{ row }">{{ deliveryDate(row) }}</template>
      </el-table-column>
      <el-table-column label="状态" min-width="110">
        <template #default="{ row }"><el-tag effect="plain" :type="row.status === 'voided' ? 'info' : row.recognition_status === 'failed' ? 'danger' : 'warning'">{{ noteStatus(row) }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="creator" label="创建人" min-width="100" show-overflow-tooltip />
      <el-table-column label="创建时间" min-width="165">
        <template #default="{ row }">{{ formatBeijingDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" class-name="table-action-column" fixed="right" min-width="86">
        <template #default="{ row }"><GlassButton variant="link" @click="detailId = row.id">详情</GlassButton></template>
      </el-table-column>
    </el-table>
    <div class="pagination-wrapper">
      <el-pagination small background layout="total, sizes, prev, pager, next" :total="total"
        :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]"
        @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>
    <InboundDetailDrawer :id="detailId" @close="detailId = null" />
    <AliasManageDialog :open="aliasesOpen" @close="aliasesOpen = false" />
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Camera, Setting } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useListPage } from '@/composables/useListPage'
import { factoryInboundApi } from '@/api/factoryInbound'
import { formatBeijingDateTime } from '@/utils/datetime'
import AliasManageDialog from './components/AliasManageDialog.vue'
import InboundDetailDrawer from './components/InboundDetailDrawer.vue'
import { deliveryDate, noteStatus } from './inboundLabels'

const router = useRouter()
const detailId = ref(null)
const aliasesOpen = ref(false)
const { list, total, page, pageSize, loading, errorMessage, hasData, searchForm,
  fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = useListPage(
  async ({ dates, status, creator, ...filters }, { signal }) => {
    const [date_from, date_to] = dates || []
    const { data } = await factoryInboundApi.list({
      ...filters, status: status || undefined, date_from, date_to, creator: creator || undefined,
    }, { signal, suppressToast: true })
    return data
  }, { searchForm: { keyword: '', dates: null, status: '', creator: '' } },
)
</script>
