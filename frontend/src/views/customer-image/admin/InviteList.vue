<template>
  <div class="invite-list">
    <div class="list-toolbar">
      <div>
        <strong>客户邀请</strong>
        <span>链接明文只在创建成功时展示；列表仅保留末 6 位用于核对。</span>
      </div>
    </div>

    <section ref="panelRef" class="table-card">
      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <InviteCreateDialog v-if="canWrite" :state="state" />
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="load()"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listResource.hasData.value" :paged="true" :error="listResource.errorMessage.value" :loading="loading" :has-data="true" :data-page="listResource.dataPage.value" @retry="load()" />
      <el-table v-loading="loading" :data="invites" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <template #empty><ListPageStatus :paged="true" :error="listResource.errorMessage.value" :loading="loading" @retry="load()"><el-empty v-if="listResource.isEmpty.value" :image-size="96" description="暂无数据" /></ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('customer')" prop="customer_name" label="客户" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <strong>{{ row.customer_name }}</strong>
            <small>{{ row.customer_id }}</small>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('token')" label="链接核对码" min-width="110">
          <template #default="{ row }">••••••{{ row.token_suffix }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('quota')" label="额度" min-width="100">
          <template #default="{ row }">{{ row.quota_used }} / {{ row.quota_total }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('expires-at')" label="失效时间" min-width="170">
          <template #default="{ row }">{{ formatDate(row.expires_at) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="100">
          <template #default="{ row }">
            <StatusBadge :type="statusOf(row).type" effect="plain">{{ statusOf(row).label }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="canWrite" class-name="table-action-column" label="操作" min-width="100" fixed="right">
          <template #default="{ row }">
            <GlassButton
              v-if="!row.revoked_at"
              v-permission="'customer_image:write'"
              variant="link"
              link-tone="danger"
              @click="revoke(row)"
            >停用</GlassButton>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="invitePage"
        v-model:page-size="invitePageSize"
        :total="inviteTotal"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @current-change="load"
        @size-change="changeSize"
      />
    </section>
  </div>
</template>

<script setup>import { confirmAction, msgSuccessText } from '@/utils/feedback'
import { onMounted, ref } from 'vue'

import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import InviteCreateDialog from './InviteCreateDialog.vue'
import { formatBeijingDateTime, parseApiDateTime } from '@/utils/datetime'

const props = defineProps({
  state: { type: Object, required: true },
  canWrite: { type: Boolean, default: false },
})
const { invites, invitePage, invitePageSize, inviteTotal } = props.state
const listResource = props.state.invitesResource
const loading = listResource.loading

const formatDate = value => formatBeijingDateTime(value, { naiveTimeZone: 'UTC' })
function statusOf(invite) {
  if (invite.revoked_at) return { label: '已停用', type: 'danger' }
  if (parseApiDateTime(invite.expires_at, { naiveTimeZone: 'UTC' })?.getTime() <= Date.now()) return { label: '已失效', type: 'info' }
  if (invite.quota_used >= invite.quota_total) return { label: '额度用尽', type: 'warning' }
  return { label: '有效', type: 'success' }
}

// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'customer', label: '客户' },
  { key: 'token', label: '链接核对码' },
  { key: 'quota', label: '额度' },
  { key: 'expires-at', label: '失效时间' },
  { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('customer-image-invites', columnDefs)

function load(page = invitePage.value) { return listResource.handlePageChange(page) }
function changeSize(size) { return listResource.handleSizeChange(size) }

async function revoke(invite) {
  try {
    await confirmAction(`停用“${invite.customer_name}”的邀请？客户将立即无法继续使用。`, '停用邀请', { type: 'warning' })
  } catch { return }
  try {
    await props.state.revokeInvite(invite.id)
    msgSuccessText('邀请已停用')
  } catch { /* shared interceptor provides request feedback */ }
}

onMounted(async () => {
  await Promise.all([props.state.loadProducts(), load()])
})
</script>

<style scoped>
.invite-list { min-width: 0; }
.list-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 64px; }
.list-toolbar div { display: grid; gap: 3px; }
.list-toolbar span, td small { color: var(--el-text-color-secondary); font-size: 13px; }
td strong, td small { display: block; }
@media (max-width: 720px) { .list-toolbar { align-items: flex-start; flex-direction: column; padding-block: 12px; } }
</style>
