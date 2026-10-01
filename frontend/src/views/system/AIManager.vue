<template>
  <div class="ai-manager-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="ai-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>
    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="6" v-for="s in stats" :key="s.label">
        <div class="stat-card lg-card is-static">
          <div class="stat-main">
            <div>
              <p class="stat-label">{{ s.label }}</p>
              <p class="stat-value" :style="{ color: s.color }">{{ s.value }}</p>
              <p class="stat-sub">{{ s.sub }}</p>
            </div>
            <div class="stat-icon-wrap" :style="{ background: s.bg }">
              <el-icon :size="20" :color="s.color"><component :is="s.icon" /></el-icon>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- Tab 导航 -->
    <el-tabs v-model="activeTab" type="border-card" class="ai-tabs">
      <!-- Provider Tab -->
      <el-tab-pane label="提供商管理" name="providers">
        <div ref="providerPanelRef" class="table-card">
        <div class="toolbar tab-toolbar">
          <div class="toolbar-left">
            <el-input v-model="providerSearch" placeholder="搜索名称 / API Base" clearable class="filter-w-md" />
            <el-select v-model="providerTypeFilter" placeholder="全部类型" clearable class="filter-w-sm">
              <el-option label="直连大模型" value="direct" />
              <el-option label="ACCIO WORK" value="accio_work" />
            </el-select>
            <el-select v-model="providerStatusFilter" placeholder="全部状态" clearable class="filter-w-sm">
              <el-option label="已启用" :value="true" />
              <el-option label="已禁用" :value="false" />
            </el-select>
          </div>
        </div>
        <div class="action-bar">
          <GlassButton variant="primary" left-icon="Plus" @click="openProviderDialog()">新增提供商</GlassButton>
          <TableTools v-model:visible-keys="providerVisibleKeys" v-model:density="providerDensity" :columns="providerColumnDefs" :fullscreen="providerIsFullscreen" @refresh="fetchProviders" @fullscreen="toggleProviderFullscreen" />
        </div>

        <el-table :data="filteredProviders" border class="list-table" :class="providerDensityClass" :max-height="providerIsFullscreen ? undefined : 640" v-loading="providerLoading">
          <el-table-column v-if="providerVisibleKeys.includes('id')" prop="id" label="ID" min-width="60" />
          <el-table-column v-if="providerVisibleKeys.includes('name')" label="名称" min-width="160">
            <template #default="{ row }">
              <div class="cell-with-icon">
                <el-icon :size="16" :color="row.provider_type === 'direct' ? '#2563eb' : '#059669'">
                  <component :is="row.provider_type === 'direct' ? 'Globe' : 'Monitor'" />
                </el-icon>
                <span class="cell-title">{{ row.name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="providerVisibleKeys.includes('type')" label="类型" min-width="110">
            <template #default="{ row }">
              <el-tag :type="row.provider_type === 'direct' ? 'primary' : 'success'" size="small" effect="plain">
                {{ row.provider_type === 'direct' ? '直连' : 'ACCIO' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="providerVisibleKeys.includes('protocol')" label="协议" min-width="100">
            <template #default="{ row }">
              <el-tag v-if="row.provider_type === 'direct'" :type="row.api_type === 'anthropic' ? 'warning' : 'info'" size="small" effect="plain">
                {{ row.api_type === 'anthropic' ? 'Anthropic' : 'OpenAI' }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column v-if="providerVisibleKeys.includes('api')" label="API Base / Key" min-width="220">
            <template #default="{ row }">
              <div class="mono-text">{{ row.api_base }}</div>
              <div class="key-row">
                <span class="mono-text key-mask">{{ showKeyMap[row.id] ? row.api_key : (row.api_key ? '****' : '-') }}</span>
                <el-button v-if="row.api_key" link @click="toggleKey(row.id)">
                  <el-icon><component :is="showKeyMap[row.id] ? 'Hide' : 'View'" /></el-icon>
                </el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="providerVisibleKeys.includes('timeout')" prop="timeout_sec" label="超时" min-width="70" />
          <el-table-column v-if="providerVisibleKeys.includes('remark')" prop="remark" label="备注" min-width="120" show-overflow-tooltip />
          <el-table-column v-if="providerVisibleKeys.includes('status')" label="状态" min-width="80">
            <template #default="{ row }">
              <el-switch v-model="row.is_enabled" @change="toggleProvider(row)" />
            </template>
          </el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="200" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :loading="testingId === row.id" @click="handleTestProvider(row)">
                <el-icon><Lightning /></el-icon> 测试
              </el-button>
              <el-button link type="primary" @click="openProviderDialog(row)">
                <el-icon><Edit /></el-icon> 编辑
              </el-button>
              <el-button link type="danger" @click="handleDeleteProvider(row)">
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        </div>
      </el-tab-pane>

      <!-- Preset Tab -->
      <el-tab-pane label="预设管理" name="presets">
        <div ref="presetPanelRef" class="table-card">
        <div class="toolbar tab-toolbar">
          <div class="toolbar-left">
            <el-input v-model="presetSearch" placeholder="搜索预设名称 / 描述" clearable class="filter-w-md" />
            <el-select v-model="presetProviderFilter" placeholder="全部提供商" clearable class="filter-w-sm">
              <el-option v-for="p in providerOptions" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </div>
        </div>
        <div class="action-bar">
          <GlassButton variant="primary" left-icon="Plus" @click="openPresetDialog()">新增预设</GlassButton>
          <TableTools v-model:visible-keys="presetVisibleKeys" v-model:density="presetDensity" :columns="presetColumnDefs" :fullscreen="presetIsFullscreen" @refresh="fetchPresets" @fullscreen="togglePresetFullscreen" />
        </div>

        <el-table :data="filteredPresets" border class="list-table" :class="presetDensityClass" :max-height="presetIsFullscreen ? undefined : 640" v-loading="presetLoading">
          <el-table-column v-if="presetVisibleKeys.includes('id')" prop="id" label="ID" min-width="60" />
          <el-table-column v-if="presetVisibleKeys.includes('name')" label="预设名称" min-width="180">
            <template #default="{ row }">
              <div>
                <span class="cell-title">{{ row.preset_name }}</span>
                <p class="cell-desc">{{ row.description }}</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="presetVisibleKeys.includes('provider')" label="绑定提供商" min-width="140">
            <template #default="{ row }">
              <div class="cell-with-icon">
                <el-icon :size="14" color="#2563eb"><Position /></el-icon>
                <span>{{ row.provider_name || '-' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="presetVisibleKeys.includes('model')" prop="model" label="模型" min-width="140">
            <template #default="{ row }">
              <span class="mono-text">{{ row.model || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column v-if="presetVisibleKeys.includes('status')" label="状态" min-width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small" effect="plain">
                {{ row.is_enabled ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="240" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openTestPreset(row)">
                <el-icon><VideoPlay /></el-icon> 测试
              </el-button>
              <el-button link type="primary" @click="openPresetDialog(row)">
                <el-icon><Edit /></el-icon> 编辑
              </el-button>
              <el-button link type="primary" @click="handleCopyPreset(row)">
                <el-icon><DocumentCopy /></el-icon> 复制
              </el-button>
              <el-button link type="danger" @click="handleDeletePreset(row)">
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        </div>
      </el-tab-pane>

      <!-- Logs Tab -->
      <el-tab-pane label="调用日志" name="logs">
        <!-- 汇总卡片 -->
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
        <div class="toolbar tab-toolbar">
          <div class="toolbar-left">
            <el-select v-model="logModuleFilter" placeholder="全部模块" clearable class="filter-w-sm">
              <el-option label="物流跟踪" value="logistics" />
              <el-option label="设计预约" value="design_booking" />
              <el-option label="提成管理" value="commission" />
            </el-select>
            <el-select v-model="logStatusFilter" placeholder="全部状态" clearable class="filter-w-sm">
              <el-option label="成功" value="success" />
              <el-option label="错误" value="error" />
              <el-option label="超时" value="timeout" />
              <el-option label="进行中" value="pending" />
            </el-select>
            <el-date-picker v-model="logDateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束" value-format="YYYY-MM-DD" class="filter-w-lg" />
          </div>
        </div>
        <div class="action-bar">
          <TableTools v-model:visible-keys="logVisibleKeys" v-model:density="logDensity" :columns="logColumnDefs" :fullscreen="logIsFullscreen" @refresh="fetchLogs" @fullscreen="toggleLogFullscreen" />
        </div>

        <el-table :data="logsData" border class="list-table" :class="logDensityClass" :max-height="logIsFullscreen ? undefined : 640" v-loading="logsLoading" @expand-change="onLogExpand" @sort-change="logSort.onSortChange">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="log-detail">
                <el-descriptions :column="2" size="small" border>
                  <el-descriptions-item label="任务 ID">{{ row.task_id || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="调用用户">{{ row.caller_user_id || '系统' }}</el-descriptions-item>
                  <el-descriptions-item label="输入 Token">{{ row.tokens_prompt || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="输出 Token">{{ row.tokens_completion || '-' }}</el-descriptions-item>
                </el-descriptions>
                <div v-if="row.error_message" class="log-error-box">
                  <p class="log-error-code">{{ row.error_code }}</p>
                  <p class="log-error-msg">{{ row.error_message }}</p>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="logVisibleKeys.includes('id')" prop="id" label="ID" min-width="70" />
          <el-table-column v-if="logVisibleKeys.includes('module')" label="模块 / Preset" min-width="160">
            <template #default="{ row }">
              <div>
                <span>{{ moduleLabel(row.caller_module) }}</span>
                <p class="cell-desc">{{ row.preset_name }}</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="logVisibleKeys.includes('type')" label="类型" min-width="80">
            <template #default="{ row }">
              <el-tag :type="row.provider_type === 'direct' ? 'primary' : 'success'" size="small" effect="plain">
                {{ row.provider_type === 'direct' ? '直连' : 'ACCIO' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="logVisibleKeys.includes('model')" prop="model" label="模型" min-width="120" sortable="custom">
            <template #default="{ row }"><span class="mono-text">{{ row.model || '-' }}</span></template>
          </el-table-column>
          <el-table-column v-if="logVisibleKeys.includes('tokens')" prop="tokens_used" label="Token" min-width="80" align="right">
            <template #default="{ row }">
              <span class="mono-text">{{ row.tokens_used != null ? row.tokens_used.toLocaleString() : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column v-if="logVisibleKeys.includes('duration')" prop="duration_ms" label="耗时" min-width="90" align="right">
            <template #default="{ row }">
              <span class="mono-text">{{ row.duration_ms != null ? formatDuration(row.duration_ms) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column v-if="logVisibleKeys.includes('status')" label="状态" min-width="80">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small" effect="plain">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="logVisibleKeys.includes('created')" prop="created_at" label="时间" min-width="150" sortable="custom" />
        </el-table>

        <el-pagination v-model:current-page="logPage" v-model:page-size="logPageSize" :page-sizes="[20, 50, 100]" :total="logTotal" layout="total, sizes, prev, pager, next" class="pager" />
        </div>
      </el-tab-pane>
      <el-tab-pane label="站点应用" name="sites" lazy>
        <AiGatewayApps />
      </el-tab-pane>
    </el-tabs>

    <!-- Provider Dialog -->
    <el-dialog v-model="providerDialogVisible" :title="providerEditId ? '编辑提供商' : '新增提供商'" width="520px" destroy-on-close>
      <el-form ref="providerFormRef" :model="providerForm" :rules="providerRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="providerForm.name" placeholder="如 OpenAI-生产" />
        </el-form-item>
        <el-form-item label="类型" prop="provider_type">
          <el-radio-group v-model="providerForm.provider_type" @change="onProviderTypeChange">
            <el-radio-button label="direct">直连大模型</el-radio-button>
            <el-radio-button label="accio_work">ACCIO WORK</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="API Base" prop="api_base">
          <el-input v-model="providerForm.api_base" :placeholder="providerForm.provider_type === 'accio_work' ? 'http://119.28.107.92:3100' : 'https://api.openai.com/v1'" />
        </el-form-item>
        <el-form-item label="协议类型" v-if="providerForm.provider_type === 'direct'">
          <el-radio-group v-model="providerForm.api_type">
            <el-radio-button label="openai">OpenAI</el-radio-button>
            <el-radio-button label="anthropic">Anthropic</el-radio-button>
          </el-radio-group>
          <div class="form-tip">ELBNT-AI 等代理选 Anthropic；OpenAI/DeepSeek/StepFun 选 OpenAI</div>
        </el-form-item>
        <el-form-item label="API Key" v-if="providerForm.provider_type !== 'accio_work'">
          <el-input v-model="providerForm.api_key" type="password" show-password :placeholder="providerEditId ? '留空表示不修改' : 'sk-xxxxxxxxxxxxxxxx'" />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="providerForm.timeout_sec" :min="1" :max="3600" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="providerForm.remark" type="textarea" :rows="2" placeholder="用途说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="providerSaving" @click="submitProvider">保存</el-button>
      </template>
    </el-dialog>

    <!-- Preset Dialog -->
    <el-dialog v-model="presetDialogVisible" :title="presetEditId ? '编辑预设' : '新增预设'" width="560px" destroy-on-close>
      <el-form ref="presetFormRef" :model="presetForm" :rules="presetRules" label-width="110px">
        <el-form-item label="预设名称" prop="preset_name">
          <el-input v-model="presetForm.preset_name" placeholder="customer_analysis" />
          <div class="form-hint">只允许字母、数字、下划线</div>
        </el-form-item>
        <el-form-item label="绑定提供商" prop="provider_id">
          <el-select v-model="presetForm.provider_id" placeholder="选择提供商" style="width: 100%" @change="onPresetProviderChange">
            <el-option v-for="p in providerOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="presetForm.model" placeholder="gpt-4o" :disabled="isAccioProvider" />
        </el-form-item>
        <el-form-item label="System Prompt">
          <el-input v-model="presetForm.system_prompt" type="textarea" :rows="3" placeholder="输入系统提示词..." />
        </el-form-item>
        <el-form-item label="调用参数">
          <el-input v-model="presetForm.parameters" type="textarea" :rows="2" placeholder='{"temperature": 0.3}' class="mono-input" />
        </el-form-item>
        <el-form-item label="用途说明">
          <el-input v-model="presetForm.description" placeholder="描述此预设的用途" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="presetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="presetSaving" @click="submitPreset">保存</el-button>
      </template>
    </el-dialog>

    <!-- Preset Test Dialog -->
    <el-dialog v-model="testDialogVisible" :title="`测试预设：${testPresetName}`" width="640px" destroy-on-close>
      <el-form>
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
            <el-button>
              <el-icon><UploadFilled /></el-icon> 选择图片
            </el-button>
            <template #tip>
              <div class="upload-tip">
                {{ isCompositePreset ? '必填。需要一张客户正面照片，支持 JPG / PNG / WEBP，最大 10MB。' : '可选。用于测试 expo_face_analysis 这类视觉预设，支持 JPG / PNG / WEBP，最大 10MB。' }}
              </div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="isCompositePreset" label="假发参考图">
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
            <el-button>
              <el-icon><UploadFilled /></el-icon> 选择参考图
            </el-button>
            <template #tip>
              <div class="upload-tip">必填。上传假发款式或模特参考图，用于验证换发合成效果。</div>
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
          <el-icon :size="16" :color="testResult.status === 'error' ? '#dc2626' : '#7c3aed'"><ChatDotRound /></el-icon>
          <span>{{ testResult.status === 'error' ? '测试失败' : '测试结果' }}</span>
          <div class="test-result-meta">
            <span>Token: {{ testResult.tokens_used || 'N/A' }}</span>
            <span>{{ testResult.duration_ms }}ms</span>
          </div>
        </div>
        <img
          v-if="isImageResponse(testResult.response)"
          class="test-result-image"
          :src="testResult.response"
          alt="AI generated preview"
        >
        <pre v-else class="test-result-content">{{ testResult.response }}</pre>
      </div>
    </el-dialog>

    <!-- Test Result Popover -->
    <el-dialog v-model="testResultVisible" title="连通性测试结果" width="360px" :show-close="true">
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
import AiGatewayApps from './components/AiGatewayApps.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import {
  Cpu, Monitor, Position, Lightning, Edit, Delete,
  VideoPlay, DocumentCopy, ChatDotRound, UploadFilled,
  View, Hide, SuccessFilled, CircleCloseFilled, WarningFilled, Loading,
  Histogram,
} from '@element-plus/icons-vue'

import { useAiManager } from './composables/useAiManager'

const providerColumnDefs = [
  { key: 'id', label: 'ID' }, { key: 'name', label: '名称' },
  { key: 'type', label: '类型' }, { key: 'protocol', label: '协议' },
  { key: 'api', label: 'API Base / Key' }, { key: 'timeout', label: '超时' },
  { key: 'remark', label: '备注' }, { key: 'status', label: '状态' },
]
const presetColumnDefs = [
  { key: 'id', label: 'ID' }, { key: 'name', label: '预设名称' },
  { key: 'provider', label: '绑定提供商' }, { key: 'model', label: '模型' },
  { key: 'status', label: '状态' },
]
const logColumnDefs = [
  { key: 'id', label: 'ID' }, { key: 'module', label: '模块 / Preset' },
  { key: 'type', label: '类型' }, { key: 'model', label: '模型' },
  { key: 'tokens', label: 'Token' }, { key: 'duration', label: '耗时' },
  { key: 'status', label: '状态' }, { key: 'created', label: '时间' },
]
const {
  density: providerDensity, densityClass: providerDensityClass,
  visibleKeys: providerVisibleKeys, panelRef: providerPanelRef,
  isFullscreen: providerIsFullscreen, toggleFullscreen: toggleProviderFullscreen,
} = useTableView('ai-manager-providers', providerColumnDefs)
const {
  density: presetDensity, densityClass: presetDensityClass,
  visibleKeys: presetVisibleKeys, panelRef: presetPanelRef,
  isFullscreen: presetIsFullscreen, toggleFullscreen: togglePresetFullscreen,
} = useTableView('ai-manager-presets', presetColumnDefs)
const {
  density: logDensity, densityClass: logDensityClass,
  visibleKeys: logVisibleKeys, panelRef: logPanelRef,
  isFullscreen: logIsFullscreen, toggleFullscreen: toggleLogFullscreen,
} = useTableView('ai-manager-logs', logColumnDefs)

const {
  activeTab,
  // Provider
  providers, providerLoading, providerSearch, providerTypeFilter, providerStatusFilter,
  showKeyMap, testingId, testResultVisible, testResultData,
  providerDialogVisible, providerEditId, providerFormRef, providerSaving,
  providerForm, providerRules,
  fetchProviders, openProviderDialog, onProviderTypeChange, submitProvider,
  toggleProvider, handleTestProvider, handleDeleteProvider, toggleKey,
  filteredProviders,
  // Preset
  presets, presetLoading, presetSearch, presetProviderFilter, providerOptions,
  presetDialogVisible, presetEditId, presetFormRef, presetSaving,
  presetForm, presetRules, isAccioProvider,
  testDialogVisible, testPresetName, testMessage,
  testImageFileList, testReferenceImageFileList, testing, testResult, isCompositePreset,
  fetchPresets, openPresetDialog, onPresetProviderChange, submitPreset,
  handleDeletePreset, handleCopyPreset, openTestPreset,
  handleTestImageChange, handleTestImageExceed, clearTestImage,
  handleTestReferenceImageChange, handleTestReferenceImageExceed, clearTestReferenceImage,
  isImageResponse, sendTest,
  filteredPresets,
  // Logs
  logsData, logsLoading, logModuleFilter, logStatusFilter, logDateRange,
  logPage, logPageSize, logTotal,
  fetchLogs, onLogExpand, logSort,
  logSummary,
  // shared
  stats,
  moduleLabel, statusLabel, statusTagType, formatDuration,
} = useAiManager()
</script>

<style scoped src="./ai-manager.css"></style>
