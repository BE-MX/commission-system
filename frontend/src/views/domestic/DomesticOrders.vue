<template>
  <div class="orders-page">
    <div class="orders-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="5">
        <el-input v-model="searchForm.keyword" placeholder="搜索系统单号 / 客户订单号" clearable prefix-icon="Search" @keyup.enter="handleSearch" @clear="handleSearch" />
      </el-col>
      <el-col :span="4">
        <el-select v-model="searchForm.status" placeholder="订单状态" clearable style="width: 100%" @change="handleSearch">
          <el-option v-for="s in ORDER_STATUS" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="searchForm.order_type" placeholder="普货/特单" clearable style="width: 100%" @change="handleSearch">
          <el-option label="普货" value="normal" />
          <el-option label="特单" value="special" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-date-picker
          v-model="searchForm.dateRange" type="daterange" value-format="YYYY-MM-DD"
          start-placeholder="下单起" end-placeholder="下单止" style="width: 100%" @change="handleSearch"
        />
      </el-col>
      <el-col :span="6">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
        <GlassButton v-permission="'domestic:write'" variant="ghost" left-icon="Plus" @click="goCreate">新建订单</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card orders-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="domestic_no" label="系统单号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="order_no" label="客户订单号" min-width="110" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户店名" min-width="130" show-overflow-tooltip />
        <el-table-column prop="order_date" label="下单日期" min-width="105" />
        <el-table-column label="类型" min-width="80">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.order_type === 'special' ? 'warning' : ''">{{ row.order_type_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="明细 / 数量" min-width="110">
          <template #default="{ row }">{{ row.item_count }} 行 / {{ row.total_qty }} 件</template>
        </el-table-column>
        <el-table-column label="生产进度" min-width="150">
          <template #default="{ row }">
            <el-progress :percentage="row.progress_pct" :stroke-width="10" />
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="ORDER_STATUS_TAGS[row.status]">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="170" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="openDetail(row)">详情</GlassButton>
            <GlassButton v-permission="'domestic:write'" variant="link" left-icon="CircleClose" :disabled="row.status >= 3" @click="handleTerminate(row)">终止</GlassButton>
            <GlassButton v-permission="'domestic:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <DetailDrawer v-model="detailVisible" title="内贸订单详情" :width="880" :loading="detailLoading">
      <template v-if="detail">
        <div class="info-card">
          <div class="info-name">{{ detail.domestic_no }} · {{ detail.customer_name }}</div>
          <div class="info-grid">
            <span>客户订单号：{{ detail.order_no }}</span>
            <span>下单日期：{{ detail.order_date }}</span>
            <span>类型：{{ detail.order_type_label }}</span>
            <span>状态：{{ detail.status_label }}</span>
            <span v-if="detail.customer_contact">联系人：{{ detail.customer_contact }}</span>
            <span v-if="detail.customer_phone">电话：{{ detail.customer_phone }}</span>
          </div>
          <div v-if="detail.remark" class="notes-line">备注：{{ detail.remark }}</div>
        </div>

        <el-alert
          v-if="hasUnrouted" type="warning" show-icon :closable="false" class="unrouted-alert"
          title="有明细还没配工艺路线，这些货暂时不能开工" description="在下方明细里点「配工艺路线」补配，或去「产品与工艺」页配好该工艺的默认路线。"
        />

        <div v-for="item in detail.items" :key="item.id" class="item-block">
          <div class="item-title">
            <span class="item-name">{{ item.product_name }}</span>
            <el-tag size="small" effect="plain">{{ item.order_qty }} 件</el-tag>
            <el-tag size="small" :type="item.status === 2 ? 'info' : (item.status === 1 ? 'success' : '')">{{ item.status_label }}</el-tag>
            <span class="item-current">当前：{{ item.current_process }}</span>
            <div class="item-actions">
              <GlassButton variant="link" left-icon="Printer" @click="openPrintCard(item)">流转卡</GlassButton>
              <GlassButton variant="link" left-icon="Grid" @click="openQrLabel(item)">二维码</GlassButton>
              <GlassButton variant="link" left-icon="Share" @click="openWxacode(item)">进度码</GlassButton>
              <GlassButton variant="link" left-icon="Tickets" @click="openLogs(item)">报工流水</GlassButton>
              <GlassButton v-if="!item.route_id" v-permission="'domestic:write'" variant="link" left-icon="Connection" @click="openAttachRoute(item)">配工艺路线</GlassButton>
              <GlassButton v-if="item.status === 1" v-permission="'domestic:write'" variant="link" left-icon="Van" @click="openShip(item)">登记发货</GlassButton>
            </div>
          </div>

          <el-table v-if="item.steps.length" :data="item.steps" size="small" border class="step-table">
            <el-table-column prop="step_order" label="#" width="46" />
            <el-table-column prop="process_name" label="工序" min-width="100" />
            <el-table-column label="已完成" min-width="90">
              <template #default="{ row }">{{ row.completed_qty }} / {{ row.order_qty }}</template>
            </el-table-column>
            <el-table-column label="可报数量" min-width="90">
              <template #default="{ row }">
                <span :class="{ 'qty-ready': row.reportable_qty > 0 }">{{ row.reportable_qty }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="last_reported_at" label="最后报工" min-width="150" show-overflow-tooltip />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <GlassButton
                  v-if="row.reportable_qty > 0 && item.status === 0" v-permission="'domestic:write'"
                  variant="link" left-icon="EditPen" @click="openReport(item, row)"
                >代报工</GlassButton>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="no-route">未配工艺路线，还没有工序进度</div>

          <div class="section-grid">
            <div v-for="s in DETAIL_SECTIONS" :key="s.key" class="section-block">
              <template v-if="item[s.key] || item[s.imageKey]?.length">
                <div class="section-label">{{ s.label }}</div>
                <div v-if="item[s.key]" class="notes-line">{{ item[s.key] }}</div>
                <DomesticImages :paths="item[s.imageKey]" />
              </template>
            </div>
          </div>

          <div v-if="item.ship_time" class="ship-line">
            已发货：{{ item.ship_time }} · {{ item.ship_weight }}g
          </div>
        </div>
      </template>
    </DetailDrawer>

    <el-dialog v-model="shipDialog.visible" title="登记发货" width="420px">
      <el-form label-width="90px">
        <el-form-item label="发货时间">
          <el-date-picker v-model="shipDialog.ship_time" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" style="width: 100%" />
        </el-form-item>
        <el-form-item label="发货克重">
          <el-input-number v-model="shipDialog.ship_weight" :min="0.01" :precision="2" style="width: 100%" />
          <span class="unit-hint">单位 g</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="shipDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="confirmShip">确定</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="reportDialog.visible" title="代车间报工" width="460px">
      <el-form label-width="100px" v-loading="reportDialog.loading">
        <el-form-item label="工序">
          <span>{{ reportDialog.step?.process_name }}</span>
        </el-form-item>
        <el-form-item label="做活的工人" required>
          <!-- 件数必须记在实际做活的人头上，否则计件工资算错人 -->
          <el-select v-model="reportDialog.workerId" placeholder="选择工人" filterable style="width: 100%">
            <el-option v-for="w in reportDialog.workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
          <span v-if="!reportDialog.loading && !reportDialog.workers.length" class="unit-hint">
            这道工序还没有绑定工人，请先去用户管理里绑
          </span>
        </el-form-item>
        <el-form-item label="报工数量">
          <el-input-number v-model="reportDialog.qty" :min="1" :max="reportDialog.step?.reportable_qty || 1" style="width: 100%" />
          <span class="unit-hint">最多 {{ reportDialog.step?.reportable_qty }} 件；拆批就把数量改小</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="reportDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="confirmReport">确定</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="logDialog.visible" title="报工流水" width="680px">
      <el-table :data="logDialog.logs" v-loading="logDialog.loading" size="small" border style="width: 100%">
        <el-table-column prop="process_name" label="工序" min-width="100" />
        <el-table-column prop="report_qty" label="数量" min-width="70" />
        <el-table-column prop="reported_by_name" label="报工人" min-width="90" />
        <el-table-column prop="reported_at" label="时间" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" min-width="80">
          <template #default="{ row }">
            <el-tag v-if="row.revoked" size="small" type="info" effect="plain">已撤销</el-tag>
            <el-tag v-else size="small" type="success" effect="plain">有效</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <GlassButton
              v-if="!row.revoked" v-permission="'domestic:write'"
              variant="link" link-tone="danger" left-icon="RefreshLeft"
              @click="handleRevokeReport(row.log_id)"
            >撤销</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <GlassButton variant="ghost" @click="logDialog.visible = false">关闭</GlassButton>
      </template>
    </el-dialog>

    <DomesticPrintDialog
      v-model:visible="printDialog.visible"
      :mode="printDialog.mode" :item-id="printDialog.itemId"
    />

    <el-dialog v-model="wxacodeDialog.visible" title="产品进度码" width="420px">
      <div v-loading="wxacodeDialog.loading" class="wxacode-body">
        <template v-if="wxacodeDialog.image">
          <img :src="wxacodeDialog.image" class="wxacode-img" alt="产品进度小程序码" />
          <div class="wxacode-no">{{ wxacodeDialog.info?.domestic_no }} · {{ wxacodeDialog.info?.product_name }}</div>
          <div v-if="wxacodeDialog.envVersion !== 'release'" class="wxacode-hint wxacode-warn">
            这是{{ wxacodeDialog.envVersion === 'trial' ? '体验版' : '开发版' }}码：只有小程序体验成员能扫开，<b>不要发给客户</b>
          </div>
          <div v-else class="wxacode-hint">微信扫码直接看这个产品的生产进度，不用登录，可以转发给客户</div>
        </template>
        <el-empty v-else-if="!wxacodeDialog.loading" description="码没生成出来，原因见右上角报错提示" :image-size="80" />
      </div>
      <template #footer>
        <GlassButton variant="ghost" @click="wxacodeDialog.visible = false">关闭</GlassButton>
        <GlassButton variant="ghost" left-icon="Printer" :disabled="!wxacodeDialog.image" @click="openWxacodeLabel">打印标签</GlassButton>
        <GlassButton variant="primary" left-icon="Download" :disabled="!wxacodeDialog.image" @click="downloadWxacode">下载图片</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="attachDialog.visible" title="配工艺路线" width="460px">
      <el-form label-width="90px">
        <el-form-item label="工艺路线">
          <el-select v-model="attachDialog.route_id" placeholder="选择路线" style="width: 100%">
            <el-option v-for="r in routes" :key="r.id" :label="`${r.name}（${r.step_count} 道）`" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="attachDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="confirmAttachRoute">确定</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 内贸订单列表 + 详情。逻辑在 composables/useDomesticOrders.js（宪法 12）。
 * 进度按「数量」展示：每道工序看到已完成多少 / 还能接多少，拆批状态一眼可见。
 */
import { DETAIL_SECTIONS, ORDER_STATUS, ORDER_STATUS_TAGS } from '@/api/domestic'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import DomesticImages from '@/components/domestic/DomesticImages.vue'
import DomesticPrintDialog from './print/DomesticPrintDialog.vue'
import { useDomesticOrders } from './composables/useDomesticOrders'

const {
  loading, list, total, page, pageSize, searchForm,
  handleSearch, handlePageChange, handleSizeChange,
  detailVisible, detailLoading, detail, routes, hasUnrouted, openDetail,
  shipDialog, openShip, confirmShip,
  reportDialog, openReport, confirmReport,
  logDialog, openLogs, handleRevokeReport,
  attachDialog, openAttachRoute, confirmAttachRoute,
  printDialog, openPrintCard, openQrLabel, openWxacodeLabel,
  wxacodeDialog, openWxacode, downloadWxacode,
  handleTerminate, handleDelete, goCreate,
} = useDomesticOrders()
</script>

<style scoped>
.orders-page { position: relative; }
.orders-aurora { inset: -24px -28px; }
.orders-page .toolbar,
.orders-page .orders-panel { position: relative; z-index: 1; }

.toolbar { margin-bottom: 16px; }

.orders-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.orders-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.orders-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.orders-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.orders-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

.pager { margin: 12px; justify-content: flex-end; }

.info-card {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
  margin-bottom: 12px;
}

.info-name { font-weight: 600; margin-bottom: 8px; }

.info-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.unrouted-alert { margin-bottom: 12px; }

.item-block {
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  margin-bottom: 12px;
}

.item-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.item-name { font-weight: 600; }

.item-current {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.item-actions { margin-left: auto; display: flex; gap: 4px; }

.step-table { margin-bottom: 10px; }

.qty-ready { color: var(--el-color-success); font-weight: 600; }

.no-route {
  font-size: 13px;
  color: var(--el-color-warning);
  margin-bottom: 10px;
}

.section-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
}

.section-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.notes-line {
  font-size: 13px;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
  margin-bottom: 6px;
}

.ship-line {
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-color-info);
}

.unit-hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.wxacode-body {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.wxacode-img {
  width: 240px;
  height: 240px;
}

.wxacode-no { font-weight: 600; }

.wxacode-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.wxacode-warn { color: var(--el-color-warning); }
</style>
