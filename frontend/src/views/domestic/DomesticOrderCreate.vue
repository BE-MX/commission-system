<template>
  <div class="create-page" v-loading="loading">
    <div class="create-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="panel head-panel">
      <div class="panel-title">订单信息</div>
      <el-form :model="form" label-width="92px" class="head-form">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="客户店名" required>
              <el-select
                v-model="form.customer_id" filterable clearable remote
                :remote-method="searchCustomers" :loading="customerLoading"
                placeholder="搜索已有客户，没有就在下面直接填新店名" style="width: 100%"
              >
                <el-option
                  v-for="c in customers" :key="c.id"
                  :label="`${c.shop_name}（余额 ¥${Number(c.balance || 0).toFixed(2)}）`"
                  :value="c.id"
                />
              </el-select>
              <el-input
                v-if="!form.customer_id" v-model="form.customer_shop_name"
                placeholder="新客户：直接输入店名，下单时自动建档" class="new-customer"
              />
              <div v-if="selectedCustomer" class="balance-hint">
                当前余额 ¥{{ Number(selectedCustomer.balance || 0).toFixed(2) }}
              </div>
            </el-form-item>
          </el-col>
          <el-col :span="5">
            <el-form-item label="订单号" required>
              <el-input v-model="form.order_no" placeholder="客户订单号，如 710 / 特涵5-506" />
            </el-form-item>
          </el-col>
          <el-col :span="5">
            <el-form-item label="下单日期" required>
              <el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="订单类型">
              <el-radio-group v-model="form.order_type">
                <el-radio-button v-for="t in options.order_types" :key="t.value" :value="t.value">{{ t.label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="订单备注">
          <el-input v-model="form.remark" type="textarea" :rows="1" placeholder="整单说明，选填" />
        </el-form-item>
      </el-form>
    </div>

    <div v-for="(item, index) in form.items" :key="item.key" class="panel item-panel">
      <div class="item-head">
        <span class="panel-title">明细 {{ index + 1 }}</span>
        <div class="item-actions">
          <GlassButton variant="link" left-icon="CopyDocument" @click="copyItem(index)">复制这行</GlassButton>
          <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="removeItem(index)">删除</GlassButton>
        </div>
      </div>

      <el-form :model="item" label-width="92px">
        <el-row :gutter="16">
          <el-col :span="6">
            <el-form-item label="产品类型" required>
              <el-radio-group v-model="item.attrs.product_type" @change="onProductTypeChange(item)">
                <el-radio-button v-for="t in options.product_types" :key="t.value" :value="t.value">{{ t.label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item :label="item.attrs.product_type === 'cap' ? '头套工艺' : '发片工艺'" required>
              <el-select v-model="item.attrs.craft" placeholder="选择工艺" filterable style="width: 100%">
                <el-option v-for="v in attrOptions(item.attrs.product_type, 'craft')" :key="v" :label="v" :value="v" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col v-if="hasField(item.attrs.product_type, 'net_color')" :span="6">
            <el-form-item label="网底颜色">
              <el-select v-model="item.attrs.net_color" placeholder="选择网底颜色" clearable filterable style="width: 100%">
                <el-option v-for="v in attrOptions(item.attrs.product_type, 'net_color')" :key="v" :label="v" :value="v" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="数量" required>
              <el-input-number v-model="item.order_qty" :min="1" :max="2000" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16" class="price-row">
          <el-col :span="6">
            <el-form-item label="产品单价" required>
              <el-input-number v-model="item.unit_price" :min="0" :precision="2" :step="10" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="明细总价">
              <span class="amount-value">¥{{ (Number(item.order_qty || 0) * Number(item.unit_price || 0)).toFixed(2) }}</span>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="6">
            <el-form-item :label="item.attrs.product_type === 'cap' ? '头套尺寸' : '发片尺寸'" required>
              <el-select v-model="item.attrs.size" placeholder="选择尺寸" filterable style="width: 100%">
                <el-option v-for="v in attrOptions(item.attrs.product_type, 'size')" :key="v" :label="v" :value="v" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="长度" required>
              <el-select v-model="item.attrs.length" placeholder="选择长度" filterable style="width: 100%">
                <el-option v-for="v in attrOptions(item.attrs.product_type, 'length')" :key="v" :label="v" :value="v" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="发量" required>
              <el-select v-model="item.attrs.density" placeholder="选择发量" filterable style="width: 100%">
                <el-option v-for="v in attrOptions(item.attrs.product_type, 'density')" :key="v" :label="v" :value="v" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="工艺路线">
              <!-- 路线不让下单人选：选完工艺就地显示会走哪条，没配的当场提示 -->
              <el-tag v-if="routeOf(item)" type="success" effect="plain">{{ routeOf(item).route_name }}</el-tag>
              <el-tag v-else-if="item.attrs.craft" type="warning" effect="plain">未配路线，下单后不能开工</el-tag>
              <span v-else class="muted">选完工艺后自动匹配</span>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col v-for="section in DETAIL_SECTIONS" :key="section.key" :span="12">
            <el-form-item :label="section.label">
              <el-input
                v-model="item[section.key]" type="textarea" :rows="2"
                :placeholder="section.placeholder"
              />
              <!-- show-list=false + uploadFn 自管状态：AppUpload 的 v-model 回写
                   在并发上传时会丢行（见组件头注释） -->
              <AppUpload
                :upload-fn="makeUploadFn(item, section.imageKey)"
                accept="image/*" :max-size-mb="20" multiple :limit="6"
                :show-list="false" button-text="加参考图" class="section-upload"
              />
              <div v-if="item[section.imageKey].length" class="thumb-row">
                <div v-for="(img, i) in item[section.imageKey]" :key="img.path" class="thumb">
                  <el-image :src="img.url" fit="cover" class="thumb-img" />
                  <span class="thumb-del" @click="removeImage(item, section.imageKey, i)">×</span>
                </div>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </div>

    <div class="panel footer-panel">
      <GlassButton variant="ghost" left-icon="Plus" @click="addItem">再加一行明细</GlassButton>
      <div class="footer-right">
        <span v-if="unroutedCount" class="warn-text">{{ unroutedCount }} 行明细的工艺未配路线</span>
        <span class="order-total">订单总价：¥{{ orderTotal.toFixed(2) }}</span>
        <GlassButton variant="ghost" left-icon="Document" :loading="submitting" @click="submit(true)">保存草稿</GlassButton>
        <GlassButton variant="primary" left-icon="Check" :loading="submitting" @click="submit(false)">提交订单</GlassButton>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * 内贸下单。逻辑全在 composables/useDomesticOrderCreate.js（宪法 12）。
 * 产品不用先建：选完属性后端 find-or-create 自动沉淀，并按工艺映射自动配工艺路线。
 */
import { DETAIL_SECTIONS } from '@/api/domestic'
import AppUpload from '@/components/AppUpload.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useDomesticOrderCreate } from './composables/useDomesticOrderCreate'

const {
  loading, submitting, options, customers, customerLoading, form,
  attrOptions, hasField, routeOf, unroutedCount, orderTotal, selectedCustomer,
  onProductTypeChange, addItem, copyItem, removeItem,
  makeUploadFn, removeImage, searchCustomers, submit,
} = useDomesticOrderCreate()
</script>

<style scoped>
.create-page { position: relative; }
.create-aurora { inset: -24px -28px; }
.create-page .panel { position: relative; z-index: 1; }

.panel {
  margin-bottom: 16px;
  padding: 16px 20px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.panel-title {
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 12px;
}

.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.item-head .panel-title { margin-bottom: 12px; }
.item-actions { display: flex; gap: 4px; }

.new-customer { margin-top: 8px; }
.balance-hint { margin-top: 6px; color: var(--el-color-success); font-size: 12px; }
.price-row { margin-top: 2px; }
.amount-value, .order-total { font-weight: 600; color: var(--el-text-color-primary); }
.section-upload { margin-top: 8px; }

.thumb-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.thumb { position: relative; }

.thumb-img {
  width: 72px;
  height: 72px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
}

.thumb-del {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  line-height: 16px;
  text-align: center;
  border-radius: 50%;
  background: var(--el-color-danger);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}

.footer-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  bottom: 0;
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.warn-text {
  font-size: 13px;
  color: var(--el-color-warning);
}

.muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
