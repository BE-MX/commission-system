<template>
  <div class="trend-page">
    <el-empty description="色彩趋势看板开发中（P2）">
      <template #description>
        <div style="text-align: center;">
          <p>色彩趋势看板</p>
          <p style="color: var(--el-text-color-secondary); font-size: 14px;">
            包含：历史趋势折线图、色族热力图、30天预测、社媒色彩快照
          </p>
          <p style="color: var(--el-text-color-placeholder); font-size: 13px;">
            预计 P2 阶段实现（1-2 周后）
          </p>
        </div>
      </template>
    </el-empty>
  </div>
</template>

<style scoped>
.trend-page {
  padding: 60px 20px;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
}
</style>
