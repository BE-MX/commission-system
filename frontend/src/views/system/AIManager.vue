<template>
  <div class="ai-manager-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="ai-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- Tab 导航（已移除顶部旧 4 张统计卡，统计聚合至各 Tab 内部） -->
    <el-tabs v-model="activeTab" type="border-card" class="ai-tabs">
      <!-- 订阅管理（取代原提供商管理，默认打开） -->
      <el-tab-pane name="subscriptions">
        <template #label>
          <span class="tab-label">订阅管理 <span class="tab-count">{{ subSummary.total_providers }}</span></span>
        </template>
        <SubscriptionBoard
          :summary="subSummary"
          :items="subFilteredItems"
          :filters="subFilters"
          v-model:view-mode="subViewMode"
          :loading="subLoading"
          :error-message="subResource.errorMessage.value"
          :show-merge-notice="showMergeNotice"
          :logo-urls="logoUrls"
          :show-key-map="showKeyMap"
          :testing-id="testingId"
          @dismiss-notice="dismissMergeNotice"
          @toggle-status="toggleStatusCard"
          @refresh="refreshAllSubscriptions"
          @add="openSubDrawer(null)"
          @confirm-renew="handleConfirmRenew"
          @register-balance="openBalanceModal"
          @edit="openSubDrawer"
          @test="handleTestProvider"
          @view-logs="row => jumpToProviderLogs(row.id)"
          @toggle="handleToggleSubProvider"
          @delete="handleDeleteSubProvider"
          @toggle-key="toggleKey"
        />
      </el-tab-pane>

      <!-- 预设管理（三层面包屑筛选 + 分组列表） -->
      <el-tab-pane name="presets">
        <template #label>
          <span class="tab-label">预设管理 <span class="tab-count">{{ presets.length }}</span></span>
        </template>
        <PresetBoard
          :groups="groupedPresets"
          :feature-chips="featureChips"
          :provider-chips="providerChips"
          :model-chips="modelChips"
          :selected-features="selectedFeatures"
          :selected-providers="selectedProviders"
          :selected-models="selectedModels"
          v-model:search="presetFilterSearch"
          :filtered-count="breadcrumbPresets.length"
          :total-count="presets.length"
          :unassigned-count="unassignedCount"
          :has-active-filters="hasActiveFilters"
          :loading="presetLoading"
          :error-message="presetResource.errorMessage.value"
          @toggle-chip="toggleChip"
          @clear-all="clearAllPresetFilters"
          @filter-unassigned="filterOnlyUnassigned"
          @add="openPresetDialog()"
          @refresh="fetchPresets"
          @inspect="openPresetInspect"
          @test="openTestPreset"
          @edit="openPresetDialog"
          @copy="handleCopyPreset"
          @delete="handleDeletePresetAndRefresh"
          @jump-route="handleJumpRoute"
        />
      </el-tab-pane>

      <!-- 调用日志（新增提供商与费用状态筛选、费用列） -->
      <el-tab-pane label="调用日志" name="logs">
        <el-row :gutter="12" class="log-summary-row">
          <el-col :xs="8" :sm="4" v-for="s in logSummary" :key="s.label">
            <div class="log-summary-card lg-card is-static">
              <div class="log-summary-header">
                <el-icon :size="14" :color="s.color"><component :is="s.icon" /></el-icon>
                <span class="log-summary-label">{{ s.label }}</span>
              </div>
              <p class="log-summary-value" :style="{ color: s.color }">{{ s.value }}</p>
            </div>
          </el-col>
        </el-row>

        <div ref="logPanelRef" class="table-card">
          <FilterBar :loading="logsLoading" :pending="logState.hasPendingSearch.value" @search="searchLogs" @reset="resetLogs">
            <el-select v-model="logProviderFilter" placeholder="全部提供商" clearable class="filter-w-sm">
              <el-option v-for="p in providerOptions" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-select v-model="logModuleFilter" placeholder="全部模块" clearable class="filter-w-sm">
              <el-option v-for="(label, code) in dynamicModuleLabels" :key="code" :label="label" :value="code" />
            </el-select>
            <el-select v-model="logStatusFilter" placeholder="全部状态" clearable class="filter-w-sm">
              <el-option label="成功" value="success" />
              <el-option label="错误" value="error" />
              <el-option label="超时" value="timeout" />
              <el-option label="进行中" value="pending" />
            </el-select>
            <el-select v-model="logCostStatusFilter" placeholder="费用状态" clearable class="filter-w-sm">
              <el-option label="已计费" value="priced" />
              <el-option label="未定价" value="unpriced" />
              <el-option label="无用量" value="no_usage" />
              <el-option label="失败不计费" value="failed" />
              <el-option label="不计费" value="not_billed" />
              <el-option label="上线前" value="legacy" />
              <el-option label="测试" value="test" />
            </el-select>
            <el-date-picker v-model="logDateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束" value-format="YYYY-MM-DD" class="filter-w-lg" />
          </FilterBar>
          <div class="action-bar">
            <TableTools v-model:visible-keys="logVisibleKeys" v-model:density="logDensity" :columns="logColumnDefs" :loading="logsLoading" :fullscreen="logIsFullscreen" @refresh="fetchLogs" @fullscreen="toggleLogFullscreen" />
          </div>

          <ListPageStatus v-if="logState.hasData.value" :error="logState.errorMessage.value" :loading="logsLoading" :has-data="true" @retry="fetchLogs" />
          <el-table :data="logsData" border class="list-table" :class="logDensityClass" :max-height="logIsFullscreen ? undefined : 640" v-loading="logsLoading" @expand-change="onLogExpand" @sort-change="sortLogs" v-sticky-scrollbar>
            <template #empty><ListPageStatus :error="logState.errorMessage.value" :loading="logsLoading" @retry="fetchLogs"><el-empty description="暂无数据" :image-size="96" /></ListPageStatus></template>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="log-detail">
                  <ResponsiveDescriptions :column="2" size="small" border>
                    <el-descriptions-item label="任务 ID">{{ row.task_id || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="调用用户">{{ row.caller_user_id || '系统' }}</el-descriptions-item>
                    <el-descriptions-item label="输入 Token">{{ row.tokens_prompt ?? '-' }}</el-descriptions-item>
                    <el-descriptions-item label="输出 Token">{{ row.tokens_completion ?? '-' }}</el-descriptions-item>
                    <el-descriptions-item label="结束时间">{{ row.finished_at || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="费用状态">{{ costStatusLabel(row.cost_status) }}</el-descriptions-item>
                  </ResponsiveDescriptions>
                  <div v-if="row.error_message" class="log-error-box">
                    <p class="log-error-code">{{ row.error_code }}</p>
                    <p class="log-error-msg">{{ row.error_message }}</p>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('id')" prop="id" label="ID" min-width="70" />
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('module')" prop="caller_module" label="模块 / Preset" min-width="160">
              <template #default="{ row }">
                <div>
                  <span>{{ moduleLabel(row.caller_module) }}</span>
                  <p class="cell-desc">{{ row.preset_name }}</p>
                </div>
              </template>
            </el-table-column>
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('type')" prop="provider_type" label="类型" min-width="100">
              <template #default="{ row }">
                <StatusBadge :type="row.provider_type === 'direct' ? 'primary' : 'success'" size="small" effect="plain">
                  {{ row.provider_type === 'direct' ? '直连' : 'ACCIO' }}
                </StatusBadge>
              </template>
            </el-table-column>
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('model')" prop="model" label="模型" min-width="130">
              <template #default="{ row }"><span class="mono-text">{{ row.model || '-' }}</span></template>
            </el-table-column>
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('tokens')" prop="tokens_used" label="Token" min-width="85" align="right">
              <template #default="{ row }">
                <span class="mono-text">{{ row.tokens_used != null ? row.tokens_used.toLocaleString() : '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('cost')" prop="cost_amount" label="估算费用" min-width="120" align="right">
              <template #default="{ row }">
                <span v-if="row.cost_status === 'priced' && row.cost_amount != null" class="mono-text">
                  {{ row.cost_currency === 'USD' ? '$' : '¥' }}{{ Number(row.cost_amount).toFixed(4) }}
                </span>
                <StatusBadge v-else :type="costStatusTone(row.cost_status)" size="small" effect="plain">
                  {{ costStatusLabel(row.cost_status) }}
                </StatusBadge>
              </template>
            </el-table-column>
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('duration')" prop="duration_ms" label="耗时" min-width="85" align="right">
              <template #default="{ row }">
                <span class="mono-text">{{ row.duration_ms != null ? formatDuration(row.duration_ms) : '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('status')" prop="status" label="状态" min-width="96">
              <template #default="{ row }">
                <StatusBadge :type="statusTagType(row.status)" size="small" effect="plain">
                  {{ statusLabel(row.status) }}
                </StatusBadge>
              </template>
            </el-table-column>
            <el-table-column sortable="custom" v-if="logVisibleKeys.includes('created')" prop="created_at" label="时间" min-width="150" />
          </el-table>

          <el-pagination v-model:current-page="logPage" v-model:page-size="logPageSize" :page-sizes="[20, 50, 100]" :total="logTotal" layout="total, sizes, prev, pager, next" class="pager" @current-change="changeLogPage" @size-change="changeLogSize" />
        </div>
      </el-tab-pane>
      <el-tab-pane label="聊天运行" name="chat" lazy><ChatOperations v-if="activeTab === 'chat'" /></el-tab-pane>
      <el-tab-pane label="站点应用" name="sites" lazy><AiGatewayApps /></el-tab-pane>
    </el-tabs>

    <!-- 订阅源编辑 / 新增抽屉（含连接配置、订阅周期、余额流水与单价表） -->
    <SubscriptionDrawer
      ref="subDrawerRef"
      v-model="subDrawerVisible"
      :subscription-item="subDrawerItem"
      @saved="handleSubDrawerSaved"
      @logo-updated="id => refreshLogo(id, true, { bust: true })"
      @open-balance="openBalanceModal"
    />

    <!-- 快捷登记余额弹层 -->
    <BalanceCheckpointModal
      v-model="balanceModalVisible"
      :target="balanceTarget"
      :saving="balanceSaving"
      @submit="submitBalanceCheckpoint"
    />

    <!-- 预设详情抽屉 -->
    <PresetDrawer
      v-model="presetDrawerVisible"
      :preset="presetDrawerItem"
      @test="row => { presetDrawerVisible = false; openTestPreset(row) }"
      @edit="row => { presetDrawerVisible = false; openPresetDialog(row) }"
      @copy="handleCopyPreset"
      @toggle="handleTogglePresetFromDrawer"
      @delete="handleDeletePresetFromDrawer"
      @jump-route="handleJumpRoute"
    />

    <!-- Preset Dialog（新增必填所属功能 feature_key） -->
    <el-dialog v-model="presetDialogVisible" :title="presetEditId ? '编辑预设' : '新增预设'" width="640px" destroy-on-close append-to-body>
      <el-form label-position="top" ref="presetFormRef" :model="presetForm" :rules="presetRules">
        <el-form-item label="预设名称" prop="preset_name">
          <el-input v-model="presetForm.preset_name" placeholder="customer_analysis" />
          <div class="form-hint">业务功能按预设名称调用；换模型请修改下方型号，保留现有预设名称。</div>
        </el-form-item>
        <el-form-item label="所属功能" prop="feature_key">
          <el-select v-model="presetForm.feature_key" placeholder="选择所属功能导航" filterable class="w-full">
            <el-option-group v-for="grp in featureGroupedOptions" :key="grp.label" :label="grp.label">
              <el-option v-for="opt in grp.options" :key="opt.key" :label="opt.label" :value="opt.key" />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="绑定提供商" prop="provider_id">
          <el-select v-model="presetForm.provider_id" placeholder="选择提供商" class="w-full" @change="onPresetProviderChange">
            <el-option v-for="p in providerOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="presetForm.model" placeholder="gpt-4o" :disabled="isAccioProvider" />
        </el-form-item>
        <AiPresetImageFields v-model="presetForm.parameters" :preset-name="presetForm.preset_name" />
        <AiPresetChatFields v-model="presetForm.parameters" :preset-name="presetForm.preset_name" :disabled="isAccioProvider" />
        <el-collapse>
          <el-collapse-item title="文本、测试与运行参数" name="preset-runtime">
            <AiConfigFields v-model="presetForm.parameters" :fields="presetFields" @validity="presetFieldsValid = $event" />
          </el-collapse-item>
          <el-collapse-item title="图片参数（含展会、客户生图等用途）" name="preset-image">
            <AiConfigFields v-model="presetForm.parameters" :fields="imageFields" @validity="imageFieldsValid = $event" />
          </el-collapse-item>
        </el-collapse>
        <el-form-item label="System Prompt">
          <el-input v-model="presetForm.system_prompt" type="textarea" :rows="3" placeholder="输入系统提示词..." />
        </el-form-item>
        <el-form-item label="调用参数">
          <el-input v-model="presetForm.parameters" type="textarea" :rows="5" placeholder='{"temperature": 0.3}' class="mono-input" />
          <div class="form-hint">保存后用于后续新请求，无需重启；需使用提供商支持的协议与参数。</div>
        </el-form-item>
        <el-form-item label="用途说明">
          <el-input v-model="presetForm.description" placeholder="描述此预设的用途" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="presetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="presetSaving" :disabled="!presetFieldsValid || !imageFieldsValid" @click="handleSubmitPresetAndRefresh">保存</el-button>
      </template>
    </el-dialog>

    <!-- Preset Test Dialog（保留完整多模态双图测试） -->
    <el-dialog v-model="testDialogVisible" :title="`测试预设：${testPresetName}`" width="640px" destroy-on-close append-to-body>
      <el-form label-position="top">
        <el-form-item label="发送消息">
          <el-input v-model="testMessage" type="textarea" :rows="4" placeholder="输入测试消息..." />
        </el-form-item>
        <el-form-item :label="isCompositePreset ? '客户原图' : '测试图片'">
          <el-upload
            class="preset-image-upload"
            :auto-upload="false"
            :limit="1"
            :file-list="testImageFileList"
            accept=".jpg,.jpeg,.png,.webp"
            :on-change="handleTestImageChange"
            :on-exceed="handleTestImageExceed"
            :on-remove="clearTestImage"
          >
            <el-button><el-icon><UploadFilled /></el-icon> 选择图片</el-button>
            <template #tip>
              <div class="upload-tip">
                {{ isCompositePreset ? '必填。需要一张客户正面照片，支持 JPG / PNG / WEBP，最大 10MB。' : '可选。用于测试视觉预设，支持 JPG / PNG / WEBP，最大 10MB。' }}
              </div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="isImageTest" label="第二张参考图（可选）">
          <el-upload
            class="preset-image-upload"
            :auto-upload="false"
            :limit="1"
            :file-list="testReferenceImageFileList"
            accept=".jpg,.jpeg,.png,.webp"
            :on-change="handleTestReferenceImageChange"
            :on-exceed="handleTestReferenceImageExceed"
            :on-remove="clearTestReferenceImage"
          >
            <el-button><el-icon><UploadFilled /></el-icon> 选择参考图</el-button>
            <template #tip>
              <div class="upload-tip">上传假发款式或模特参考图，用于验证换发合成效果。</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <div class="test-dialog-footer">
        <el-button type="primary" :loading="testing" @click="sendTest">
          <el-icon><VideoPlay /></el-icon> 发送测试
        </el-button>
      </div>
      <div v-if="testResult" class="test-result">
        <div class="test-result-header">
          <el-icon :size="16" :color="testResult.status === 'error' ? 'var(--tag-danger-text)' : 'var(--metric-violet-ink)'"><ChatDotRound /></el-icon>
          <span>{{ testResult.status === 'error' ? '测试失败' : '测试结果' }}</span>
          <div class="test-result-meta">
            <span>Token: {{ testResult.tokens_used || 'N/A' }}</span>
            <span>{{ testResult.duration_ms }}ms</span>
          </div>
        </div>
        <img v-if="isImageResponse(testResult.response)" class="test-result-image" :src="testResult.response" alt="AI generated preview">
        <pre v-else class="test-result-content">{{ testResult.response }}</pre>
      </div>
    </el-dialog>

    <!-- Test Result Popover -->
    <el-dialog v-model="testResultVisible" title="连通性测试结果" width="480px" :show-close="true" append-to-body>
      <div class="test-popover-body">
        <div class="test-status-row">
          <div class="status-dot" :class="testResultData?.status === 'ok' ? 'ok' : 'error'" />
          <span class="test-status-text">{{ testResultData?.status === 'ok' ? '连接成功' : '连接失败' }}</span>
        </div>
        <p class="test-latency">延迟: {{ testResultData?.latency_ms }}ms</p>
        <p class="test-detail">{{ testResultData?.detail }}</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, UploadFilled, VideoPlay } from '@element-plus/icons-vue'
import AiConfigFields from './components/AiConfigFields.vue'
import { presetFields, imageFields } from './aiConfigFields'
import AiPresetImageFields from './components/AiPresetImageFields.vue'
import AiPresetChatFields from './components/AiPresetChatFields.vue'
import ChatOperations from './components/ChatOperations.vue'
import AiGatewayApps from './components/AiGatewayApps.vue'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { useAiManager } from './composables/useAiManager'
import { useSubscriptions } from './composables/useSubscriptions'
import { usePresetFilters } from './composables/usePresetFilters'
import SubscriptionBoard from './ai/SubscriptionBoard.vue'
import SubscriptionDrawer from './ai/SubscriptionDrawer.vue'
import BalanceCheckpointModal from './ai/BalanceCheckpointModal.vue'
import PresetBoard from './ai/PresetBoard.vue'
import PresetDrawer from './ai/PresetDrawer.vue'

const route = useRoute()
const router = useRouter()

const logColumnDefs = [
  { key: 'id', label: 'ID' }, { key: 'module', label: '模块 / Preset' },
  { key: 'type', label: '类型' }, { key: 'model', label: '模型' },
  { key: 'tokens', label: 'Token' }, { key: 'cost', label: '估算费用' },
  { key: 'duration', label: '耗时' }, { key: 'status', label: '状态' },
  { key: 'created', label: '时间' },
]
const {
  density: logDensity, densityClass: logDensityClass,
  visibleKeys: logVisibleKeys, panelRef: logPanelRef,
  isFullscreen: logIsFullscreen, toggleFullscreen: toggleLogFullscreen,
} = useTableView('ai-manager-logs', logColumnDefs)

const {
  presetResource, logState, searchLogs, resetLogs, changeLogPage, changeLogSize, sortLogs, activeTab,
  featureCatalog, featureGroupedOptions, dynamicModuleLabels,
  showKeyMap, testingId, testResultVisible, testResultData,
  fetchProviders, toggleProvider, handleTestProvider, handleDeleteProvider, toggleKey,
  presets, presetLoading, providerOptions,
  presetDialogVisible, presetEditId, presetFormRef, presetSaving,
  presetForm, presetRules, isAccioProvider,
  testDialogVisible, testPresetName, testMessage,
  testImageFileList, testReferenceImageFileList, testing, testResult, isCompositePreset, isImageTest,
  fetchPresets, openPresetDialog, onPresetProviderChange, submitPreset, togglePreset,
  handleDeletePreset, handleCopyPreset, openTestPreset,
  handleTestImageChange, handleTestImageExceed, clearTestImage,
  handleTestReferenceImageChange, handleTestReferenceImageExceed, clearTestReferenceImage,
  isImageResponse, sendTest,
  logsData, logsLoading, logModuleFilter, logProviderFilter, logStatusFilter, logCostStatusFilter, logDateRange,
  logPage, logPageSize, logTotal, fetchLogs, onLogExpand, jumpToProviderLogs, logSummary,
  moduleLabel, statusLabel, statusTagType, costStatusLabel, costStatusTone, formatDuration,
} = useAiManager()

if (route?.query?.tab && ['subscriptions', 'presets', 'logs', 'chat', 'sites'].includes(String(route.query.tab))) {
  activeTab.value = String(route.query.tab)
}

watch(activeTab, tab => {
  if (!router || !route) return
  if (String(route.query?.tab || 'subscriptions') === tab) return
  const nextQuery = { ...route.query }
  if (tab === 'subscriptions') delete nextQuery.tab
  else nextQuery.tab = tab
  router.replace({ query: nextQuery }).catch(() => {})
})

const subDrawerRef = ref(null)

const {
  resource: subResource, loading: subLoading, summary: subSummary,
  filteredItems: subFilteredItems, filters: subFilters, viewMode: subViewMode,
  showMergeNotice, logoUrls,
  balanceModalVisible, balanceTarget, balanceSaving,
  fetchSubscriptions, refreshLogo, toggleStatusCard, dismissMergeNotice,
  openBalanceModal, submitBalanceCheckpoint, handleConfirmRenew,
} = useSubscriptions({
  onMutated: fetchProviders,
  onBalanceRecorded: pid => subDrawerRef.value?.refreshCheckpoints(pid),
})

const {
  selectedFeatures, selectedProviders, selectedModels,
  search: presetFilterSearch, featureChips, providerChips, modelChips,
  filteredPresets: breadcrumbPresets, groupedPresets, unassignedCount, hasActiveFilters,
  toggleChip, clearAll: clearAllPresetFilters, filterOnlyUnassigned,
} = usePresetFilters(presets, featureCatalog, { route, router, activeTab })

const subDrawerVisible = ref(false)
const subDrawerItem = ref(null)
const presetDrawerVisible = ref(false)
const presetDrawerItem = ref(null)

function openSubDrawer(item) {
  subDrawerItem.value = item || null
  subDrawerVisible.value = true
}

function refreshAllSubscriptions() {
  fetchSubscriptions()
  fetchProviders()
}

async function handleSubDrawerSaved() {
  await Promise.all([fetchSubscriptions(), fetchProviders()])
}

async function handleToggleSubProvider(row) {
  const ok = await toggleProvider(row)
  if (ok) await fetchSubscriptions()
}

async function handleDeleteSubProvider(row) {
  const ok = await handleDeleteProvider(row)
  if (ok) await fetchSubscriptions()
}

function openPresetInspect(row) {
  presetDrawerItem.value = row
  presetDrawerVisible.value = true
}

async function handleSubmitPresetAndRefresh() {
  await submitPreset()
  await fetchSubscriptions()
}

async function handleDeletePresetAndRefresh(row) {
  const ok = await handleDeletePreset(row)
  if (ok) await fetchSubscriptions()
}

async function handleTogglePresetFromDrawer(row) {
  const ok = await togglePreset(row)
  if (ok) {
    presetDrawerVisible.value = false
    await fetchSubscriptions()
  }
}

async function handleDeletePresetFromDrawer(row) {
  const ok = await handleDeletePreset(row)
  if (ok) {
    presetDrawerVisible.value = false
    await fetchSubscriptions()
  }
}

function handleJumpRoute(path) {
  if (path) router.push(path)
}

const presetFieldsValid = ref(true)
const imageFieldsValid = ref(true)
watch(presetDialogVisible, () => { presetFieldsValid.value = true; imageFieldsValid.value = true })

onMounted(() => {
  fetchSubscriptions()
})
</script>

<style scoped src="./ai-manager.css"></style>
