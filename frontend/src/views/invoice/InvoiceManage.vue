<template>
  <div class="invoice-page">
    <div class="page-header">
      <div>
        <h2>订单发票管理</h2>
        <p>客户发票、产品明细、价格管控、导出与小满同步集中处理。</p>
      </div>
      <div class="header-actions">
        <el-button v-permission="'invoice:write'" type="primary" class="primary-action" @click="openCreate('stock')">
          <el-icon><Plus /></el-icon>
          新建库存单
        </el-button>
        <el-button v-permission="'invoice:write'" @click="openCreate('production')">
          <el-icon><Plus /></el-icon>
          新建生产单
        </el-button>
      </div>
    </div>

    <div class="summary-grid">
      <div class="summary-card">
        <span>发票数</span>
        <strong>{{ summary.total }}</strong>
      </div>
      <div class="summary-card">
        <span>可同步</span>
        <strong>{{ summary.ready }}</strong>
      </div>
      <div class="summary-card">
        <span>草稿</span>
        <strong>{{ summary.draft }}</strong>
      </div>
      <div class="summary-card emphasis">
        <span>当前页金额</span>
        <strong>USD {{ money(summary.amount) }}</strong>
      </div>
    </div>

    <section class="table-card invoice-panel">
      <div class="toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="搜索发票号/客户"
          style="width: 260px"
          @keyup.enter="loadInvoices"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filters.order_type" clearable placeholder="订单类型" style="width: 130px">
          <el-option label="库存单" value="stock" />
          <el-option label="生产单" value="production" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" style="width: 150px">
          <el-option label="草稿" value="draft" />
          <el-option label="可同步" value="ready" />
          <el-option label="已同步" value="synced" />
          <el-option label="同步失败" value="sync_failed" />
        </el-select>
        <el-button @click="loadInvoices">
          <el-icon><Search /></el-icon>
          筛选
        </el-button>
      </div>

      <el-table v-loading="loading" :data="invoices" border class="list-table invoice-table">
        <template #empty>
          <div class="empty-state">
            <strong>暂无发票</strong>
            <span>新建一张发票后会显示在这里。</span>
          </div>
        </template>
        <el-table-column prop="invoice_no" label="发票号" min-width="132" max-width="170" show-overflow-tooltip />
        <el-table-column label="类型" min-width="76" max-width="96">
          <template #default="{ row }">
            <el-tag :type="row.order_type === 'production' ? 'warning' : 'info'" effect="plain">
              {{ row.order_type === 'production' ? '生产单' : '库存单' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="customer_name" label="客户" min-width="150" max-width="260" show-overflow-tooltip />
        <el-table-column prop="invoice_date" label="日期" min-width="96" max-width="120" show-overflow-tooltip />
        <el-table-column prop="item_count" label="明细" min-width="56" max-width="76" align="right" />
        <el-table-column label="金额" min-width="104" max-width="150" align="right">
          <template #default="{ row }">{{ row.currency }} {{ money(row.total_amount) }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="84" max-width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="同步" min-width="84" max-width="110">
          <template #default="{ row }">
            <el-tag :type="syncType(row.sync_status)" effect="plain">{{ syncText(row.sync_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建人" min-width="84" max-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.created_by_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="130" max-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="356" max-width="390" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button v-permission="'invoice:write'" link type="primary" @click="openEdit(row.id)">
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-dropdown trigger="click" @command="cmd => handleExport(cmd, row)">
                <el-button link>
                  <el-icon><Download /></el-icon>
                  导出
                  <el-icon><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="excel">Excel</el-dropdown-item>
                    <el-dropdown-item command="pdf">PDF</el-dropdown-item>
                    <el-dropdown-item command="print">打印 / 预览</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button v-permission="'invoice:sync'" link type="warning" @click="validateAndSync(row.id)">
                <el-icon><Refresh /></el-icon>
                同步
              </el-button>
              <el-button v-permission="'invoice:read'" link @click="openSyncLogs(row)">
                <el-icon><Document /></el-icon>
                日志
              </el-button>
              <el-button v-permission="'invoice:write'" link type="danger" @click="removeInvoice(row)">
                <el-icon><Delete /></el-icon>
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total,sizes,prev,pager,next,jumper"
        @size-change="loadInvoices"
        @current-change="loadInvoices"
      />
    </div>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="94%">
      <template #default>
        <el-form ref="formRef" :model="form" label-width="80px" class="invoice-form">
          <section class="head-section">
            <div class="col-title">客户信息</div>
            <div class="head-grid">
              <el-form-item label="客户" required class="span-3">
                <div class="customer-filter-row">
                  <el-select
                    v-model="selectedCustomer"
                    value-key="company_id"
                    filterable
                    remote
                    reserve-keyword
                    :remote-method="searchCustomers"
                    :loading="customerLoading"
                    placeholder="输入客户名称/ID 搜索"
                    class="customer-filter-select"
                    @change="onCustomerChange"
                  >
                    <el-option
                      v-for="customer in customerOptions"
                      :key="customer.company_id"
                      :label="customerLabel(customer)"
                      :value="customer"
                    />
                  </el-select>
                  <el-checkbox v-permission="'invoice_private_filter:read'" v-model="privateOnlyCompany" class="customer-filter-check">仅私海</el-checkbox>
                </div>
                <div v-if="customerRule" class="rule-badge">
                  该客户价格规则：{{ describeCustomerRule(customerRule) }}
                </div>
              </el-form-item>
              <el-form-item label="按联系人" class="span-3">
                <div class="customer-filter-row">
                  <el-select
                    v-model="selectedContact"
                    value-key="contact_id"
                    filterable
                    remote
                    clearable
                    reserve-keyword
                    :remote-method="searchContacts"
                    :loading="contactLoading"
                    :placeholder="form.customer_id ? '搜索该客户的联系人' : '输入联系人姓名定位客户'"
                    class="customer-filter-select"
                    @change="onContactChange"
                  >
                    <el-option
                      v-for="contact in contactOptions"
                      :key="contact.contact_id"
                      :label="contactLabel(contact)"
                      :value="contact"
                    />
                  </el-select>
                  <el-checkbox v-permission="'invoice_private_filter:read'" v-model="privateOnlyContact" class="customer-filter-check">仅私海</el-checkbox>
                </div>
                <div v-if="!okkiBound && (privateOnlyCompany || privateOnlyContact)" class="binding-helper">
                  {{ canTogglePrivate
                    ? '未绑定 OKKI，私海筛选无结果。请取消“仅私海”或前往外部账号绑定。'
                    : '未绑定 OKKI，暂无法搜索私海客户。请到 系统管理 → 外部账号绑定 处理。' }}
                </div>
              </el-form-item>
              <el-form-item label="联系人" class="span-2">
                <el-input v-model="form.contact_name" maxlength="100" placeholder="To" />
              </el-form-item>
              <el-form-item label="电话" class="span-2">
                <el-input v-model="form.contact_phone" maxlength="50" placeholder="TEL/Fax" />
              </el-form-item>
              <el-form-item label="邮箱" class="span-2">
                <el-input v-model="form.contact_email" maxlength="100" placeholder="E-mail" />
              </el-form-item>
              <el-form-item label="收货地址" class="span-6">
                <el-input v-model="form.delivery_address" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="500" placeholder="Delivery address" />
              </el-form-item>
            </div>
          </section>

          <section class="head-section">
            <div class="col-title">业务员信息</div>
            <div class="head-grid">
              <el-form-item label="业务员" class="span-2">
                <el-input v-model="form.sales_user_name" maxlength="50" placeholder="From" />
              </el-form-item>
              <el-form-item label="业务电话" class="span-2">
                <el-input v-model="form.sales_phone" maxlength="50" />
              </el-form-item>
              <el-form-item label="业务邮箱" class="span-2">
                <el-input v-model="form.sales_email" maxlength="100" />
              </el-form-item>
            </div>
          </section>

          <section class="head-section">
            <div class="col-title">订单信息</div>
            <div class="head-grid">
              <el-form-item label="发票号" class="span-2" :error="invoiceNoTaken ? '发票号已存在，请更换' : ''">
                <el-input
                  v-model="form.invoice_no"
                  maxlength="64"
                  placeholder="已自动生成，可修改"
                  @input="onInvoiceNoInput"
                  @blur="onInvoiceNoBlur"
                />
              </el-form-item>
              <el-form-item label="日期" required class="span-2">
                <el-date-picker v-model="form.invoice_date" value-format="YYYY-MM-DD" style="width: 100%" />
              </el-form-item>
              <el-form-item label="币种" class="span-1">
                <el-input v-model="form.currency" maxlength="16" />
              </el-form-item>
              <el-form-item label="小满标记" required class="span-3">
                <div class="okki-flags-row">
                  <span class="okki-flag">
                    新成交
                    <el-switch v-model="form.okki_new_deal" :active-value="1" :inactive-value="0"
                               @change="markOkkiFlagTouched('newDeal')" />
                  </span>
                  <span class="okki-flag">
                    包邮
                    <el-switch v-model="form.okki_free_shipping" :active-value="1" :inactive-value="0"
                               @change="markOkkiFlagTouched('freeShipping')" />
                  </span>
                  <span class="okki-flag">
                    首返
                    <el-switch v-model="form.okki_first_return" :active-value="1" :inactive-value="0" />
                  </span>
                  <span class="okki-flag-tip">推小满必填，已按历史预判</span>
                </div>
              </el-form-item>
              <el-form-item label="备注" class="span-3">
                <el-input v-model="form.remark" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="500" />
              </el-form-item>
            </div>
          </section>

          <section class="head-section settlement-section">
            <div class="col-title">费用与结算信息</div>
            <div class="head-grid">
              <el-form-item label="付款方式" class="span-2">
                <el-select v-model="form.internal_payment_method" clearable placeholder="请选择">
                  <el-option v-for="option in PAYMENT_METHOD_OPTIONS" :key="option" :label="option" :value="option" />
                </el-select>
              </el-form-item>
              <el-form-item label="预付款" class="span-2" :error="settlementError">
                <el-input-number v-model="form.internal_received" :min="0" :max="formTotal" :precision="2" controls-position="right" style="width: 100%" />
              </el-form-item>
              <el-form-item label="尾款" class="span-2">
                <el-input :model-value="form.internal_balance == null ? '' : money(form.internal_balance)" readonly class="balance-field">
                  <template #append>根据订单总额与预付款自动计算</template>
                </el-input>
              </el-form-item>
              <el-form-item label="头发金额" class="span-2">
                <el-input :model-value="money(formHairPrice)" readonly class="calculated-amount">
                  <template #suffix><span class="amount-note">Hair Price</span></template>
                </el-input>
              </el-form-item>
              <el-form-item label="折扣金额" class="span-2 negative-field">
                <el-input :model-value="money(formLineDiscountTotal)" readonly class="calculated-amount">
                  <template #suffix><span class="amount-note">Discount</span></template>
                </el-input>
              </el-form-item>
              <el-form-item label="包装数量" class="span-1">
                <el-input-number v-model="form.packaging_quantity" :min="0" :precision="0" controls-position="right" style="width: 100%" />
              </el-form-item>
              <el-form-item label="包装费用" class="span-1">
                <el-input-number v-model="form.internal_accessory" :min="0" :precision="2" controls-position="right" style="width: 100%" />
              </el-form-item>
              <el-form-item label="快递渠道" class="span-2">
                <el-select v-model="form.express_channel" clearable placeholder="请选择">
                  <el-option v-for="option in EXPRESS_CHANNEL_OPTIONS" :key="option" :label="option" :value="option" />
                </el-select>
              </el-form-item>
              <el-form-item label="运费" class="span-2">
                <el-input-number v-model="form.shipping_fee" :min="0" :precision="2" controls-position="right" style="width: 100%" />
              </el-form-item>
              <el-form-item label="手续费" class="span-2">
                <el-input-number v-model="form.surcharge_amount" :min="0" :precision="2" controls-position="right" style="width: 100%" />
              </el-form-item>
            </div>
          </section>

          <div class="line-header">
            <div>
              <strong>产品明细</strong>
              <span v-if="isProduction">生产单：关键词下拉可选可输，已有属性直接选，没有就按输入沉淀新产品。</span>
              <span v-else>四个关键词选择完整后自动匹配唯一 Product_name。</span>
            </div>
            <div class="line-header-actions">
              <el-tooltip :disabled="canPasteImport" :content="pasteImportDisabledReason">
                <span>
                  <el-button
                    v-permission="'invoice:write'"
                    :disabled="!canPasteImport"
                    @click="pasteImportVisible = true"
                  >
                    <el-icon><DocumentCopy /></el-icon>
                    从 Excel 粘贴
                  </el-button>
                </span>
              </el-tooltip>
              <el-button link type="primary" @click="showOptionalCols = !showOptionalCols">
                <el-icon><component :is="showOptionalCols ? ArrowUp : ArrowDown" /></el-icon>
                {{ showOptionalCols ? '收起选填列' : '展开选填列' }}
              </el-button>
              <el-button @click="addLine">
                <el-icon><Plus /></el-icon>
                添加明细
              </el-button>
            </div>
          </div>

          <div class="line-table-wrap">
            <el-table :data="form.items" border class="list-table line-table">
              <el-table-column label="#" type="index" min-width="48" max-width="60" fixed />

              <el-table-column v-if="isProduction" label="Product" min-width="190" max-width="260">
                <template #default="{ row }">
                  <el-select
                    v-model="row.product_display"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="系列描述，可输入"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.displays" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column v-if="showOptionalCols || !isProduction" label="Model" min-width="120" max-width="180">
                <template #default="{ row }">
                  <el-select
                    v-if="isProduction"
                    v-model="row.model"
                    filterable
                    allow-create
                    clearable
                    default-first-option
                    placeholder="可选"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.models" :key="v" :label="v" :value="v" />
                  </el-select>
                  <el-select
                    v-else
                    v-model="row.model"
                    filterable
                    placeholder="Model"
                    @visible-change="v => v && loadLineOptions(row)"
                    @change="onLineFilterChange(row)"
                  >
                    <el-option v-for="v in row.options.models" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="Color" min-width="120" max-width="170">
                <template #default="{ row }">
                  <el-select
                    v-if="isProduction"
                    v-model="row.color"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="Color"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.colors" :key="v" :label="v" :value="v" />
                  </el-select>
                  <el-select
                    v-else
                    v-model="row.color"
                    filterable
                    placeholder="Color"
                    @visible-change="v => v && loadLineOptions(row)"
                    @change="onLineFilterChange(row)"
                  >
                    <el-option v-for="v in row.options.colors" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="Length" min-width="95" max-width="130">
                <template #default="{ row }">
                  <el-select
                    v-if="isProduction"
                    v-model="row.length"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="Length"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.sizes" :key="v" :label="v" :value="v" />
                  </el-select>
                  <el-select
                    v-else
                    v-model="row.length"
                    filterable
                    placeholder="Length"
                    @visible-change="v => v && loadLineOptions(row)"
                    @change="onLineFilterChange(row)"
                  >
                    <el-option v-for="v in row.options.sizes" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="Net Weight" min-width="105" max-width="150">
                <template #default="{ row }">
                  <el-select
                    v-if="isProduction"
                    v-model="row.net_weight_grams"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="Unit"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.units" :key="v" :label="v" :value="v" />
                  </el-select>
                  <el-select
                    v-else
                    v-model="row.net_weight_grams"
                    filterable
                    placeholder="Unit"
                    @visible-change="v => v && loadLineOptions(row)"
                    @change="onLineFilterChange(row)"
                  >
                    <el-option v-for="v in row.options.units" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column v-if="!isProduction" label="Product_name" min-width="230" max-width="360" show-overflow-tooltip>
                <template #default="{ row }">
                  <div :class="['product-cell', row.product_name ? 'is-matched' : 'is-pending']">
                    <span>{{ row.product_name || '待匹配' }}</span>
                    <el-tag v-if="row.sku_id" size="small" effect="plain">SKU {{ row.sku_id }}</el-tag>
                    <el-tag v-else-if="row.matching" size="small" type="info" effect="plain">匹配中</el-tag>
                  </div>
                </template>
              </el-table-column>

              <el-table-column v-if="showOptionalCols" label="Curl" min-width="110" max-width="150">
                <template #default="{ row }">
                  <el-select v-model="row.curl" clearable placeholder="可选">
                    <el-option v-for="v in CURL_OPTIONS" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="标准价" min-width="95" max-width="140" align="right">
                <template #default="{ row }">
                  <span v-if="row.standard_price != null" class="std-price">
                    {{ money4(row.standard_price) }}
                    <el-tooltip v-if="row.color_type_source === 'inferred'" content="该色号未登记色型映射，价格按命名规则推断的色型取得，请人工核对">
                      <el-tag size="small" type="warning" effect="plain">色型推断</el-tag>
                    </el-tooltip>
                  </span>
                  <el-tag v-else size="small" type="warning" effect="plain">无标准价</el-tag>
                </template>
              </el-table-column>

              <el-table-column label="客户价" min-width="140" max-width="180">
                <template #default="{ row }">
                  <div :class="['price-cell', row.price_source === 'manual' ? 'is-manual' : '']">
                    <el-input-number v-model="row.price_per_piece" :min="0.01" :precision="4" :controls="false" @change="onPriceInput(row)" />
                    <el-tag v-if="row.price_source === 'manual'" size="small" type="warning" effect="plain">手改</el-tag>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="Quantity" min-width="100" max-width="140">
                <template #default="{ row }">
                  <el-input-number v-model="row.quantity" :min="1" :precision="0" :controls="false" @change="updateLineTotal(row)" />
                </template>
              </el-table-column>

              <el-table-column label="折扣" min-width="110" max-width="150">
                <template #default="{ row }">
                  <el-input-number
                    v-model="row.discount_amount"
                    :precision="2"
                    :controls="false"
                    class="line-discount-input"
                    @change="onLineDiscountChange(row)"
                  />
                </template>
              </el-table-column>

              <el-table-column label="TotalPrice" min-width="100" max-width="150" align="right">
                <template #default="{ row }">{{ money(row.total_price) }}</template>
              </el-table-column>

              <el-table-column label="操作" min-width="64" max-width="80" fixed="right">
                <template #default="{ $index }">
                  <el-button link type="danger" @click="removeLine($index)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

        </el-form>
      </template>

      <template #footer>
        <div class="drawer-footer">
          <div class="total-box">
            <span class="total-breakdown">
              头发金额 {{ money(formHairPrice) }}
              + 折扣金额 {{ money(formLineDiscountTotal) }}
              + 包装费用 {{ money(form.internal_accessory) }}（数量 {{ form.packaging_quantity }}）
              + 运费 {{ money(form.shipping_fee) }}
              + 手续费 {{ money(form.surcharge_amount) }}
            </span>
            <span class="grand">Total: <strong>{{ form.currency }} {{ money(formTotal) }}</strong></span>
          </div>
          <div>
            <el-button @click="drawerVisible = false">取消</el-button>
            <el-button v-permission="'invoice:write'" @click="saveDraft">保存</el-button>
            <el-button v-permission="'invoice:write'" type="primary" @click="saveAndValidate">保存并校验</el-button>
          </div>
        </div>
      </template>
    </el-drawer>

    <InvoicePasteImport
      v-model="pasteImportVisible"
      :customer-id="form.customer_id"
      :customer-name="form.customer_name"
      :order-type="form.order_type"
      :currency="form.currency"
      :existing-items="form.items"
      @append="appendPastedLines"
    />

    <el-dialog v-model="syncLogsVisible" :title="syncLogsTitle" width="720px">
      <el-table v-loading="syncLogsLoading" :data="syncLogs" border class="list-table" max-height="420">
        <el-table-column label="时间" min-width="150" max-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="动作" min-width="96" max-width="110">
          <template #default="{ row }">{{ actionText(row.action) }}</template>
        </el-table-column>
        <el-table-column label="结果" min-width="80" max-width="90">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" effect="plain">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="信息" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.error_message || (row.success ? 'OKKI 已受理' : '-') }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp, Delete, Document, DocumentCopy, Download, Edit, Plus, Printer, Refresh, Search } from '@element-plus/icons-vue'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import {
  deleteInvoice,
  downloadInvoiceExcel,
  downloadInvoicePdf,
  fetchInvoicePrintHtml,
  getInvoiceSyncLogs,
  listInvoices,
  syncInvoice,
  validateInvoice,
} from '@/api/invoice'
import { EXPRESS_CHANNEL_OPTIONS, PAYMENT_METHOD_OPTIONS } from './composables/invoiceSettlement'
import { CURL_OPTIONS, contactLabel, customerLabel, describeCustomerRule, useInvoiceEditor } from './composables/useInvoiceEditor'
import InvoicePasteImport from './components/InvoicePasteImport.vue'

const loading = ref(false)
const invoices = ref([])
const showOptionalCols = ref(false)
const pasteImportVisible = ref(false)
const filters = reactive({ keyword: '', status: '', order_type: '' })
const pagination = reactive({ page: 1, page_size: 20, total: 0 })

const {
  drawerVisible,
  customerLoading,
  customerOptions,
  selectedCustomer,
  customerRule,
  contactLoading,
  contactOptions,
  selectedContact,
  privateOnlyCompany,
  privateOnlyContact,
  canTogglePrivate,
  okkiBound,
  invoiceNoTaken,
  entryOptions,
  form,
  formHairPrice,
  formLineDiscountTotal,
  formTotal,
  settlementError,
  isProduction,
  searchCustomers,
  searchContacts,
  onCustomerChange,
  onContactChange,
  onInvoiceNoInput,
  onInvoiceNoBlur,
  openCreate,
  openEdit,
  addLine,
  removeLine,
  loadLineOptions,
  onLineFilterChange,
  onCustomFieldChange,
  onPriceInput,
  onLineDiscountChange,
  updateLineTotal,
  appendImportedLines,
  saveDraft,
  saveAndValidate,
  showIssues,
  markOkkiFlagTouched,
} = useInvoiceEditor({ onSaved: () => loadInvoices() })

const canPasteImport = computed(() => Boolean(form.customer_id && form.order_type && form.currency))
const pasteImportDisabledReason = computed(() => {
  const missing = []
  if (!form.customer_id) missing.push('客户')
  if (!form.order_type) missing.push('订单类型')
  if (!form.currency) missing.push('币种')
  return missing.length ? `请先选择${missing.join('、')}` : ''
})

function appendPastedLines({ rows, fingerprint }) {
  if (!appendImportedLines(rows, fingerprint)) {
    ElMessage.warning('这批数据已经加入当前发票')
    return
  }
  ElMessage.success(`已加入 ${rows.length} 条产品明细，发票尚未保存`)
}

const drawerTitle = computed(() => {
  const typeLabel = form.order_type === 'production' ? '生产单' : '库存单'
  return form.id ? `编辑${typeLabel} ${form.invoice_no}` : `新建${typeLabel}`
})

const summary = computed(() => {
  return invoices.value.reduce((acc, invoice) => {
    acc.total += 1
    acc.amount += Number(invoice.total_amount || 0)
    if (invoice.status === 'ready') acc.ready += 1
    if (invoice.status === 'draft') acc.draft += 1
    return acc
  }, { total: 0, ready: 0, draft: 0, amount: 0 })
})

onMounted(() => {
  loadInvoices()
})

async function loadInvoices() {
  loading.value = true
  try {
    const params = { ...filters, page: pagination.page, page_size: pagination.page_size }
    if (!params.order_type) delete params.order_type
    const res = await listInvoices(params)
    invoices.value = res.items || []
    pagination.total = res.total || 0
  } finally {
    loading.value = false
  }
}

async function validateAndSync(id) {
  const validation = await validateInvoice(id)
  if (!validation.ok) {
    showIssues(validation.issues)
    return
  }
  const result = await syncInvoice(id)
  if (result.ok) {
    ElMessage.success('已同步到小满')
  } else if (result.issues?.length) {
    // 推单前置校验（绑定/通用产品/默认状态缺失）——逐条展示，用户才知道去哪修
    showIssues(result.issues)
  } else {
    ElMessage.warning(result.message || '小满同步未完成')
  }
  loadInvoices()
}

const syncLogsVisible = ref(false)
const syncLogsLoading = ref(false)
const syncLogs = ref([])
const syncLogsTitle = ref('')

async function openSyncLogs(row) {
  syncLogsTitle.value = `同步日志 - ${row.invoice_no}`
  syncLogsVisible.value = true
  syncLogsLoading.value = true
  try {
    const res = await getInvoiceSyncLogs(row.id)
    syncLogs.value = res.items || []
  } finally {
    syncLogsLoading.value = false
  }
}

function actionText(action) {
  return { create: '首次推送', update: '编辑推送', retry: '重试' }[action] || action
}

function handleExport(command, row) {
  if (command === 'excel') return exportExcel(row)
  if (command === 'pdf') return exportPdf(row)
  return openPrint(row.id)
}

async function removeInvoice(row) {
  await confirmDanger('删除', `发票 ${row.invoice_no}`)
  await deleteInvoice(row.id)
  msgSuccess('删除')
  loadInvoices()
}

async function exportExcel(row) {
  const res = await downloadInvoiceExcel(row.id)
  downloadBlob(res, `${row.invoice_no || 'invoice'}.xlsx`)
}

async function exportPdf(row) {
  const res = await downloadInvoicePdf(row.id)
  downloadBlob(res, `${row.invoice_no || 'invoice'}.pdf`)
}

function downloadBlob(res, fallbackName) {
  const blob = new Blob([res.data], { type: res.headers['content-type'] })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fallbackName
  link.click()
  URL.revokeObjectURL(url)
}

async function openPrint(id) {
  // 新标签直连后端会因不带 Authorization 而 403，先鉴权取回 HTML 再本地打开
  const html = await fetchInvoicePrintHtml(id)
  const blob = new Blob([html], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

function money(value) {
  return Number(value || 0).toFixed(2)
}

function formatDateTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

function money4(value) {
  return Number(value || 0).toFixed(4)
}

function statusText(status) {
  return { draft: '草稿', ready: '可同步', synced: '已同步', sync_failed: '同步失败' }[status] || status
}

function statusType(status) {
  return { draft: 'info', ready: 'success', synced: 'success', sync_failed: 'danger' }[status] || 'info'
}

function syncText(status) {
  return { not_synced: '未同步', synced: '已同步', sync_failed: '失败' }[status] || status
}

function syncType(status) {
  return { not_synced: 'info', synced: 'success', sync_failed: 'danger' }[status] || 'info'
}
</script>

<style scoped src="./invoice-manage.css"></style>
