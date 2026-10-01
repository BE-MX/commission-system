# 组件与交互样例

在 frontend 运行 npm run dev -- --host 127.0.0.1，打开 /tests/fixtures/ui-convergence/。
直接使用主站 ComponentShowcase.vue，不调用业务 API。选择场景检查首次失败与刷新失败，重试恢复；修改筛选后翻页验证查询快照；列设置可恢复默认，详情与短表单支持窄屏和键盘。
刷新页面恢复数据；表格偏好保留在本地 storage。正式应用的入口在 navigation.js。
