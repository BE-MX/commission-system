<template>
  <div class="waybill-upload-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="upload-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-page-header content="运单上传" @back="$router.back()" />

    <!-- 上传表单与验货单「上传物流单」弹框共用 -->
    <WaybillUploadForm class="upload-form" :state="upload" />

    <!-- 提交成功弹窗 -->
    <WaybillSuccessDialog
      v-model="upload.successVisible.value"
      :result-data="upload.resultData"
      @continue="upload.resetAll"
    />
  </div>
</template>

<script setup>
import { useWaybillUpload } from './composables/useWaybillUpload'
import WaybillUploadForm from './components/WaybillUploadForm.vue'
import WaybillSuccessDialog from './components/WaybillSuccessDialog.vue'

const upload = useWaybillUpload()
</script>

<style scoped>
.waybill-upload-page {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.upload-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   会覆盖就地渲染的 el-drawer/el-dialog 的 .el-overlay position: fixed */
.waybill-upload-page .el-page-header,
.waybill-upload-page .upload-form {
  position: relative;
  z-index: 1;
}

.upload-form {
  margin-top: 24px;
}

@media (max-width: 768px) {
  .waybill-upload-page { padding: 0; }
}
</style>
