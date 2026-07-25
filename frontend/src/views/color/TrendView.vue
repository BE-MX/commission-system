<template>
  <div class="trend-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="trend-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

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
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 padding 环（同工作台/发票页） */
.trend-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上（点名内容块，禁用 > :not(.lg-aurora) 通配） */
.trend-page .el-empty {
  position: relative;
  z-index: 1;
}
</style>
