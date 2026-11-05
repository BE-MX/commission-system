<template>
  <main class="feed-page">
    <header class="feed-heading"><h1>TM 资料</h1><p>查看历史沟通资料，人工匹配本人私海客户。</p></header>
    <div class="feed-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /></div>
    <div ref="panelRef" class="table-card feed-panel">
      <div class="feed-tabs" role="tablist" aria-label="TM资料视图">
        <GlassButton role="tab" :aria-selected="tab === 'records'" :variant="tab === 'records' ? 'primary' : 'secondary'" @click="tab = 'records'">我的资料</GlassButton>
        <GlassButton v-permission="'alibaba_feed:admin'" role="tab" :aria-selected="tab === 'sources'" :variant="tab === 'sources' ? 'primary' : 'secondary'" @click="tab = 'sources'">来源配置</GlassButton>
      </div>
      <template v-if="tab === 'records'">
        <FilterBar :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset">
          <el-select v-model="searchForm.linked" class="filter-w-sm" aria-label="资料关联状态"><el-option label="我的未关联" value="unlinked" /><el-option label="我的已关联" value="linked" /><el-option label="我的全部" value="all" /></el-select>
          <el-input v-model="searchForm.keyword" clearable class="filter-w-lg" placeholder="搜索买家 / 国家 / 负责人" aria-label="搜索TM资料" prefix-icon="Search" />
        </FilterBar>
        <div class="action-bar">
          <div class="analysis-tools"><GlassButton v-permission="'client_desk:write'" variant="primary" :disabled="!selection.valid || saving || uncertain" :loading="saving" @click="reanalyze">选入人工重分析{{ selected.length ? `（${selected.length}）` : '' }}</GlassButton><span class="muted">{{ selection.reason || '仅用于本次分析 · 每客每日 3 次 · 不进入早报' }}</span></div>
          <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columns" :fullscreen="isFullscreen" :loading="loading" @refresh="fetchList" @fullscreen="toggleFullscreen" />
        </div>
        <p class="feed-note">关联仅匹配资料，不改变客户归属。历史快照可能存在覆盖缺口；平台回复状态不代表方舟内消息状态。自动规则保持关闭。</p>
        <el-alert v-if="actionError" :title="actionError" type="warning" :closable="false" class="action-error" />
        <ListPageStatus v-if="listError" :error="listError" :loading="loading" :has-data="false" @retry="fetchList" />
        <el-table v-else :data="list" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" row-key="id" v-sticky-scrollbar @selection-change="selected = $event">
          <template #empty><el-empty :image-size="96" description="暂无符合条件的TM资料" /></template>
          <el-table-column type="selection" min-width="48" max-width="48" :selectable="row => !!row.link && row.ai_eligible && !saving && !uncertain" />
          <el-table-column v-if="narrow || visibleKeys.includes('buyer')" label="买家" :min-width="narrow ? 240 : 160" max-width="240" :fixed="narrow ? false : 'left'" :show-overflow-tooltip="!narrow"><template #default="{ row }"><strong class="buyer-name">{{ row.buyer?.name || '未提供买家名' }}</strong><div class="muted small">{{ row.source_name }}</div><div v-if="visibilityLabel(row)" class="visibility-notice quality-warning small">{{ visibilityLabel(row) }}</div><template v-if="narrow"><div class="buyer-inquiry muted small">询盘 ID：{{ row.inquiry_id || '未提供' }}</div><FeedRecordActions :row="row" :disabled="saving || uncertain" @detail="openDetail" @customer="openCustomer" @unlink="unlink" @link="openLink" /></template></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('country')" label="国家" min-width="100" max-width="140" show-overflow-tooltip><template #default="{ row }">{{ row.buyer?.country || '—' }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('type')" prop="record_type" label="资料类型" min-width="110" max-width="150" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('owner')" prop="assignee_name" label="平台负责人" min-width="130" max-width="180" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('reply')" label="平台回复" min-width="110" max-width="150"><template #default="{ row }"><StatusBadge size="small" effect="plain">{{ row.reply_status || '未知' }}</StatusBadge></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('observed')" label="观察快照 · 北京时间" min-width="175" max-width="205"><template #default="{ row }">{{ minuteTime(row.observed_at) }}<div class="muted small">{{ row.is_current ? '当前快照' : '历史快照' }}</div></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('quality')" label="资料质量" min-width="150" max-width="220" show-overflow-tooltip><template #default="{ row }"><StatusBadge size="small" effect="plain" :type="row.ai_eligible ? 'success' : 'warning'">{{ row.ai_eligible ? '可人工选入' : '暂不可选入' }}</StatusBadge><div class="muted small">{{ quality(row) }}</div></template></el-table-column>
          <el-table-column v-if="!narrow" class-name="table-action-column" label="操作" min-width="255" max-width="330" fixed="right"><template #default="{ row }"><FeedRecordActions :row="row" :disabled="saving || uncertain" @detail="openDetail" @customer="openCustomer" @unlink="unlink" @link="openLink" /></template></el-table-column>
        </el-table>
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager" @current-change="handlePageChange" @size-change="handleSizeChange" />
      </template>
      <FeedSources v-else-if="tab === 'sources'" />
    </div>

    <DetailDrawer v-model="detailVisible" title="TM 历史资料" :width="760" :loading="detailLoading" @closed="clearDetail">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <template v-if="detail">
        <h2>{{ detail.buyer?.name || '未提供买家名' }}</h2>
        <p class="muted">{{ detail.buyer?.country || '国家未提供' }} · {{ detail.record_type }} · {{ detail.assignee_name || '负责人未提供' }}</p>
        <div class="snapshot-meta"><span>观察时间　{{ minuteTime(detail.observed_at) }}（北京时间）</span><span>资料协议　{{ detail.schema_version || '—' }}</span><span>平台回复状态　{{ detail.reply_status || '未知' }}</span><span>质量　{{ quality(detail) }}</span></div>
        <el-alert title="只读历史快照：分钟精度，不保证完整覆盖；同分钟消息先后与回复关系无法从数组顺序确定。资料中的链接仅作为文本展示。" type="info" :closable="false" />
        <p v-if="detail.issues?.length" class="quality-warning">覆盖 / 质量提示：{{ detail.issues.map(issueText).join('；') }}</p>
        <p v-if="detail.coverage_gaps?.length" class="quality-warning">覆盖缺口：{{ detail.coverage_gaps.map(issueText).join('；') }}</p>
        <section class="messages" aria-label="历史聊天文本"><article v-for="message in detail.messages || []" :key="message.key" class="message"><div class="message-meta"><b>{{ directionText(message.dir) }}</b><time>{{ minuteTime(message.at) }}</time></div><p>{{ message.text || '（无文本内容）' }}</p></article><el-empty v-if="!detail.messages?.length" :image-size="64" description="当前快照未提供聊天文本，不能推断无沟通" /></section>
      </template>
    </DetailDrawer>

    <el-dialog v-model="linkVisible" title="人工匹配本人私海客户" width="640px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
      <div v-if="linkRow" class="link-record-identity"><b>{{ linkRow.buyer?.name || '未提供买家名' }}</b><span>询盘 ID：{{ linkRow.inquiry_id || '未提供' }}</span></div>
      <p class="muted">请选择真实对应的客户。不会按姓名自动合并，也不会改变客户归属。</p>
      <el-form label-position="top" @submit.prevent="searchCustomers(1)"><el-form-item label="搜索客户名称 / 国家"><div class="customer-search"><el-input v-model="customerKeyword" clearable /><GlassButton native-type="submit" :loading="customerLoading">查询</GlassButton></div></el-form-item>
        <el-form-item label="手动确认客户" required><el-select v-model="companyId" placeholder="请选择匹配客户" :loading="customerLoading" class="customer-select"><el-option v-for="customer in customers" :key="customer.company_id" :label="`${customer.name} · ${customer.country || '国家未提供'}`" :value="String(customer.company_id)" /></el-select></el-form-item></el-form>
      <el-alert v-if="customerError" :title="customerError" type="error" :closable="false" />
      <p v-if="!customers.length && !customerLoading && !customerError" class="muted">暂无本人私海候选客户。</p>
      <el-pagination :current-page="customerPage" v-model:page-size="customerPageSize" :page-sizes="[20, 50, 100]" :total="customerTotal" layout="total, sizes, prev, pager, next" @current-change="searchCustomers" @size-change="searchCustomers(1)" />
      <template #footer><GlassButton :disabled="saving" @click="linkVisible = false">取消</GlassButton><GlassButton variant="primary" :loading="saving" :disabled="!companyId || uncertain" @click="linkCustomer">确认关联</GlassButton></template>
    </el-dialog>
  </main>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import FeedSources from './FeedSources.vue'
import FeedRecordActions from './FeedRecordActions.vue'
import { useAlibabaFeed } from './useAlibabaFeed'
import { minuteTime, directionText, visibilityLabel } from './feedState'
const router = useRouter(), auth = useAuthStore(), tab = ref('records')
const narrowMedia = typeof window !== 'undefined' ? window.matchMedia('(max-width: 768px)') : null
const narrow = ref(narrowMedia?.matches ?? false)
function updateNarrow(event) { narrow.value = event.matches }
onMounted(() => narrowMedia?.addEventListener('change', updateNarrow))
onUnmounted(() => narrowMedia?.removeEventListener('change', updateNarrow))
const columns = [{ key: 'buyer', label: '买家' }, { key: 'country', label: '国家' }, { key: 'type', label: '资料类型' }, { key: 'owner', label: '平台负责人' }, { key: 'reply', label: '平台回复' }, { key: 'observed', label: '观察快照' }, { key: 'quality', label: '资料质量' }]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('alibaba-feed', columns)
const { listPage, listError, detail, detailVisible, detailLoading, detailError, clearDetail, openDetail, selected, selection, saving, actionError, uncertain, linkVisible, linkRow, companyId, customerKeyword, customers, customerTotal, customerPage, customerPageSize, customerLoading, customerError, searchCustomers, openLink, linkCustomer, unlink, reanalyze } = useAlibabaFeed()
const { loading, list, total, page, pageSize, searchForm, hasPendingSearch, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange } = listPage
function issueText(issue) { return typeof issue === 'string' ? issue : issue.message || issue.code || '资料质量待核对' }
function quality(row) { return visibilityLabel(row) || (row.issues?.length ? row.issues.map(issueText).join('；') : row.window_result || '未提供覆盖结论') }
function openCustomer(row) { router.push({ path: '/client-desk', query: { company_id: String(row.link.company_id) } }) }
watch(() => auth.hasPermission('alibaba_feed:admin'), allowed => { if (!allowed) tab.value = 'records' })
watch(tab, () => { clearDetail(); selected.value = [] })
</script>

<style scoped>
.feed-page { position: relative; }
.feed-heading, .feed-panel { position: relative; z-index: 1; }
.feed-heading h1 { margin: 0; font-size: 24px; }
.feed-heading p { color: var(--text-secondary); margin: 8px 0 20px; }
.feed-aurora { inset: -24px -28px; pointer-events: none; }
.feed-panel { border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); }
.feed-tabs { display: flex; gap: 8px; padding: 16px 20px; border-bottom: 1px solid var(--border-color); }
.analysis-tools, .customer-search { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.analysis-tools { min-width: 0; }
.feed-note { margin: 0; padding: 0 20px 16px; font-size: 12px; color: var(--text-secondary); }
.action-error { margin-bottom: 12px; }
.muted, .message-meta { color: var(--text-secondary); }
.small { font-size: 12px; margin-top: 3px; }
.snapshot-meta { display: grid; gap: 8px; padding: 16px 0; }
.messages { display: grid; gap: 14px; padding-top: 20px; }
.message { padding: 14px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--button-surface); }
.message-meta { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.message p { margin: 10px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; }
.quality-warning { color: var(--color-warning-text); }
.visibility-notice { white-space: normal; overflow-wrap: anywhere; }
.customer-search, .customer-select { width: 100%; }
.customer-search .el-input { flex: 1; min-width: 160px; }
.link-record-identity { display: grid; gap: 6px; padding: 12px; margin-bottom: 12px; border: 1px solid var(--border-color); border-radius: 8px; white-space: normal; overflow-wrap: anywhere; }
.link-record-identity span { color: var(--text-secondary); }
@media (max-width: 768px) {
  .buyer-name, .buyer-inquiry { display: block; white-space: normal; overflow-wrap: anywhere; }
}
@media (max-width: 600px) { .feed-tabs { padding: 12px; } .feed-note { padding: 0 12px 12px; } }
</style>
