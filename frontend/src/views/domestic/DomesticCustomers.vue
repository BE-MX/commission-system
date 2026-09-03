<template>
  <div class="customers-page">
    <div class="customers-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="4">
        <el-input v-model="searchForm.keyword" placeholder="搜索编码 / 店名 / 联系人 / 电话" clearable prefix-icon="Search" @keyup.enter="handleSearch" @clear="handleSearch" />
      </el-col>
      <el-col :span="4">
        <el-select v-model="searchForm.status" placeholder="状态" clearable style="width: 100%" @change="handleSearch">
          <el-option label="启用" :value="1" />
          <el-option label="停用" :value="0" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-radio-group v-model="searchForm.owner_scope" @change="handleSearch">
          <el-radio-button label="private">私海客户</el-radio-button>
          <el-radio-button label="public">公海客户</el-radio-button>
        </el-radio-group>
      </el-col>
      <el-col :span="3">
        <el-select v-model="searchForm.province" placeholder="省份" filterable clearable style="width: 100%" @change="handleProvinceChange">
          <el-option v-for="province in options.provinces" :key="province" :label="province" :value="province" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="searchForm.city" placeholder="城市" filterable clearable style="width: 100%" @change="handleSearch">
          <el-option v-for="city in options.cities" :key="city" :label="city" :value="city" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
        <GlassButton v-permission="'domestic:write'" variant="ghost" left-icon="Plus" @click="openDialog()">新增客户</GlassButton>
        <GlassButton v-permission="'domestic:admin'" variant="ghost" left-icon="Upload" @click="openImport">导入客户</GlassButton>
      </el-col>
    </el-row>

    <el-alert class="membership-tip" type="info" :closable="false" show-icon title="会员等级默认按最近一次充值金额核定；管理员可「初始化」期初或「调整」临时覆盖，下一次充值会重新按金额核定。" />

    <div class="table-card customers-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="custom_code" label="客户编码" min-width="110" show-overflow-tooltip />
        <el-table-column prop="shop_name" label="客户店名" min-width="160" show-overflow-tooltip />
        <el-table-column label="客户等级" min-width="90">
          <template #default="{ row }">
            <el-tag v-if="row.customer_level" size="small" effect="plain" type="warning">{{ row.customer_level }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="客户状态" min-width="90">
          <template #default="{ row }">
            <el-tag v-if="row.lifecycle_status" size="small" effect="plain"
              :type="{ 活跃: 'success', 潜在: 'warning', 沉默: 'info', 流失: 'danger' }[row.lifecycle_status] || 'info'">
              {{ row.lifecycle_status }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="owner_name" label="归属销售" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ row.owner_name || '-' }}</template>
        </el-table-column>
        <el-table-column prop="customer_source" label="客户来源" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.customer_source || '-' }}</template>
        </el-table-column>
        <el-table-column prop="store_type" label="门店类型" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.store_type || '-' }}</template>
        </el-table-column>
        <el-table-column label="会员等级" min-width="110">
          <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.membership_label }}</el-tag></template>
        </el-table-column>
        <el-table-column label="最近充值" min-width="170">
          <template #default="{ row }">
            <template v-if="row.last_recharge_amount != null">
              <div>¥{{ Number(row.last_recharge_amount).toFixed(2) }}</div>
              <div class="muted">{{ row.last_recharged_at || '-' }}</div>
            </template>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="省 / 市" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ [row.province, row.city].filter(Boolean).join(' / ') || '-' }}</template>
        </el-table-column>
        <el-table-column prop="contact" label="联系人" min-width="100" show-overflow-tooltip />
        <el-table-column prop="phone" label="电话" min-width="130" show-overflow-tooltip />
        <el-table-column label="累计订单 / 销售额" min-width="150">
          <template #default="{ row }">
            <template v-if="row.total_order_count != null || row.total_sales_amount != null">
              {{ row.total_order_count ?? '-' }} 单 / ¥{{ Number(row.total_sales_amount || 0).toFixed(2) }}
            </template>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_count" label="订单数" min-width="90" />
        <el-table-column label="结算方式" min-width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="row.settle_mode === 'credit' ? 'warning' : 'info'" effect="plain">
              {{ row.settle_mode_label || '先充值后下单' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="充值余额" min-width="110" align="right">
          <template #default="{ row }">
            <span v-if="Number(row.balance || 0) < 0" class="debt-value">欠款 ¥{{ Math.abs(Number(row.balance)).toFixed(2) }}</span>
            <span v-else class="balance-value">¥{{ Number(row.balance || 0).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status ? 'success' : 'info'" effect="plain">{{ row.status ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="270" fixed="right">
          <template #default="{ row }">
            <GlassButton v-if="canOperateCustomer(row)" v-permission="'domestic:write'" variant="link" left-icon="Edit" @click="openDialog(row)">编辑</GlassButton>
            <GlassButton v-if="canOperateCustomer(row)" v-permission="'domestic:write'" variant="link" :link-tone="row.status ? '' : 'success'" left-icon="SwitchButton" @click="toggleStatus(row)">
              {{ row.status ? '停用' : '启用' }}
            </GlassButton>
            <GlassButton v-if="canOperateCustomer(row)" v-any-permission="['domestic:recharge', 'domestic:admin']" variant="link" left-icon="Wallet" @click="openRecharge(row)">充值</GlassButton>
            <GlassButton v-if="canOperateCustomer(row) && !row.initialized" v-any-permission="['domestic:recharge', 'domestic:admin']" variant="link" left-icon="CirclePlus" @click="openInit(row)">初始化</GlassButton>
            <GlassButton v-if="canOperateCustomer(row)" v-any-permission="['domestic:recharge', 'domestic:admin']" variant="link" left-icon="EditPen" @click="openAdjust(row)">调整</GlassButton>
            <GlassButton v-if="canOperateCustomer(row)" v-any-permission="['domestic:recharge', 'domestic:admin']" variant="link" left-icon="Tickets" @click="openLedger(row)">流水</GlassButton>
            <GlassButton v-if="canOperateCustomer(row)" v-permission="'domestic:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="dialog.visible" :title="dialog.id ? '编辑客户' : '新增客户'" width="640px">
      <el-form :model="dialog" label-width="100px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="客户编码">
              <el-input v-model="dialog.custom_code" maxlength="64" placeholder="自定义，可不填" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="客户店名" required>
              <el-input v-model="dialog.shop_name" placeholder="如：马姐假发" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="联系人"><el-input v-model="dialog.contact" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="手机号"><el-input v-model="dialog.phone" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="省份 / 城市">
          <el-cascader
            v-model="dialog.region" :options="chinaRegions" :props="{ expandTrigger: 'hover' }"
            filterable clearable placeholder="选择省份 / 城市" style="width: 100%"
          />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="归属销售">
              <el-select v-model="dialog.owner_user_id" filterable clearable style="width: 100%">
                <el-option v-for="opt in options.owners" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="客户来源">
              <el-select v-model="dialog.customer_source" clearable style="width: 100%">
                <el-option v-for="opt in options.customer_source" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="客户等级">
              <el-select v-model="dialog.customer_level" clearable style="width: 100%">
                <el-option v-for="opt in options.customer_level" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="客户状态">
              <el-select v-model="dialog.lifecycle_status" clearable style="width: 100%">
                <el-option v-for="opt in options.lifecycle_status" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="门店类型">
              <el-select v-model="dialog.store_type" clearable style="width: 100%">
                <el-option v-for="opt in options.store_type" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="首次联系">
              <el-date-picker v-model="dialog.first_contact_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="首次下单">
              <el-date-picker v-model="dialog.first_order_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="最近下单">
              <el-date-picker v-model="dialog.last_order_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="累计订单数">
              <el-input-number v-model="dialog.total_order_count" :min="0" :precision="0" style="width: 100%" placeholder="历史档案口径" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="累计销售额">
              <el-input-number v-model="dialog.total_sales_amount" :min="0" :precision="2" :step="1000" style="width: 100%" placeholder="历史档案口径" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="收货地址">
          <el-input v-model="dialog.address" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="结算方式" required>
          <el-radio-group v-model="dialog.settle_mode">
            <el-radio-button value="prepay">先充值后下单</el-radio-button>
            <el-radio-button value="credit">先下单后付款</el-radio-button>
          </el-radio-group>
          <div class="preview-hint" style="margin-left: 0">先下单后付款：下单不校验余额，欠款记为负余额，充值后自动冲抵</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dialog.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="dialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="save">确定</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="importDialog.visible" title="导入客户（莱莎客户信息录入表）" width="560px">
      <el-alert type="info" show-icon :closable="false" class="tips"
        title="按客户编码更新已有客户；同店名不同编码的只补空档并保留先导入的归属。财务字段（余额/会员等级）导入不改动。" />
      <AppUpload
        v-model="importDialog.files" :upload-fn="doImport" accept=".xlsx"
        :show-list="false" :limit="1" button-text="选择 xlsx 文件导入"
      />
      <template v-if="importDialog.result">
        <el-result
          icon="success" class="import-result"
          :title="`新建 ${importDialog.result.created}，更新 ${importDialog.result.updated}，合并同名 ${importDialog.result.merged}`"
          :sub-title="`失败 ${importDialog.result.errors?.length || 0} 条，解析跳过 ${importDialog.result.skipped?.length || 0} 条，数据警告 ${importDialog.result.warnings?.length || 0} 条`"
        />
        <el-scrollbar v-if="(importDialog.result.errors?.length || 0) + (importDialog.result.collisions?.length || 0) + (importDialog.result.warnings?.length || 0) > 0" max-height="220px">
          <div v-for="(item, i) in importDialog.result.errors" :key="`e${i}`" class="import-line error">
            {{ item.row }}：{{ item.reason }}
          </div>
          <div v-for="(item, i) in importDialog.result.warnings" :key="`w${i}`" class="import-line warning">
            {{ item.sheet }}第{{ item.row_no }}行[{{ item.code }}]：{{ item.reason }}
          </div>
          <div v-for="(item, i) in importDialog.result.collisions" :key="`c${i}`" class="import-line">
            {{ item.row }}：{{ item.reason }}
          </div>
        </el-scrollbar>
      </template>
      <template #footer>
        <GlassButton variant="ghost" @click="importDialog.visible = false">关闭</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="rechargeDialog.visible" title="客户充值" width="440px">
      <el-form label-width="90px">
        <el-form-item label="客户"><strong>{{ rechargeDialog.customer?.shop_name }}</strong></el-form-item>
        <el-form-item label="当前余额">¥{{ Number(rechargeDialog.customer?.balance || 0).toFixed(2) }}</el-form-item>
        <el-form-item label="充值金额" required>
          <el-input-number v-model="rechargeDialog.amount" :min="0.01" :precision="2" :step="100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="充值后会员">
          <el-tag effect="plain">{{ membershipPreview(rechargeDialog.amount) }}</el-tag>
          <span class="preview-hint">仅按本次充值金额计算</span>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="rechargeDialog.remark" type="textarea" :rows="2" maxlength="500" placeholder="如：银行转账到账" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="rechargeDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="rechargeDialog.saving" @click="confirmRecharge">确认充值</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="initDialog.visible" title="期初初始化（仅一次）" width="440px">
      <el-alert type="warning" show-icon :closable="false" class="tips" title="只适用于还没有任何资金流水的新建档客户；已有流水请用「调整」。" />
      <el-form label-width="90px">
        <el-form-item label="客户"><strong>{{ initDialog.customer?.shop_name }}</strong></el-form-item>
        <el-form-item label="期初余额">
          <el-input-number v-model="initDialog.balance" :min="0" :precision="2" :step="100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="会员等级">
          <el-select v-model="initDialog.membership_level" style="width: 100%">
            <el-option v-for="opt in membershipOptions" :key="opt.label" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="initDialog.remark" type="textarea" :rows="2" maxlength="500" placeholder="如：老客户线下余额迁入" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="initDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="initDialog.saving" @click="confirmInit">确认初始化</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="adjustDialog.visible" title="临时调整余额 / 等级" width="460px">
      <el-alert type="warning" show-icon :closable="false" class="tips" title="余额正数加、负数减；等级覆盖是临时的，下一次充值会按金额重新核定。" />
      <el-form label-width="90px">
        <el-form-item label="客户"><strong>{{ adjustDialog.customer?.shop_name }}</strong></el-form-item>
        <el-form-item label="当前状态">
          <span>{{ adjustDialog.customer?.membership_label }} · 余额 ¥{{ Number(adjustDialog.customer?.balance || 0).toFixed(2) }}</span>
        </el-form-item>
        <el-form-item label="余额调整">
          <el-input-number v-model="adjustDialog.amount" :precision="2" :step="50" style="width: 100%" />
          <span class="preview-hint">0 表示不动余额</span>
        </el-form-item>
        <el-form-item label="会员等级">
          <el-select v-model="adjustDialog.membership_level" style="width: 100%">
            <el-option label="不修改" value="__keep__" />
            <el-option v-for="opt in membershipOptions" :key="opt.label" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="调整原因" required>
          <el-input v-model="adjustDialog.remark" type="textarea" :rows="2" maxlength="500" placeholder="必填：为什么调，如「多扣退回」「老板特批至尊」" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="adjustDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="adjustDialog.saving" @click="confirmAdjust">确认调整</GlassButton>
      </template>
    </el-dialog>

    <el-drawer v-model="ledgerDrawer.visible" :title="`${ledgerDrawer.customer?.shop_name || ''} · 余额流水`" size="720px">
      <el-table :data="ledgerDrawer.items" v-loading="ledgerDrawer.loading" border size="small" class="list-table">
        <el-table-column prop="created_at" label="时间" min-width="150" />
        <el-table-column label="类型" min-width="100">
          <template #default="{ row }">{{ ledgerTypeLabel[row.transaction_type] || row.transaction_type }}</template>
        </el-table-column>
        <el-table-column label="变动" min-width="100" align="right">
          <template #default="{ row }"><span :class="row.amount >= 0 ? 'amount-in' : 'amount-out'">{{ row.amount >= 0 ? '+' : '' }}¥{{ Number(row.amount).toFixed(2) }}</span></template>
        </el-table-column>
        <el-table-column label="余额" min-width="100" align="right">
          <template #default="{ row }">¥{{ Number(row.balance_after).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="domestic_no" label="关联订单" min-width="130" />
        <el-table-column prop="remark" label="说明" min-width="180" show-overflow-tooltip />
        <el-table-column prop="created_by_name" label="操作人" min-width="90" />
      </el-table>
      <el-pagination
        v-model:current-page="ledgerDrawer.page" :page-size="20" :total="ledgerDrawer.total"
        layout="total, prev, pager, next" class="pager" @current-change="loadLedger"
      />
    </el-drawer>
  </div>
</template>

<script setup>
/** 内贸客户管理。下单页可就地新建客户，这里做集中维护；逻辑在 composables/useDomesticCustomers.js。 */
import { CHINA_REGIONS } from '@/data/chinaRegions'
import AppUpload from '@/components/AppUpload.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useDomesticCustomers } from './composables/useDomesticCustomers'

const chinaRegions = CHINA_REGIONS

const {
  loading, list, total, page, pageSize, searchForm,
  handleSearch, handlePageChange, handleSizeChange,
  canOperateCustomer, handleProvinceChange,
  saving, dialog, options, openDialog, save,
  rechargeDialog, openRecharge, confirmRecharge,
  initDialog, openInit, confirmInit,
  adjustDialog, openAdjust, confirmAdjust,
  ledgerDrawer, ledgerTypeLabel, openLedger, loadLedger,
  importDialog, openImport, doImport,
  toggleStatus, handleDelete, membershipOptions,
  membershipPreview,
} = useDomesticCustomers()
</script>

<style scoped>
.customers-page { position: relative; }
.customers-aurora { inset: -24px -28px; }
.customers-page .toolbar,
.customers-page .customers-panel { position: relative; z-index: 1; }

.toolbar { margin-bottom: 16px; }
.membership-tip { margin-bottom: 12px; position: relative; z-index: 1; }

.customers-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.customers-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.customers-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.customers-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }

.pager { margin: 12px; justify-content: flex-end; }
.balance-value { color: var(--el-color-success); font-weight: 600; }
.debt-value { color: var(--el-color-danger); font-weight: 600; }
.amount-in { color: var(--el-color-success); font-weight: 600; }
.amount-out { color: var(--el-color-danger); font-weight: 600; }
.muted, .preview-hint { color: var(--el-text-color-secondary); font-size: 12px; }
.preview-hint { margin-left: 8px; }
.tips { margin-bottom: 12px; }
.import-result { padding: 8px 0; }
.import-line { font-size: 12px; color: var(--el-text-color-secondary); padding: 3px 0; }
.import-line.error { color: var(--el-color-danger); }
.import-line.warning { color: var(--el-color-warning); }
</style>
