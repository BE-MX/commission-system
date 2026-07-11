<template>
  <section class="surface-section">
    <div class="section-title"><el-icon><Document /></el-icon><span>客户与订单</span></div>
    <el-form :model="form" label-position="top" :disabled="locked" class="form-grid">
      <el-form-item label="客户名称" required>
        <el-select v-model="form.customer_id" filterable remote reserve-keyword :remote-method="keyword => $emit('search-customer', keyword)" placeholder="输入客户名称搜索" @change="value => $emit('customer-change', value)">
          <el-option v-for="item in customers" :key="item.customer_id" :label="item.customer_name" :value="item.customer_id" />
        </el-select>
      </el-form-item>
      <el-form-item label="客户等级" required>
        <el-segmented v-model="form.customer_grade" :options="['A', 'B', 'C', 'D', 'E']" />
      </el-form-item>
      <el-form-item label="订单号" required>
        <el-select v-model="form.order_id" filterable remote :disabled="locked || !form.customer_id" :remote-method="keyword => $emit('search-order', keyword)" placeholder="先选择客户，再搜索订单" @change="value => $emit('order-change', value)">
          <el-option v-for="item in orders" :key="item.order_id" :label="`${item.order_no} · USD ${item.amount_usd || '—'}`" :value="item.order_id" />
        </el-select>
      </el-form-item>
      <el-form-item label="反馈渠道">
        <el-select v-model="form.feedback_channel" placeholder="选择渠道" clearable>
          <el-option v-for="item in ['邮件', 'WhatsApp', '钉钉', '电话', '其他']" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item label="购买日期" required><el-date-picker v-model="form.purchase_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="反馈日期" required><el-date-picker v-model="form.feedback_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="是否影响终端客户使用或销售" required class="span-2">
        <el-radio-group v-model="form.affects_end_customer">
          <el-radio-button value="yes">是</el-radio-button><el-radio-button value="no">否</el-radio-button><el-radio-button value="unknown">未知</el-radio-button>
        </el-radio-group>
      </el-form-item>
    </el-form>
  </section>

  <section class="surface-section">
    <div class="section-title"><el-icon><Goods /></el-icon><span>产品与问题</span></div>
    <el-form :model="form" label-position="top" :disabled="locked" class="form-grid">
      <el-form-item label="产品类型" class="span-2">
        <el-radio-group v-model="form.is_custom_product" @change="$emit('product-mode-change')">
          <el-radio-button :value="false">标准产品</el-radio-button><el-radio-button :value="true">定制产品</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="产品型号" required class="span-2">
        <el-input v-if="form.is_custom_product" v-model="form.product_name_snapshot" placeholder="填写定制产品名称" />
        <el-select v-else v-model="form.product_id" filterable remote reserve-keyword :remote-method="keyword => $emit('search-product', keyword)" placeholder="搜索 product.name" @change="value => $emit('product-change', value)">
          <el-option v-for="item in products" :key="item.product_id" :label="`${item.product_name}${item.model ? ` · ${item.model}` : ''}`" :value="item.product_id" />
        </el-select>
      </el-form-item>
      <el-form-item label="库存批次号"><el-input v-model="form.batch_no" placeholder="无批次可填“未知”" /></el-form-item>
      <el-form-item label="颜色" required><el-input v-model="form.color_value" placeholder="标准色号或定制颜色" /></el-form-item>
      <el-form-item label="长度" required><el-input v-model="form.length_value" placeholder="如 20 inch" /></el-form-item>
      <el-form-item label="克重" required><el-input-number v-model="form.weight_value" :min="0.01" :precision="2" /><el-select v-model="form.weight_unit" class="unit-select"><el-option label="g" value="g" /><el-option label="kg" value="kg" /></el-select></el-form-item>
      <el-form-item label="数量" required><el-input-number v-model="form.quantity" :min="0.01" :precision="2" /></el-form-item>
      <el-form-item label="涉及问题产品货值" required><el-input-number v-model="form.affected_goods_value" :min="0.01" :precision="2" /><el-select v-model="form.affected_goods_currency" class="unit-select"><el-option label="USD" value="USD" /><el-option label="CNY" value="CNY" /></el-select></el-form-item>
      <el-form-item label="主要问题类型" required>
        <el-select v-model="form.primary_issue_type" placeholder="选择问题类型">
          <el-option v-for="item in options.issue_types || []" :key="item.code" :label="item.label" :value="item.code" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="form.primary_issue_type === '产品做工'" label="做工问题细分">
        <el-select v-model="form.secondary_issue_types" multiple placeholder="可多选">
          <el-option v-for="item in workmanshipOptions" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item label="出现时间" required><el-select v-model="form.occurred_stage"><el-option v-for="item in stages" :key="item" :label="item" :value="item" /></el-select></el-form-item>
      <el-form-item label="问题描述" required class="span-2"><el-input v-model="form.problem_description" type="textarea" :rows="4" maxlength="4000" show-word-limit placeholder="至少 20 字，说明出现时间、范围和影响" /></el-form-item>
      <el-form-item label="安装 / 护理 / 存储说明" required class="span-2"><el-input v-model="form.care_storage_note" type="textarea" :rows="3" maxlength="4000" show-word-limit placeholder="至少 20 字" /></el-form-item>
    </el-form>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  form: { type: Object, required: true },
  locked: Boolean,
  options: { type: Object, default: () => ({}) },
  customers: { type: Array, default: () => [] },
  orders: { type: Array, default: () => [] },
  products: { type: Array, default: () => [] },
})
defineEmits(['search-customer', 'customer-change', 'search-order', 'order-change', 'search-product', 'product-change', 'product-mode-change'])
const stages = ['刚收到', '安装后', '使用几天', '1–3 个月', '超过 3 个月', '其他']
const workmanshipOptions = computed(() => props.options.issue_types?.find(item => item.code === '产品做工')?.secondary || [])
</script>

<style scoped>
.surface-section { padding: 18px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); box-shadow: var(--card-shadow); }
.surface-section + .surface-section { margin-top: 16px; }
.section-title { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; color: var(--text-primary); font: 700 15px/1.3 var(--font-display); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.span-2 { grid-column: 1 / -1; }
:deep(.el-select), :deep(.el-date-editor), :deep(.el-input-number) { width: 100%; }
:deep(.el-form-item) { margin-bottom: 16px; }
:deep(.el-form-item__label) { color: var(--text-secondary); font-weight: 600; }
.unit-select { width: 84px !important; margin-left: 8px; }
@media (max-width: 900px) { .form-grid { grid-template-columns: 1fr; } .span-2 { grid-column: auto; } }
</style>
