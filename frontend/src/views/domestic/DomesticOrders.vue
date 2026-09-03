<template>
  <div class="orders-page">
    <div class="orders-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="4">
        <el-input v-model="searchForm.keyword" placeholder="搜索系统单号 / 客户订单号" clearable prefix-icon="Search" @keyup.enter="handleSearch" @clear="handleSearch" />
      </el-col>
      <el-col :span="3">
        <el-select v-model="searchForm.status" placeholder="订单状态" clearable style="width: 100%" @change="handleSearch">
          <el-option v-for="s in ORDER_STATUS" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="searchForm.order_category" placeholder="订单类别" clearable style="width: 100%" @change="handleSearch">
          <el-option v-for="v in filterOptions.order_categories" :key="v.value" :label="v.label" :value="v.value" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="searchForm.order_type" placeholder="订单类型" clearable style="width: 100%" @change="handleSearch">
          <el-option v-for="v in filterOptions.order_types" :key="v.value" :label="v.label" :value="v.value" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="searchForm.order_channel" placeholder="订单渠道" clearable style="width: 100%" @change="handleSearch">
          <el-option v-for="v in filterOptions.order_channels" :key="v.value" :label="v.label" :value="v.value" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-date-picker
          v-model="searchForm.dateRange" type="daterange" value-format="YYYY-MM-DD"
          start-placeholder="下单起" end-placeholder="下单止" style="width: 100%" @change="handleSearch"
        />
      </el-col>
      <el-col :span="4">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
        <GlassButton v-permission="'domestic:write'" variant="ghost" left-icon="Plus" @click="goCreate">新建订单</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card orders-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <!-- 列顺序按内贸销售台账：编号 → 日期 → 客户 → 归属销售 → 类型 → 渠道 → 状态 → 交付日期 → 客户复购节奏，与线下台账一致 -->
        <el-table-column prop="domestic_no" label="订单编号" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.domestic_no }}</div>
            <div v-if="row.order_no" class="muted">{{ row.order_no }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="order_date" label="下单日期" min-width="105" />
        <el-table-column prop="customer_name" label="客户名称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="owner_name" label="归属销售" min-width="95" show-overflow-tooltip>
          <template #default="{ row }">{{ row.owner_name || '-' }}</template>
        </el-table-column>
        <el-table-column prop="order_type_label" label="订单类型" min-width="95" />
        <el-table-column prop="order_channel_label" label="订单渠道" min-width="95" />
        <el-table-column label="订单状态" min-width="95">
          <template #default="{ row }">
            <el-tag size="small" :type="ORDER_STATUS_TAGS[row.status]">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="要求交付日期" min-width="110">
          <template #default="{ row }">
            <span :class="{ 'ship-date-overdue': isShipDateOverdue(row) }">{{ row.required_ship_date || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="实际交付日期" min-width="110">
          <template #default="{ row }">{{ row.actual_ship_date || '-' }}</template>
        </el-table-column>
        <el-table-column label="上次下单日期" min-width="110">
          <template #default="{ row }">{{ row.last_order_date || '-' }}</template>
        </el-table-column>
        <el-table-column label="复购周期/天" min-width="100" align="right">
          <template #default="{ row }">{{ row.repurchase_cycle_days != null ? row.repurchase_cycle_days : '-' }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="订单备注" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="220" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="openDetail(row)">详情</GlassButton>
            <GlassButton variant="link" left-icon="Download" @click="handleExport(row)">导出</GlassButton>
            <GlassButton v-if="row.status === 0 && canOperateOrder(row)" v-permission="'domestic:write'" variant="link" left-icon="Promotion" :loading="submittingOrderIds.has(row.id)" :disabled="submittingOrderIds.has(row.id)" @click="handleSubmitDraft(row)">提交</GlassButton>
            <GlassButton v-else-if="canOperateOrder(row)" v-permission="'domestic:write'" variant="link" left-icon="CircleClose" :disabled="row.status >= 3" @click="handleTerminate(row)">终止</GlassButton>
            <GlassButton v-if="canOperateOrder(row)" v-permission="'domestic:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
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
            <span>要求发货：{{ detail.required_ship_date || '-' }}</span>
            <span>订单类别：{{ detail.order_category_label }}</span>
            <span>订单类型：{{ detail.order_type_label }}</span>
            <span>订单渠道：{{ detail.order_channel_label }}</span>
            <span>状态：{{ detail.status_label }}</span>
            <span>订单总价：¥{{ Number(detail.total_amount || 0).toFixed(2) }}</span>
            <span>已扣余额：¥{{ Number(detail.charged_amount || 0).toFixed(2) }}</span>
            <span v-if="detail.customer_custom_code">客户编码：{{ detail.customer_custom_code }}</span>
            <span>当前会员：{{ membershipLevelLabel(detail.customer_membership_level) }}</span>
            <span v-if="detail.customer_province || detail.customer_city">地区：{{ [detail.customer_province, detail.customer_city].filter(Boolean).join(' / ') }}</span>
            <span v-if="detail.customer_contact">联系人：{{ detail.customer_contact }}</span>
            <span v-if="detail.customer_phone">电话：{{ detail.customer_phone }}</span>
            <span v-if="detail.customer_address">地址：{{ detail.customer_address }}</span>
          </div>
          <div v-if="detail.remark" class="notes-line">备注：{{ detail.remark }}</div>
        </div>

        <el-alert
          v-if="hasUnrouted" type="warning" show-icon :closable="false" class="unrouted-alert"
          title="有明细还没配工艺路线，这些货暂时不能开工" description="在下方明细里点「配工艺路线」补配，或去「产品与工艺」页配好该工艺的默认路线。"
        />

        <div v-for="item in detail.items" :key="item.id" class="item-block">
          <!-- 明细头分三行：名称与状态 / 价格信息 / 操作按钮，避免一行里塞满标签和按钮 -->
          <div class="item-head">
            <span class="item-name">{{ item.line_code }} · {{ item.product_name }}</span>
            <span class="item-head-right">
              <el-tag size="small" :type="item.status === 2 ? 'info' : (item.status === 1 ? 'success' : '')">{{ item.status_label }}</el-tag>
              <span class="item-current">当前：{{ item.current_process }}</span>
            </span>
          </div>

          <div class="item-meta">
            <span class="meta-item">数量 <b>{{ item.order_qty }} 件</b></span>
            <template v-if="detail.order_category === 'special'">
              <span class="meta-item">销售价 <b>¥{{ Number(item.unit_price || 0).toFixed(2) }}</b> / 件</span>
            </template>
            <template v-else>
              <span class="meta-item">明细单价 <b>¥{{ Number(item.unit_price || 0).toFixed(2) }}</b> / 件</span>
              <span class="meta-item muted">优惠价 ¥{{ (Number(item.unit_price || 0) - Number(item.labor_fee || 0)).toFixed(2) }}<template v-if="Number(item.labor_fee || 0) > 0"> + 手工费 ¥{{ Number(item.labor_fee).toFixed(2) }}</template></span>
              <span class="meta-item muted">原始价 ¥{{ Number(item.original_price || 0).toFixed(2) }}</span>
              <span v-if="Number(item.discount_amount || 0) > 0" class="meta-item meta-discount">优惠 -¥{{ Number(item.discount_amount).toFixed(2) }}</span>
              <span class="meta-item muted">{{ membershipLevelLabel(item.membership_level_snapshot) }} · {{ item.pricing_rule_label || '历史人工价' }}</span>
            </template>
            <span class="meta-item meta-amount">小计 ¥{{ Number(item.line_amount || 0).toFixed(2) }}</span>
          </div>

          <div class="item-actions">
            <GlassButton v-if="detail.status !== 0" variant="link" left-icon="Printer" @click="openPrintCard(item)">流转卡</GlassButton>
            <GlassButton variant="link" left-icon="Grid" @click="openQrLabel(item)">逐件码</GlassButton>
            <GlassButton v-if="detail.status !== 0" variant="link" left-icon="Share" @click="openWxacode(item)">进度码</GlassButton>
            <GlassButton v-if="detail.status !== 0" variant="link" left-icon="Tickets" @click="openLogs(item)">报工流水</GlassButton>
            <GlassButton
              v-if="item.route_id" v-permission="'domestic:admin'"
              variant="link" left-icon="Warning" @click="openSkipAudits(item)"
            >异常跳过记录</GlassButton>
            <GlassButton v-if="!item.route_id" v-permission="'domestic:write'" variant="link" left-icon="Connection" @click="openAttachRoute(item)">配工艺路线</GlassButton>
            <GlassButton
              v-if="detail.status <= 2 && item.status !== 2" v-permission="'domestic:write'"
              variant="link" left-icon="EditPen" @click="openPriceEdit(item)"
            >改价</GlassButton>
            <GlassButton v-if="item.status === 1" v-permission="'domestic:write'" variant="link" left-icon="Van" @click="openShip(item)">登记发货</GlassButton>
          </div>

          <el-table v-if="item.steps.length" :data="item.steps" size="small" border class="step-table list-table">
            <el-table-column prop="step_order" label="#" min-width="46" />
            <el-table-column prop="process_name" label="工序" min-width="100" />
            <el-table-column label="报工进度" min-width="135">
              <template #default="{ row }">
                <div>已报 {{ row.completed_qty }} / 应做 {{ row.required_qty }}</div>
                <div v-if="row.skipped_qty" class="skip-progress">已跳过 {{ row.skipped_qty }}（不计工资）</div>
              </template>
            </el-table-column>
            <el-table-column label="可报数量" min-width="90">
              <template #default="{ row }">
                <span :class="{ 'qty-ready': row.reportable_qty > 0 }">{{ row.reportable_qty }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="last_reported_at" label="最后报工" min-width="150" show-overflow-tooltip />
            <el-table-column label="操作" min-width="170">
              <template #default="{ row }">
                <GlassButton
                  v-if="row.reportable_qty > 0 && item.status === 0" v-permission="'domestic:write'"
                  variant="link" left-icon="EditPen" @click="openReport(item, row)"
                >代报工</GlassButton>
                <GlassButton
                  v-if="row.reportable_qty > 0 && item.status === 0" v-permission="'domestic:admin'"
                  variant="link" link-tone="danger" left-icon="Warning" @click="openSkip(item, row)"
                >异常跳过</GlassButton>
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

    <el-dialog v-model="priceEditDialog.visible" title="手工改价" width="420px">
      <el-form label-width="90px" v-loading="priceEditDialog.saving">
        <el-form-item label="明细">
          <span>{{ priceEditDialog.item?.line_code }} · {{ priceEditDialog.item?.product_name }} × {{ priceEditDialog.item?.order_qty }}</span>
        </el-form-item>
        <el-form-item label="原始价">
          <span>¥{{ Number(priceEditDialog.item?.original_price || 0).toFixed(2) }}</span>
        </el-form-item>
        <el-form-item label="当前优惠价">
          <span>¥{{ Number(priceEditDialog.item?.unit_price || 0).toFixed(2) }}（{{ priceEditDialog.item?.pricing_rule_label || '历史人工价' }}）</span>
        </el-form-item>
        <el-form-item label="新优惠价" required>
          <el-input-number
            v-model="priceEditDialog.price" :min="0.01"
            :max="Number(priceEditDialog.item?.original_price || 0) || undefined"
            :precision="2" style="width: 100%"
          />
          <span class="unit-hint">不能超过原价；已提交订单的差额立即与客户余额结算</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="priceEditDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="priceEditDialog.saving" @click="confirmPriceEdit">确认改价</GlassButton>
      </template>
    </el-dialog>

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
        <template v-if="reportDialog.step?.rule_type === 'decision'">
          <el-form-item v-for="option in reportDialog.step.outcome_options" :key="option.code" :label="option.label">
            <el-input-number
              v-model="reportDialog.outcomes[option.code]" :min="0"
              :max="reportDialog.step?.reportable_qty || 0" style="width: 100%"
            />
          </el-form-item>
          <div class="unit-hint">分流判定可按数量拆分，合计最多 {{ reportDialog.step?.reportable_qty }} 件</div>
        </template>
        <el-form-item v-else label="报工数量">
          <el-input-number v-model="reportDialog.qty" :min="1" :max="reportDialog.step?.reportable_qty || 1" style="width: 100%" />
          <span class="unit-hint">最多 {{ reportDialog.step?.reportable_qty }} 件；拆批就把数量改小</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="reportDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="confirmReport">确定</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="skipDialog.visible" title="异常跳过工序" width="460px">
      <el-alert type="warning" :closable="false" show-icon title="跳过只放行生产路线，不会记报工数量，也不计工资。" />
      <el-form label-width="90px" class="skip-form">
        <el-form-item label="工序">{{ skipDialog.step?.process_name }}</el-form-item>
        <el-form-item label="跳过数量" required>
          <el-input-number v-model="skipDialog.qty" :min="1" :max="skipDialog.step?.reportable_qty || 1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="异常原因" required>
          <el-input v-model="skipDialog.reason" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="至少 5 个字，例如：客户要求不做定型" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="skipDialog.visible = false">取消</GlassButton>
        <GlassButton variant="danger" :loading="skipDialog.submitting" @click="confirmSkip">确认异常跳过</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="logDialog.visible" title="报工流水" width="680px">
      <el-table :data="logDialog.logs" v-loading="logDialog.loading" size="small" border style="width: 100%" class="list-table">
        <el-table-column prop="process_name" label="工序" min-width="100" />
        <el-table-column prop="report_qty" label="数量" min-width="70" />
        <el-table-column label="单件" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ (row.unit_codes || []).join('、') || '-' }}</template>
        </el-table-column>
        <el-table-column prop="reported_by_name" label="报工人" min-width="90" />
        <el-table-column prop="reported_at" label="时间" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" min-width="80">
          <template #default="{ row }">
            <el-tag v-if="row.revoked" size="small" type="info" effect="plain">已撤销</el-tag>
            <el-tag v-else size="small" type="success" effect="plain">有效</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="90">
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

    <DomesticSkipAuditDialog
      v-model="skipAuditDialog.visible" :audits="skipAuditDialog.audits"
      :loading="skipAuditDialog.loading" :revoking-id="skipAuditDialog.revokingId"
      @refresh="loadSkipAudits" @revoke="handleRevokeSkip"
    />

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
import DomesticSkipAuditDialog from './components/DomesticSkipAuditDialog.vue'
import DomesticPrintDialog from './print/DomesticPrintDialog.vue'
import { useDomesticOrders } from './composables/useDomesticOrders'
import { membershipLevelLabel } from './composables/domesticMemberPricing'

const {
  loading, list, total, page, pageSize, searchForm, filterOptions,
  handleSearch, handlePageChange, handleSizeChange,
  detailVisible, detailLoading, detail, routes, hasUnrouted, openDetail,
  shipDialog, openShip, confirmShip,
  reportDialog, openReport, confirmReport,
  skipDialog, openSkip, confirmSkip,
  skipAuditDialog, openSkipAudits, loadSkipAudits, handleRevokeSkip,
  logDialog, openLogs, handleRevokeReport,
  attachDialog, openAttachRoute, confirmAttachRoute,
  printDialog, openPrintCard, openQrLabel, openWxacodeLabel,
  wxacodeDialog, openWxacode, downloadWxacode,
  handleExport, handleSubmitDraft, submittingOrderIds, handleTerminate, handleDelete, goCreate,
  canOperateOrder,
  priceEditDialog, openPriceEdit, confirmPriceEdit,
  isShipDateOverdue,
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

.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.item-head-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.item-name { font-weight: 600; }

.item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 20px;
  padding: 8px 10px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 8px;
}

.meta-item b { font-weight: 600; color: var(--el-text-color-primary); }
.meta-item.muted { color: var(--el-text-color-secondary); }
.meta-discount { color: var(--el-color-success); }
.meta-amount { font-weight: 600; color: var(--el-text-color-primary); }

.item-current {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
  margin-bottom: 10px;
}

.muted { font-size: 12px; color: var(--el-text-color-secondary); }

.step-table { margin-bottom: 10px; }

.qty-ready { color: var(--el-color-success); font-weight: 600; }
.skip-progress { margin-top: 2px; font-size: 12px; color: var(--el-text-color-secondary); }
.skip-form { margin-top: 16px; }

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

.ship-date-overdue { color: var(--el-color-danger); font-weight: 600; }

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
