<template>
  <div class="page-container">
    <el-row :gutter="12">
      <el-col v-for="metric in metrics" :key="metric.label" :md="6" :sm="12" :xs="24">
        <el-card class="metric-card" shadow="never">
          <span class="metric-label">{{ metric.label }}</span>
          <strong class="metric-value">{{ metric.value }}</strong>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="section-card" shadow="never">
      <template #header>内部扩展</template>
      <p v-if="release">{{ release.version }} · SHA-256 <code class="checksum">{{ release.sha256 }}</code></p>
      <el-link v-if="downloadUrl" :href="downloadUrl" type="primary">下载 ZIP</el-link>
    </el-card>

    <el-card class="section-card" shadow="never">
      <template #header>翻译术语表</template>
      <p>外贸术语由「系统管理 → 数据字典」维护，按目标语言分类型：<code>whatsapp_glossary_en</code>、<code>whatsapp_glossary_es</code>、<code>whatsapp_glossary_fr</code>、<code>whatsapp_glossary_ar</code>、<code>whatsapp_glossary_ja</code>。code 填中文术语，label 填对应语言术语，翻译时只注入命中的条目。</p>
    </el-card>

    <section ref="panelRef" class="table-card">
        <div class="toolbar">
          <span>设备</span>
          <el-input v-model="keyword" class="filter-w-md" clearable placeholder="搜索设备名" />
        </div>
      <div class="action-bar">
        <span />
        <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columnDefs" :fullscreen="isFullscreen" @refresh="load" @fullscreen="toggleFullscreen" />
      </div>
      <el-table :data="visibleDevices" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <el-table-column v-if="visibleKeys.includes('device')" prop="device_name" label="设备" min-width="140" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('browser')" prop="browser_name" label="浏览器" min-width="100" />
        <el-table-column v-if="visibleKeys.includes('version')" prop="extension_version" label="版本" min-width="90" />
        <el-table-column v-if="visibleKeys.includes('last-used')" prop="last_used_at" label="最近使用" min-width="140" />
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="90">
          <template #default="{ row }">{{ deviceStatusLabel(row) }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="100" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'whatsapp_translation:admin'" link type="danger" @click="revoke(row.device_id)"><el-icon><Close /></el-icon>撤销</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>import { msgSuccessText, msgWarning } from '@/utils/feedback'
import { computed, onMounted, ref } from 'vue'

import { getAdminDevices, getAdminHealth, revokeAdminDevice } from '@/api/whatsappTranslation'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { deviceStatusLabel, healthLabel, parseReleaseManifest, releaseDownloadUrl, sanitizeDeviceRows } from './whatsappTranslationAdmin'

const columnDefs = [
  { key: 'device', label: '设备' }, { key: 'browser', label: '浏览器' },
  { key: 'version', label: '版本' }, { key: 'last-used', label: '最近使用' },
  { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('whatsapp-translation', columnDefs)
const loading = ref(false)
const keyword = ref('')
const health = ref({})
const devices = ref([])
const release = ref(null)
const downloadUrl = ref('')

const metrics = computed(() => [
  { label: '今日请求数', value: health.value.request_count ?? 0 },
  { label: '输入字符', value: health.value.input_chars ?? 0 },
  { label: '成功率', value: healthLabel(health.value) },
  { label: '服务状态', value: health.value.preset_enabled ? '正常' : '已停用' },
])
const visibleDevices = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return query ? devices.value.filter(row => row.device_name?.toLowerCase().includes(query)) : devices.value
})

async function revoke(deviceId) {
  await revokeAdminDevice(deviceId)
  msgSuccessText('设备已撤销')
  await load()
}

async function loadRelease() {
  const response = await fetch('/downloads/whatsapp-translation/latest.json', { cache: 'no-store' })
  release.value = parseReleaseManifest(await response.json())
  downloadUrl.value = releaseDownloadUrl(release.value)
}

async function load() {
  loading.value = true
  try {
    const [healthResponse, devicesResponse] = await Promise.all([getAdminHealth(), getAdminDevices()])
    health.value = healthResponse.data || {}
    devices.value = sanitizeDeviceRows(devicesResponse.data || [])
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    await loadRelease()
  } catch {
    msgWarning('扩展发布清单暂不可用')
  }
})
</script>

<style scoped>
.page-container { display: grid; gap: 12px; }
.metric-card { display: grid; gap: 6px; }
.metric-label { color: var(--el-text-color-secondary); font-size: 12px; }
.metric-value { font-size: 22px; }
.section-card { margin-top: 0; }
.card-header { align-items: center; display: flex; gap: 12px; justify-content: space-between; }
.checksum { word-break: break-all; }
</style>
