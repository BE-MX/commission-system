<template>
  <div v-permission="'customer_image:write'">
    <GlassButton variant="primary" left-icon="Link" @click="open">创建邀请链接</GlassButton>

    <el-dialog v-model="visible" title="创建客户专属邀请" width="min(620px, 92vw)" destroy-on-close>
      <div class="invite-form">
        <label>
          客户
          <el-select
            v-model="draft.customer_id"
            filterable
            remote
            reserve-keyword
            :remote-method="searchCustomers"
            :loading="customerLoading"
            placeholder="输入客户名称或联系人名称搜索"
          >
            <el-option
              v-for="customer in customers"
              :key="customer.id"
              :label="customerOptionLabel(customer)"
              :value="customer.id"
            />
          </el-select>
          <small>搜索结果仅包含当前账号有权服务的客户。</small>
        </label>

        <div class="product-field">
          <span class="field-label">可生成产品</span>
          <el-checkbox-group v-if="publishedProducts.length" v-model="draft.product_ids" class="product-choices">
            <el-checkbox v-for="product in publishedProducts" :key="product.id" :value="product.id" class="product-choice">
              <img v-if="productCoverUrls[product.id]" :src="productCoverUrls[product.id]" :alt="product.name">
              <span v-else class="product-placeholder">暂无封面</span>
              <strong>{{ product.name }}</strong>
              <small>{{ product.category }}</small>
            </el-checkbox>
          </el-checkbox-group>
          <el-empty v-else :image-size="64" description="暂无已发布产品，请联系模板管理员" />
        </div>

        <div class="form-grid">
          <label>
            明确失效时间
            <el-date-picker
              v-model="draft.expires_at"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              placeholder="请选择日期和时间"
              :disabled-date="disablePastDate"
            />
          </label>
          <label>
            生成额度
            <el-input-number v-model="draft.quota_total" :min="1" :max="9999" placeholder="请输入正整数" />
          </label>
        </div>
        <el-alert type="info" :closable="false" show-icon title="链接即客户访问凭证；请只发送给对应客户。" />
      </div>
      <template #footer>
        <GlassButton variant="ghost" @click="visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="submitting" @click="submit">生成链接</GlassButton>
      </template>
    </el-dialog>

    <el-dialog
      :model-value="Boolean(oneTimeInviteUrl)"
      title="邀请链接已生成"
      width="min(560px, 92vw)"
      :close-on-click-modal="false"
      @closed="clearOneTimeInviteUrl"
      @update:model-value="closeResult"
    >
      <el-alert type="warning" :closable="false" show-icon title="此链接只展示一次">
        关闭后系统不会再次返回明文链接，请立即复制并妥善发送。
      </el-alert>
      <div class="one-time-link">
        <code>{{ oneTimeInviteUrl }}</code>
        <GlassButton variant="primary" left-icon="CopyDocument" @click="copyLink">复制链接</GlassButton>
      </div>
      <template #footer>
        <GlassButton variant="primary" @click="closeResult(false)">我已复制，关闭</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { customerOptionLabel, inviteSubmissionErrorMessage, validateInviteDraft } from './composables/useCustomerImageAdmin'
import { beijingStartOfToday } from '@/utils/datetime'

const props = defineProps({ state: { type: Object, required: true } })
const { customers, oneTimeInviteUrl, productCoverUrls, products } = props.state
const visible = ref(false)
const submitting = ref(false)
const customerLoading = ref(false)
const draft = ref(emptyDraft())
const publishedProducts = computed(() => products.value.filter(product => product.is_published))

function emptyDraft() {
  return { customer_id: '', product_ids: [], expires_at: '', quota_total: null }
}

function open() {
  draft.value = emptyDraft()
  visible.value = true
}

async function searchCustomers(query) {
  customerLoading.value = true
  try { await props.state.searchScopedCustomers(query) } finally { customerLoading.value = false }
}

const disablePastDate = date => date < beijingStartOfToday()

async function submit() {
  const error = validateInviteDraft(draft.value)
  if (error) { ElMessage.warning(error); return }
  submitting.value = true
  try {
    await props.state.submitInvite(draft.value)
    visible.value = false
  } catch (error) {
    ElMessage.warning(inviteSubmissionErrorMessage(error))
  } finally { submitting.value = false }
}

async function copyLink() {
  if (await props.state.copyOneTimeInviteUrl()) {
    ElMessage.success('链接已复制')
  } else {
    ElMessage.warning('自动复制失败，请手动选择上方链接复制')
  }
}

function clearOneTimeInviteUrl() { props.state.clearOneTimeInviteUrl() }
function closeResult(opened) {
  if (!opened) props.state.clearOneTimeInviteUrl()
}
</script>

<style scoped>
.invite-form { display: grid; gap: 18px; }
label { display: grid; gap: 7px; color: var(--el-text-color-regular); font-size: 13px; font-weight: 600; }
.product-field { display: grid; gap: 8px; }
.field-label { color: var(--el-text-color-regular); font-size: 13px; font-weight: 600; }
.product-choices { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.product-choice { position: relative; display: grid; grid-template-columns: 24px 54px minmax(0, 1fr); grid-template-rows: 28px 24px; align-items: center; width: auto; height: auto; min-height: 76px; margin: 0; padding: 8px; border: 1px solid var(--el-border-color); border-radius: 11px; }
.product-choice :deep(.el-checkbox__input) { grid-row: 1 / 3; }
.product-choice :deep(.el-checkbox__label) { display: contents; }
.product-choice img, .product-placeholder { grid-row: 1 / 3; width: 54px; height: 54px; border-radius: 8px; object-fit: cover; }
.product-placeholder { display: grid; place-items: center; background: var(--el-fill-color-light); color: var(--el-text-color-placeholder); font-size: 11px; white-space: normal; text-align: center; }
.product-choice strong, .product-choice small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
small { color: var(--el-text-color-secondary); font-weight: 400; }
.form-grid { display: grid; grid-template-columns: 1.35fr .65fr; gap: 14px; }
.one-time-link { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; margin-top: 18px; }
.one-time-link code { overflow-wrap: anywhere; padding: 13px; border-radius: 9px; background: var(--el-fill-color-light); }
:deep(.glass-button:not(.glass-button--link)) { min-height: 44px; }
@media (max-width: 600px) { .form-grid, .one-time-link { grid-template-columns: 1fr; } }
</style>
