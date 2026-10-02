# 状态标签窄列回归

在 frontend 启动 Vite：`npm run dev -- --host 127.0.0.1 --port 3198`。
打开 `/tests/fixtures/status-badge/`，直接使用实际 StatusBadge、Element Plus 表格和主站样式，不调用业务 API。

覆盖 84px 窄列、发票状态160px/同步110px/类型110px、长未知值、flex 容器、70px可关闭标签、动态插槽与显式 title、多个标签及真实操作列样式。包含售后、工资、邮件队列、物流、产品色型、订单风险与情报可信度真实字典/页面显示映射的48个状态，列宽从页面源码读取；当前桌面样例共72个标签。页面内部显示映射只解析源码，不执行页面setup或业务API。
在 frontend 运行 `python tests/statusBadgeLayout.py`（需要 Python Playwright 和本机 Chrome）。
断言标签与文字均保持单行、选取的真实字典状态完整展示、未知状态可通过 tooltip 查看全文、动态文字的 title 同步、多个标签在标签之间换行、操作列保留 flex 换行、关闭按钮位于标签内且实际点击有效，并生成桌面/390px截图与几何指标。

在 frontend 运行 `npm run audit:status-badges` 检查主站 Vue 源码的状态列宽；需要保存明细时运行 `node scripts/auditStatusBadgeColumns.mjs --report ../tmp/status-badge-audit/all-columns-after.json`。该静态检查与隔离浏览器夹具互补，不等于逐页登录业务系统验收。
