<!--
  培训速递 · 附件面板：批次类型/备注选择 + 多选上传（逐文件进度在 AppUpload）+ 富列表行内编辑。
  状态与方法全部来自 useTrainingEditor，本组件只是展示壳（500 行红线拆分）。
-->
<template>
  <div class="attach-area">
    <div class="attach-bar">
      <el-select v-model="attach.fileType" class="attach-type">
        <el-option label="类型：自动识别" value="auto" />
        <el-option v-for="t in FILE_TYPE_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
      <el-input v-model="attach.remark" maxlength="200" clearable class="attach-remark"
        placeholder="附件备注（可选，随本批上传的文件一起保存）" />
      <AppUpload :model-value="filesModel" :upload-fn="uploadFn" multiple :limit="20" :max-size-mb="300"
        :show-list="false" class="attach-upload"
        accept=".jpg,.jpeg,.png,.webp,.pdf,.ppt,.pptx,.doc,.docx,.xls,.xlsx,.txt,.md,.zip,.mp4,.mp3,.m4a"
        button-text="上传附件（可多选）" />
    </div>
    <div v-if="files.length" class="attach-list">
      <div v-for="f in files" :key="f.id" class="attach-row">
        <span class="attach-name" :title="f.file_name">{{ f.file_name }}</span>
        <span class="attach-size">{{ formatSize(f.file_size) }}</span>
        <el-select v-model="f.file_type" placeholder="未分类" class="attach-row-type"
          @change="v => saveFileMeta(f, { file_type: v })">
          <el-option v-for="t in FILE_TYPE_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-input v-model="f.remark" maxlength="200" placeholder="备注" class="attach-row-remark"
          @change="v => saveFileMeta(f, { remark: v || '' })" />
        <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="removeFile(f)">删除</GlassButton>
      </div>
    </div>
  </div>
</template>

<script setup>
import AppUpload from '@/components/AppUpload.vue'
import { FILE_TYPE_OPTIONS } from '@/api/training'
import { formatSize } from '@/utils/format'

defineProps({
  files: { type: Array, required: true },
  attach: { type: Object, required: true },      // reactive({ fileType, remark })，v-model 直改回流 composable
  filesModel: { type: Array, required: true },   // 只读映射，供 AppUpload 数量上限判断
  uploadFn: { type: Function, required: true },
  removeFile: { type: Function, required: true },
  saveFileMeta: { type: Function, required: true },
})
</script>

<style scoped>
.attach-area {
  width: 100%;
}

.attach-bar {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
}

.attach-type {
  width: 150px;
  flex-shrink: 0;
}

.attach-remark {
  flex: 1;
  min-width: 200px;
}

.attach-upload {
  flex-basis: 100%;
}

.attach-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.attach-row {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 6px 10px;
}

.attach-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attach-size {
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.attach-row-type {
  width: 118px;
  flex-shrink: 0;
}

.attach-row-remark {
  width: 200px;
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .attach-row {
    flex-wrap: wrap;
  }

  .attach-row-remark {
    width: 100%;
  }
}
</style>
