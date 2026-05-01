<template>
  <div>
    <!-- 返回 + 刷新 -->
    <el-row class="toolbar" justify="space-between" align="middle">
      <el-col :span="12">
        <GlassButton left-icon="ArrowLeft" @click="$router.push('/tracking')">返回列表</GlassButton>
      </el-col>
      <el-col :span="12" style="text-align:right">
        <GlassButton variant="primary" :loading="refreshing" @click="handleRefresh" left-icon="Refresh">
          刷新物流
        </GlassButton>
      </el-col>
    </el-row>

    <div v-loading="loading">
      <!-- 运单信息卡片 -->
      <div class="info-banner" v-if="shipment">
        <div class="info-top">
          <div class="info-title">
            <span class="waybill-no">{{ shipment.waybill_no }}</span>
            <el-tag size="small" effect="dark" style="margin-left:8px">{{ shipment.carrier_name }}</el-tag>
          </div>
          <div class="info-status">
            <el-tag :type="statusTagType(shipment.current_status)" size="large" effect="dark" round>
              {{ statusText(shipment.current_status) }}
            </el-tag>
          </div>
        </div>
        <div class="info-grid">
          <div class="info-item">
            <div class="info-label">收件人</div>
            <div class="info-value">{{ shipment.receiver_name || '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">收件公司</div>
            <div class="info-value">{{ shipment.receiver_company || '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">目的地</div>
            <div class="info-value">{{ [shipment.receiver_city, shipment.receiver_country].filter(Boolean).join(', ') || '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">当前位置</div>
            <div class="info-value">{{ shipment.current_location || '-' }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">提交人</div>
            <div class="info-value">{{ shipment.dingtalk_user_name }}</div>
          </div>
          <div class="info-item">
            <div class="info-label">录入时间</div>
            <div class="info-value">{{ shipment.created_at || '-' }}</div>
          </div>
          <div class="info-item" v-if="shipment.short_link">
            <div class="info-label">物流查询短链接</div>
            <div class="info-value short-link-value">
              <span class="short-link-text">{{ shipment.short_link }}</span>
              <GlassButton variant="link" size="xs" @click="copyLink(shipment.short_link)" style="margin-left:6px" left-icon="CopyDocument">
                复制
              </GlassButton>
            </div>
          </div>
        </div>
      </div>

      <!-- 物流轨迹时间线 -->
      <div class="timeline-section" v-if="shipment">
        <h3 class="section-title">物流轨迹</h3>
        <div v-if="shipment.events && shipment.events.length">
          <el-timeline>
            <el-timeline-item
              v-for="(evt, idx) in shipment.events"
              :key="evt.id"
              :type="idx === 0 ? 'primary' : ''"
              :hollow="idx !== 0"
              :timestamp="evt.event_time"
              placement="top"
            >
              <div class="event-card" :class="{ latest: idx === 0 }">
                <div class="event-desc">{{ evt.description }}</div>
                <div class="event-location" v-if="evt.location">{{ evt.location }}</div>
              </div>
            </el-timeline-item>
          </el-timeline>
        </div>
        <el-empty v-else description="暂无物流轨迹" :image-size="80" />
      </div>

      <!-- 轮询信息 -->
      <div class="poll-section" v-if="shipment">
        <h3 class="section-title">轮询信息</h3>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="跟踪状态">
            <el-tag :type="shipment.is_active ? 'success' : 'info'" size="small">
              {{ shipment.is_active ? '进行中' : '已结束' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="轮询次数">{{ shipment.poll_count }}</el-descriptions-item>
          <el-descriptions-item label="上次轮询">{{ shipment.last_polled_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="签收时间">{{ shipment.delivered_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="发运时间">{{ shipment.shipped_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="轮询错误" v-if="shipment.poll_error">
            <el-text type="danger" size="small">{{ shipment.poll_error }}</el-text>
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getShipmentDetail, refreshShipment } from '@/api/tracking'

const route = useRoute()
const waybillNo = route.params.waybillNo

const shipment = ref(null)
const loading = ref(false)
const refreshing = ref(false)

function copyLink(link) {
  navigator.clipboard.writeText(link).then(() => {
    ElMessage.success('短链接已复制')
  })
}

const STATUS_MAP = {
  pending: '待查询',
  picked_up: '已揽收',
  in_transit: '运输中',
  out_for_delivery: '派送中',
  customs: '清关中',
  customs_hold: '海关扣留',
  delivered: '已签收',
  returned: '已退回',
  exception: '异常',
}
const STATUS_TAG = {
  pending: 'info',
  picked_up: '',
  in_transit: '',
  out_for_delivery: 'warning',
  customs: 'warning',
  customs_hold: 'danger',
  delivered: 'success',
  returned: 'danger',
  exception: 'danger',
}

function statusText(s) { return STATUS_MAP[s] || s }
function statusTagType(s) { return STATUS_TAG[s] || 'info' }

async function fetchDetail() {
  loading.value = true
  try {
    const res = await getShipmentDetail(waybillNo)
    shipment.value = res.data
  } finally {
    loading.value = false
  }
}

async function handleRefresh() {
  refreshing.value = true
  try {
    await refreshShipment(waybillNo)
    ElMessage.success('刷新完成')
    await fetchDetail()
  } catch { /* handled by interceptor */ }
  finally {
    refreshing.value = false
  }
}

onMounted(fetchDetail)
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }

.info-banner {
  background: linear-gradient(135deg, #141210 0%, #1E1B18 60%, #141210 100%);
  border-radius: 16px;
  padding: 28px 32px;
  margin-bottom: 24px;
  color: #fff;
}
.info-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.waybill-no {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.info-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.info-item {
  background: rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 12px 16px;
}
.info-label {
  font-size: 12px;
  color: rgba(255,255,255,0.55);
  margin-bottom: 4px;
}
.info-value {
  font-size: 15px;
  font-weight: 500;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 16px;
  padding-left: 10px;
  border-left: 3px solid var(--color-primary);
}

.timeline-section {
  margin-bottom: 24px;
}
.event-card {
  padding: 4px 0;
}
.event-card.latest .event-desc {
  font-weight: 600;
  color: var(--color-primary);
}
.event-desc {
  font-size: 14px;
  color: var(--text-primary);
}
.event-location {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.poll-section {
  margin-bottom: 24px;
}
.short-link-value {
  display: flex;
  align-items: center;
}
.short-link-text {
  font-size: 13px;
  word-break: break-all;
  opacity: 0.85;
}
</style>
