<template>
  <div class="authorize-page">
    <el-card class="authorize-card">
      <template #header>
        <h1>WhatsApp 翻译设备授权</h1>
      </template>

      <el-alert v-if="state === 'invalid'" type="warning" :closable="false" title="配对码无效或已过期" description="请回到扩展重新发起授权。" />
      <el-alert v-else-if="state === 'error'" type="error" :closable="false" title="授权失败" description="请稍后重试或联系管理员。" />

      <template v-else-if="inspection">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="状态">{{ inspection.status }}</el-descriptions-item>
          <el-descriptions-item v-if="inspection.expires_at" label="有效期至">{{ inspection.expires_at }}</el-descriptions-item>
          <el-descriptions-item v-if="inspection.device_id" label="设备编号">{{ inspection.device_id }}</el-descriptions-item>
        </el-descriptions>
        <p class="privacy">翻译仅处理当前一对一聊天中的可见文字；译文不存储，联系人信息不入库。</p>
        <div class="actions">
          <el-button type="primary" :loading="saving" @click="decide('approve')">批准授权</el-button>
          <el-button :loading="saving" @click="decide('reject')">拒绝</el-button>
        </div>
      </template>

      <el-skeleton v-else :rows="4" animated />

      <div v-if="devices.length" class="devices">
        <h2>我的设备</h2>
        <el-table :data="devices" size="small">
          <el-table-column prop="device_name" label="设备" min-width="120" />
          <el-table-column prop="browser_name" label="浏览器" min-width="100" />
          <el-table-column prop="extension_version" label="扩展版本" min-width="90" />
          <el-table-column prop="expires_at" label="有效期" min-width="130" />
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="danger" @click="revoke(row.device_id)">撤销</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { approvePairing, getMyDevices, inspectPairing, rejectPairing, revokeMyDevice } from '@/api/whatsappTranslation'
import { useAuthStore } from '@/stores/auth'
import { captureDeviceCode, cleanAuthorizeUrl, clearDeviceCode, readDeviceCode } from './whatsappTranslationAuthorize'

const router = useRouter()
const auth = useAuthStore()
const state = ref('loading')
const saving = ref(false)
const inspection = ref(null)
const devices = ref([])

function handleError(error) {
  const code = error?.response?.data?.data?.error_code
  if (['pairing_not_found', 'pairing_expired', 'pairing_state'].includes(code)) {
    state.value = 'invalid'
    clearDeviceCode(window.sessionStorage)
    return
  }
  state.value = 'error'
  ElMessage.error(error?.message || '授权失败')
}

async function loadDevices() {
  const response = await getMyDevices()
  devices.value = response.data || []
}

async function inspect() {
  const code = readSessionCode()
  if (!code) {
    state.value = 'invalid'
    return
  }
  const response = await inspectPairing(code)
  inspection.value = response.data
  state.value = 'ready'
}

async function decide(action) {
  const code = readSessionCode()
  if (!code) return
  saving.value = true
  try {
    if (action === 'approve') await approvePairing(code)
    else await rejectPairing(code)
    clearDeviceCode(window.sessionStorage)
    ElMessage.success(action === 'approve' ? '授权成功，请回到扩展继续' : '已拒绝该设备')
    inspection.value = null
    state.value = 'invalid'
    await loadDevices()
  } catch (error) {
    handleError(error)
  } finally {
    saving.value = false
  }
}

async function revoke(deviceId) {
  await revokeMyDevice(deviceId)
  await loadDevices()
}

function readSessionCode() {
  return window.sessionStorage.getItem('ark_whatsapp_translation_device_code') || ''
}

onMounted(async () => {
  captureDeviceCode(window.location, window.history, window.sessionStorage)
  if (!auth.user) {
    router.replace(`/login?redirect=${encodeURIComponent(cleanAuthorizeUrl(window.location))}`)
    return
  }
  try {
    await inspect()
    await loadDevices()
  } catch (error) {
    handleError(error)
  }
})
</script>

<style scoped>
.authorize-page {
  align-items: center;
  background: var(--bg-color-page);
  display: flex;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
}
.authorize-card {
  max-width: 620px;
  width: 100%;
}
h1, h2 { font-size: 18px; margin: 0 0 12px; }
.privacy { color: var(--el-text-color-secondary); }
.actions { display: flex; gap: 12px; margin-top: 16px; }
.devices { margin-top: 24px; }
</style>
