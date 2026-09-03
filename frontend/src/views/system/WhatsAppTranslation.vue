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
      <template #header>
        <div class="card-header">
          <span>设备</span>
          <el-input v-model="keyword" clearable placeholder="搜索设备名" />
        </div>
      </template>
      <el-table :data="visibleDevices" v-loading="loading" border class="list-table">
        <el-table-column prop="device_name" label="设备" min-width="140" show-overflow-tooltip />
        <el-table-column prop="browser_name" label="浏览器" min-width="100" />
        <el-table-column prop="extension_version" label="版本" min-width="90" />
        <el-table-column prop="last_used_at" label="最近使用" min-width="140" />
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">{{ deviceStatusLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="100" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'whatsapp_translation:admin'" link type="danger" @click="revoke(row.device_id)">撤销</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAdminDevices, getAdminHealth } from '@/api/whatsappTranslation'
import { deviceStatusLabel, healthLabel, parseReleaseManifest, releaseDownloadUrl, sanitizeDeviceRows } from './whatsappTranslationAdmin'

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
  ElMessage.success('设备已撤销')
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
    ElMessage.warning('扩展发布清单暂不可用')
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
